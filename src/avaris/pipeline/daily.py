import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import duckdb
import httpx
import numpy as np
import pandas as pd

from avaris.analytics.drivers import explain, top_drivers
from avaris.analytics.injury_impact import injury_impact, player_names
from avaris.config import Settings
from avaris.db import upsert
from avaris.features.build import FeatureSet, build_features, feature_hash, write_features
from avaris.features.decision_time import DECISION_LEAD
from avaris.ingest.injuries import InjuryClient, ingest_injuries
from avaris.ingest.runner import ingest_stats
from avaris.ingest.stats_client import RawCache, StatsClient, Throttle
from avaris.models.dataset import inputs, with_targets
from avaris.models.ladder import TARGETS
from avaris.models.predictor import GamePredictor
from avaris.models.registry import Registry
from avaris.pipeline.score import score_predictions
from avaris.pipeline.train import train
from avaris.seasons import et_date, season_for_date

Progress = Callable[[str], None]
# Refreshes stored data from the sources as of now (naive UTC)
Refresher = Callable[[duckdb.DuckDBPyConnection, datetime, Progress], None]
Models = dict[str, tuple[GamePredictor, dict[str, Any]]]

DRIVER_SCALE = {"home_win": "log_odds", "margin": "points", "total": "points"}
TOP_DRIVERS = 3
# A prediction row is rewritten only when one of these changed
COMPARED = [
    "status", "decision_ts", "report_ts", "feature_hash", "home_win_run", "margin_run",
    "total_run", "p_home_win", "margin_mu", "margin_sigma", "total_mu", "total_sigma",
    "drivers", "injuries",
]


@dataclass
class DailySummary:
    refreshed: bool = False
    retrained: list[str] = field(default_factory=list)  # one line per target
    provisional: int = 0  # rows written
    final: int = 0
    unchanged: int = 0
    scored: int = 0
    warnings: list[str] = field(default_factory=list)


def make_stats_client(settings: Settings) -> StatsClient:
    cfg = settings.stats
    return StatsClient(
        cache=RawCache(settings.paths.cache_dir), throttle=Throttle(cfg.min_interval_s),
        timeout_s=cfg.timeout_s, max_attempts=cfg.max_attempts,
    )


def make_injury_client(settings: Settings) -> InjuryClient:
    cfg = settings.injuries
    return InjuryClient(
        settings.paths.cache_dir, Throttle(cfg.min_interval_s), timeout_s=cfg.timeout_s,
        max_attempts=cfg.max_attempts,
    )


def source_refresher(settings: Settings) -> Refresher:
    # This season's schedule, game logs, rosters and injury reports
    def refresh(con: duckdb.DuckDBPyConnection, now: datetime, progress: Progress) -> None:
        today = et_date(now)
        season = season_for_date(today)
        stats = make_stats_client(settings)
        try:
            ingest_stats(con, stats, [season], today=today,
                         refetch_days=settings.stats.refetch_days, progress=progress)
        finally:
            stats.close()
        injuries = make_injury_client(settings)
        try:
            ingest_injuries(con, injuries, [season], now_utc=now,
                            step_back_hours=settings.injuries.step_back_hours, progress=progress)
        finally:
            injuries.close()

    return refresh


def prediction_status(tip_off_utc: datetime, now: datetime) -> str:
    # Final once tip-off - 60 min has passed: the injury report is frozen then
    return "final" if now >= tip_off_utc - DECISION_LEAD else "provisional"


def is_stale(registry: Registry, today: date, every_days: int) -> bool:
    # Stale when a target has no production model, or its newest run (production or a
    # held candidate) was trained on data cut off every_days or more ago
    for target in TARGETS:
        production = registry.production(target)
        if production is None:
            return True
        runs = [production, *registry.candidates(target)]
        newest = max(date.fromisoformat(registry.read_meta(target, r)["through"]) for r in runs)
        if (today - newest).days >= every_days:
            return True
    return False


