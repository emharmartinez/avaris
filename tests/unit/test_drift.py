import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from avaris.api.drift import drift_scopes, interval, reference_errors


def write_reference(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def row(target: str, y: float, pred: float, season_type: str = "regular",
        model: str = "model", availability: str = "report") -> dict[str, object]:
    return {"game_id": "0022100001", "season": "2021-22", "season_type": season_type,
            "y": y, "pred": pred, "target": target, "model": model,
            "availability": availability}


def test_reference_errors_per_scope_from_model_rows_in_report_mode(tmp_path: Path) -> None:
    path = write_reference(tmp_path / "predictions.csv.gz", [
        row("home_win", 1.0, 0.8),
        row("home_win", 0.0, 0.8, season_type="cup_final"),
        row("home_win", 1.0, 0.1, model="elo"),
        row("home_win", 1.0, 0.1, availability="actual"),
        row("margin", 4.0, 1.0),
        row("margin", -2.0, 1.0, season_type="playoffs"),
        row("total", 220.0, 210.0, season_type="preseason"),
    ])
    ref = reference_errors(path)
    assert ref is not None
    assert ref["regular"]["log_loss"].tolist() == pytest.approx([-math.log(0.8),
                                                                 -math.log(0.2)])
    assert ref["regular"]["margin_mae"].tolist() == [3.0]
    assert ref["postseason"]["margin_mae"].tolist() == [3.0]
    assert ref["preseason"]["total_mae"].tolist() == [10.0]
    assert ref["preseason"]["log_loss"].size == 0


def test_reference_errors_missing_file(tmp_path: Path) -> None:
    assert reference_errors(tmp_path / "missing.csv.gz") is None


def test_interval_of_n_game_means_narrows_with_n() -> None:
    errors = np.array([0.0, 1.0] * 500)
    lo1, hi1 = interval(errors, 1)
    lo100, hi100 = interval(errors, 100)
    assert (lo1, hi1) == (0.0, 1.0)
    assert lo1 < lo100 < 0.5 < hi100 < hi1
    assert interval(errors, 100) == (lo100, hi100)  # fixed seed


def test_drift_flags_live_values_outside_the_interval() -> None:
    ref = {"regular": {"log_loss": np.full(50, 0.6), "margin_mae": np.full(50, 10.0),
                       "total_mae": np.full(50, 14.0)},
           "preseason": {"log_loss": np.array([]), "margin_mae": np.array([]),
                         "total_mae": np.array([])},
           "postseason": {"log_loss": np.full(5, 0.6), "margin_mae": np.full(5, 10.0),
                          "total_mae": np.full(5, 14.0)}}
    scopes = {
        "regular": {"n": 3, "log_loss": 0.6, "margin_mae": 12.0, "total_mae": None},
        "preseason": {"n": 4, "log_loss": 0.7, "margin_mae": 9.0, "total_mae": 15.0},
        "postseason": {"n": 0, "log_loss": None, "margin_mae": None, "total_mae": None},
        "all": {"n": 7, "log_loss": 0.6, "margin_mae": 10.0, "total_mae": 14.0},
    }
    out = drift_scopes(ref, scopes)
    assert set(out) == {"regular", "preseason", "postseason"}
    regular = out["regular"]
    assert regular is not None
    assert regular["n"] == 3
    assert regular["log_loss"] == {"live": 0.6, "lo": 0.6, "hi": 0.6, "drift": False}
    assert regular["margin_mae"] == {"live": 12.0, "lo": 10.0, "hi": 10.0, "drift": True}
    assert regular["total_mae"] is None
    assert out["preseason"] is None  # no reference games for the scope
    assert out["postseason"] is None  # no live games yet
