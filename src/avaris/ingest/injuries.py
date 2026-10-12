import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import duckdb
import httpx
import pandas as pd
import pymupdf
from nba_injury_report.report import _process_pdf
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from avaris.db import upsert
from avaris.features.decision_time import DECISION_LEAD
from avaris.ingest.stats_client import Throttle
from avaris.ingest.teams import team_ids_by_name, team_ids_by_tricode
from avaris.seasons import ET, season_for_date

BASE_URL = "https://ak-static.cms.nba.com/referee/injury"
# Hourly reports (the "05PM" file is the 5:30 pm ET report) until 2025-12-21, then
# a report every 15 minutes named by its own time ("05_30PM")
QUARTER_HOUR_FROM = date(2025, 12, 22)
EARLY_AFTERNOON = time(13, 30)
STATUSES = {
    "Out": "out",
    "Doubtful": "doubtful",
    "Questionable": "questionable",
    "Probable": "probable",
    "Available": "available",
}
NOT_SUBMITTED = "NOT YET SUBMITTED"
HEADER_RE = re.compile(r"Injury Report: (\d{2}/\d{2}/\d{2}) (\d{2}:\d{2} [AP]M)")
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
ENTRY_COLUMNS = ["game_date_et", "matchup", "team_name", "player_name", "status", "reason"]

Progress = Callable[[str], None]


def cadence(day: date) -> timedelta:
    return timedelta(minutes=15) if day >= QUARTER_HOUR_FROM else timedelta(hours=1)


def floor_to_report_slot(ts_et: datetime) -> datetime:
    # Latest report slot at or before ts (aware ET)
    ts_et = ts_et.replace(second=0, microsecond=0)
    if cadence(ts_et.date()) == timedelta(hours=1):
        slot = ts_et.replace(minute=30)
        return slot if ts_et.minute >= 30 else slot - timedelta(hours=1)
    return ts_et.replace(minute=ts_et.minute - ts_et.minute % 15)


def report_filename(slot_et: datetime) -> str:
    if cadence(slot_et.date()) == timedelta(hours=1):
        stamp = (slot_et - timedelta(minutes=30)).strftime("%I%p")
    else:
        stamp = slot_et.strftime("%I_%M%p")
    return f"Injury-Report_{slot_et:%Y-%m-%d}_{stamp}.pdf"


def to_utc(ts_et: datetime) -> datetime:
    # Stored timestamps are naive UTC
    return ts_et.astimezone(UTC).replace(tzinfo=None)


def target_slots(tip_offs_utc: Iterable[datetime], day: date) -> list[datetime]:
    # The report each game's decision_ts resolves to, plus the early-afternoon report
    slots = {datetime.combine(day, EARLY_AFTERNOON, tzinfo=ET)}
    for tip in tip_offs_utc:
        cutoff = (tip - DECISION_LEAD).replace(tzinfo=UTC).astimezone(ET)
        slots.add(floor_to_report_slot(cutoff))
    return sorted(slots)


@dataclass(frozen=True)
class ParsedReport:
    report_ts: datetime  # naive UTC, from the PDF header
    entries: pd.DataFrame  # ENTRY_COLUMNS


def _header_ts(pdf: bytes) -> datetime:
    try:
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            text = str(doc[0].get_text())
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise ValueError(f"not an injury report PDF (no header): {exc}") from exc
    match = HEADER_RE.search(text)
    if not match:
        raise ValueError("injury report header not found")
    local = datetime.strptime(f"{match[1]} {match[2]}", "%m/%d/%y %I:%M %p")
    return to_utc(local.replace(tzinfo=ET))


def parse_report(pdf: bytes) -> ParsedReport:
    report_ts = _header_ts(pdf)
    rows = []
    for e in _process_pdf(pdf):
        status = STATUSES.get(e.current_status or "")
        if status is None and e.player_name is None and (e.reason or "") == NOT_SUBMITTED:
            status = "not_submitted"
        if status is None or e.game_date is None or e.matchup is None or e.team is None:
            raise ValueError(f"unparsed injury report row: {e.model_dump()}")
        rows.append({
            "game_date_et": datetime.strptime(e.game_date, "%m/%d/%Y").date(),
            "matchup": e.matchup,
            "team_name": e.team,
            "player_name": e.player_name or "",
            "status": status,
            "reason": e.reason,
        })
    return ParsedReport(report_ts, pd.DataFrame(rows, columns=ENTRY_COLUMNS))


