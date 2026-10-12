import json
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

REGISTRY_FILE = "registry.json"
META_FILE = "meta.json"
MODEL_FILE = "model.joblib"

Entry = dict[str, Any]
TARGETS = frozenset({"home_win", "margin", "total"})
# Run IDs and targets become path parts: no separators or "..", so a promote or load can
# never reach (and unpickle) a file outside models_dir
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class FeatureHashMismatch(Exception):
    pass


class NoProductionModel(Exception):
    pass


@dataclass(frozen=True)
class Decision:
    promoted: bool
    reasons: tuple[str, ...] = ()


class Registry:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self.path = models_dir / REGISTRY_FILE

    def run_dir(self, target: str, run_id: str) -> Path:
        if target not in TARGETS:
            raise ValueError(f"unknown target {target!r}")
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError(f"invalid run ID {run_id!r}")
        return self.models_dir / target / run_id

    def read_meta(self, target: str, run_id: str) -> dict[str, Any]:
        meta_path = self.run_dir(target, run_id) / META_FILE
        if not meta_path.exists():
            raise FileNotFoundError(f"no {target} artifact {run_id} in {self.models_dir}")
        return json.loads(meta_path.read_text())

    def production(self, target: str) -> str | None:
        return self._entry(self._load(), target)["production"]

    def candidates(self, target: str) -> list[str]:
        return list(self._entry(self._load(), target)["candidates"])

    def find_run(self, run_id: str) -> str:
        for target in sorted(TARGETS):
            if (self.run_dir(target, run_id) / META_FILE).exists():
                return target
        raise FileNotFoundError(f"no artifact {run_id} in {self.models_dir}")

    def register(self, target: str, run_id: str, current_hash: str, tolerance: float) -> Decision:
        meta = self.read_meta(target, run_id)
        state = self._load()
        entry = self._entry(state, target)
        if entry["production"] == run_id:
            return Decision(promoted=True)
        prod_id = entry["production"]
        prod = self.read_meta(target, prod_id) if prod_id is not None else None
        reasons = _failed_rules(meta, prod, current_hash, tolerance)
        if reasons:
            if run_id not in entry["candidates"]:
                entry["candidates"].append(run_id)
            _log(entry, run_id, "candidate", reasons)
        else:
            _set_production(entry, run_id, "promoted")
        self._save(state)
        return Decision(promoted=not reasons, reasons=tuple(reasons))

    def promote(self, target: str, run_id: str, current_hash: str) -> None:
        meta = self.read_meta(target, run_id)
        _check_hash(meta, current_hash)
        state = self._load()
        _set_production(self._entry(state, target), run_id, "manual_promote")
        self._save(state)

    def load_production(self, target: str, current_hash: str) -> tuple[object, dict[str, Any]]:
        run_id = self.production(target)
        if run_id is None:
            raise NoProductionModel(f"no production {target} model; run avaris train")
        meta = self.read_meta(target, run_id)
        # Refuse before loading: a stale feature set would silently mispredict
        _check_hash(meta, current_hash)
        return joblib.load(self.run_dir(target, run_id) / MODEL_FILE), meta

    def _load(self) -> dict[str, Entry]:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def _entry(self, state: dict[str, Entry], target: str) -> Entry:
        return state.setdefault(target, {"production": None, "candidates": [], "history": []})

    def _save(self, state: dict[str, Entry]) -> None:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        # Temp file in the same directory so os.replace stays atomic
        tmp_path = self.path.with_name(f"{REGISTRY_FILE}.tmp")
        tmp_path.write_text(json.dumps(state, indent=2))
        os.replace(tmp_path, self.path)


def _failed_rules(
    meta: dict[str, Any], prod: dict[str, Any] | None, current_hash: str, tolerance: float
) -> list[str]:
    reasons = []
    if not math.isfinite(meta["oof_metric"]) or meta["n_rows"] <= 0:
        reasons.append(f"oof_metric {meta['oof_metric']} or n_rows {meta['n_rows']} unusable")
    if meta["feature_hash"] != current_hash:
        reasons.append(f"feature_hash {meta['feature_hash']} != current {current_hash}")
    if prod is None:
        return reasons
    if meta["n_rows"] <= prod["n_rows"]:
        reasons.append(f"n_rows {meta['n_rows']} not above production {prod['n_rows']}")
    if meta["oof_metric"] > prod["oof_metric"] * (1 + tolerance):
        reasons.append(
            f"oof_metric {meta['oof_metric']:.4f} worse than production "
            f"{prod['oof_metric']:.4f} beyond tolerance {tolerance}"
        )
    if meta["rung"] != prod["rung"]:
        reasons.append(f"rung {meta['rung']} != production {prod['rung']}; promote manually")
    if meta["params"] != prod["params"]:
        reasons.append("params differ from production; promote manually")
    if meta.get("calibration") != prod.get("calibration"):
        reasons.append("calibration differs from production; promote manually")
    return reasons


def _check_hash(meta: dict[str, Any], current_hash: str) -> None:
    if meta["feature_hash"] != current_hash:
        raise FeatureHashMismatch(
            f"{meta['run_id']} was trained on features {meta['feature_hash']}, "
            f"current is {current_hash}; retrain"
        )


def _set_production(entry: Entry, run_id: str, action: str) -> None:
    entry["production"] = run_id
    entry["candidates"] = [c for c in entry["candidates"] if c != run_id]
    _log(entry, run_id, action, [])


def _log(entry: Entry, run_id: str, action: str, reasons: list[str]) -> None:
    at = datetime.now(UTC).isoformat()
    entry["history"].append({"run_id": run_id, "action": action, "at": at, "reasons": reasons})
