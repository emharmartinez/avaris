from datetime import date

import duckdb
import pandas as pd

from avaris.ingest.teams import Venues
from avaris.seasons import is_finished, season_start_year

# Regular-season game counts that differ from 30 teams x 82 / 2
EXPECTED_REGULAR = {
    "2012-13": 1229,  # BOS-IND cancelled after the Boston Marathon bombing
    "2019-20": 1059,  # COVID suspension, 88 seeding games in the bubble
    "2020-21": 1080,  # 72-game season
}
TIP_OFF_REQUIRED_FROM = "2020-21"
BUBBLE_SEASON = "2019-20"

REPORT_SQL = """
with g as (
    select g.*, v.kind as venue_kind, (v.venue is not null or h.venue is not null) as known_venue
    from games g
    left join _neutral_venues v on v.venue = g.venue
    left join _home_arenas h on h.venue = g.venue and h.team_id = g.home_team_id
),
logs as (select game_id, count(*) as n from team_games group by game_id),
games_by_season as (
    select season,
        count(*) filter (where season_type = 'preseason') as preseason,
        count(*) filter (where season_type = 'regular') as regular,
        count(*) filter (where season_type = 'play_in') as play_in,
        count(*) filter (where season_type = 'playoffs') as playoffs,
        count(*) filter (where season_type = 'cup_final') as cup_final,
        count(*) filter (where tip_off_utc is null) as missing_tip_off,
        count(*) filter (where neutral_site and season_type <> 'preseason') as neutral,
        count(*) filter (where not known_venue and season_type <> 'preseason') as unknown_venues,
        count(*) filter (where venue_kind = 'bubble' and neutral_site) as bubble_neutral,
        count(*) filter (where venue_kind = 'bubble' and not neutral_site) as bubble_not_neutral,
        count(*) filter (
            where status = 'final' and season_type <> 'preseason' and coalesce(l.n, 0) <> 2
        ) as finals_missing_team_logs
    from g left join logs l using (game_id)
    group by season
),
team_rows as (select season, count(*) as team_games from team_games group by season),
player_rows as (select season, count(*) as player_games from player_games group by season),
roster_rows as (
    select season, count(distinct team_id) as roster_teams, count(*) as roster_players
    from rosters group by season
)
select * from games_by_season
left join team_rows using (season)
left join player_rows using (season)
left join roster_rows using (season)
order by season
"""


def expected_regular_games(season: str) -> int:
    return EXPECTED_REGULAR.get(season, 1230)


def season_report(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    venues = Venues.load()
    home = pd.DataFrame(
        [{"venue": v.venue, "team_id": v.team_id} for v in venues.all_rows() if v.team_id]
    )
    neutral = pd.DataFrame(
        [{"venue": v.venue, "kind": v.kind} for v in venues.all_rows() if not v.team_id]
    )
    con.register("_home_arenas", home)
    con.register("_neutral_venues", neutral)
    try:
        report = con.execute(REPORT_SQL).df()
    finally:
        con.unregister("_home_arenas")
        con.unregister("_neutral_venues")
    count_cols = report.columns.drop("season")
    report[count_cols] = report[count_cols].fillna(0).astype(int)
    return report


def check_report(report: pd.DataFrame, today: date) -> list[str]:
    # Phase 1 done-when checks; returns one message per failure
    failures: list[str] = []
    for row in report.to_dict("records"):
        season = str(row["season"])
        finished = is_finished(season, today)
        if finished and row["regular"] != expected_regular_games(season):
            failures.append(
                f"{season}: {row['regular']} regular-season games, "
                f"expected {expected_regular_games(season)}"
            )
        if finished and row["finals_missing_team_logs"]:
            missing = row["finals_missing_team_logs"]
            failures.append(f"{season}: {missing} final games without 2 team logs")
        if row["roster_teams"] != 30:
            failures.append(f"{season}: rosters for {row['roster_teams']} teams, expected 30")
        if row["unknown_venues"]:
            failures.append(f"{season}: {row['unknown_venues']} games at venues not in the CSVs")
        if (
            season_start_year(season) >= season_start_year(TIP_OFF_REQUIRED_FROM)
            and row["missing_tip_off"]
        ):
            failures.append(f"{season}: {row['missing_tip_off']} games without tip-off time")
        if season == BUBBLE_SEASON and (row["bubble_not_neutral"] or not row["bubble_neutral"]):
            failures.append(
                f"{season}: bubble games not tagged neutral "
                f"({row['bubble_neutral']} neutral, {row['bubble_not_neutral']} not)"
            )
    return failures
