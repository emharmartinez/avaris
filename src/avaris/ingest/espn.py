import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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
from avaris.seasons import ET, et_date, season_for_date, season_start_year

# NBA injury reports do not cover the preseason (ADR-022) and cannot be valued before a
# team's first game of the season (ADR-025)
ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_INJURIES_URL = f"{ESPN_API}/injuries"
# Live scores for the Traditional tab (ADR-024): one ET date per request
ESPN_SCOREBOARD_URL = f"{ESPN_API}/scoreboard"
OUT_WINDOW_HOURS = 36.0
ENTRY_COLUMNS = ["team_id", "player_name", "status", "comment", "entry_ts"]
# Future-tense rulings only: a recap ("did not play Monday") is not a ruling
OUT_NOTE = re.compile(
    r"\b(?:won't|will not|wouldn't|would not) (?:play|suit up|be available|travel)\b"
    r"|\bruled out\b|\bwill (?:rest|sit|sit out|miss)\b|\bis out\b"
    r"|\b(?:will|to) be (?:rested|held out|sidelined|inactive|unavailable)\b"
    r"|(?:not|n't) expected to (?:play|suit up|be available|face)\b"
    r"|\bunlikely to (?:play|suit up|be available)\b"
    r"|\bis not playing\b|\bisn't playing\b|\bis (?:doubtful|inactive)\b"
)
NOT_RULED_OUT = re.compile(r"(?:not|n't) (?:been |be )?ruled out\b")
WEEKDAYS = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")
# Not a ruling when negated or hedged: "won't miss", "isn't expected to miss", "could miss"
UNSURE = ("(?<!won't )(?<!will not )(?<!could )(?<!may )(?<!might )(?<!n't expected to )"
          "(?<!not expected to )")
NEGATED = "(?:won't|will not|not) "
# A note that rules a player out for a span counts for that span, past the window and
# whatever weekday it names: "will miss at least two weeks", "re-evaluated in two weeks"
SPAN_NOTE = re.compile(
    rf"{UNSURE}\b(?:miss|be out|be sidelined|sidelined for|re-?evaluated in)"
    r" (?:at least |about |approximately |roughly |around |up to )?(?:the next )?"
    r"(?P<count>\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten|twelve"
    r"|a couple(?: of)?|a few|several)(?:(?: to |-)\w+)? (?P<unit>day|week|month)s?\b"
)
# ... or for the preseason or the season ("the 2026-27 season" names it), until that
# season ends; "the preseason finale" or "the season opener" is one game
SEASON_NOTE = re.compile(
    rf"(?:{UNSURE}\b(?:miss|be out for|out for)|{NEGATED}play (?:during|in)) (?:the )?"
    r"(?:rest of the |remainder of the |entire |entirety of the |whole )?"
    r"(?:(?P<season>\d{4}-\d{2}) )?(?:regular )?(?:pre)?season\b"
    r"(?![ -](?:finale|opener|games?|contest|matchup|meeting|exhibition|rematch|tilt|debut))"
    rf"|\bseason-ending\b|{NEGATED}be ready for the start of the (?:regular )?season\b"
)
COUNTS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "a couple": 2,
          "a couple of": 2, "a few": 3, "several": 3}
UNIT_DAYS = {"day": 1, "week": 7, "month": 30}
SEASON_END = (7, 1)  # month, day: after the Finals

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


def out_until(text: str, entry_ts: datetime) -> datetime | None:
    # When a (lowercase) note posted at entry_ts stops ruling the player out: the end of its
    # span or season, the earlier of the two; None if it names neither or a past season
    ends = []
    span = SPAN_NOTE.search(text)
    if span is not None:
        count = span["count"]
        days = (int(count) if count.isdigit() else COUNTS[count]) * UNIT_DAYS[span["unit"]]
        ends.append(entry_ts + timedelta(days=days))
    season = SEASON_NOTE.search(text)
    if season is not None:
        posted_in = season_for_date(et_date(entry_ts))
        named = season["season"] or posted_in
        if named >= posted_in:
            ends.append(datetime(season_start_year(named) + 1, *SEASON_END))
    return min(ends, default=None)


def is_out(
    status: str, comment: str | None, entry_ts: datetime | None, tip_utc: datetime,
    window_hours: float,
) -> bool:
    # Status Out; a note ruling the player out for a span that covers tip-off; or a note
    # posted within window_hours before tip-off that rules the player out, which when it
    # names weekdays must name the game's (ET)
    if status.strip().lower() == "out":
        return True
    if not comment or entry_ts is None or pd.isna(entry_ts) or entry_ts > tip_utc:
        return False
    text = comment.replace("\u2019", "'").lower()
    if NOT_RULED_OUT.search(text):
        return False
    until = out_until(text, entry_ts)
    if until is not None and tip_utc <= until:
        return True
    if tip_utc - timedelta(hours=window_hours) > entry_ts or not OUT_NOTE.search(text):
        return False
    days = set(WEEKDAYS.findall(text))
    weekday = tip_utc.replace(tzinfo=UTC).astimezone(ET).strftime("%A").lower()
    return not days or weekday in days


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class EspnClient:
    # Neither feed has history: every response is kept under live/espn for inspection only
    def __init__(
        self,
        cache_dir: Path,
        throttle: Throttle,
        timeout_s: float = 20.0,
        max_attempts: int = 3,
        retry_wait_s: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.cache_dir = cache_dir / "live" / "espn"
        self.throttle = throttle
        self.max_attempts = max_attempts
        self.retry_wait_s = retry_wait_s
        self.requests_made = 0
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

    def close(self) -> None:
        self._http.close()

    def get_injuries(self, now_utc: datetime) -> dict[str, Any]:
        return self._get(ESPN_INJURIES_URL, {}, f"injuries_{now_utc:%Y%m%dT%H%M%S}Z.json")

    def get_scoreboard(self, day: date) -> dict[str, Any]:
        # The latest copy per date
        return self._get(ESPN_SCOREBOARD_URL, {"dates": f"{day:%Y%m%d}"},
                         f"scoreboard_{day:%Y%m%d}.json")

    def _get(self, url: str, params: dict[str, str], saved_as: str) -> dict[str, Any]:
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
                response = self._http.get(url, params=params)
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                (self.cache_dir / saved_as).write_text(json.dumps(payload))
                return payload
        raise AssertionError("unreachable")


@dataclass
class EspnIngestSummary:
    fetched: bool = False
    new_snapshot: bool = False
    entries: int = 0
    unmatched: int = 0


def espn_due(con: duckdb.DuckDBPyConnection, now_utc: datetime, window_hours: float) -> bool:
    # A game that reads the list tips off in (now, now + window] and has no final prediction
    # yet: a preseason game (ADR-022), or a game where a team has no final non-preseason game
    # this season, whose report cannot be valued yet (ADR-025)
    row = con.execute(
        """
        select count(*) from games g
        where g.tip_off_utc > ? and g.tip_off_utc <= ?
            and g.game_id not in (select game_id from predictions where status = 'final')
            and (g.season_type = 'preseason' or exists (
                select 1 from (values (g.home_team_id), (g.away_team_id)) t(team_id)
                where not exists (
                    select 1 from games e
                    where e.season = g.season and e.season_type <> 'preseason'
                        and e.status = 'final' and e.tip_off_utc < g.tip_off_utc
                        and t.team_id in (e.home_team_id, e.away_team_id))))
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
    # One request, only when a game that reads the list is due. An unchanged list adds a
    # fetch row pointing at the stored snapshot, so reruns leave predictions untouched
    summary = EspnIngestSummary()
    if not espn_due(con, now_utc, window_hours):
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
