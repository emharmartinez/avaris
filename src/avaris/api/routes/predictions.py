import json
from datetime import date
from typing import Any

from fastapi import APIRouter

from avaris.api.deps import AppClock, Cursor, rows, team
from avaris.backtest.metrics import Z_80
from avaris.seasons import et_date

router = APIRouter(prefix="/api/predictions", tags=["predictions"])

GAMES_SQL = """
select g.game_id, g.season, g.season_type, g.game_date_et, g.tip_off_utc,
    g.status as game_status, g.home_team_id, g.away_team_id, g.home_pts, g.away_pts,
    g.neutral_site, g.venue,
    p.status, p.decision_ts, p.report_ts, p.predicted_at, p.home_win_run, p.margin_run,
    p.total_run, p.p_home_win, p.margin_mu, p.margin_sigma, p.total_mu, p.total_sigma,
    p.drivers, p.injuries, p.raw_p_home_win, p.raw_margin_mu, p.raw_total_mu, p.rest
from games g left join predictions p using (game_id)
"""


def _interval(mu: float, sigma: float) -> dict[str, float]:
    return {"mu": mu, "sigma": sigma, "lo": mu - Z_80 * sigma, "hi": mu + Z_80 * sigma}


def _impact(side: dict[str, Any] | None) -> dict[str, Any] | None:
    if side is None:
        return None
    return {k: side[k] for k in ("full_strength", "lost", "lost_share")}


def _rest(row: dict[str, Any]) -> dict[str, Any] | None:
    # Preseason only (ADR-022): the ESPN out list, the k applied and the model's raw values
    if row["rest"] is None:
        return None
    return {**json.loads(row["rest"]), "raw_p_home_win": row["raw_p_home_win"],
            "raw_margin_mu": row["raw_margin_mu"], "raw_total_mu": row["raw_total_mu"]}


def prediction_view(row: dict[str, Any], full: bool) -> dict[str, Any] | None:
    # Probability, mu with the 80% interval, top drivers and injury impact; full adds
    # every driver family and the players behind the strength lost
    if row["status"] is None:
        return None
    drivers = json.loads(row["drivers"])
    injuries = json.loads(row["injuries"])
    view: dict[str, Any] = {
        "status": row["status"], "decision_ts": row["decision_ts"],
        "report_ts": row["report_ts"], "predicted_at": row["predicted_at"],
        "runs": {t: row[f"{t}_run"] for t in ("home_win", "margin", "total")},
        "p_home_win": row["p_home_win"],
        "margin": _interval(row["margin_mu"], row["margin_sigma"]),
        "total": _interval(row["total_mu"], row["total_sigma"]),
        "top_drivers": {t: d["top"] for t, d in drivers.items()},
        "injury_impact": {side: _impact(v) for side, v in injuries.items()},
        "rest": _rest(row),
    }
    if full:
        view["drivers"] = drivers
        view["injuries"] = injuries
    return view


def game_view(row: dict[str, Any], full: bool = False) -> dict[str, Any]:
    final = row["game_status"] == "final" and row["home_pts"] is not None
    return {
        "game_id": row["game_id"], "season": row["season"], "season_type": row["season_type"],
        "game_date_et": row["game_date_et"], "tip_off_utc": row["tip_off_utc"],
        "game_status": row["game_status"], "neutral_site": row["neutral_site"],
        "venue": row["venue"], "home": team(row["home_team_id"]),
        "away": team(row["away_team_id"]),
        "result": {"home_pts": row["home_pts"], "away_pts": row["away_pts"]} if final else None,
        "prediction": prediction_view(row, full),
    }


def games_on(cur: Any, day: date) -> list[dict[str, Any]]:
    found = rows(cur, GAMES_SQL + " where g.game_date_et = ? order by g.tip_off_utc, g.game_id",
                 [day])
    return [game_view(r) for r in found]


@router.get("/today")
def today(cur: Cursor, clock: AppClock) -> dict[str, Any]:
    day = et_date(clock())
    return {"date": day.isoformat(), "games": games_on(cur, day)}


@router.get("")
def by_date(cur: Cursor, date: date) -> dict[str, Any]:
    return {"date": date.isoformat(), "games": games_on(cur, date)}
