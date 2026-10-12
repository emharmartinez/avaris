import json
from pathlib import Path
from typing import Any

import joblib
import pytest

from avaris.models.registry import (
    Decision,
    FeatureHashMismatch,
    NoProductionModel,
    Registry,
)

HASH = "h1"
TOL = 0.01


def write_artifact(models_dir: Path, run_id: str, target: str = "home_win", **meta: Any) -> None:
    run_dir = models_dir / target / run_id
    run_dir.mkdir(parents=True)
    joblib.dump({"run": run_id}, run_dir / "model.joblib")
    base: dict[str, Any] = {
        "run_id": run_id,
        "target": target,
        "rung": "lgbm",
        "params": {"lr": 0.05},
        "feature_hash": HASH,
        "n_rows": 100,
        "oof_metric": 0.60,
        "created_at": "2026-10-12T00:00:00+00:00",
    }
    (run_dir / "meta.json").write_text(json.dumps(base | meta))


@pytest.fixture
def reg(tmp_path: Path) -> Registry:
    write_artifact(tmp_path, "r1")
    registry = Registry(tmp_path)
    registry.register("home_win", "r1", HASH, TOL)
    return registry


def held(registry: Registry, run_id: str, **meta: Any) -> Decision:
    write_artifact(registry.models_dir, run_id, **meta)
    decision = registry.register("home_win", run_id, HASH, TOL)
    assert not decision.promoted
    assert registry.production("home_win") == "r1"
    assert registry.candidates("home_win") == [run_id]
    return decision


def test_first_artifact_is_promoted(tmp_path: Path) -> None:
    write_artifact(tmp_path, "r1")
    decision = Registry(tmp_path).register("home_win", "r1", HASH, TOL)
    assert decision == Decision(promoted=True, reasons=())
    assert Registry(tmp_path).production("home_win") == "r1"


def test_first_artifact_with_stale_hash_is_a_candidate(tmp_path: Path) -> None:
    write_artifact(tmp_path, "r1", feature_hash="old")
    registry = Registry(tmp_path)
    decision = registry.register("home_win", "r1", HASH, TOL)
    assert not decision.promoted
    assert any("feature_hash" in r for r in decision.reasons)
    assert registry.production("home_win") is None
    assert registry.candidates("home_win") == ["r1"]


def test_better_artifact_is_promoted(reg: Registry) -> None:
    write_artifact(reg.models_dir, "r2", n_rows=120, oof_metric=0.58)
    decision = reg.register("home_win", "r2", HASH, TOL)
    assert decision.promoted
    assert decision.reasons == ()
    assert reg.production("home_win") == "r2"
    assert reg.candidates("home_win") == []


def test_metric_within_tolerance_still_promotes(reg: Registry) -> None:
    write_artifact(reg.models_dir, "r2", n_rows=120, oof_metric=0.60 * 1.009)
    assert reg.register("home_win", "r2", HASH, TOL).promoted


def test_hash_mismatch_is_held(reg: Registry) -> None:
    decision = held(reg, "r2", n_rows=120, feature_hash="other")
    assert len(decision.reasons) == 1
    assert "feature_hash" in decision.reasons[0]


def test_fewer_rows_is_held(reg: Registry) -> None:
    decision = held(reg, "r2", n_rows=100, oof_metric=0.50)
    assert len(decision.reasons) == 1
    assert "n_rows" in decision.reasons[0]


def test_worse_metric_beyond_tolerance_is_held(reg: Registry) -> None:
    decision = held(reg, "r2", n_rows=120, oof_metric=0.60 * 1.02)
    assert len(decision.reasons) == 1
    assert "oof_metric" in decision.reasons[0]


def test_rung_change_is_held(reg: Registry) -> None:
    decision = held(reg, "r2", n_rows=120, rung="linear")
    assert len(decision.reasons) == 1
    assert "rung" in decision.reasons[0]


def test_params_change_is_held(reg: Registry) -> None:
    decision = held(reg, "r2", n_rows=120, params={"lr": 0.1})
    assert len(decision.reasons) == 1
    assert "params" in decision.reasons[0]


def test_every_failed_rule_gets_a_reason(reg: Registry) -> None:
    decision = held(reg, "r2", n_rows=90, rung="elo", feature_hash="other")
    assert len(decision.reasons) == 3


def test_reregistering_production_keeps_it(reg: Registry) -> None:
    assert reg.register("home_win", "r1", HASH, TOL).promoted
    assert reg.production("home_win") == "r1"
    assert reg.candidates("home_win") == []


def test_candidate_is_listed_once(reg: Registry) -> None:
    held(reg, "r2", rung="linear")
    reg.register("home_win", "r2", HASH, TOL)
    assert reg.candidates("home_win") == ["r2"]


def test_manual_promote_of_a_candidate(reg: Registry) -> None:
    held(reg, "r2", rung="linear", n_rows=50)
    reg.promote("home_win", "r2", HASH)
    assert reg.production("home_win") == "r2"
    assert reg.candidates("home_win") == []
    history = json.loads((reg.models_dir / "registry.json").read_text())["home_win"]["history"]
    assert [h["action"] for h in history] == ["promoted", "candidate", "manual_promote"]


def test_manual_promote_refuses_hash_mismatch(reg: Registry) -> None:
    held(reg, "r2", feature_hash="other")
    with pytest.raises(FeatureHashMismatch):
        reg.promote("home_win", "r2", HASH)
    assert reg.production("home_win") == "r1"


def test_manual_promote_unknown_run(reg: Registry) -> None:
    with pytest.raises(FileNotFoundError):
        reg.promote("home_win", "nope", HASH)


def test_load_production(reg: Registry) -> None:
    model, meta = reg.load_production("home_win", HASH)
    assert model == {"run": "r1"}
    assert meta["run_id"] == "r1"


def test_load_production_refuses_hash_mismatch(reg: Registry) -> None:
    with pytest.raises(FeatureHashMismatch):
        reg.load_production("home_win", "new-hash")


def test_load_production_without_production(tmp_path: Path) -> None:
    with pytest.raises(NoProductionModel):
        Registry(tmp_path).load_production("margin", HASH)


def test_registry_survives_reload(reg: Registry) -> None:
    held(reg, "r2", rung="linear")
    write_artifact(reg.models_dir, "m1", target="margin")
    reg.register("margin", "m1", HASH, TOL)
    reloaded = Registry(reg.models_dir)
    assert reloaded.production("home_win") == "r1"
    assert reloaded.candidates("home_win") == ["r2"]
    assert reloaded.production("margin") == "m1"
    assert reloaded.production("total") is None
    assert reloaded.candidates("total") == []
    assert not list(reg.models_dir.glob("*.tmp"))


def test_find_run(reg: Registry) -> None:
    write_artifact(reg.models_dir, "t1", target="total")
    assert reg.find_run("t1") == "total"
    assert reg.find_run("r1") == "home_win"
    with pytest.raises(FileNotFoundError):
        reg.find_run("nope")
