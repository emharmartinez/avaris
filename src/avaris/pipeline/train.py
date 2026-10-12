import json
import secrets
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from avaris.config import ModelsSettings
from avaris.features.build import FEATURE_VERSION, MODEL_FEATURES, feature_hash
from avaris.models.ladder import TARGETS
from avaris.models.predictor import GamePredictor, fit_predictor, oof_metric
from avaris.models.registry import META_FILE, MODEL_FILE, Decision, Registry

PACKAGES = ("avaris", "lightgbm", "scikit-learn", "numpy", "pandas", "duckdb")


@dataclass(frozen=True)
class TrainResult:
    target: str
    run_id: str
    predictor: GamePredictor
    meta: dict[str, Any]
    decision: Decision


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10,
            cwd=Path(__file__).parent,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def new_run_id(now: datetime) -> str:
    # Timestamp plus a random suffix, so two runs in one second never share a directory
    return f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"


def train(
    data: pd.DataFrame,
    settings: ModelsSettings,
    through: date,
    targets: Iterable[str] = TARGETS,
    run_id: str | None = None,
    now: datetime | None = None,
) -> list[TrainResult]:
    # Refit each target's kept rung with its frozen hyperparameters on every final game
    # dated before `through`, write the artifact and let the registry decide promotion
    now = now or datetime.now(UTC)
    run_id = run_id or new_run_id(now)
    rows = data[data["game_date_et"] < pd.Timestamp(through)]
    registry = Registry(settings.models_dir)
    results = []
    for target in targets:
        cfg = settings.target(target)
        params = cfg.params()
        predictor = fit_predictor(rows, target, cfg.rung, params, settings.seed,
                                  settings.oof_seasons)
        labelled = rows[rows[target].notna()]
        meta = {
            "run_id": run_id, "target": target, "rung": cfg.rung, "params": params,
            "feature_hash": feature_hash(), "feature_version": FEATURE_VERSION,
            "features": MODEL_FEATURES, "availability": "actual",
            "n_rows": len(labelled), "through": through.isoformat(),
            "train_first_date": str(labelled["game_date_et"].min().date()),
            "train_last_date": str(labelled["game_date_et"].max().date()),
            "oof_metric": oof_metric(predictor),
            "oof_metrics": predictor.calibration.oof_metrics,
            "sigma": predictor.calibration.sigma, "seed": settings.seed,
            "oof_seasons": settings.oof_seasons, "git_sha": git_sha(),
            "versions": {p: version(p) for p in PACKAGES},
            "created_at": now.isoformat(),
        }
        out = settings.models_dir / target / run_id
        out.mkdir(parents=True)
        joblib.dump(predictor, out / MODEL_FILE)
        (out / META_FILE).write_text(json.dumps(meta, indent=2) + "\n")
        decision = registry.register(target, run_id, feature_hash(), settings.promote_tolerance)
        results.append(TrainResult(target, run_id, predictor, meta, decision))
    return results
