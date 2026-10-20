from typing import Annotated, Any, Self

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from avaris.api.deps import AppClock, Cursor, not_cross_site, rows, team
from avaris.bankroll import SIDES, Market, Side, grade, profit, summarize

# Bet tracking (ADR-026): the user's bankroll and the bets they record on the Edge tab
router = APIRouter(prefix="/api", tags=["bets"])

BETS_SQL = """
select b.bet_id, b.game_id, b.placed_at, b.market, b.side, b.line, b.odds, b.stake,
    g.game_date_et, g.tip_off_utc, g.season_type, g.status as game_status,
    g.home_team_id, g.away_team_id, g.home_pts, g.away_pts
from bets b join games g using (game_id)
"""


class BankrollIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starting: float = Field(gt=0)
    unit_pct: float = Field(gt=0, le=100)


class BetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game_id: str = Field(pattern=r"^[0-9]{10}$")
    market: Market
    side: Side
    line: float | None = None  # the side's own spread, or the total
    odds: float = Field(gt=1)  # decimal
    stake: float = Field(gt=0)

    @model_validator(mode="after")
    def check_market(self) -> Self:
        if self.side not in SIDES[self.market]:
            raise ValueError(f"a {self.market} bet is on {' or '.join(SIDES[self.market])}")
        if (self.market == "moneyline") != (self.line is None):
            raise ValueError("a spread or total bet needs a line; a moneyline bet has none")
        if self.market == "total" and self.line is not None and self.line <= 0:
            raise ValueError("a total line is above 0")
        return self


def bet_view(row: dict[str, Any]) -> dict[str, Any]:
    final = row["game_status"] == "final"
    result = grade(row["market"], row["side"], row["line"],
                   row["home_pts"] if final else None, row["away_pts"] if final else None)
    return {
        **{k: row[k] for k in ("bet_id", "game_id", "placed_at", "market", "side", "line",
                               "odds", "stake")},
        "result": result, "profit": profit(result, row["odds"], row["stake"]),
        "game": {
            "game_date_et": row["game_date_et"], "tip_off_utc": row["tip_off_utc"],
            "season_type": row["season_type"], "status": row["game_status"],
            "home": team(row["home_team_id"]), "away": team(row["away_team_id"]),
            "home_pts": row["home_pts"], "away_pts": row["away_pts"],
        },
    }


@router.get("/bankroll")
def bankroll(cur: Cursor) -> dict[str, Any]:
    # The bankroll with its unit, and every bet graded, newest first
    found = rows(cur, "select starting, unit_pct from bankroll where id = 1")
    settings = found[0] if found else {"starting": None, "unit_pct": None}
    bets = [bet_view(r) for r in rows(cur, BETS_SQL + " order by b.placed_at desc, b.bet_id desc")]
    return {**summarize(settings["starting"], settings["unit_pct"], bets), "bets": bets}


@router.put("/bankroll", dependencies=[Depends(not_cross_site)])
def set_bankroll(cur: Cursor, clock: AppClock, body: BankrollIn) -> dict[str, Any]:
    cur.execute("insert or replace into bankroll values (1, ?, ?, ?)",
                [body.starting, body.unit_pct, clock()])
    return bankroll(cur)


@router.post("/bets", status_code=201, dependencies=[Depends(not_cross_site)])
def place_bet(cur: Cursor, clock: AppClock, body: BetIn) -> dict[str, Any]:
    if not rows(cur, "select 1 from games where game_id = ?", [body.game_id]):
        raise HTTPException(404, f"no game {body.game_id}")
    found = cur.execute(
        "insert into bets (game_id, placed_at, market, side, line, odds, stake) "
        "values (?, ?, ?, ?, ?, ?, ?) returning bet_id",
        [body.game_id, clock(), body.market, body.side, body.line, body.odds, body.stake],
    ).fetchone()
    assert found is not None
    return bet_view(rows(cur, BETS_SQL + " where b.bet_id = ?", [found[0]])[0])


@router.delete("/bets/{bet_id}", status_code=204, dependencies=[Depends(not_cross_site)])
def delete_bet(cur: Cursor, bet_id: Annotated[int, Path(ge=1)]) -> Response:
    if not rows(cur, "delete from bets where bet_id = ? returning bet_id", [bet_id]):
        raise HTTPException(404, f"no bet {bet_id}")
    return Response(status_code=204)
