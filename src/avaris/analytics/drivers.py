from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import logit
from sklearn.pipeline import Pipeline

from avaris.features.build import MODEL_FEATURES
from avaris.models.ladder import ELO_COLUMN, EloRung, Model, SklearnRung

PROB_CLIP = 1e-9
FAMILY_FEATURES = {
    "elo": ["elo_diff", "elo_prob", "elo_margin"],
    "form": [
        "home_ortg", "away_ortg", "home_drtg", "away_drtg", "net_diff", "home_pace",
        "away_pace", "net_l10_diff", "home_gp", "away_gp", "exp_total",
    ],
    "rest_travel": [
        "home_rest_days", "away_rest_days", "home_b2b", "away_b2b", "home_3in4", "away_3in4",
        "home_travel_km", "away_travel_km", "home_tz_shift", "away_tz_shift", "altitude_m",
    ],
    "availability": [
        "home_full_strength", "away_full_strength", "home_lost", "away_lost", "lost_diff",
    ],
    "home_court": ["home_court", "no_fans"],
    "game_type": ["is_preseason", "is_postseason"],
    "league": ["league_total", "league_pace"],
}
FAMILIES = {f: family for family, features in FAMILY_FEATURES.items() for f in features}


@dataclass(frozen=True)
class Drivers:
    # Feature contributions on the link scale (log-odds for home_win, the prediction for
    # margin and total): base + contributions summed over features = output
    base: np.ndarray
    contributions: pd.DataFrame
    output: np.ndarray

    def families(self) -> pd.DataFrame:
        c = self.contributions
        return pd.DataFrame({fam: c[feats].sum(axis=1) for fam, feats in FAMILY_FEATURES.items()})


def _link(p: np.ndarray) -> np.ndarray:
    return np.asarray(logit(np.clip(p, PROB_CLIP, 1 - PROB_CLIP)), dtype=float)


def link_output(target: str, prediction: np.ndarray) -> np.ndarray:
    # A rung's raw prediction on the drivers' scale: log-odds for home_win
    return _link(prediction) if target == "home_win" else np.asarray(prediction, dtype=float)


def _elo(rung: EloRung, target: str, x: pd.DataFrame) -> Drivers:
    output = link_output(target, rung.predict(x))
    contrib = pd.DataFrame(0.0, index=x.index, columns=MODEL_FEATURES)
    contrib[ELO_COLUMN[target]] = output
    return Drivers(np.zeros(len(x)), contrib, output)


def _linear(pipe: Pipeline, x: pd.DataFrame) -> Drivers:
    # coef x scaled value; a missing-value indicator counts toward its source feature
    imputer, scaler, model = (step for _, step in pipe.steps)
    z = scaler.transform(imputer.transform(x))
    coef = np.ravel(model.coef_)
    terms = z * coef
    n_features = x.shape[1]
    contrib = pd.DataFrame(terms[:, :n_features], index=x.index, columns=list(x.columns))
    indicator: Any = imputer.indicator_
    if indicator is not None:
        for j, source in enumerate(indicator.features_):
            contrib.iloc[:, source] += terms[:, n_features + j]
    base = np.full(len(x), float(np.ravel(model.intercept_)[0]))
    return Drivers(base, contrib, base + terms.sum(axis=1))


def _lgbm(estimator: Any, x: pd.DataFrame) -> Drivers:
    values = np.asarray(estimator.predict(x, pred_contrib=True), dtype=float)
    contrib = pd.DataFrame(values[:, :-1], index=x.index, columns=list(x.columns))
    base = values[:, -1]
    return Drivers(base, contrib, base + values[:, :-1].sum(axis=1))


def explain(model: Model, target: str, x: pd.DataFrame) -> Drivers:
    # Drivers of a ladder rung's raw prediction for model inputs x (model_frame columns)
    if isinstance(model, EloRung):
        return _elo(model, target, x)
    if isinstance(model, SklearnRung):
        if isinstance(model.estimator, Pipeline):
            return _linear(model.estimator, x)
        return _lgbm(model.estimator, x)
    raise TypeError(f"no drivers for {type(model).__name__}")


def top_drivers(families: pd.Series, k: int = 3) -> list[dict[str, Any]]:
    # The k largest family contributions by size, for one prediction
    top = families.reindex(families.abs().sort_values(ascending=False).index)[:k]
    return [{"family": str(f), "value": float(v)} for f, v in top.items()]
