from pathlib import Path

import duckdb
import pandas as pd
import pytest

from avaris.db import MIGRATIONS, connect, upsert

PHASE_1_TABLES = {"games", "team_games", "player_games", "rosters"}


def tables(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute("select table_name from information_schema.tables").fetchall()
    return {r[0] for r in rows}


def test_connect_creates_file_and_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "avaris.duckdb"
    con = connect(db_path)
    assert db_path.exists()
    assert tables(con) >= PHASE_1_TABLES
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
