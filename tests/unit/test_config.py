from pathlib import Path

import pytest

from avaris.config import load_settings


def test_defaults_without_file(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "missing.toml")
    assert s.stats.first_season == "2012-13"
    assert s.stats.min_interval_s == 1.0
    assert s.stats.refetch_days == 7
    assert s.paths.db_path == Path("data/avaris.duckdb")


def test_toml_overrides(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[paths]\ndb_path = "x/y.duckdb"\ncache_dir = "x/cache"\n'
        '[stats]\nfirst_season = "2019-20"\nrefetch_days = 3\n'
    )
    s = load_settings(cfg)
    assert s.paths.db_path == Path("x/y.duckdb")
    assert s.paths.cache_dir == Path("x/cache")
    assert s.stats.first_season == "2019-20"
    assert s.stats.refetch_days == 3
    assert s.stats.timeout_s == 60.0


def test_repo_config_loads() -> None:
    s = load_settings(Path(__file__).parents[2] / "config.toml")
    assert s.stats.max_attempts >= 1


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[stats]\nrefetch_days = 3\n")
    monkeypatch.setenv("AVARIS_STATS__REFETCH_DAYS", "9")
    assert load_settings(cfg).stats.refetch_days == 9


def test_injury_defaults(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "missing.toml")
    assert s.injuries.first_season == "2021-22"
    assert s.injuries.step_back_hours == 4.0


def test_model_settings_defaults_and_overrides(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "missing.toml")
    assert s.models.home_win.rung == "elo"
    assert s.models.promote_tolerance == 0.02
    assert s.models.home_win.calibration == "isotonic"
    assert s.models.models_dir == Path("artifacts/models")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[models]\nseed = 3\n[models.margin]\nrung = "lgbm"\n'
        "[models.margin.lgbm]\nnum_leaves = 8\nlearning_rate = 0.05\n"
    )
    s = load_settings(cfg)
    assert s.models.seed == 3
    assert s.models.target("margin").rung == "lgbm"
    assert s.models.target("margin").params() == {"num_leaves": 8, "learning_rate": 0.05}
    assert s.models.target("total").params() == {}


def test_espn_defaults_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = load_settings(tmp_path / "missing.toml")
    assert s.espn.enabled is True
    assert s.espn.min_interval_s == 1.0
    assert s.espn.timeout_s == 20
    assert s.espn.max_attempts == 3
    assert s.espn.out_window_hours == 36
    monkeypatch.setenv("AVARIS_ESPN__ENABLED", "false")
    assert load_settings(tmp_path / "missing.toml").espn.enabled is False
    assert load_settings(Path(__file__).parents[2] / "config.toml").espn.out_window_hours == 36
