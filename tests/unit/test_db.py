from pathlib import Path

import duckdb
import pandas as pd
import pytest

from avaris.db import MIGRATIONS, connect, upsert

PHASE_1_TABLES = {"games", "team_games", "player_games", "rosters"}
PHASE_2_TABLES = {"injury_report_files", "injury_reports"}
DROPPED_TABLES = {"api_usage", "odds_events", "odds_snapshots"}  # migration 4
PHASE_3_TABLES = {"features", "team_ratings"}


def tables(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute("select table_name from information_schema.tables").fetchall()
    return {r[0] for r in rows}


def test_connect_creates_file_and_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "avaris.duckdb"
    con = connect(db_path)
    assert db_path.exists()
    assert tables(con) >= PHASE_1_TABLES | PHASE_2_TABLES | PHASE_3_TABLES
    assert not tables(con) & DROPPED_TABLES
    version = con.execute("select max(version) from schema_version").fetchone()
    assert version is not None
    assert version[0] == len(MIGRATIONS)


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    connect(tmp_path / "a.duckdb").close()
    con = connect(tmp_path / "a.duckdb")
    count = con.execute("select count(*) from schema_version").fetchone()
    assert count is not None
    assert count[0] == len(MIGRATIONS)


def test_upsert_replaces_by_primary_key(tmp_path: Path) -> None:
    con = connect(tmp_path / "a.duckdb")
    row = {
        "season": "2025-26", "team_id": 1, "player_id": 7, "player_name": "A",
        "position": "G", "how_acquired": None,
    }
    upsert(con, "rosters", pd.DataFrame([row]))
    upsert(con, "rosters", pd.DataFrame([{**row, "player_name": "B"}]))
    assert con.execute("select player_name from rosters").fetchall() == [("B",)]


def test_season_type_is_required(tmp_path: Path) -> None:
    con = connect(tmp_path / "a.duckdb")
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "insert into games (game_id, season, season_type, game_date_et, home_team_id, "
            "away_team_id, status, neutral_site) values ('1', '2025-26', null, '2025-10-21', "
            "1, 2, 'final', false)"
        )


def test_season_type_values_are_checked(tmp_path: Path) -> None:
    con = connect(tmp_path / "a.duckdb")
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "insert into games (game_id, season, season_type, game_date_et, home_team_id, "
            "away_team_id, status, neutral_site) values ('1', '2025-26', 'all_star', "
            "'2025-10-21', 1, 2, 'final', false)"
        )


def test_migration_4_drops_tables_from_a_version_3_db(tmp_path: Path) -> None:
    # The real DB was created at version 3 with populated tables
    db_path = tmp_path / "a.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("create table schema_version (version integer primary key)")
    for version, ddl in enumerate(MIGRATIONS[:3], start=1):
        con.execute(ddl)
        con.execute("insert into schema_version values (?)", [version])
    con.execute(
        "insert into api_usage (run_id, ts_utc, endpoint, purpose, est_cost, status) "
        "values ('r', now(), '/v4/sports', 'prime', 0, 'ok')"
    )
    con.close()
    con = connect(db_path)
    assert not tables(con) & DROPPED_TABLES
    assert tables(con) >= PHASE_1_TABLES | PHASE_2_TABLES
    assert con.execute("select max(version) from schema_version").fetchone() == (
        len(MIGRATIONS),
    )


def test_migration_6_adds_season_to_date_columns_to_a_populated_version_5_db(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "a.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("create table schema_version (version integer primary key)")
    for version, ddl in enumerate(MIGRATIONS[:5], start=1):
        con.execute(ddl)
        con.execute("insert into schema_version values (?)", [version])
    con.execute(
        "insert into features (game_id, decision_ts, feature_hash, season, season_type, "
        "game_date_et, home_team_id, away_team_id, home_court, no_fans, is_preseason, "
        "is_postseason) values ('g', now(), 'h', '2024-25', 'regular', '2024-11-01', 1, 2, "
        "1, 0, 0, 0)"
    )
    con.close()
    con = connect(db_path)
    row = con.execute("select game_id, home_ortg_std, away_pace_std from features").fetchone()
    assert row == ("g", None, None)
