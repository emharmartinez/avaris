import numpy as np
from scipy.stats import norm

PROB_CLIP = 1e-6
INTERVAL_LEVEL = 0.8
Z_80 = float(norm.ppf(0.5 + INTERVAL_LEVEL / 2))


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
