from collections.abc import Callable

import numpy as np
import pandas as pd

from avaris.backtest.metrics import accuracy, brier, coverage, ece, log_loss, mae, rmse

CI_LEVEL = 0.95
N_BOOT = 1000

Metric = Callable[[np.ndarray, np.ndarray, np.ndarray], float]
# Metrics with a bootstrap interval per target; ECE is recomputed on every replicate
METRICS: dict[str, dict[str, Metric]] = {
    "home_win": {
        "log_loss": lambda y, p, _s: log_loss(y, p),
        "brier": lambda y, p, _s: brier(y, p),
        "accuracy": lambda y, p, _s: accuracy(y, p),
        "ece": lambda y, p, _s: ece(y, p),
    },
    "margin": {
        "mae": lambda y, mu, _s: mae(y, mu),
        "rmse": lambda y, mu, _s: rmse(y, mu),
        "coverage_80": coverage,
    },
}
METRICS["total"] = METRICS["margin"]


def bootstrap(
    target: str,
    preds: dict[str, pd.DataFrame],
    reference: str,
    n_boot: int = N_BOOT,
    seed: int = 0,
) -> pd.DataFrame:
    # Percentile CIs over games. Each replicate draws one set of game indices for every
    # model, so the difference to the reference is a paired interval
    ref_games = preds[reference]["game_id"].to_numpy()
    for frame in preds.values():
        if not np.array_equal(frame["game_id"].to_numpy(), ref_games):
            raise ValueError("bootstrap needs every model scored on the same games, in order")
    arrays = {
        name: tuple(f[c].to_numpy(dtype=float) for c in ("y", "pred", "sigma"))
        for name, f in preds.items()
    }
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(ref_games), size=(n_boot, len(ref_games)))
    alpha = (1 - CI_LEVEL) / 2
    rows = []
    for metric, fn in METRICS[target].items():
        point = {m: fn(*a) for m, a in arrays.items()}
        reps = {m: np.array([fn(*(x[idx] for x in a)) for idx in draws]) for m, a in arrays.items()}
        for model in preds:
            lo, hi = np.quantile(reps[model], [alpha, 1 - alpha])
            row = {"model": model, "metric": metric, "value": point[model], "lo": lo, "hi": hi,
                   "diff": np.nan, "diff_lo": np.nan, "diff_hi": np.nan}
            if model != reference:
                diff = reps[model] - reps[reference]
                row.update(diff=point[model] - point[reference],
                           diff_lo=np.quantile(diff, alpha), diff_hi=np.quantile(diff, 1 - alpha))
            rows.append(row)
    return pd.DataFrame(rows)
