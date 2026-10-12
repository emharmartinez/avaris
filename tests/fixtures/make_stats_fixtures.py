# Trims recorded stats.nba.com responses from data/cache into small test fixtures.
# Run once after a real ingest: uv run python tests/fixtures/make_stats_fixtures.py
import gzip
import json
from pathlib import Path
from typing import Any

from avaris.ingest.endpoints import GAME_LOG, ROSTER, SCHEDULE, log_season_types

CACHE = Path("data/cache")
OUT = Path(__file__).parent / "stats"

GAMES: dict[str, set[str]] = {
    "2019-20": {
        "0021900573",  # regular, normal tip
        "0021900002",  # 10:30 pm ET tip (next UTC day)
        "0021900669",  # Paris, neutral (no isNeutral flag in old seasons)
        "0021901232",  # bubble seeding game
        "0041900111",  # bubble playoffs
        "0051900111",  # bubble play-in
        "0031900001",  # All-Star, must be dropped
    },
    "2025-26": {
        "0012500008",  # preseason, Abu Dhabi
        "0022500001",  # regular
        "0022500798",  # Spurs home game in Austin (not neutral)
        "0022501201",  # Cup knockout (regular season, also in IST log)
        "0062500001",  # Cup final, Las Vegas
        "0042500121",  # playoffs
        "0052500111",  # play-in
    },
    "2026-27": {
        "0012600009",  # finished preseason game
        "0022600001",  # scheduled regular-season game
        "0022601201",  # Cup knockout placeholder with TBD teams
    },
}
ROSTER_TEAM = 1610612759


def read_cache(endpoint: str, params_glob: str) -> dict[str, Any]:
    matches = sorted(CACHE.glob(f"*/{endpoint}/{params_glob}.json.gz"))
    with gzip.open(matches[-1], "rt", encoding="utf-8") as f:
        return json.load(f)


def write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n")


def trim_schedule(season: str, keep: set[str]) -> None:
    payload = read_cache(SCHEDULE, f"LeagueID=00_Season={season}")
    schedule = payload["leagueSchedule"]
    dates = []
    for game_date in schedule["gameDates"]:
        games = [
            {k: v for k, v in g.items() if k not in ("broadcasters", "pointsLeaders", "tickets")}
            for g in game_date["games"]
            if g["gameId"] in keep
        ]
        if games:
            dates.append({**game_date, "games": games})
    schedule["gameDates"] = dates
    schedule.pop("weeks", None)
    write(OUT / SCHEDULE / f"{season}.json", payload)


def trim_logs(season: str, keep: set[str]) -> None:
    for season_type in log_season_types(season):
        for kind in "TP":
            pattern = (
                f"Counter=0_DateFrom=_DateTo=_Direction=ASC_LeagueID=00_PlayerOrTeam={kind}"
                f"_Season={season}_SeasonType={season_type.replace(' ', '-')}_Sorter=DATE"
            )
            payload = read_cache(GAME_LOG, pattern)
            result = payload["resultSets"][0]
            game_col = result["headers"].index("GAME_ID")
            rows = [r for r in result["rowSet"] if r[game_col] in keep]
            if kind == "P":
                # Keep three players per team-game so fixtures stay small
                team_col = result["headers"].index("TEAM_ID")
                seen: dict[tuple[str, int], int] = {}
                trimmed = []
                for r in rows:
                    key = (r[game_col], r[team_col])
                    seen[key] = seen.get(key, 0) + 1
                    if seen[key] <= 3:
                        trimmed.append(r)
                rows = trimmed
            result["rowSet"] = rows
            write(OUT / GAME_LOG / f"{season}_{season_type.replace(' ', '-')}_{kind}.json", payload)


def trim_roster(season: str) -> None:
    payload = read_cache(ROSTER, f"LeagueID=00_Season={season}_TeamID={ROSTER_TEAM}")
    payload["resultSets"] = payload["resultSets"][:1]
    payload["resultSets"][0]["rowSet"] = payload["resultSets"][0]["rowSet"][:4]
    write(OUT / ROSTER / f"{season}.json", payload)


def main() -> None:
    for season, keep in GAMES.items():
        trim_schedule(season, keep)
        if season != "2026-27":
            trim_logs(season, keep)
    trim_roster("2025-26")


if __name__ == "__main__":
    main()
