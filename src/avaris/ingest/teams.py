import csv
from dataclasses import dataclass
from importlib.resources import files

import pandas as pd

DATA = files("avaris") / "data"


@dataclass(frozen=True)
class Venue:
    venue: str
    city: str
    lat: float
    lon: float
    tz: str
    altitude_m: float
    team_id: int | None = None  # set for a team's home arena
    kind: str = "home"  # home, bubble, international, cup


def load_teams() -> pd.DataFrame:
    with (DATA / "teams.csv").open() as f:
        return pd.read_csv(f, dtype={"alt_tricodes": "string"})


# Other spellings of a team's "City Nickname" seen in external feeds
TEAM_NAME_ALIASES = {"Los Angeles Clippers": "LA Clippers"}


def _read_teams() -> list[dict[str, str]]:
    with (DATA / "teams.csv").open() as f:
        return list(csv.DictReader(f))


def team_ids_by_name() -> dict[str, int]:
    # "LA Clippers", "Los Angeles Clippers", "Milwaukee Bucks", ...
    ids = {f"{r['city']} {r['nickname']}": int(r["team_id"]) for r in _read_teams()}
    ids.update({alias: ids[name] for alias, name in TEAM_NAME_ALIASES.items()})
    return ids


def team_ids_by_tricode() -> dict[str, int]:
    # Current and former tricodes (NJN, NOH)
    ids: dict[str, int] = {}
    for r in _read_teams():
        for code in [r["tricode"], *filter(None, r["alt_tricodes"].split("|"))]:
            ids[code] = int(r["team_id"])
    return ids


def _read_venues(name: str) -> list[dict[str, str]]:
    with (DATA / name).open() as f:
        return list(csv.DictReader(f))


def _venue(row: dict[str, str], **extra: object) -> Venue:
    return Venue(
        venue=row["venue"],
        city=row["city"],
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        tz=row["tz"],
        altitude_m=float(row["altitude_m"]),
        **extra,  # type: ignore[arg-type]
    )


class Venues:
    def __init__(self, home: list[Venue], neutral: list[Venue]) -> None:
        self._home = {(v.venue, v.team_id): v for v in home}
        self._neutral = {v.venue: v for v in neutral}

    @classmethod
    def load(cls) -> "Venues":
        home = [_venue(r, team_id=int(r["team_id"])) for r in _read_venues("arenas.csv")]
        neutral = [_venue(r, kind=r["kind"]) for r in _read_venues("neutral_venues.csv")]
        return cls(home, neutral)

    def all_rows(self) -> list[Venue]:
        return [*self._home.values(), *self._neutral.values()]

    def home_arenas(self, team_id: int) -> set[str]:
        return {name for name, tid in self._home if tid == team_id}

    def is_neutral(self, venue: str, home_team_id: int, flagged: bool) -> bool:
        # isNeutral is only set from 2024-25, so a game away from the home team's
        # arenas (bubble, international, Cup in Las Vegas) is neutral too. A blank
        # venue is unknown, not neutral (ingest status reports it)
        return flagged or (bool(venue) and (venue, home_team_id) not in self._home)

    def lookup(self, venue: str, home_team_id: int) -> Venue | None:
        return self._home.get((venue, home_team_id)) or self._neutral.get(venue)
