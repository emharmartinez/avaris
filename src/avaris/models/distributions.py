import numpy as np
import pandas as pd
from scipy.stats import norm

from avaris.backtest.metrics import Z_80

# sigma is fitted per bucket so preseason intervals are not borrowed from the regular season
BUCKETS = {
    "preseason": "preseason",
    "regular": "regular",
    "cup_final": "regular",
    "play_in": "postseason",
    "playoffs": "postseason",
}
MIN_BUCKET_ROWS = 30


def bucket(season_type: str) -> str:
    return BUCKETS[season_type]


def fit_sigma(
    residuals: np.ndarray, season_types: pd.Series, min_rows: int = MIN_BUCKET_ROWS
) -> dict[str, float]:
    # Root mean squared out-of-fold residual per bucket; small buckets use all rows
    pooled = float(np.sqrt(np.mean(residuals**2)))
    buckets = season_types.map(BUCKETS).to_numpy()
    sigma = {"all": pooled}
    for name in sorted(set(BUCKETS.values())):
        mask = buckets == name
        enough = mask.sum() >= min_rows
        sigma[name] = float(np.sqrt(np.mean(residuals[mask] ** 2))) if enough else pooled
    return sigma


def sigma_for(sigma: dict[str, float], season_types: pd.Series) -> np.ndarray:
    return season_types.map(BUCKETS).map(sigma).fillna(sigma["all"]).to_numpy(dtype=float)


def interval(mu: np.ndarray, sigma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return mu - Z_80 * sigma, mu + Z_80 * sigma


def prob_above(mu: np.ndarray, sigma: np.ndarray, x: float) -> np.ndarray:
    # P(outcome > x) under N(mu, sigma)
    return np.asarray(norm.sf(x, loc=mu, scale=sigma))