def normalize_name(name: str) -> str:
    # "Trent Jr., Gary" and "Gary Trent Jr." both become "gary trent"
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first} {last}"
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^a-z ]", " ", ascii_name.lower().replace(".", "").replace("'", ""))
    return " ".join(t for t in cleaned.split() if t not in NAME_SUFFIXES)


def _initial_key(normalized: str) -> str:
    first, *rest = normalized.split()
    return f"{first[0]} {' '.join(rest)}"


class PlayerIndex:
    # Player IDs by normalized name: team-season first, then the season, then any season
    # (long-term injured players can miss a whole season's rosters and logs)
    def __init__(self, players: pd.DataFrame) -> None:
        self._team: dict[tuple[str, int, str], set[int]] = {}
        self._initial: dict[tuple[str, int, str], set[int]] = {}
        self._season: dict[tuple[str, str], set[int]] = {}
        self._any: dict[str, set[int]] = {}
        for season, team_id, player_id, name in players.itertuples(index=False):
            norm = normalize_name(str(name))
            if not norm:
                continue
            pid = int(player_id)
            self._team.setdefault((season, int(team_id), norm), set()).add(pid)
            self._initial.setdefault((season, int(team_id), _initial_key(norm)), set()).add(pid)
            self._season.setdefault((season, norm), set()).add(pid)
            self._any.setdefault(norm, set()).add(pid)

    @classmethod
    def load(cls, con: duckdb.DuckDBPyConnection) -> "PlayerIndex":
        return cls(con.execute(
            """
            select season, team_id, player_id, player_name from rosters
            union
            select distinct season, team_id, player_id, player_name from player_games
            """
        ).df())

    def find(self, season: str, team_id: int, printed: str) -> int | None:
        norm = normalize_name(printed)
        if not norm:
            return None
        for ids in (
            self._team.get((season, team_id, norm)),
            self._initial.get((season, team_id, _initial_key(norm))),
            self._season.get((season, norm)),
            self._any.get(norm),
        ):
            if ids and len(ids) == 1:
                return next(iter(ids))
        return None


def resolve_entries(
    con: duckdb.DuckDBPyConnection,
    entries: pd.DataFrame,
    report_ts: datetime,
    players: PlayerIndex | None = None,
) -> pd.DataFrame:
    # Adds game_id, team_id and player_id (null when unmatched) for the injury_reports table
    players = players or PlayerIndex.load(con)
    by_name, by_tricode = team_ids_by_name(), team_ids_by_tricode()
    dates = sorted(set(entries["game_date_et"]))
    games = con.execute(
        "select game_id, season, game_date_et, home_team_id, away_team_id from games "
        "where game_date_et in (select unnest(?::date[]))",
        [dates],
    ).fetchall()
    game_by_key = {(d, h, a): (gid, s) for gid, s, d, h, a in games}
    rows = []
    for e in entries.to_dict("records"):
        team_id = by_name.get(str(e["team_name"]))
        if team_id is None:
            raise ValueError(f"unknown team in injury report: {e['team_name']}")
        away, _, home = str(e["matchup"]).partition("@")
        key = (e["game_date_et"], by_tricode.get(home), by_tricode.get(away))
        game_id, season = game_by_key.get(key, (None, season_for_date(e["game_date_et"])))
        rows.append({
            **e,
            "report_ts": report_ts,
            "game_id": game_id,
            "team_id": team_id,
            "player_id": players.find(season, team_id, str(e["player_name"])),
        })
    out = pd.DataFrame(rows).drop(columns="team_name")
    out["player_id"] = out["player_id"].astype("Int64")
    return out


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class InjuryClient:
    # Report PDFs are immutable once posted, so every fetched PDF is cached for good
    def __init__(
        self,
        cache_dir: Path,
        throttle: Throttle,
        timeout_s: float = 30.0,
        max_attempts: int = 3,
        retry_wait_s: float = 2.0,
    ) -> None:
        self.cache_dir = cache_dir / "final" / "injuries"
        self.throttle = throttle
        self.max_attempts = max_attempts
        self.retry_wait_s = retry_wait_s
        self.requests_made = 0
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout_s)

    def close(self) -> None:
        self._http.close()

    def get_pdf(self, filename: str) -> bytes | None:
        # None when the report does not exist (403/404)
        path = self.cache_dir / filename
        if path.exists():
            return path.read_bytes()
        pdf = self._fetch(filename)
        if pdf is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(pdf)
            tmp.replace(path)
        return pdf

    def _fetch(self, filename: str) -> bytes | None:
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
                response = self._http.get(f"/{filename}")
                if response.status_code in (403, 404):
                    return None
                response.raise_for_status()
                return response.content
        raise AssertionError("unreachable")


