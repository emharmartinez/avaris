import math
from collections.abc import Callable, Sequence
from datetime import datetime

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from avaris.betting.devig import (
    american_to_decimal,
    decimal_to_american,
    devig_multiplicative,
    devig_shin,
    fair_probs,
    implied_prob,
    overround,
)

Devig = Callable[[Sequence[float]], list[float]]

TS = datetime(2025, 1, 10, 23, 0)
OUTPUT_COLUMNS = [
    "game_id",
    "snapshot_ts",
    "book",
    "market",
    "line",
    "price_a",
    "price_b",
    "p_fair",
    "overround",
    "method",
]


def shin_prices(fair: list[float], z: float) -> list[float]:
    # Shin's forward model: implied prob q_i = s_i * sum(s), s_i = sqrt(z*p_i + (1-z)*p_i^2)
    s = [math.sqrt(z * p + (1 - z) * p * p) for p in fair]
    return [1 / (si * sum(s)) for si in s]


def row(
    side: str,
    price: float,
    *,
    market: str = "h2h",
    line: float = math.nan,
    book: str = "fanduel",
    game_id: str = "0022400500",
    snapshot_ts: datetime = TS,
) -> dict[str, object]:
    return {
        "game_id": game_id,
        "snapshot_ts": snapshot_ts,
        "book": book,
        "market": market,
        "side": side,
        "line": line,
        "price": price,
        "kind": "decision",
    }