def load_models(registry: Registry) -> Models:
    models: Models = {}
    for target in TARGETS:
        predictor, meta = registry.load_production(target, feature_hash())
        if not isinstance(predictor, GamePredictor):
            raise TypeError(f"{target} artifact {meta['run_id']} is not a GamePredictor")
        models[target] = (predictor, meta)
    return models


def due_games(
    features: pd.DataFrame, games: pd.DataFrame, finals: set[str], now: datetime
) -> pd.DataFrame:
    # This season's games dated today (ET) or earlier, with a tip-off and no final yet
    today = et_date(now)
    rows = features.merge(games[["game_id", "tip_off_utc"]], on="game_id")
    keep = (
        (rows["season"] == season_for_date(today))
        & (pd.to_datetime(rows["game_date_et"]).dt.date <= today)
        & ~rows["game_id"].isin(finals)
    )
    return rows[keep].reset_index(drop=True)


def _clean(value: Any) -> Any:
    # JSON-safe: numpy scalars to Python, NaN to null
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float | int | str | bool):
        return value
    return None if pd.isna(value) else str(value)


def _json(value: Any) -> str:
    return json.dumps(_clean(value), sort_keys=True, allow_nan=False)


def _drivers(models: Models, rows: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{} for _ in range(len(rows))]
    for target, (predictor, _) in models.items():
        x = inputs(rows, predictor.rung, "report")
        drivers = explain(predictor.model, target, x)
        families = drivers.families()
        for i in range(len(rows)):
            fam = families.iloc[i]
            out[i][target] = {
                "scale": DRIVER_SCALE[target], "base": float(drivers.base[i]),
                "families": fam.to_dict(), "top": top_drivers(fam, TOP_DRIVERS),
            }
    return out


def _injuries(fs: FeatureSet, rows: pd.DataFrame, names: dict[int, str]) -> list[dict[str, Any]]:
    # Strength lost per side on the decision report; null when unknown (preseason)
    avail = fs.availability
    impact: dict[tuple[str, int], dict[str, Any]] = {}
    if not avail.empty:
        subset = avail[avail["game_id"].isin(rows["game_id"])]
        if not subset.empty:
            for r in injury_impact(subset, "report", names).to_dict("records"):
                impact[(str(r["game_id"]), int(r["team_id"]))] = {
                    k: r[k] for k in ("full_strength", "lost", "lost_share", "players")
                }
    return [{
        "home": impact.get((str(r["game_id"]), int(r["home_team_id"]))),
        "away": impact.get((str(r["game_id"]), int(r["away_team_id"]))),
    } for r in rows.to_dict("records")]


def prediction_rows(
    fs: FeatureSet, rows: pd.DataFrame, models: Models, names: dict[int, str], now: datetime
) -> pd.DataFrame:
    # One predictions row per game in rows: live availability is the decision report
    if rows.empty:
        return pd.DataFrame(columns=["game_id", *COMPARED, "predicted_at"])
    out = pd.DataFrame({
        "game_id": rows["game_id"].to_numpy(),
        "status": [prediction_status(pd.Timestamp(t).to_pydatetime(), now)
                   for t in rows["tip_off_utc"]],
        "decision_ts": pd.to_datetime(rows["decision_ts"]).to_numpy(),
        "report_ts": pd.to_datetime(rows["report_ts"]).to_numpy(),
        "predicted_at": now, "feature_hash": feature_hash(),
    })
    for target, (predictor, meta) in models.items():
        pred = predictor.predict(rows, "report")
        out[f"{target}_run"] = meta["run_id"]
        if target == "home_win":
            out["p_home_win"] = pred["pred"].to_numpy()
        else:
            out[f"{target}_mu"] = pred["pred"].to_numpy()
            out[f"{target}_sigma"] = pred["sigma"].to_numpy()
    out["drivers"] = [_json(d) for d in _drivers(models, rows)]
    out["injuries"] = [_json(i) for i in _injuries(fs, rows, names)]
    return out


