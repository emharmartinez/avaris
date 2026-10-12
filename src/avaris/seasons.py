from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Game ID digits 1-3 encode the game type; All-Star events ("003") are not stored
SEASON_TYPE_BY_PREFIX: dict[str, str] = {
    "001": "preseason",
    "002": "regular",
    "004": "playoffs",
    "005": "play_in",
    "006": "cup_final",
}


def season_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def season_start_year(season: str) -> int:
    return int(season[:4])


def season_for_date(d: date) -> str:
    # Seasons roll over on Sep 1; the 2019-20 bubble Finals ran to Oct 11, 2020
    cutoff = date(d.year, 11, 1) if d.year == 2020 else date(d.year, 9, 1)
    return season_label(d.year if d >= cutoff else d.year - 1)


def season_range(first: str, last: str) -> list[str]:
    return [season_label(y) for y in range(season_start_year(first), season_start_year(last) + 1)]


def is_finished(season: str, today: date) -> bool:
    return season_start_year(season) < season_start_year(season_for_date(today))


def season_type_from_game_id(game_id: str) -> str | None:
    return SEASON_TYPE_BY_PREFIX.get(game_id[:3])


def et_date(tip_off_utc: datetime) -> date:
    # Timestamps are stored as naive UTC; game_date_et is the ET calendar date of tip-off
    return tip_off_utc.replace(tzinfo=UTC).astimezone(ET).date()


def today_et() -> date:
    return datetime.now(ET).date()
