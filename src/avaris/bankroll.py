# Bet tracking (ADR-026): bets the user records from the Edge tab, graded from final scores.
# Results and the bankroll are derived on read, never stored, so a score correction or a
# changed starting bankroll needs no rewrite. Odds are decimal.
from collections.abc import Mapping, Sequence
from typing import Any, Literal

Market = Literal["moneyline", "spread", "total"]
Side = Literal["home", "away", "over", "under"]
Result = Literal["pending", "won", "lost", "push"]

SIDES: dict[str, tuple[str, str]] = {
    "moneyline": ("away", "home"), "spread": ("away", "home"), "total": ("over", "under"),
}


def grade(
    market: str, side: str, line: float | None, home_pts: int | None, away_pts: int | None
) -> Result:
    # `line` is the bet side's own: its spread (home -3.5, away +3.5) or the total
    if home_pts is None or away_pts is None:
        return "pending"
    if market == "total":
        assert line is not None
        diff = home_pts + away_pts - line
        diff = diff if side == "over" else -diff
    else:
        diff = home_pts - away_pts if side == "home" else away_pts - home_pts
        diff += line if market == "spread" and line is not None else 0
    return "won" if diff > 0 else "lost" if diff < 0 else "push"


def profit(result: str, odds: float, stake: float) -> float | None:
    # A push returns the stake
    return {"won": stake * (odds - 1), "lost": -stake, "push": 0.0}.get(result)


def summarize(
    starting: float | None, unit_pct: float | None, bets: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    # The bankroll is the starting amount plus settled profit; a unit is unit_pct of it
    settled = [b for b in bets if b["result"] != "pending"]
    total = sum(b["profit"] for b in settled)
    decided = sum(b["stake"] for b in settled if b["result"] != "push")
    current = None if starting is None else starting + total
    record = {r: sum(b["result"] == r for b in bets) for r in ("won", "lost", "push", "pending")}
    return {
        "starting": starting, "unit_pct": unit_pct, "current": current,
        "unit": None if current is None or unit_pct is None
        else max(current, 0.0) * unit_pct / 100,
        "profit": total,
        "in_play": sum(b["stake"] for b in bets if b["result"] == "pending"),
        "record": record,
        "roi": total / decided if decided else None,
    }