def frame(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


@pytest.mark.parametrize(
    ("american", "decimal"),
    [(150, 2.5), (-200, 1.5), (100, 2.0), (-100, 2.0), (-110, 1 + 100 / 110), (1000, 11.0)],
)
def test_american_to_decimal(american: float, decimal: float) -> None:
    assert american_to_decimal(american) == pytest.approx(decimal)


@pytest.mark.parametrize("american", [0, 99, -99.5, 50])
def test_american_to_decimal_rejects_inside_100(american: float) -> None:
    with pytest.raises(ValueError):
        american_to_decimal(american)


@pytest.mark.parametrize(
    ("decimal", "american"),
    [(2.5, 150), (1.5, -200), (2.0, 100), (11.0, 1000), (1 + 100 / 110, -110)],
)
def test_decimal_to_american(decimal: float, american: float) -> None:
    assert decimal_to_american(decimal) == pytest.approx(american)


@pytest.mark.parametrize("decimal", [1.0, 0.5, 0.0, -2.0])
def test_decimal_to_american_rejects_at_or_below_one(decimal: float) -> None:
    with pytest.raises(ValueError):
        decimal_to_american(decimal)


@given(st.floats(min_value=1.001, max_value=1000))
def test_decimal_american_round_trip(decimal: float) -> None:
    assert abs(american_to_decimal(decimal_to_american(decimal)) - decimal) < 1e-9


# Just below -100 the price rounds to even money (decimal 2.0), which is quoted +100
@given(st.one_of(st.floats(100, 100_000), st.floats(-100_000, -100.001)))
def test_american_decimal_round_trip(american: float) -> None:
    assert decimal_to_american(american_to_decimal(american)) == pytest.approx(american, rel=1e-9)


def test_even_money_is_quoted_plus_100() -> None:
    assert decimal_to_american(american_to_decimal(-100)) == 100


def test_implied_prob() -> None:
    assert implied_prob(2.0) == 0.5
    assert implied_prob(1.25) == pytest.approx(0.8)


@pytest.mark.parametrize("decimal", [1.0, 0.0, -1.5])
def test_implied_prob_rejects_invalid_price(decimal: float) -> None:
    with pytest.raises(ValueError):
        implied_prob(decimal)


def test_overround() -> None:
    assert overround([1.909090909, 1.909090909]) == pytest.approx(0.047619, abs=1e-6)
    assert overround([2.0, 2.0]) == pytest.approx(0.0)


def test_devig_multiplicative() -> None:
    probs = devig_multiplicative([1.25, 4.0])
    assert probs == pytest.approx([0.8 / 1.05, 0.25 / 1.05])
    assert sum(probs) == pytest.approx(1.0)


@pytest.mark.parametrize("devig", [devig_multiplicative, devig_shin])
@pytest.mark.parametrize("n", [2, 3, 5])
def test_equal_prices_give_uniform(devig: Devig, n: int) -> None:
    probs = devig([1.9] * n)
    assert probs == pytest.approx([1 / n] * n, abs=1e-10)


@pytest.mark.parametrize("devig", [devig_multiplicative, devig_shin])
def test_devig_rejects_single_outcome(devig: Devig) -> None:
    with pytest.raises(ValueError):
        devig([1.5])


@given(
    st.lists(st.floats(min_value=1.01, max_value=50), min_size=2, max_size=6),
)
def test_devig_probs_sum_to_one(prices: list[float]) -> None:
    for devig in (devig_multiplicative, devig_shin):
        probs = devig(prices)
        assert sum(probs) == pytest.approx(1.0, abs=1e-9)
        assert all(0 < p < 1 for p in probs)


def test_shin_recovers_forward_model_two_outcomes() -> None:
    prices = shin_prices([0.7, 0.3], z=0.02)
    assert devig_shin(prices) == pytest.approx([0.7, 0.3], abs=1e-9)


def test_shin_recovers_forward_model_three_outcomes() -> None:
    prices = shin_prices([0.5, 0.35, 0.15], z=0.05)
    assert devig_shin(prices) == pytest.approx([0.5, 0.35, 0.15], abs=1e-9)


def test_shin_shifts_probability_to_favorite() -> None:
    prices = [1.25, 4.0]
    mult = devig_multiplicative(prices)
    shin = devig_shin(prices)
    # Favorite-longshot bias: Shin strips more margin from the longshot
    assert shin[1] < mult[1]
    assert shin[0] > mult[0]


def test_shin_without_overround_is_multiplicative() -> None:
    prices = [1.8, 2.3]  # implied probs sum < 1
    assert overround(prices) < 0
    assert devig_shin(prices) == pytest.approx(devig_multiplicative(prices))


def test_fair_probs_h2h_pair() -> None:
    out = fair_probs(frame(row("home", 1.5), row("away", 2.8)))
    assert list(out.columns) == OUTPUT_COLUMNS
    assert len(out) == 1
    r = out.iloc[0]
    assert r["game_id"] == "0022400500"
    assert r["snapshot_ts"] == TS
    assert r["book"] == "fanduel"
    assert r["market"] == "h2h"
    assert math.isnan(r["line"])
    assert r["price_a"] == 1.5
    assert r["price_b"] == 2.8
    assert r["p_fair"] == pytest.approx((1 / 1.5) / (1 / 1.5 + 1 / 2.8))
    assert r["overround"] == pytest.approx(1 / 1.5 + 1 / 2.8 - 1)
    assert r["method"] == "multiplicative"


def test_fair_probs_spread_uses_home_line() -> None:
    # Away listed first to check side a is always home
    odds = frame(
        row("away", 1.95, market="spreads", line=3.5),
        row("home", 1.87, market="spreads", line=-3.5),
    )
    out = fair_probs(odds)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["line"] == -3.5
    assert r["price_a"] == 1.87
    assert r["price_b"] == 1.95
    assert r["p_fair"] == pytest.approx((1 / 1.87) / (1 / 1.87 + 1 / 1.95))


def test_fair_probs_spread_home_underdog_line_positive() -> None:
    odds = frame(
        row("home", 1.91, market="spreads", line=6.0),
        row("away", 1.91, market="spreads", line=-6.0),
    )
    out = fair_probs(odds)
    assert out.iloc[0]["line"] == 6.0
    assert out.iloc[0]["p_fair"] == pytest.approx(0.5)


def test_fair_probs_totals_pair() -> None:
    odds = frame(
        row("under", 1.95, market="totals", line=224.5),
        row("over", 1.87, market="totals", line=224.5),
    )
    out = fair_probs(odds)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["line"] == 224.5
    assert r["price_a"] == 1.87
    assert r["price_b"] == 1.95
    assert r["p_fair"] == pytest.approx((1 / 1.87) / (1 / 1.87 + 1 / 1.95))


def test_fair_probs_drops_mismatched_spread_lines() -> None:
    odds = frame(
        row("home", 1.91, market="spreads", line=-3.5),
        row("away", 1.91, market="spreads", line=4.0),
    )
    assert fair_probs(odds).empty


def test_fair_probs_drops_mismatched_total_lines() -> None:
    odds = frame(
        row("over", 1.91, market="totals", line=224.5),
        row("under", 1.91, market="totals", line=225.0),
    )
    assert fair_probs(odds).empty


def test_fair_probs_drops_missing_side() -> None:
    odds = frame(
        row("home", 1.5),
        row("over", 1.91, market="totals", line=224.5),
        row("home", 1.6, book="draftkings"),
        row("away", 2.5, book="draftkings"),
    )
    out = fair_probs(odds)
    assert list(out["book"]) == ["draftkings"]
    assert list(out["market"]) == ["h2h"]


def test_fair_probs_never_mixes_books() -> None:
    odds = frame(
        row("home", 1.91, market="spreads", line=-3.5, book="fanduel"),
        row("away", 1.91, market="spreads", line=3.5, book="fanduel"),
        row("home", 2.05, market="spreads", line=-4.5, book="draftkings"),
        row("away", 1.80, market="spreads", line=4.5, book="draftkings"),
    )
    out = fair_probs(odds)
    assert list(out["book"]) == ["draftkings", "fanduel"]
    assert list(out["line"]) == [-4.5, -3.5]
    assert list(out["price_a"]) == [2.05, 1.91]
    assert out.iloc[1]["p_fair"] == pytest.approx(0.5)


def test_fair_probs_never_mixes_snapshots_or_games() -> None:
    later = datetime(2025, 1, 11, 0, 15)
    odds = frame(
        row("home", 1.5),
        row("away", 2.8, snapshot_ts=later),
        row("home", 1.6, game_id="0022400501"),
        row("away", 2.5, game_id="0022400502"),
    )
    assert fair_probs(odds).empty


def test_fair_probs_shin_method() -> None:
    odds = frame(row("home", 1.25), row("away", 4.0))
    mult = fair_probs(odds)
    shin = fair_probs(odds, method="shin")
    assert mult.iloc[0]["method"] == "multiplicative"
    assert shin.iloc[0]["method"] == "shin"
    assert shin.iloc[0]["p_fair"] == pytest.approx(devig_shin([1.25, 4.0])[0])
    assert shin.iloc[0]["p_fair"] > mult.iloc[0]["p_fair"]
    assert shin.iloc[0]["overround"] == pytest.approx(mult.iloc[0]["overround"])


def test_fair_probs_rejects_duplicates() -> None:
    odds = frame(row("home", 1.5), row("home", 1.55), row("away", 2.8))
    with pytest.raises(ValueError, match="duplicate"):
        fair_probs(odds)


def test_fair_probs_rejects_invalid_side() -> None:
    odds = frame(row("home", 1.5), row("over", 2.8))
    with pytest.raises(ValueError):
        fair_probs(odds)


def test_fair_probs_accepts_none_lines() -> None:
    odds = frame(row("home", 1.5), row("away", 2.8)).astype({"line": object})
    odds["line"] = None
    out = fair_probs(odds)
    assert len(out) == 1
    assert math.isnan(out.iloc[0]["line"])


def test_fair_probs_empty_input() -> None:
    empty = pd.DataFrame(
        columns=["game_id", "snapshot_ts", "book", "market", "side", "line", "price"]
    )
    out = fair_probs(empty)
    assert out.empty
    assert list(out.columns) == OUTPUT_COLUMNS


def test_fair_probs_sorted_output() -> None:
    odds = frame(
        row("over", 1.91, market="totals", line=224.5, game_id="0022400502"),
        row("under", 1.91, market="totals", line=224.5, game_id="0022400502"),
        row("home", 1.91, market="spreads", line=-2.5),
        row("away", 1.91, market="spreads", line=2.5),
        row("home", 1.5),
        row("away", 2.8),
    )
    out = fair_probs(odds)
    assert list(zip(out["game_id"], out["market"], strict=True)) == [
        ("0022400500", "h2h"),
        ("0022400500", "spreads"),
        ("0022400502", "totals"),
    ]
    assert list(out.index) == [0, 1, 2]
