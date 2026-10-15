from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from avaris.api.deps import AppClock, Cursor, json_value, rows, team
from avaris.api.routes.predictions import interval
from avaris.ingest.scoreboard import LiveGame, LiveScoreboard, LiveSnapshot
from avaris.seasons import et_date
from avaris.traditional.live import clock_minutes, format_clock, game_minutes, live_update
from avaris.traditional.pregame import Line, pregame

router = APIRouter(prefix="/api/traditional", tags=["traditional"])

FEATURES = [
    "elo_margin", "league_total", "league_pace", "home_court", "no_fans", "home_b2b",
    "away_b2b", "home_gp", "away_gp",
    *(f"{side}_{stat}_std" for side in ("home", "away") for stat in ("ortg", "drtg", "pace")),
]
# Each game with its latest features row (point-in-time at decision_ts); `tipped` is
# whether the listed tip-off has passed
GAMES_SQL = f"""
select g.game_id, g.season_type, g.tip_off_utc, g.status, g.home_team_id, g.away_team_id,
    g.home_pts, g.away_pts, coalesce(g.tip_off_utc <= ?, false) as tipped,
    {", ".join(f"f.{name}" for name in FEATURES)}
from games g left join (
    select * from features
    qualify row_number() over (partition by game_id order by decision_ts desc) = 1
) f on f.game_id = g.game_id
where g.game_date_et = ?
order by g.tip_off_utc, g.game_id
"""


def _live(request: Request) -> LiveScoreboard:
    return request.app.state.live


Live = Annotated[LiveScoreboard, Depends(_live)]


def _line(line: Line) -> dict[str, Any]:
    return {"p_home_win": line.p_home_win,
            "margin": interval(line.margin_mu, line.margin_sigma),
            "total": interval(line.total_mu, line.total_sigma)}


def _live_view(game: LiveGame, pre: Line | None) -> dict[str, Any] | None:
    if game.status != "in_progress" or pre is None:
        return None
    clock = clock_minutes(game.clock)
    elapsed, left = game_minutes(game.period, clock, game.regulation_periods)
    return {"period": game.period, "clock": format_clock(clock), "label": game.label,
            "minutes_left": left,
            **_line(live_update(pre, game.home_pts, game.away_pts, elapsed, left))}


def _game_view(row: dict[str, Any], live: LiveGame | None) -> dict[str, Any]:
    pre = pregame(row)
    status = live.status if live is not None else row["status"]
    if live is not None and live.status != "scheduled":
        score = {"home_pts": live.home_pts, "away_pts": live.away_pts}
    elif row["status"] == "final" and row["home_pts"] is not None:
        score = {"home_pts": row["home_pts"], "away_pts": row["away_pts"]}
    else:
        score = None
    return {
        "game_id": row["game_id"], "season_type": row["season_type"],
        "tip_off_utc": row["tip_off_utc"], "home": team(row["home_team_id"]),
        "away": team(row["away_team_id"]), "status": status, "score": score,
        "pregame": None if pre is None else {**_line(pre), "inputs": pre.inputs},
        "live": None if live is None else _live_view(live, pre),
    }


@router.get("")
def traditional(
    cur: Cursor, clock: AppClock, live: Live, date: date | None = None
) -> dict[str, Any]:
    # The rule-based model (ADR-024): pregame lines for every game, and live lines from the
    # scoreboard for today's games that have started
    now = clock()
    today = et_date(now)
    day = date or today
    found = rows(cur, GAMES_SQL, [now, day])
    started = any(r["status"] == "in_progress" or (r["tipped"] and r["status"] != "final")
                  for r in found)
    snapshot = live.get(day) if day == today and started else LiveSnapshot()
    return {
        "date": day.isoformat(), "is_today": day == today,
        "live_at": json_value(snapshot.fetched_at), "live_error": snapshot.error,
        "games": [_game_view(r, snapshot.games.get(r["game_id"])) for r in found],
    }
