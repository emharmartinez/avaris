import math
from collections import deque
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from avaris.ingest.teams import Venue

REST_CAP = 7  # days; also the gap after which travel no longer counts
EARTH_RADIUS_KM = 6371.0


def haversine_km(a: Venue, b: Venue) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(
        (lon2 - lon1) / 2
    ) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def utc_offset_hours(venue: Venue, at_utc: datetime) -> float:
    offset = at_utc.replace(tzinfo=UTC).astimezone(ZoneInfo(venue.tz)).utcoffset()
    return (offset or timedelta()).total_seconds() / 3600


class ScheduleTracker:
    # Each team's previous non-preseason games: rest, back-to-backs, 3 games in 4 nights,
    # travel and time-zone shift from the previous venue
    def __init__(self) -> None:
        self._games: dict[int, deque[tuple[datetime, date, Venue | None]]] = {}

    def add(self, team_id: int, tip_utc: datetime, day: date, venue: Venue | None) -> None:
        self._games.setdefault(team_id, deque(maxlen=3)).append((tip_utc, day, venue))

    def snapshot(
        self, team_id: int, tip_utc: datetime, day: date, venue: Venue | None
    ) -> dict[str, float | None]:
        history = self._games.get(team_id, deque())
        if not history:
            return {"rest_days": REST_CAP, "b2b": 0, "3in4": 0, "travel_km": 0, "tz_shift": 0}
        prev_tip, prev_day, prev_venue = history[-1]
        rest = min((day - prev_day).days, REST_CAP)
        recent = sum(1 for _, d, _ in history if (day - d).days <= 3)
        travel: float | None
        shift: float | None
        if rest >= REST_CAP:
            travel, shift = 0, 0
        elif venue is None or prev_venue is None:
            travel, shift = None, None
        else:
            travel = haversine_km(prev_venue, venue)
            shift = utc_offset_hours(venue, tip_utc) - utc_offset_hours(prev_venue, prev_tip)
        return {
            "rest_days": rest,
            "b2b": int(rest == 1),
            "3in4": int(recent + 1 >= 3),
            "travel_km": travel,
            "tz_shift": shift,
        }
