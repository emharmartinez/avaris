from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from avaris.api.deps import TEAMS, AppClock, Cursor, rows, team
from avaris.seasons import et_date, season_for_date

router = APIRouter(prefix="/api/teams", tags=["teams"])

Season = Annotated[str | None, Query(pattern=r"^[0-9]{4}-[0-9]{2}$")]


# A team's ratings now are its next game's pre-game snapshot: a snapshot only holds results
# already stored, so it includes the last game played (the latest one before now does not).
# Without a next game, the latest snapshot
CURRENT_SQL = """
select team_id, season, game_id, as_of_ts, elo, ortg, drtg, net, pace, net_l10, gp
from team_ratings where {where}
qualify row_number() over (
    partition by team_id
    order by (as_of_ts >= $now) desc,
        case when as_of_ts >= $now then as_of_ts end asc,
        as_of_ts desc, game_id
) = 1
"""
COLUMNS = "game_id, as_of_ts, elo, ortg, drtg, net, pace, net_l10, gp"


@router.get("")
def teams(cur: Cursor, clock: AppClock) -> list[dict[str, Any]]:
    # Each team's current ratings, strongest Elo first
    current = rows(cur, CURRENT_SQL.format(where="true") + " order by elo desc",
                   {"now": clock()})
    return [{**team(r["team_id"]), **r} for r in current]


@router.get("/{team_id}")
def team_history(
    cur: Cursor, clock: AppClock, team_id: int, season: Season = None
) -> dict[str, Any]:
    if team_id not in TEAMS:
        raise HTTPException(404, f"no team {team_id}")
    season = season or season_for_date(et_date(clock()))
    # Pre-game snapshots up to now, then the current ratings
    params = {"now": clock(), "team": team_id, "season": season}
    history = rows(cur, f"""
        select {COLUMNS} from team_ratings
        where team_id = $team and season = $season and as_of_ts < $now
        union
        select {COLUMNS} from ({CURRENT_SQL.format(where="team_id = $team and season = $season")})
        order by as_of_ts, game_id
    """, params)
    return {"team": team(team_id), "season": season, "ratings": history}
