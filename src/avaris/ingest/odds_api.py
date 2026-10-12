import gzip
import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import httpx

from avaris.config import GuardSettings

API_BASE = "https://api.the-odds-api.com"
API_KEY_ENV = "ODDS_API_KEY"
HISTORICAL_MULTIPLIER = 10  # historical odds cost 10 x markets x regions
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

Params = Mapping[str, str]
Headers = Mapping[str, str]


class OddsApiError(Exception):
    pass


class CreditRefused(Exception):
    pass


class LedgerMismatch(Exception):
    pass


def load_api_key(env_file: Path = Path(".env.local")) -> str | None:
    # The environment wins; otherwise read ODDS_API_KEY from .env.local. The sandbox
    # blocks that file, so odds commands that spend credits are user-run
    if key := os.environ.get(API_KEY_ENV):
        return key
    try:
        lines = env_file.read_text().splitlines()
    except (FileNotFoundError, PermissionError):
        return None
    for line in lines:
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == API_KEY_ENV:
            return value.strip().strip("'\"") or None
    return None


def iso_z(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _int_header(headers: Headers, name: str) -> int | None:
    value = headers.get(name)
    return int(float(value)) if value not in (None, "") else None


class CreditGuard:
    # Every Odds API call is cost-checked here first and written to the api_usage ledger
    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        limits: GuardSettings,
        run_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC).replace(tzinfo=None),
    ) -> None:
        self.con = con
        self.limits = limits
        self.run_id = run_id
        self.clock = clock
        self.used: int | None = None  # credits used this billing month (x-requests-used)
        self.remaining: int | None = None
        self.run_spent = 0

    def prime(self, used: int, remaining: int) -> None:
        self.used, self.remaining = used, remaining

    def refusal(self, cost: int, purpose: str) -> str | None:
        if cost == 0:
            return None
        if self.used is None or self.remaining is None:
            return "guard not primed with current usage"
        lim = self.limits
        month_after = self.used + cost
        if self.run_spent + cost > lim.max_credits_per_run:
            return f"per-run cap: {self.run_spent} + {cost} > {lim.max_credits_per_run}"
        budget = lim.monthly_credit_budget - lim.headroom.get(purpose, 0)
        if month_after > budget:
            return f"monthly budget: {month_after} > {budget} for {purpose}"
        if lim.usd_per_credit > 0 and month_after * lim.usd_per_credit > lim.max_monthly_usd:
            usd = month_after * lim.usd_per_credit
            return f"monthly USD: ${usd:.2f} > ${lim.max_monthly_usd:.2f}"
        if self.remaining - cost < lim.min_remaining_reserve:
            return f"reserve: {self.remaining} - {cost} < {lim.min_remaining_reserve}"
        return None

    def authorize(self, endpoint: str, params: Params, cost: int, purpose: str) -> None:
        if reason := self.refusal(cost, purpose):
            self.record(endpoint, params, purpose, cost, {}, "refused", reason)
            raise CreditRefused(f"{endpoint} ({purpose}, {cost} credits) refused: {reason}")

    def record(
        self,
        endpoint: str,
        params: Params,
        purpose: str,
        est_cost: int,
        headers: Headers,
        status: str,
        message: str | None = None,
    ) -> None:
        actual = _int_header(headers, "x-requests-last")
        used = _int_header(headers, "x-requests-used")
        remaining = _int_header(headers, "x-requests-remaining")
        if actual is not None:
            self.run_spent += actual
        if used is not None:
            self.used = used
        if remaining is not None:
            self.remaining = remaining
        safe_params = {k: v for k, v in params.items() if k != "apiKey"}
        self.con.execute(
            """
            insert into api_usage (run_id, ts_utc, endpoint, params, purpose, est_cost,
                actual_cost, requests_used, requests_remaining, status, message)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [self.run_id, self.clock(), endpoint, json.dumps(safe_params, sort_keys=True),
             purpose, est_cost, actual, used, remaining, status, message],
        )


class OddsApiClient:
    def __init__(
        self,
        api_key: str | None,
        guard: CreditGuard,
        cache_dir: Path,
        sport: str,
        regions: list[str],
        markets: list[str],
        timeout_s: float = 30.0,
        max_attempts: int = 3,
        retry_wait_s: float = 2.0,
    ) -> None:
        self.guard = guard
        self.sport = sport
        self.regions = regions
        self.markets = markets
        self.max_attempts = max_attempts
        self.retry_wait_s = retry_wait_s
        self.requests_made = 0
        self._key = api_key
        self._final = cache_dir / "final" / "odds"
        self._live = cache_dir / "live" / "odds"
        self._http = httpx.Client(base_url=API_BASE, timeout=timeout_s)
        # httpx logs each request URL, apiKey included, at INFO
        logging.getLogger("httpx").setLevel(logging.WARNING)

    def close(self) -> None:
        self._http.close()

    @property
    def historical_cost(self) -> int:
        return HISTORICAL_MULTIPLIER * len(self.markets) * len(self.regions)

    def _scrub(self, text: str) -> str:
        return text.replace(self._key, "***") if self._key else text

    def _historical_path(self, snapshot_ts: datetime, start: datetime, end: datetime) -> Path:
        # Built from the request fields only, never from the params (which carry the key)
        name = (
            f"{snapshot_ts:%Y%m%dT%H%M%SZ}_{start:%Y%m%dT%H%M}-{end:%Y%m%dT%H%M}_"
            f"{'+'.join(self.regions)}_{'+'.join(self.markets)}.json.gz"
        )
        return self._final / "historical" / self.sport / name

    def is_cached(self, snapshot_ts: datetime, start: datetime, end: datetime) -> bool:
        return self._historical_path(snapshot_ts, start, end).exists()

    def prime(self) -> None:
        # /v4/sports is free and returns the month's usage headers
        headers, _ = self._get("/v4/sports", {}, est_cost=0, purpose="prime")
        self.guard.record("/v4/sports", {}, "prime", 0, headers, "ok")
        used = _int_header(headers, "x-requests-used")
        remaining = _int_header(headers, "x-requests-remaining")
        if used is None or remaining is None:
            raise OddsApiError("/v4/sports returned no usage headers")
        self.guard.prime(used, remaining)

    def historical_odds(
        self, snapshot_ts: datetime, purpose: str, start: datetime, end: datetime
    ) -> dict[str, Any]:
        # The snapshot at or before snapshot_ts for events commencing in [start, end]
        path = self._historical_path(snapshot_ts, start, end)
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        endpoint = f"/v4/historical/sports/{self.sport}/odds"
        params = {
            "regions": ",".join(self.regions),
            "markets": ",".join(self.markets),
            "date": iso_z(snapshot_ts),
            "commenceTimeFrom": iso_z(start),
            "commenceTimeTo": iso_z(end),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        est = self.historical_cost
        headers, payload = self._get(endpoint, params, est, purpose)
        returned = {m["key"] for e in payload.get("data", []) for b in e.get("bookmakers", [])
                    for m in b.get("markets", [])}
        charged_for = HISTORICAL_MULTIPLIER * len(returned & set(self.markets)) * len(self.regions)
        actual = _int_header(headers, "x-requests-last")
        if actual not in (est, charged_for):
            message = f"x-requests-last {actual} != estimate {est} (or {charged_for})"
            self.guard.record(endpoint, params, purpose, est, headers, "mismatch", message)
            raise LedgerMismatch(f"{endpoint} at {params['date']}: {message}")
        self.guard.record(endpoint, params, purpose, est, headers, "ok")
        _write_gz(path, payload)
        return payload

    def live_odds(self, purpose: str) -> list[dict[str, Any]]:
        endpoint = f"/v4/sports/{self.sport}/odds"
        params = {
            "regions": ",".join(self.regions),
            "markets": ",".join(self.markets),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        est = len(self.markets) * len(self.regions)
        headers, payload = self._get(endpoint, params, est, purpose)
        actual = _int_header(headers, "x-requests-last")
        status = "ok" if actual in (est, 0) else "mismatch"
        self.guard.record(endpoint, params, purpose, est, headers, status)
        if status == "mismatch":
            raise LedgerMismatch(f"{endpoint}: x-requests-last {actual} != estimate {est}")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        _write_gz(self._live / self.sport / f"{stamp}.json.gz", payload)
        return payload

    def _get(
        self, endpoint: str, params: Params, est_cost: int, purpose: str
    ) -> tuple[Headers, Any]:
        if not self._key:
            raise OddsApiError(f"{API_KEY_ENV} is not set (env var or .env.local)")
        for attempt in range(1, self.max_attempts + 1):
            self.guard.authorize(endpoint, params, est_cost, purpose)
            self.requests_made += 1
            try:
                response = self._http.get(endpoint, params={**params, "apiKey": self._key})
            except httpx.TransportError as exc:
                message = self._scrub(f"{type(exc).__name__}: {exc}")
                self.guard.record(endpoint, params, purpose, est_cost, {}, "error", message)
                if attempt == self.max_attempts:
                    raise OddsApiError(f"{endpoint} failed: {message}") from None
            else:
                if response.status_code == 200:
                    return response.headers, response.json()
                message = self._scrub(f"HTTP {response.status_code}: {response.text[:200]}")
                self.guard.record(
                    endpoint, params, purpose, est_cost, response.headers, "error", message
                )
                if response.status_code not in RETRYABLE_STATUS or attempt == self.max_attempts:
                    raise OddsApiError(f"{endpoint} failed: {message}") from None
            time.sleep(self.retry_wait_s * 2 ** (attempt - 1))
        raise AssertionError("unreachable")


def _write_gz(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    tmp.replace(path)
