import pytest

from avaris.bankroll import grade, profit, summarize

# A final 110-100 home win: margin +10, total 210


@pytest.mark.parametrize(("market", "side", "line", "result"), [
    ("moneyline", "home", None, "won"),
    ("moneyline", "away", None, "lost"),
    ("spread", "home", -9.5, "won"),
    ("spread", "home", -10.0, "push"),
    ("spread", "home", -10.5, "lost"),
    ("spread", "away", 10.5, "won"),
    ("spread", "away", 10.0, "push"),
    ("spread", "away", 9.5, "lost"),
    ("spread", "away", -2.5, "lost"),
    ("total", "over", 209.5, "won"),
    ("total", "over", 210.0, "push"),
    ("total", "under", 209.5, "lost"),
    ("total", "under", 210.5, "won"),
])
def test_grade_a_final(market: str, side: str, line: float | None, result: str) -> None:
    assert grade(market, side, line, 110, 100) == result


def test_grade_is_pending_without_a_score() -> None:
    assert grade("moneyline", "home", None, None, None) == "pending"
    assert grade("total", "over", 210.5, 110, None) == "pending"


def test_profit_pays_decimal_odds_and_returns_a_push() -> None:
    assert profit("won", 2.5, 10) == 15
    assert profit("lost", 2.5, 10) == -10
    assert profit("push", 2.5, 10) == 0
    assert profit("pending", 2.5, 10) is None


def bet(result: str, stake: float, odds: float = 2.0) -> dict[str, object]:
    return {"result": result, "stake": stake, "odds": odds, "profit": profit(result, odds, stake)}


def test_summarize_settles_into_the_bankroll_and_sizes_the_unit() -> None:
    bets = [bet("won", 10, 1.9), bet("lost", 20), bet("push", 5), bet("pending", 30)]
    s = summarize(1000, 1, bets)
    assert s["starting"] == 1000 and s["unit_pct"] == 1
    assert s["profit"] == pytest.approx(9 - 20)
    assert s["current"] == pytest.approx(989)
    assert s["unit"] == pytest.approx(9.89)  # 1% of the current bankroll
    assert s["in_play"] == 30
    assert s["record"] == {"won": 1, "lost": 1, "push": 1, "pending": 1}
    assert s["roi"] == pytest.approx(-11 / 30)  # profit over won and lost stakes


def test_summarize_without_a_bankroll_or_bets() -> None:
    s = summarize(None, None, [])
    assert s["current"] is None and s["unit"] is None and s["roi"] is None
    assert s["profit"] == 0 and s["in_play"] == 0
    assert summarize(1000, 2, [])["unit"] == 20  # 2% of 1000


def test_a_busted_bankroll_has_no_unit_to_stake() -> None:
    assert summarize(10, 1, [bet("lost", 20)])["unit"] == 0
