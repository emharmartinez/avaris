import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from avaris.config import Settings
from avaris.ingest.nba_schedule import STATUS_BY_CODE
from avaris.ingest.stats_client import Payload, RawCache, StatsClient, Throttle

# Live scores, period and clock for one ET date (ADR-024); one request covers every game
SCOREBOARD = "scoreboardv3"
LIVE_TTL_S = 30.0
LIVE_TIMEOUT_S = 15.0
LIVE_ATTEMPTS = 2

log = logging.getLogger(__name__)
Fetch = Callable[[date], Payload]


@dataclass(frozen=True)
class LiveGame:
    game_id: str
    status: str  # scheduled, in_progress or final
    label: str  # e.g. "2nd Qtr", "Halftime", "Final/OT"
    period: int
    clock: str
    regulation_periods: int
    home_pts: int
    away_pts: int


def fetch_scoreboard(client: StatsClient, day: date) -> Payload:
    # Not final: refetched every time (the raw cache keeps the latest copy per date)
    return client.get_json(SCOREBOARD, {"GameDate": day.isoformat(), "LeagueID": "00"},
                           final=False)


def _game(raw: dict[str, Any]) -> LiveGame:
    return LiveGame(
        game_id=str(raw["gameId"]),
        status=STATUS_BY_CODE.get(int(raw.get("gameStatus") or 1), "scheduled"),
        label=str(raw.get("gameStatusText") or "").strip(),
        period=int(raw.get("period") or 0),
        clock=str(raw.get("gameClock") or ""),
        regulation_periods=int(raw.get("regulationPeriods") or 4),
        home_pts=int(raw["homeTeam"].get("score") or 0),
        away_pts=int(raw["awayTeam"].get("score") or 0),
    )


def parse_scoreboard(payload: Payload) -> dict[str, LiveGame]:
    games = (payload.get("scoreboard") or {}).get("games") or []
    return {game.game_id: game for game in map(_game, games)}


def stats_fetcher(settings: Settings) -> Fetch:
    # The server's own client, opened on first use: short timeout, one retry
    client: StatsClient | None = None

    def fetch(day: date) -> Payload:
        nonlocal client
        if client is None:
            client = StatsClient(RawCache(settings.paths.cache_dir),
                                 Throttle(settings.stats.min_interval_s),
                                 timeout_s=LIVE_TIMEOUT_S, max_attempts=LIVE_ATTEMPTS)
        return fetch_scoreboard(client, day)

    return fetch


@dataclass(frozen=True)
class LiveSnapshot:
    games: dict[str, LiveGame] = field(default_factory=dict)
    fetched_at: datetime | None = None
    error: str | None = None


class LiveScoreboard:
    # The latest scoreboard per date, refetched at most every `ttl_s`. A failure is held as
    # long, so an open tab never hammers a blocked feed. Held in memory only: live scores are
    # never written to DuckDB
    def __init__(
        self, fetch: Fetch, clock: Callable[[], datetime], monotonic: Callable[[], float],
        ttl_s: float = LIVE_TTL_S,
    ) -> None:
        self._fetch = fetch
        self._clock = clock
        self._monotonic = monotonic
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        self._cached: dict[date, tuple[float, LiveSnapshot]] = {}

    def get(self, day: date) -> LiveSnapshot:
        with self._lock:
            hit = self._cached.get(day)
            if hit is not None and self._monotonic() - hit[0] < self._ttl_s:
                return hit[1]
            try:
                snapshot = LiveSnapshot(parse_scoreboard(self._fetch(day)), self._clock())
            except Exception as exc:  # a dead feed must not break the pregame lines
                log.warning("Live scoreboard for %s unavailable: %r", day, exc)
                snapshot = LiveSnapshot(error=f"Live scores unavailable ({type(exc).__name__})")
            self._cached = {day: (self._monotonic(), snapshot)}
            return snapshot
