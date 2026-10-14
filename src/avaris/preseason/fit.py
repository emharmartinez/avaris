import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from avaris.backtest.metrics import score
from avaris.backtest.walkforward import walk_forward
from avaris.config import ModelsSettings, Settings
from avaris.features.build import build_features
from avaris.models.dataset import with_targets
from avaris.preseason.rest import P_CLIP, RestParams
from avaris.seasons import season_range

TARGETS = ("margin", "total", "home_win")
NEWTON_STEPS = 50
# Gate metric per output: lower is better
GATE_METRIC = {"margin": "mae", "total": "mae", "home_win": "log_loss"}
Predict = Callable[[pd.DataFrame, ModelsSettings, list[str]], pd.DataFrame]


@dataclass(frozen=True)
class RestFit:
    params: RestParams
    report: dict[str, Any]


def preseason_predictions(
    data: pd.DataFrame, cfg: ModelsSettings, seasons: list[str]
) -> pd.DataFrame:
    # Walk-forward with the production rungs and frozen parameters, one refit per season:
    # a preseason game is predicted by a model trained on earlier seasons only. One row per
    # preseason game: game_id, season, <target>_y, <target>_pred
    out: pd.DataFrame | None = None
    for target in TARGETS:
        t = cfg.target(target)
        preds = walk_forward(
            data, target, t.rung, t.params(), cfg.seed, seasons, "season",
            oof_seasons=cfg.oof_seasons, isotonic=t.calibration == "isotonic",
        )
        preds = preds[preds["season_type"] == "preseason"][["game_id", "season", "y", "pred"]]
        preds = preds.rename(columns={"y": f"{target}_y", "pred": f"{target}_pred"})
        out = preds if out is None else out.merge(preds, on=["game_id", "season"])
    assert out is not None
    return out.reset_index(drop=True)


def k_ols(residual: np.ndarray, x: np.ndarray) -> float:
    # residual = y - pred = -k x: least squares without intercept
    sxx = float(np.dot(x, x))
    return 0.0 if sxx == 0 else -float(np.dot(residual, x)) / sxx


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, P_CLIP, 1 - P_CLIP)
    return np.log(p / (1 - p))


def k_logistic(y: np.ndarray, p: np.ndarray, x: np.ndarray) -> float:
    # Maximum likelihood of P(y) = sigmoid(logit(p) - k x), logit(p) as offset (Newton)
    offset, k = _logit(p), 0.0
    for _ in range(NEWTON_STEPS):
        q = 1 / (1 + np.exp(-(offset - k * x)))
        grad = float(np.dot(y - q, -x))
        hess = -float(np.dot(q * (1 - q), x * x))
        if hess == 0:
            break
        step = grad / hess
        k -= step
        if abs(step) < 1e-10:
            break
    return k


def adjusted(frame: pd.DataFrame, k_margin: float, k_total: float, k_win: float) -> pd.DataFrame:
    diff = frame["home_lost"] - frame["away_lost"]
    total = frame["home_lost"] + frame["away_lost"]
    z = _logit(frame["home_win_pred"].to_numpy()) - k_win * diff.to_numpy()
    return frame.assign(
        margin_pred=frame["margin_pred"] - k_margin * diff,
        total_pred=frame["total_pred"] - k_total * total,
        home_win_pred=1 / (1 + np.exp(-z)),
    )


def _metrics(frame: pd.DataFrame) -> dict[str, float]:
    return {
        t: score(t, frame[f"{t}_y"].to_numpy(), frame[f"{t}_pred"].to_numpy())[GATE_METRIC[t]]
        for t in TARGETS
    }


def fit_coefficients(frame: pd.DataFrame, fit_seasons: list[str], gate_seasons: list[str]
                     ) -> RestFit:
    # k fitted on fit_seasons, each switched on only if it beats the raw model on
    # gate_seasons (ADR-022). frame: one row per preseason game with home_lost, away_lost
    # (who actually sat out), <target>_y and <target>_pred
    fit = frame[frame["season"].isin(fit_seasons)]
    gate = frame[frame["season"].isin(gate_seasons)]
    for name, rows in (("fit", fit), ("gate", gate)):
        if rows.empty:
            raise ValueError(f"no preseason games with box scores in the {name} window: "
                             "run `avaris ingest preseason-logs`")
    diff = (fit["home_lost"] - fit["away_lost"]).to_numpy()
    k = {
        "margin": k_ols((fit["margin_y"] - fit["margin_pred"]).to_numpy(), diff),
        "total": k_ols((fit["total_y"] - fit["total_pred"]).to_numpy(),
                       (fit["home_lost"] + fit["away_lost"]).to_numpy()),
        "home_win": k_logistic(fit["home_win_y"].to_numpy(), fit["home_win_pred"].to_numpy(),
                               diff),
    }
    raw, adj = _metrics(gate), _metrics(adjusted(gate, k["margin"], k["total"], k["home_win"]))
    use = {t: adj[t] < raw[t] for t in TARGETS}
    params = RestParams(k["margin"], k["total"], k["home_win"], use["margin"], use["total"],
                        use["home_win"])
    report = {
        "fit_seasons": fit_seasons, "gate_seasons": gate_seasons,
        "n_fit": len(fit), "n_gate": len(gate), "k": k,
        "gate": {t: {"metric": GATE_METRIC[t], "raw": raw[t], "adjusted": adj[t],
                     "enabled": use[t]} for t in TARGETS},
    }
    return RestFit(params, report)


def fit_rest(
    con: duckdb.DuckDBPyConnection, settings: Settings,
    predict: Predict = preseason_predictions, now: datetime | None = None,
) -> RestFit:
    # Fit on the tuning window, gate on the evaluation window; the holdout is never read
    cfg = settings.models
    fit_seasons = season_range(cfg.tune_first_season, cfg.tune_last_season)
    gate_seasons = season_range(cfg.eval_first_season, cfg.eval_last_season)
    if max(gate_seasons) >= cfg.holdout_season or max(fit_seasons) >= cfg.holdout_season:
        raise ValueError(f"the rest fit must not reach the {cfg.holdout_season} holdout")
    fs = build_features(con, settings.espn.out_window_hours)
    data = with_targets(fs.features, con)
    data = data[data["season"] <= gate_seasons[-1]].reset_index(drop=True)
    preds = predict(data, cfg, [*fit_seasons, *gate_seasons])
    lost = fs.rest[["game_id", "home_lost_actual", "away_lost_actual"]].rename(
        columns={"home_lost_actual": "home_lost", "away_lost_actual": "away_lost"})
    frame = preds.merge(lost, on="game_id").dropna(subset=["home_lost", "away_lost"])
    fit = fit_coefficients(frame, fit_seasons, gate_seasons)
    p = fit.params
    fitted_at = now or datetime.now(UTC).replace(tzinfo=None)
    con.execute(
        "insert into rest_params values (?, ?, ?, ?, ?, ?, ?, ?)",
        [fitted_at, p.k_margin, p.k_total, p.k_win, p.use_margin, p.use_total, p.use_win,
         json.dumps(fit.report, sort_keys=True)],
    )
    return RestFit(RestParams(p.k_margin, p.k_total, p.k_win, p.use_margin, p.use_total,
                              p.use_win, fitted_at), fit.report)
