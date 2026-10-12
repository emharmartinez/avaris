import tomllib
from pathlib import Path

from typing import Any, Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path("config.toml")


class PathsSettings(BaseModel):
    data_dir: Path = Path("data")
    db_path: Path = Path("data/avaris.duckdb")
    cache_dir: Path = Path("data/cache")


class StatsSettings(BaseModel):
    first_season: str = "2012-13"
    min_interval_s: float = 1.0
    timeout_s: float = 60.0
    max_attempts: int = 4
    refetch_days: int = 7


class InjurySettings(BaseModel):
    first_season: str = "2021-22"
    min_interval_s: float = 0.5
    timeout_s: float = 30.0
    max_attempts: int = 3
    step_back_hours: float = 4.0  # how far back earlier slots are tried for a missing report


class TargetModelSettings(BaseModel):
    # The kept rung and frozen hyperparameters per rung (tuned on 2015-16 to 2019-20)
    rung: Literal["elo", "linear", "lgbm"] = "elo"
    linear: dict[str, Any] = {}
    lgbm: dict[str, Any] = {}

    def params(self, rung: str | None = None) -> dict[str, Any]:
        rung = rung or self.rung
        return dict(self.linear if rung == "linear" else self.lgbm if rung == "lgbm" else {})


class ModelsSettings(BaseModel):
    artifacts_dir: Path = Path("artifacts")
    seed: int = 7
    oof_seasons: int = 3  # seasons of out-of-fold predictions for calibration and sigma
    promote_tolerance: float = 0.02  # a new artifact's OOF metric may be this much worse
    retrain_every_days: int = 7
    tune_first_season: str = "2015-16"
    tune_last_season: str = "2019-20"
    n_trials: int = 40
    n_jobs: int = 1
    home_win: TargetModelSettings = TargetModelSettings()
    margin: TargetModelSettings = TargetModelSettings()
    total: TargetModelSettings = TargetModelSettings()

    @property
    def models_dir(self) -> Path:
        return self.artifacts_dir / "models"

    @property
    def reports_dir(self) -> Path:
        return self.artifacts_dir / "reports"

    @property
    def optuna_storage(self) -> Path:
        return self.artifacts_dir / "optuna.sqlite3"

    def target(self, name: str) -> TargetModelSettings:
        return {"home_win": self.home_win, "margin": self.margin, "total": self.total}[name]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AVARIS_", env_nested_delimiter="__")

    paths: PathsSettings = PathsSettings()
    stats: StatsSettings = StatsSettings()
    injuries: InjurySettings = InjurySettings()
    models: ModelsSettings = ModelsSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Env vars (AVARIS_STATS__REFETCH_DAYS=3) override config.toml values passed as init
        return (env_settings, init_settings)


def load_settings(path: Path = DEFAULT_CONFIG_PATH) -> Settings:
    # A missing config file means all defaults
    if not path.exists():
        return Settings()
    with path.open("rb") as f:
        return Settings(**tomllib.load(f))
