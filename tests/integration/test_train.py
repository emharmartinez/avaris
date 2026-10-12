import json
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from avaris.config import ModelsSettings, TargetModelSettings
from avaris.features.build import build_features, feature_hash
from avaris.models.dataset import with_targets
from avaris.models.registry import Registry
from avaris.pipeline.train import train

THROUGH = date(2021, 11, 10)
LGBM = {"n_estimators": 20, "num_leaves": 4, "min_child_samples": 5}


def load(path: Path) -> pd.DataFrame:
    con = duckdb.connect(str(path), read_only=True)
    try:
        return with_targets(build_features(con).features, con)
    finally:
        con.close()


def settings(tmp_path: Path, tolerance: float = 0.02) -> ModelsSettings:
    lgbm = TargetModelSettings(rung="lgbm", lgbm=LGBM)
    return ModelsSettings(
        artifacts_dir=tmp_path / "artifacts", oof_seasons=1, promote_tolerance=tolerance,
        home_win=TargetModelSettings(rung="linear"), margin=lgbm, total=lgbm,
    )


def test_train_writes_artifacts_and_promotes_the_first_run(
    synthetic_db: Path, tmp_path: Path
) -> None:
    cfg = settings(tmp_path)
    results = train(load(synthetic_db), cfg, through=THROUGH, run_id="r1")
    assert [r.target for r in results] == ["home_win", "margin", "total"]
    registry = Registry(cfg.models_dir)
    for r in results:
        assert r.decision.promoted
        assert registry.production(r.target) == "r1"
        meta = json.loads((cfg.models_dir / r.target / "r1" / "meta.json").read_text())
        assert meta["feature_hash"] == feature_hash()
        assert meta["through"] == THROUGH.isoformat()
        assert meta["seed"] == cfg.seed and meta["git_sha"]
        assert set(meta) >= {"params", "rung", "n_rows", "oof_metric", "features", "versions"}
    sigma = results[1].meta["sigma"]
    assert set(sigma) == {"all", "preseason", "regular", "postseason"}


def test_train_cutoff_uses_no_game_on_or_after_through(
    synthetic_db: Path, tmp_path: Path
) -> None:
    data = load(synthetic_db)
    cfg = settings(tmp_path)
    first = train(data, cfg, through=THROUGH, run_id="a", targets=("margin",))[0]
    eligible = data[(data["game_date_et"] < pd.Timestamp(THROUGH)) & data["margin"].notna()]
    assert first.meta["n_rows"] == len(eligible)
    assert first.meta["train_last_date"] < THROUGH.isoformat()

    # Rewriting every result on or after the cutoff changes nothing in the artifact
    changed = tmp_path / "changed.duckdb"
    shutil.copy(synthetic_db, changed)
    con = duckdb.connect(str(changed))
    con.execute(
        "update games set home_pts = away_pts + 40 where game_date_et >= ? and status = 'final'",
        [THROUGH],
    )
    con.execute("delete from player_games where game_date_et >= ?", [THROUGH])
    con.close()
    second = train(load(changed), settings(tmp_path / "b"), through=THROUGH, run_id="b",
                   targets=("margin",))[0]
    assert second.meta["n_rows"] == first.meta["n_rows"]
    pd.testing.assert_frame_equal(first.predictor.predict(data), second.predictor.predict(data))


def test_rerun_with_no_new_rows_stays_a_candidate(synthetic_db: Path, tmp_path: Path) -> None:
    data = load(synthetic_db)
    cfg = settings(tmp_path, tolerance=10.0)
    train(data, cfg, through=THROUGH, run_id="r1", targets=("total",))
    same = train(data, cfg, through=THROUGH, run_id="r2", targets=("total",))[0]
    assert not same.decision.promoted
    later = train(data, cfg, through=date(2022, 1, 1), run_id="r3", targets=("total",))[0]
    assert later.decision.promoted
    registry = Registry(cfg.models_dir)
    assert registry.production("total") == "r3"
    assert registry.candidates("total") == ["r2"]


def test_param_change_needs_a_manual_promote(synthetic_db: Path, tmp_path: Path) -> None:
    data = load(synthetic_db)
    cfg = settings(tmp_path, tolerance=10.0)
    train(data, cfg, through=THROUGH, run_id="r1", targets=("margin",))
    cfg.margin.lgbm = {**LGBM, "num_leaves": 6}
    changed = train(data, cfg, through=date(2022, 1, 1), run_id="r2", targets=("margin",))[0]
    assert not changed.decision.promoted
    assert any("params" in reason for reason in changed.decision.reasons)
