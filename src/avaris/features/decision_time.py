from collections.abc import Iterable
from datetime import datetime, timedelta

import duckdb
import pandas as pd

# Injuries and features for a game are frozen at its decision_ts (ADR-003)
DECISION_LEAD = timedelta(minutes=60)
# Only reports this far before the cutoff belong to the game's day; the previous
# evening's report does not count
REPORT_WINDOW = timedelta(hours=12)


def decision_ts(tip_off_utc: datetime, report_times: Iterable[datetime]) -> datetime:
    # Latest injury report at or before tip-off - 60 min (within the window), else
    # tip-off - 60 min
    cutoff = tip_off_utc - DECISION_LEAD
    start = cutoff - REPORT_WINDOW
    return max((t for t in report_times if start <= t <= cutoff), default=cutoff)


DECISION_TIMES_SQL = """
select g.game_id, g.tip_off_utc, max(f.report_ts) as report_ts,
    coalesce(max(f.report_ts), g.tip_off_utc - $lead) as decision_ts
from games g left join injury_report_files f
    on f.status = 'ok'
    and f.report_ts between g.tip_off_utc - $lead - $window and g.tip_off_utc - $lead
where g.tip_off_utc is not null
group by g.game_id, g.tip_off_utc
order by decision_ts, g.game_id
"""


def decision_times(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # One row per game with a tip-off: game_id, tip_off_utc, report_ts (null when no
    # report), decision_ts. A game without a tip-off is not predicted
    df = con.execute(DECISION_TIMES_SQL, {"lead": DECISION_LEAD, "window": REPORT_WINDOW}).df()
    df["report_ts"] = df["report_ts"].astype(object).where(df["report_ts"].notna(), None)
    return df
