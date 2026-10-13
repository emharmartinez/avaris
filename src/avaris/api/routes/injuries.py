import json
from datetime import date
from typing import Any

from fastapi import APIRouter

from avaris.api.deps import Cursor, rows, team

router = APIRouter(prefix="/api/injuries", tags=["injuries"])


@router.get("")
def injuries(cur: Cursor, date: date) -> dict[str, Any]:
    # Per game on the date: strength lost per side and the entries of the report the
    # prediction used
    games = rows(cur, """
        select g.game_id, g.home_team_id, g.away_team_id, p.report_ts, p.injuries
        from games g join predictions p using (game_id)
        where g.game_date_et = ? order by g.tip_off_utc, g.game_id
    """, [date])
    out = []
    for g in games:
        entries = rows(cur, """
            select team_id, player_id, player_name, status, reason from injury_reports
            where report_ts = ?::timestamp and game_date_et = ? and team_id in (?, ?)
            order by team_id, player_name
        """, [g["report_ts"].removesuffix("Z"), date, g["home_team_id"],
              g["away_team_id"]]) if g["report_ts"] else []
        out.append({
            "game_id": g["game_id"], "home": team(g["home_team_id"]),
            "away": team(g["away_team_id"]), "report_ts": g["report_ts"],
            "impact": json.loads(g["injuries"]), "entries": entries,
        })
    return {"date": date.isoformat(), "games": out}
