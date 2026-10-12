from typing import Self

import numpy as np
from sklearn.isotonic import IsotonicRegression

CAL_CLIP = 0.005


class IsotonicCalibrator:
    # Maps out-of-fold win probabilities to calibrated ones; clipped away from 0 and 1
    def __init__(self) -> None:
        self.model = IsotonicRegression(
            y_min=CAL_CLIP, y_max=1 - CAL_CLIP, out_of_bounds="clip"
        )

    def fit(self, p: np.ndarray, y: np.ndarray) -> Self:
        self.model.fit(p, y)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict(p), dtype=float)
