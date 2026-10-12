import numpy as np
import pandas as pd
from scipy.stats import norm

PROB_CLIP = 1e-6
INTERVAL_LEVEL = 0.8
Z_80 = float(norm.ppf(0.5 + INTERVAL_LEVEL / 2))
CAL_BINS = 10  # reliability, ECE and PIT histogram bins


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, PROB_CLIP, 1 - PROB_CLIP)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def accuracy(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p > 0.5) == (y == 1)))


def mae(y: np.ndarray, mu: np.ndarray) -> float:
    return float(np.mean(np.abs(y - mu)))


def rmse(y: np.ndarray, mu: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - mu) ** 2)))


def coverage(y: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> float:
    # Share of outcomes inside the central 80% interval
    return float(np.mean(np.abs(y - mu) <= Z_80 * sigma))


def score(
    target: str, y: np.ndarray, pred: np.ndarray, sigma: np.ndarray | None = None
) -> dict[str, float]:
    if target == "home_win":
        return {
            "log_loss": log_loss(y, pred), "brier": brier(y, pred),
            "accuracy": accuracy(y, pred), "n": float(len(y)),
        }
    out = {"mae": mae(y, pred), "rmse": rmse(y, pred), "n": float(len(y))}
    if sigma is not None:
        out["coverage_80"] = coverage(y, pred, sigma)
    return out


def primary_metric(target: str) -> str:
    # Lower is better: rung selection, tuning and promotion use it
    return "log_loss" if target == "home_win" else "mae"


def _bin_index(p: np.ndarray, bins: int) -> np.ndarray:
    # Equal-width bins on [0, 1]; p = 1 falls in the top bin
    return np.minimum((np.asarray(p) * bins).astype(int), bins - 1)


def reliability(y: np.ndarray, p: np.ndarray, bins: int = CAL_BINS) -> pd.DataFrame:
    # Per non-empty bin: games, mean predicted probability and observed frequency
    idx = _bin_index(p, bins)
    n = np.bincount(idx, minlength=bins)
    sum_p = np.bincount(idx, weights=p, minlength=bins)
    sum_y = np.bincount(idx, weights=y, minlength=bins)
    used = n > 0
    return pd.DataFrame({
        "bin": np.flatnonzero(used), "n": n[used],
        "mean_p": sum_p[used] / n[used], "freq": sum_y[used] / n[used],
    })


def ece(y: np.ndarray, p: np.ndarray, bins: int = CAL_BINS) -> float:
    # Expected calibration error: game-weighted |mean probability - frequency| over bins
    idx = _bin_index(p, bins)
    gap = np.bincount(idx, weights=p, minlength=bins) - np.bincount(idx, weights=y, minlength=bins)
    return float(np.abs(gap).sum() / len(y))


def pit(y: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    # Probability integral transform under N(mu, sigma): uniform when sigma is right
    return np.asarray(norm.cdf(y, loc=mu, scale=sigma))


def pit_counts(values: np.ndarray, bins: int = CAL_BINS) -> np.ndarray:
    return np.bincount(_bin_index(values, bins), minlength=bins)