@dataclass
class InjuryIngestSummary:
    reports: int = 0
    missing: int = 0
    entries: int = 0
    unmatched_players: int = 0


def ingest_injuries(
    con: duckdb.DuckDBPyConnection,
    client: InjuryClient,
    seasons: list[str],
    now_utc: datetime,
    max_step_back: int,
    progress: Progress = lambda _msg: None,
) -> InjuryIngestSummary:
    # For each game day, fetch the report every game's decision_ts resolves to (stepping
    # back a slot at a time when a report is missing) plus the early-afternoon report
    summary = InjuryIngestSummary()
    days = con.execute(
        """
        select season, game_date_et, list(tip_off_utc order by tip_off_utc) from games
        where season_type <> 'preseason' and tip_off_utc is not null
            and season in (select unnest(?::varchar[]))
        group by season, game_date_et order by game_date_et
        """,
        [seasons],
    ).fetchall()
    known = dict(con.execute("select slot_ts, status from injury_report_files").fetchall())
    players = PlayerIndex.load(con)
    for i, (season, day, tips) in enumerate(days):
        for target in target_slots(tips, day):
            slot = target
            for _ in range(max_step_back + 1):
                slot_utc = to_utc(slot)
                if slot_utc > now_utc:
                    break
                status = known.get(slot_utc)
                if status == "ok":
                    break
                if status is None:
                    status = _ingest_slot(con, client, slot, now_utc, players, summary)
                    if status is not None:
                        known[slot_utc] = status
                    if status == "ok":
                        break
                slot -= cadence(slot.date())
        if i + 1 == len(days) or days[i + 1][0] != season:
            progress(
                f"{season}: {summary.reports} reports, {summary.missing} missing slots, "
                f"{client.requests_made} requests so far"
            )
    return summary


def _ingest_slot(
    con: duckdb.DuckDBPyConnection,
    client: InjuryClient,
    slot: datetime,
    now_utc: datetime,
    players: PlayerIndex,
    summary: InjuryIngestSummary,
) -> str | None:
    filename = report_filename(slot)
    slot_utc = to_utc(slot)
    pdf = client.get_pdf(filename)
    file_row = {
        "slot_ts": slot_utc, "report_ts": None, "url": f"{BASE_URL}/{filename}",
        "status": "missing", "n_entries": None, "fetched_at": now_utc,
    }
    if pdf is None:
        # A recent slot may still be posted later, so only old misses are remembered
        if now_utc - slot_utc < timedelta(hours=6):
            return None
        summary.missing += 1
        upsert(con, "injury_report_files", pd.DataFrame([file_row]))
        return "missing"
    report = parse_report(pdf)
    entries = resolve_entries(con, report.entries, report.report_ts, players)
    con.begin()
    try:
        upsert(con, "injury_reports", entries)
        upsert(con, "injury_report_files", pd.DataFrame([{
            **file_row, "report_ts": report.report_ts, "status": "ok", "n_entries": len(entries),
        }]))
        con.commit()
    except BaseException:
        con.rollback()
        raise
    summary.reports += 1
    summary.entries += len(entries)
    named = entries[entries["player_name"] != ""]
    summary.unmatched_players += int(named["player_id"].isna().sum())
    return "ok"
