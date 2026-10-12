from collections.abc import Iterable
from datetime import datetime, timedelta

# Injuries and features for a game are frozen at its decision_ts (ADR-003)
DECISION_LEAD = timedelta(minutes=60)


def decision_ts(tip_off_utc: datetime, report_times: Iterable[datetime]) -> datetime:
    # Latest injury report at or before tip-off - 60 min, else tip-off - 60 min
    cutoff = tip_off_utc - DECISION_LEAD
    return max((t for t in report_times if t <= cutoff), default=cutoff)
