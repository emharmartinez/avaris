import tomllib
from pathlib import Path

from pydantic import BaseModel, Field
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


class GuardSettings(BaseModel):
    # Live (free tier) defaults; backfills pass explicit caps on the command line
    max_credits_per_run: int = 6
    monthly_credit_budget: int = 450
    min_remaining_reserve: int = 30
    usd_per_credit: float = 0.0
    max_monthly_usd: float = 0.0
    # A call is refused once the month would come within this many credits of the budget,
    # so opening snapshots go first, then closing, and decision snapshots last
    headroom: dict[str, int] = {"open": 30, "close": 15, "decision": 0}


class OddsSettings(BaseModel):
    sport: str = "basketball_nba"
    regions: list[str] = Field(default=["us"], min_length=1)
    markets: list[str] = Field(default=["h2h", "spreads", "totals"], min_length=1)
    first_date: str = "2020-12-22"
    timeout_s: float = 30.0
    max_attempts: int = 3
    match_window_min: int = 120  # event commence_time vs games.tip_off_utc
    open_time_et: str = "09:00"
    early_band_from_et: str = "17:00"  # tips before this are matinees
    late_band_from_et: str = "21:30"
    close_window_min: int = 45
    close_lead_min: int = 2  # closing snapshot this long before the first covered tip
    live_max_close_slots: int = 3
    guard: GuardSettings = GuardSettings()


class InjurySettings(BaseModel):
    first_season: str = "2021-22"
    min_interval_s: float = 0.5
    timeout_s: float = 30.0
    max_attempts: int = 3
    max_step_back: int = 4  # earlier report slots tried when the target report is missing


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AVARIS_", env_nested_delimiter="__")

    paths: PathsSettings = PathsSettings()
    stats: StatsSettings = StatsSettings()
    odds: OddsSettings = OddsSettings()
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
