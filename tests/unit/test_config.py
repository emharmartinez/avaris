from pathlib import Path

import pytest

from avaris.config import OddsSettings, load_settings


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


def test_odds_and_injury_defaults(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "missing.toml")
    assert s.odds.markets == ["h2h", "spreads", "totals"]
    assert s.odds.regions == ["us"]
    assert s.odds.guard.max_credits_per_run == 6
    assert s.odds.guard.monthly_credit_budget == 450
    assert s.odds.guard.min_remaining_reserve == 30
    assert s.odds.close_window_min == 45
    assert s.injuries.first_season == "2021-22"


def test_repo_config_has_live_guard_defaults() -> None:
    s = load_settings(Path(__file__).parents[2] / "config.toml")
    assert s.odds.guard.monthly_credit_budget == 450
    assert s.odds.guard.headroom["open"] > s.odds.guard.headroom["close"]
    assert s.odds.guard.headroom["close"] > s.odds.guard.headroom.get("decision", 0)


def test_odds_markets_and_regions_cannot_be_empty() -> None:
    with pytest.raises(ValueError):
        OddsSettings(markets=[])
    with pytest.raises(ValueError):
        OddsSettings(regions=[])
