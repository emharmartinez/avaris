from pathlib import Path

import duckdb
import pandas as pd

# Append-only: each entry is one schema version. Timestamps are naive UTC.
MIGRATIONS: list[str] = [
    """
    create table games (
        game_id varchar primary key,
        season varchar not null,
        season_type varchar not null
            check (season_type in ('preseason', 'regular', 'cup_final', 'play_in', 'playoffs')),
        game_date_et date not null,
        tip_off_utc timestamp,
        home_team_id integer not null,
        away_team_id integer not null,
        home_pts integer,
        away_pts integer,
        status varchar not null check (status in ('scheduled', 'in_progress', 'final')),
        venue varchar,
        venue_city varchar,
        neutral_site boolean not null
    );
    create table team_games (
        game_id varchar not null,
        team_id integer not null,
        opp_team_id integer,
        is_home boolean not null,
        season varchar not null,
        season_type varchar not null,
        game_date_et date not null,
        wl varchar,
        minutes double,
        pts integer, fgm integer, fga integer, fg3m integer, fg3a integer,
        ftm integer, fta integer, oreb integer, dreb integer, reb integer,
        ast integer, stl integer, blk integer, tov integer, pf integer,
        plus_minus double,
        primary key (game_id, team_id)
    );
    create table player_games (
        game_id varchar not null,
        player_id integer not null,
        team_id integer not null,
        player_name varchar,
        season varchar not null,
        season_type varchar not null,
        game_date_et date not null,
        minutes double,
        pts integer, fgm integer, fga integer, fg3m integer, fg3a integer,
        ftm integer, fta integer, oreb integer, dreb integer, reb integer,
        ast integer, stl integer, blk integer, tov integer, pf integer,
        plus_minus double,
        primary key (game_id, player_id)
    );
    create table rosters (
        season varchar not null,
        team_id integer not null,
        player_id integer not null,
        player_name varchar,
        position varchar,
        how_acquired varchar,
        primary key (season, team_id, player_id)
    );
    """,
]


def migrate(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create table if not exists schema_version (version integer primary key)")
    row = con.execute("select coalesce(max(version), 0) from schema_version").fetchone()
    current = row[0] if row else 0
    for version, ddl in enumerate(MIGRATIONS[current:], start=current + 1):
        con.execute("begin")
        con.execute(ddl)
        con.execute("insert into schema_version values (?)", [version])
        con.execute("commit")


def connect(path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    con.execute("set TimeZone = 'UTC'")
    if not read_only:
        migrate(con)
    return con


def upsert(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    # Insert or replace by the table's primary key; columns are matched by name and
    # columns missing from df keep their stored values
    if df.empty:
        return 0
    cols = ", ".join(df.columns)
    con.register("_upsert_df", df)
    try:
        con.execute(f"insert or replace into {table} ({cols}) select {cols} from _upsert_df")
    finally:
        con.unregister("_upsert_df")
    return len(df)
