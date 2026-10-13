# Live metrics against a reference backtest: is the live mean over n games inside the range
# of n-game means the backtest would produce? The report's own CI is for a mean over
# thousands of games, so it would flag almost any small live sample
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from avaris.backtest.metrics import PROB_CLIP

SCOPE_TYPES = {
    "regular": ("regular", "cup_final"),
    "preseason": ("preseason",),
    "postseason": ("play_in", "playoffs"),
}
METRIC_TARGETS = {"log_loss": "home_win", "margin_mae": "margin", "total_mae": "total"}
N_DRAWS = 2000
SEED = 7
LEVEL = 0.95

Errors = dict[str, dict[str, np.ndarray]]


def reference_errors(path: Path) -> Errors | None:
    # Per-game log loss and absolute errors of the kept model in injury-report mode
    if not path.is_file():
        return None
    return _errors(path, path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _errors(path: Path, _mtime_ns: int) -> Errors:
    df = pd.read_csv(path, usecols=["season_type", "y", "pred", "target", "model",
                                    "availability"])
    df = df[(df["model"] == "model") & (df["availability"] == "report")]
    out: Errors = {}
    for scope, types in SCOPE_TYPES.items():
        in_scope = df[df["season_type"].isin(types)]
        out[scope] = {}
        for metric, target in METRIC_TARGETS.items():
            t = in_scope[in_scope["target"] == target]
            y, pred = t["y"].to_numpy(float), t["pred"].to_numpy(float)
            if metric == "log_loss":
                p = np.clip(pred, PROB_CLIP, 1 - PROB_CLIP)
                out[scope][metric] = -(y * np.log(p) + (1 - y) * np.log(1 - p))
            else:
                out[scope][metric] = np.abs(y - pred)
    return out


def interval(errors: np.ndarray, n: int) -> tuple[float, float]:
    # Central 95% of the means of n games drawn with replacement (fixed seed)
    rng = np.random.default_rng(SEED)
    means = errors[rng.integers(0, errors.size, size=(N_DRAWS, n))].mean(axis=1)
    tail = (1 - LEVEL) / 2
    lo, hi = np.quantile(means, [tail, 1 - tail])
    return float(lo), float(hi)


def drift_scopes(
    ref: Errors, live: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any] | None]:
    # Per scope: each metric's live value, the reference range and whether it falls outside;
    # None when the scope has no live games or no reference games
    out: dict[str, dict[str, Any] | None] = {}
    for scope in SCOPE_TYPES:
        n = int(live[scope]["n"])
        if n == 0 or not any(ref[scope][m].size for m in METRIC_TARGETS):
            out[scope] = None
            continue
        checks: dict[str, Any] = {"n": n}
        for metric in METRIC_TARGETS:
            value, errors = live[scope][metric], ref[scope][metric]
            if value is None or errors.size == 0:
                checks[metric] = None
                continue
            lo, hi = interval(errors, n)
            checks[metric] = {"live": value, "lo": lo, "hi": hi,
                              "drift": bool(value < lo or value > hi)}
        out[scope] = checks
    return out
