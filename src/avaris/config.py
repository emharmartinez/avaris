import tomllib
from pathlib import Path

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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AVARIS_", env_nested_delimiter="__")

    paths: PathsSettings = PathsSettings()
    stats: StatsSettings = StatsSettings()
    injuries: InjurySettings = InjurySettings()

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
