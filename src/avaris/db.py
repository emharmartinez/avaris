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
    """
    create sequence api_usage_seq;
    create table api_usage (
        id bigint primary key default nextval('api_usage_seq'),
        run_id varchar not null,
        ts_utc timestamp not null,
        endpoint varchar not null,
        params varchar,  -- JSON, never the API key
        purpose varchar not null,
        est_cost integer not null,
        actual_cost integer,  -- x-requests-last
        requests_used integer,
        requests_remaining integer,
        status varchar not null check (status in ('ok', 'refused', 'error', 'mismatch')),
        message varchar
    );
    create table odds_events (
        event_id varchar primary key,
        game_id varchar,
        home_team varchar not null,
        away_team varchar not null,
        home_team_id integer,
        away_team_id integer,
        commence_time_utc timestamp not null,
        match_status varchar not null
            check (match_status in ('matched', 'unknown_team', 'no_game', 'preseason'))
    );
    create table odds_snapshots (
        game_id varchar not null,
        event_id varchar not null,
        snapshot_ts timestamp not null,
        book varchar not null,
        market varchar not null check (market in ('h2h', 'spreads', 'totals')),
        side varchar not null check (side in ('home', 'away', 'over', 'under')),
        line double,  -- that side's own point; null for h2h
        price double not null,  -- decimal odds
        book_last_update timestamp,
        kind varchar not null check (kind in ('open', 'decision', 'close', 'live', 'other')),
        primary key (game_id, snapshot_ts, book, market, side)
    );
    create table injury_report_files (
        slot_ts timestamp primary key,  -- the report slot the URL names
        report_ts timestamp,  -- from the PDF header
        url varchar not null,
        status varchar not null check (status in ('ok', 'missing')),
        n_entries integer,
        fetched_at timestamp not null
    );
    create table injury_reports (
        report_ts timestamp not null,
        game_date_et date not null,
        matchup varchar not null,
        game_id varchar,
        team_id integer not null,
        player_name varchar not null,  -- as printed ("Last, First"); '' when not submitted
        player_id integer,
        status varchar not null check (status in
            ('out', 'doubtful', 'questionable', 'probable', 'available', 'not_submitted')),
        reason varchar,
        primary key (report_ts, game_date_et, team_id, player_name)
    );
    """,
    # Report files that fail to parse are kept as 'error'; postponed games are not unmatched
    """
    create table injury_report_files_v3 (
        slot_ts timestamp primary key,
        report_ts timestamp,
        url varchar not null,
        status varchar not null check (status in ('ok', 'missing', 'error')),
        n_entries integer,
        fetched_at timestamp not null,
        message varchar
    );
    insert into injury_report_files_v3
        select slot_ts, report_ts, url, status, n_entries, fetched_at, null
        from injury_report_files;
    drop table injury_report_files;
    alter table injury_report_files_v3 rename to injury_report_files;
    create table odds_events_v3 (
        event_id varchar primary key,
        game_id varchar,
        home_team varchar not null,
        away_team varchar not null,
        home_team_id integer,
        away_team_id integer,
        commence_time_utc timestamp not null,
        match_status varchar not null check (match_status in
            ('matched', 'unknown_team', 'no_game', 'preseason', 'postponed'))
    );
    insert into odds_events_v3 select * from odds_events;
    drop table odds_events;
    alter table odds_events_v3 rename to odds_events;
    """,
    # Analytics pivot (ADR-014): The Odds API is dropped, so are its tables
    """
    drop table odds_snapshots;
    drop table odds_events;
    drop table api_usage;
    drop sequence api_usage_seq;
    """,
    # Phase 3: point-in-time features per game and team ratings as of each game (ADR-015)
    """
    create table features (
        game_id varchar not null,
        decision_ts timestamp not null,
        report_ts timestamp,  -- the injury report frozen at decision_ts, if any
        feature_hash varchar not null,
        season varchar not null,
        season_type varchar not null,
        game_date_et date not null,
        home_team_id integer not null,
        away_team_id integer not null,
        home_court integer not null,
        no_fans integer not null,
        is_preseason integer not null,
        is_postseason integer not null,
        home_elo double, away_elo double, elo_prob double, elo_margin double,
        home_ortg double, away_ortg double, home_drtg double, away_drtg double,
        home_net double, away_net double, home_pace double, away_pace double,
        home_net_l10 double, away_net_l10 double, home_gp integer, away_gp integer,
        league_total double, league_pace double,
        home_rest_days double, away_rest_days double, home_b2b integer, away_b2b integer,
        home_3in4 integer, away_3in4 integer, home_travel_km double, away_travel_km double,
        home_tz_shift double, away_tz_shift double, altitude_m double,
        home_full_strength double, away_full_strength double,
        home_lost_actual double, away_lost_actual double,
        home_lost_report double, away_lost_report double,
        primary key (game_id, decision_ts)
    );
    create table team_ratings (
        team_id integer not null,
        game_id varchar not null,  -- ratings as of this game's decision_ts
        as_of_ts timestamp not null,
        season varchar not null,
        elo double, ortg double, drtg double, net double, pace double, net_l10 double,
        gp integer,
        primary key (team_id, game_id)
    );
    """,
    # Phase 4: season-to-date ratings, inputs of the naive net-rating baseline
    """
    alter table features add column home_ortg_std double;
    alter table features add column away_ortg_std double;
    alter table features add column home_drtg_std double;
    alter table features add column away_drtg_std double;
    alter table features add column home_pace_std double;
    alter table features add column away_pace_std double;
    """,
    # Phase 5: live predictions (one row per game; a final row is never replaced), their
    # scores after the game, and background jobs
    """
    create table predictions (
        game_id varchar primary key,
        status varchar not null check (status in ('provisional', 'final')),
        decision_ts timestamp not null,
        report_ts timestamp,
        predicted_at timestamp not null,
        feature_hash varchar not null,
        home_win_run varchar not null,
        margin_run varchar not null,
        total_run varchar not null,
        p_home_win double not null,
        margin_mu double not null, margin_sigma double not null,
        total_mu double not null, total_sigma double not null,
        drivers varchar not null,  -- JSON: per target, base, families and top families
        injuries varchar not null  -- JSON: per side, strength lost and the players behind it
    );
    create table prediction_scores (
        game_id varchar primary key,
        scored_at timestamp not null,
        home_win double not null, margin double not null, total double not null,
        log_loss double not null, brier double not null, correct boolean not null,
        margin_error double not null, total_error double not null,  -- outcome - mu
        margin_in_80 boolean not null, total_in_80 boolean not null,
        margin_pit double not null, total_pit double not null
    );
    create table jobs (
        job_id varchar primary key,
        kind varchar not null check (kind in ('daily', 'score', 'train')),
        status varchar not null check (status in ('running', 'succeeded', 'failed')),
        params varchar,  -- JSON
        created_at timestamp not null,
        finished_at timestamp,
        message varchar,
        log varchar
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
