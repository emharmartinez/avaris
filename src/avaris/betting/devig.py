from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd

DevigMethod = Literal["multiplicative", "shin"]

PAIR_KEY = ["game_id", "snapshot_ts", "book", "market"]
OUTPUT_COLUMNS = [*PAIR_KEY, "line", "price_a", "price_b", "p_fair", "overround", "method"]

# (side a, side b) per market; p_fair is the fair probability of side a
MARKET_SIDES: dict[str, tuple[str, str]] = {
    "h2h": ("home", "away"),
    "spreads": ("home", "away"),
    "totals": ("over", "under"),
}
VALID_SIDES = {(market, side) for market, sides in MARKET_SIDES.items() for side in sides}
SIDE_A = {sides[0] for sides in MARKET_SIDES.values()}

LINE_TOL = 1e-9
SHIN_TOL = 1e-12
SHIN_MAX_ITER = 200


def american_to_decimal(american: float) -> float:
    if not abs(american) >= 100:
        raise ValueError(f"American odds must satisfy |odds| >= 100, got {american}")
    return 1 + american / 100 if american > 0 else 1 + 100 / -american


def decimal_to_american(decimal: float) -> float:
    if not decimal > 1:
        raise ValueError(f"decimal odds must be > 1, got {decimal}")
    return (decimal - 1) * 100 if decimal >= 2 else -100 / (decimal - 1)


def implied_prob(decimal: float) -> float:
    if not decimal > 1:
        raise ValueError(f"decimal odds must be > 1, got {decimal}")
    return 1 / decimal


def overround(prices: Sequence[float]) -> float:
    return sum(implied_prob(p) for p in prices) - 1


def devig_multiplicative(prices: Sequence[float]) -> list[float]:
    q = _implied_row(prices)
    return [float(p) for p in (q / q.sum())[0]]


def devig_shin(prices: Sequence[float]) -> list[float]:
    return [float(p) for p in _shin(_implied_row(prices))[0]]


def fair_probs(odds: pd.DataFrame, method: DevigMethod = "multiplicative") -> pd.DataFrame:
    if method not in ("multiplicative", "shin"):
        raise ValueError(f"unknown de-vig method {method!r}")
    df = odds[[*PAIR_KEY, "side", "line", "price"]]
    df = df.assign(line=df["line"].astype(float), price=df["price"].astype(float))
    invalid = [
        pair for pair in zip(df["market"], df["side"], strict=True) if pair not in VALID_SIDES
    ]
    if invalid:
        raise ValueError(f"invalid (market, side) pairs: {sorted(set(invalid))}")
    if df.duplicated(subset=[*PAIR_KEY, "side"]).any():
        raise ValueError("duplicate odds rows for the same game/snapshot/book/market/side")
    if not (df["price"] > 1).all():
        raise ValueError("decimal prices must be > 1")

    is_a = df["side"].isin(list(SIDE_A))
    pairs = df[is_a].merge(df[~is_a], on=PAIR_KEY, suffixes=("_a", "_b"))
    # Spreads quote each side's own point (home -3.5 / away +3.5); totals share one line
    expected_b = np.where(pairs["market"] == "spreads", -pairs["line_a"], pairs["line_a"])
    lines_match = (pairs["market"] == "h2h") | (np.abs(pairs["line_b"] - expected_b) < LINE_TOL)
    pairs = pairs[lines_match]
    if pairs.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    q = np.column_stack([1 / pairs["price_a"], 1 / pairs["price_b"]]).astype(float)
    p = _shin(q) if method == "shin" else q / q.sum(axis=1, keepdims=True)
    out = pd.DataFrame(
        {
            **{col: pairs[col].to_numpy() for col in PAIR_KEY},
            "line": pairs["line_a"].to_numpy(dtype=float),
            "price_a": pairs["price_a"].to_numpy(dtype=float),
            "price_b": pairs["price_b"].to_numpy(dtype=float),
            "p_fair": p[:, 0],
            "overround": q.sum(axis=1) - 1,
            "method": method,
        }
    )
    return out.sort_values([*PAIR_KEY, "line"]).reset_index(drop=True)


def _implied_row(prices: Sequence[float]) -> np.ndarray:
    if len(prices) < 2:
        raise ValueError(f"de-vig needs at least 2 outcomes, got {len(prices)}")
    return np.array([[implied_prob(p) for p in prices]])


def _shin_at(q: np.ndarray, booksum: np.ndarray, z: np.ndarray) -> np.ndarray:
    return (np.sqrt(z**2 + 4 * (1 - z) * q**2 / booksum) - z) / (2 * (1 - z))


def _shin(q: np.ndarray) -> np.ndarray:
    # Row-wise Shin de-vig of implied probs q (rows x outcomes). The Shin probabilities sum to
    # sqrt(B) > 1 at z=0 and to sum(q^2)/B < 1 as z -> 1, decreasing in z, so bisect on [0, 1)
    booksum = q.sum(axis=1, keepdims=True)
    lo = np.zeros_like(booksum)
    hi = np.ones_like(booksum)
    for _ in range(SHIN_MAX_ITER):
        z = (lo + hi) / 2
        too_high = _shin_at(q, booksum, z).sum(axis=1, keepdims=True) > 1
        lo = np.where(too_high, z, lo)
        hi = np.where(too_high, hi, z)
        if np.all(hi - lo < SHIN_TOL):
            break
    probs = _shin_at(q, booksum, (lo + hi) / 2)
    probs = probs / probs.sum(axis=1, keepdims=True)
    # No overround means nothing to strip; fall back to multiplicative
    return np.where(booksum > 1, probs, q / booksum)
