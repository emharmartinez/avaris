import gzip
import json
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

BASE_URL = "https://stats.nba.com/stats"

# stats.nba.com hangs (no response at all) unless the request looks like a browser
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="140", "Google Chrome";v="140", "Not;A=Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

Params = Mapping[str, str]
Payload = dict[str, Any]


class EmptyResponseError(Exception):
    # A 200 with no rows for a finished season: treated as a glitch, never cached as final
    pass


def has_rows(payload: Payload) -> bool:
    if "leagueSchedule" in payload:
        return bool(payload["leagueSchedule"].get("gameDates"))
    result_sets = payload.get("resultSets") or []
    return bool(result_sets) and bool(result_sets[0].get("rowSet"))


class Throttle:
    def __init__(
        self,
        min_interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.min_interval_s - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


class RawCache:
    # final/ holds immutable responses (finished seasons) and is read back;
    # live/ keeps in-progress responses for inspection only and is never read
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, endpoint: str, params: Params, final: bool) -> Path:
        key = "_".join(f"{k}={v}" for k, v in sorted(params.items()))
        slug = re.sub(r"[^A-Za-z0-9=_.-]+", "-", key) or "default"
        return self.root / ("final" if final else "live") / endpoint / f"{slug}.json.gz"

    def get(self, endpoint: str, params: Params) -> Payload | None:
        path = self._path(endpoint, params, final=True)
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)

    def put(self, endpoint: str, params: Params, payload: Payload, final: bool = True) -> None:
        path = self._path(endpoint, params, final)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(payload, f)
        tmp.replace(path)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, EmptyResponseError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class StatsClient:
    def __init__(
        self,
        cache: RawCache,
        throttle: Throttle,
        timeout_s: float = 60.0,
        max_attempts: int = 4,
        retry_wait_s: float = 2.0,
    ) -> None:
        self.cache = cache
        self.throttle = throttle
        self.max_attempts = max_attempts
        self.retry_wait_s = retry_wait_s
        self.requests_made = 0
        self._http = httpx.Client(base_url=BASE_URL, headers=BROWSER_HEADERS, timeout=timeout_s)

    def close(self) -> None:
        self._http.close()

    def get_json(self, endpoint: str, params: Params, final: bool) -> Payload:
        # final=True: cached forever once fetched, so it must have rows;
        # final=False: always refetched, and may be empty (season not started)
        if final and (cached := self.cache.get(endpoint, params)) is not None:
            return cached
        payload = self._fetch(endpoint, params, require_rows=final)
        self.cache.put(endpoint, params, payload, final=final)
        return payload

    def _fetch(self, endpoint: str, params: Params, require_rows: bool) -> Payload:
        retrying = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=self.retry_wait_s, max=60),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                self.throttle.wait()
                self.requests_made += 1
                response = self._http.get(f"/{endpoint}", params=dict(params))
                response.raise_for_status()
                payload = response.json()
                if require_rows and not has_rows(payload):
                    raise EmptyResponseError(f"{endpoint} {dict(params)} returned no rows")
                return payload
        raise AssertionError("unreachable")