def _fingerprint(row: Mapping[Any, Any]) -> str:
    values = {}
    for col in COMPARED:
        v = row[col]
        if col.endswith("_ts"):
            v = None if v is None or pd.isna(v) else pd.Timestamp(v).isoformat()
        values[col] = v
    return json.dumps(_clean(values), sort_keys=True)


def write_predictions(
    con: duckdb.DuckDBPyConnection, new: pd.DataFrame, summary: DailySummary
) -> None:
    # Provisional rows are replaced only when a value changed; a final row is never replaced
    if new.empty:
        return
    stored = con.execute(
        "select * from predictions where game_id in (select unnest(?::varchar[]))",
        [new["game_id"].tolist()],
    ).df()
    existing = {str(r["game_id"]): r for r in stored.to_dict("records")}
    keep = []
    for i, row in enumerate(new.to_dict("records")):
        old = existing.get(str(row["game_id"]))
        if old is not None and (old["status"] == "final" or _fingerprint(old) == _fingerprint(row)):
            summary.unchanged += 1
            continue
        keep.append(i)
        if row["status"] == "final":
            summary.final += 1
        else:
            summary.provisional += 1
    upsert(con, "predictions", new.iloc[keep])


def predict_due(
    con: duckdb.DuckDBPyConnection, fs: FeatureSet, models: Models, now: datetime,
    summary: DailySummary,
) -> None:
    games = con.execute("select game_id, tip_off_utc from games").df()
    finals = {r[0] for r in con.execute(
        "select game_id from predictions where status = 'final'").fetchall()}
    rows = due_games(fs.features, games, finals, now)
    # Only games no production model trained on (dated on or after every run's cutoff)
    through = max(date.fromisoformat(meta["through"]) for _, meta in models.values())
    rows = rows[pd.to_datetime(rows["game_date_et"]).dt.date >= through].reset_index(drop=True)
    names = player_names(con) if len(rows) else {}
    write_predictions(con, prediction_rows(fs, rows, models, names, now), summary)


def run_daily(
    con: duckdb.DuckDBPyConnection,
    settings: Settings,
    now: datetime,
    refresh: Refresher | None,
    progress: Progress = lambda _msg: None,
) -> DailySummary:
    # Refresh → features → predict with the current models (catch-up finals come from a
    # model that never saw them) → retrain when stale → predict again → score.
    # Idempotent: a rerun with no new data writes nothing
    summary = DailySummary()
    today = et_date(now)
    if refresh is not None:
        try:
            refresh(con, now, progress)
            summary.refreshed = True
        except (httpx.HTTPError, OSError) as exc:
            summary.warnings.append(f"refresh failed, using stored data: {exc}")
            progress(summary.warnings[-1])
    fs = build_features(con)
    write_features(con, fs)
    progress(f"features: {len(fs.features)} games")
    registry = Registry(settings.models.models_dir)
    if all(registry.production(t) for t in TARGETS):
        predict_due(con, fs, load_models(registry), now, summary)
    if is_stale(registry, today, settings.models.retrain_every_days):
        data = with_targets(fs.features, con)
        for r in train(data, settings.models, through=today, now=now):
            line = f"{r.target}: run {r.run_id} " + (
                "promoted" if r.decision.promoted
                else "held as candidate (" + "; ".join(r.decision.reasons) + ")"
            )
            summary.retrained.append(line)
            if not r.decision.promoted:
                summary.warnings.append(line)
            progress(line)
        predict_due(con, fs, load_models(registry), now, summary)
    summary.scored = score_predictions(con, now)
    progress(
        f"predictions: {summary.provisional} provisional, {summary.final} final written, "
        f"{summary.unchanged} unchanged; {summary.scored} scored"
    )
    return summary
