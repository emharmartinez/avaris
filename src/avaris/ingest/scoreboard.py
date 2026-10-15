import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from avaris.config import Settings
from avaris.ingest.espn import EspnClient
from avaris.ingest.nba_schedule import STATUS_BY_CODE
from avaris.ingest.stats_client import Payload, RawCache, StatsClient, Throttle
from avaris.ingest.teams import team_ids_by_name
from avaris.traditional.live import clock_minutes

# Live scores, period and clock for one ET date (ADR-024); one request covers every game.
# ESPN first: stats.nba.com's scoreboard has run minutes behind the game (#30)
SCOREBOARD = "scoreboardv3"
LIVE_TTL_S = 30.0
LIVE_TIMEOUT_S = 15.0
LIVE_ATTEMPTS = 2
ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}

log = logging.getLogger(__name__)
GameKey = tuple[int, int]  # (home_team_id, away_team_id): a pairing plays once a day at most
Fetch = Callable[[date], dict[GameKey, "LiveGame"]]


@dataclass(frozen=True)
class LiveGame:
    status: str  # scheduled, in_progress or final
    label: str  # e.g. "2nd Qtr", "Halftime", "Final/OT"
    period: int
    clock: float | None  # minutes left in the period; None when not running
    regulation_periods: int
    home_pts: int
    away_pts: int


def fetch_scoreboard(client: StatsClient, day: date) -> Payload:
    # Not final: refetched every time (the raw cache keeps the latest copy per date)
    return client.get_json(SCOREBOARD, {"GameDate": day.isoformat(), "LeagueID": "00"},
                           final=False)


def _game(raw: dict[str, Any]) -> LiveGame:
    return LiveGame(
        status=STATUS_BY_CODE.get(int(raw.get("gameStatus") or 1), "scheduled"),
        label=str(raw.get("gameStatusText") or "").strip(),
        period=int(raw.get("period") or 0),
        clock=clock_minutes(raw.get("gameClock")),
        regulation_periods=int(raw.get("regulationPeriods") or 4),
        home_pts=int(raw["homeTeam"].get("score") or 0),
        away_pts=int(raw["awayTeam"].get("score") or 0),
    )


def parse_scoreboard(payload: Payload) -> dict[GameKey, LiveGame]:
    games = (payload.get("scoreboard") or {}).get("games") or []
    return {(int(g["homeTeam"]["teamId"]), int(g["awayTeam"]["teamId"])): _game(g)
            for g in games}


def _period_name(period: int, regulation: int) -> str:
    # The NBA's own wording: "3rd Qtr", "OT", "2OT"
    if period <= regulation:
        return f"{ORDINALS.get(period, f'{period}th')} Qtr"
    extra = period - regulation
    return "OT" if extra == 1 else f"{extra}OT"


def _espn_label(status: dict[str, Any], period: int, regulation: int) -> str:
    kind = status["type"]
    name = str(kind.get("name") or "")
    if kind.get("completed"):
        return "Final" if period <= regulation else f"Final/{_period_name(period, regulation)}"
    if name == "STATUS_HALFTIME":
        return "Halftime"
    if name == "STATUS_END_PERIOD":
        return f"End of {_period_name(period, regulation)}"
    if kind.get("state") == "in":
        return _period_name(period, regulation)
    return str(kind.get("shortDetail") or "")


def _espn_status(kind: dict[str, Any]) -> str:
    # Postponed and cancelled games are "post" but not completed
    if kind.get("completed"):
        return "final"
    return "in_progress" if kind.get("state") == "in" else "scheduled"


def parse_espn_scoreboard(payload: Payload) -> dict[GameKey, LiveGame]:
    # ESPN has no NBA game ids: games are matched by teams (ESPN's display names, as for its
    # injury list). A club outside the NBA is skipped
    by_name = team_ids_by_name()
    games: dict[GameKey, LiveGame] = {}
    for event in payload.get("events") or []:
        comp = event["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        home = by_name.get(str(sides["home"]["team"].get("displayName")))
        away = by_name.get(str(sides["away"]["team"].get("displayName")))
        if home is None or away is None:
            continue
        status = comp["status"]
        period = int(status.get("period") or 0)
        regulation = int(((comp.get("format") or {}).get("regulation") or {}).get("periods") or 4)
        state = _espn_status(status["type"])
        games[(home, away)] = LiveGame(
            status=state, label=_espn_label(status, period, regulation), period=period,
            clock=float(status.get("clock") or 0) / 60 if state == "in_progress" else None,
            regulation_periods=regulation,
            home_pts=int(sides["home"].get("score") or 0),
            away_pts=int(sides["away"].get("score") or 0),
        )
    return games


def first_live(*fetches: Fetch) -> Fetch:
    # The first feed with games wins; a failed or empty one falls through to the next. Raises
    # only when every feed failed
    def fetch(day: date) -> dict[GameKey, LiveGame]:
        answered, error = False, None
        for source in fetches:
            try:
                games = source(day)
            except Exception as exc:
                log.warning("Live feed %s for %s failed: %r",
                            getattr(source, "__name__", type(source).__name__), day, exc)
                error = exc
                continue
            if games:
                return games
            answered = True
        if error is not None and not answered:
            raise error
        return {}

    return fetch


def _lazy[T](make: Callable[[], T]) -> Callable[[], T]:
    # The server's own client, opened on first use
    made: list[T] = []

    def get() -> T:
        if not made:
            made.append(make())
        return made[0]

    return get


def stats_fetcher(settings: Settings) -> Fetch:
    # Short timeout, one retry
    client = _lazy(lambda: StatsClient(RawCache(settings.paths.cache_dir),
                                       Throttle(settings.stats.min_interval_s),
                                       timeout_s=LIVE_TIMEOUT_S, max_attempts=LIVE_ATTEMPTS))

    def stats(day: date) -> dict[GameKey, LiveGame]:
        return parse_scoreboard(fetch_scoreboard(client(), day))

    return stats


def espn_fetcher(settings: Settings) -> Fetch:
    client = _lazy(lambda: EspnClient(settings.paths.cache_dir,
                                      Throttle(settings.stats.min_interval_s),
                                      timeout_s=LIVE_TIMEOUT_S, max_attempts=LIVE_ATTEMPTS))

    def espn(day: date) -> dict[GameKey, LiveGame]:
        return parse_espn_scoreboard(client().get_scoreboard(day))

    return espn


def live_fetcher(settings: Settings) -> Fetch:
    # ESPN, then stats.nba.com when ESPN fails or has no games
    return first_live(espn_fetcher(settings), stats_fetcher(settings))


@dataclass(frozen=True)
class LiveSnapshot:
    games: dict[GameKey, LiveGame] = field(default_factory=dict)
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
                snapshot = LiveSnapshot(self._fetch(day), self._clock())
            except Exception as exc:  # a dead feed must not break the pregame lines
                log.warning("Live scoreboard for %s unavailable: %r", day, exc)
                snapshot = LiveSnapshot(error=f"Live scores unavailable ({type(exc).__name__})")
            self._cached = {day: (self._monotonic(), snapshot)}
            return snapshot
