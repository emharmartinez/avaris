from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from avaris.api.deps import TEAMS, AppClock, Cursor, rows, team
from avaris.seasons import et_date, season_for_date

router = APIRouter(prefix="/api/teams", tags=["teams"])

Season = Annotated[str | None, Query(pattern=r"^[0-9]{4}-[0-9]{2}$")]


@router.get("")
def teams(cur: Cursor, clock: AppClock) -> list[dict[str, Any]]:
    # Each team's latest ratings as of now, strongest Elo first
    latest = rows(cur, """
        select team_id, season, game_id, as_of_ts, elo, ortg, drtg, net, pace, net_l10, gp
        from team_ratings where as_of_ts <= ?
        qualify row_number() over (partition by team_id order by as_of_ts desc, game_id desc) = 1
        order by elo desc
    """, [clock()])
    return [{**team(r["team_id"]), **r} for r in latest]


@router.get("/{team_id}")
def team_history(
    cur: Cursor, clock: AppClock, team_id: int, season: Season = None
) -> dict[str, Any]:
    if team_id not in TEAMS:
        raise HTTPException(404, f"no team {team_id}")
    season = season or season_for_date(et_date(clock()))
    history = rows(cur, """
        select game_id, as_of_ts, elo, ortg, drtg, net, pace, net_l10, gp from team_ratings
        where team_id = ? and season = ? and as_of_ts <= ? order by as_of_ts, game_id
    """, [team_id, season, clock()])
    return {"team": team(team_id), "season": season, "ratings": history}
