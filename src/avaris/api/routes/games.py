from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path

from avaris.api.deps import Cursor, rows
from avaris.api.routes.predictions import GAMES_SQL, game_view

router = APIRouter(prefix="/api/games", tags=["games"])

GameId = Annotated[str, Path(pattern=r"^[0-9]{10}$")]
RATINGS_SQL = """
select game_id, as_of_ts, elo, ortg, drtg, net, pace, net_l10, gp from team_ratings
where team_id = ? and season = ? and as_of_ts <= ? order by as_of_ts, game_id
"""


@router.get("/{game_id}")
def game(cur: Cursor, game_id: GameId) -> dict[str, Any]:
    # Prediction with every driver family, injury report entries at the decision report,
    # both teams' ratings this season up to the game, and the score once final
    found = rows(cur, GAMES_SQL + " where g.game_id = ?", [game_id])
    if not found:
        raise HTTPException(404, f"no game {game_id}")
    row = found[0]
    view = game_view(row, full=True)
    feature = rows(cur, "select decision_ts, report_ts from features where game_id = ?",
                   [game_id])
    decision = row["decision_ts"] or (feature[0]["decision_ts"] if feature else None)
    report_ts = row["report_ts"] if row["status"] else (feature[0]["report_ts"] if feature
                                                         else None)
    view["injury_report"] = rows(
        cur,
        "select team_id, player_id, player_name, status, reason from injury_reports "
        "where report_ts = ?::timestamp and game_date_et = ? and team_id in (?, ?) "
        "order by team_id, player_name",
        [_naive(report_ts), row["game_date_et"], row["home_team_id"], row["away_team_id"]],
    ) if report_ts else []
    view["ratings"] = {
        side: rows(cur, RATINGS_SQL, [row[f"{side}_team_id"], row["season"], _naive(decision)])
        if decision else []
        for side in ("home", "away")
    }
    scores = rows(cur, "select * exclude (game_id) from prediction_scores where game_id = ?",
                  [game_id])
    view["score"] = scores[0] if scores else None
    return view


def _naive(ts: str | None) -> str | None:
    return ts.removesuffix("Z") if ts else None
