import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pandas as pd
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from avaris.db import upsert
from avaris.ingest.injuries import PlayerIndex
from avaris.ingest.stats_client import Throttle
from avaris.ingest.teams import team_ids_by_name
from avaris.seasons import ET, et_date, season_for_date

# Preseason only (ADR-022): NBA injury reports do not cover the preseason
ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
OUT_WINDOW_HOURS = 36.0
ENTRY_COLUMNS = ["team_id", "player_name", "status", "comment", "entry_ts"]
# Future-tense rulings only: a recap ("did not play Monday") is not a ruling
OUT_NOTE = re.compile(
    r"\b(?:won't|will not|wouldn't|would not) (?:play|suit up|be available)\b"
    r"|\bruled out\b|\bwill (?:rest|sit|sit out|miss|be held out)\b|\bis out\b"
)
NOT_RULED_OUT = re.compile(r"(?:not|n't) (?:been |be )?ruled out\b")
WEEKDAYS = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")

Progress = Callable[[str], None]


def parse_espn_injuries(payload: dict[str, Any]) -> pd.DataFrame:
    # One row per listed player of an NBA team; entry_ts is the note's posting time (naive
    # UTC). Other clubs are skipped: their games get no adjustment anyway (#11)
    by_name = team_ids_by_name()
    rows = []
    for team in payload.get("injuries", []):
        team_id = by_name.get(str(team.get("displayName")))
        if team_id is None:
            continue
        for e in team.get("injuries", []):
            rows.append({
                "team_id": team_id, "player_name": str(e["athlete"]["displayName"]),
                "status": str(e.get("status") or ""), "comment": e.get("shortComment"),
                "entry_ts": e.get("date"),
            })
    df = pd.DataFrame(rows, columns=ENTRY_COLUMNS)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True, format="ISO8601").dt.tz_localize(None)
    return df.drop_duplicates(["team_id", "player_name"]).reset_index(drop=True)


def is_out(
    status: str, comment: str | None, entry_ts: datetime | None, tip_utc: datetime,
    window_hours: float,
) -> bool:
    # Status Out, or a note posted within window_hours before tip-off that rules the
    # player out; a note naming weekdays must name the game's (ET)
    if status.strip().lower() == "out":
        return True
    if not comment or entry_ts is None or pd.isna(entry_ts):
        return False
    if not tip_utc - timedelta(hours=window_hours) <= entry_ts <= tip_utc:
        return False
    text = comment.replace("\u2019", "'").lower()
    if not OUT_NOTE.search(text) or NOT_RULED_OUT.search(text):
        return False
    days = set(WEEKDAYS.findall(text))
    weekday = tip_utc.replace(tzinfo=UTC).astimezone(ET).strftime("%A").lower()
    return not days or weekday in days


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class EspnClient:
    # The list has no history: every response is kept under live/espn for inspection only
    def __init__(
        self,
        cache_dir: Path,
        throttle: Throttle,
        timeout_s: float = 20.0,
        max_attempts: int = 3,
        retry_wait_s: float = 2.0,
    ) -> None:
        self.cache_dir = cache_dir / "live" / "espn"
        self.throttle = throttle
        self.max_attempts = max_attempts
        self.retry_wait_s = retry_wait_s
        self.requests_made = 0
        self._http = httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        self._http.close()

    def get_injuries(self, now_utc: datetime) -> dict[str, Any]:
        retrying = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=self.retry_wait_s, max=30),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                self.throttle.wait()
                self.requests_made += 1
                response = self._http.get(ESPN_INJURIES_URL)
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                (self.cache_dir / f"injuries_{now_utc:%Y%m%dT%H%M%S}Z.json").write_text(
                    json.dumps(payload))
                return payload
        raise AssertionError("unreachable")


@dataclass
class EspnIngestSummary:
    fetched: bool = False
    new_snapshot: bool = False
    entries: int = 0
    unmatched: int = 0


def preseason_due(con: duckdb.DuckDBPyConnection, now_utc: datetime, window_hours: float) -> bool:
    # A preseason game tips off in (now, now + window] and has no final prediction yet
    row = con.execute(
        """
        select count(*) from games g
        where g.season_type = 'preseason' and g.tip_off_utc > ? and g.tip_off_utc <= ?
            and g.game_id not in (select game_id from predictions where status = 'final')
        """,
        [now_utc, now_utc + timedelta(hours=window_hours)],
    ).fetchone()
    return bool(row and row[0])


def _latest_snapshot(
    con: duckdb.DuckDBPyConnection,
) -> tuple[datetime | None, set[tuple[Any, ...]]]:
    row = con.execute("select max(snapshot_ts) from espn_injury_fetches").fetchone()
    snapshot_ts = row[0] if row else None
    if snapshot_ts is None:
        return None, set()
    stored = con.execute(
        "select team_id, player_name, player_id, status, comment, entry_ts "
        "from espn_injury_snapshots where fetched_at = ?", [snapshot_ts]).df()
    return snapshot_ts, _keys(stored)


def _keys(df: pd.DataFrame) -> set[tuple[Any, ...]]:
    return {
        tuple(None if pd.isna(v) else v for v in r)
        for r in df[["team_id", "player_name", "player_id", "status", "comment", "entry_ts"]]
        .astype(object).itertuples(index=False)
    }


def ingest_espn(
    con: duckdb.DuckDBPyConnection,
    client: EspnClient,
    now_utc: datetime,
    window_hours: float,
    progress: Progress = lambda _msg: None,
) -> EspnIngestSummary:
    # One request, only when a preseason game is due. An unchanged list adds a fetch row
    # pointing at the stored snapshot, so reruns leave predictions untouched
    summary = EspnIngestSummary()
    if not preseason_due(con, now_utc, window_hours):
        return summary
    payload = client.get_injuries(now_utc)
    summary.fetched = True
    entries = parse_espn_injuries(payload)
    players = PlayerIndex.load(con)
    season = season_for_date(et_date(now_utc))
    entries["player_id"] = pd.array(
        [players.find(season, int(t), str(n))
         for t, n in zip(entries["team_id"], entries["player_name"], strict=True)],
        dtype="Int64",
    )
    summary.entries = len(entries)
    summary.unmatched = int(entries["player_id"].isna().sum())
    latest_ts, latest = _latest_snapshot(con)
    snapshot_ts = latest_ts if latest_ts is not None and latest == _keys(entries) else now_utc
    summary.new_snapshot = snapshot_ts == now_utc
    con.begin()
    try:
        if summary.new_snapshot:
            upsert(con, "espn_injury_snapshots", entries.assign(fetched_at=now_utc))
        upsert(con, "espn_injury_fetches",
               pd.DataFrame([{"fetched_at": now_utc, "snapshot_ts": snapshot_ts}]))
        con.commit()
    except BaseException:
        con.rollback()
        raise
    progress(f"ESPN injuries: {summary.entries} entries, {summary.unmatched} unmatched"
             + ("" if summary.new_snapshot else " (unchanged)"))
    return summary
