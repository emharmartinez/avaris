from datetime import date

import duckdb
import pandas as pd

from avaris.seasons import is_finished, season_for_date, season_start_year

FIRST_ODDS_SEASON = "2020-21"
MAX_UNMATCHED_RATE = 0.01
KINDS = ("open", "decision", "close")

GAMES_SQL = """
with kinds as (
    select game_id,
        bool_or(kind = 'open') as has_open,
        bool_or(kind = 'decision') as has_decision,
        bool_or(kind = 'close') as has_close
    from odds_snapshots group by game_id
)
select g.season,
    count(*) as regular_games,
    count(*) filter (where k.has_open) as with_open,
    count(*) filter (where k.has_decision) as with_decision,
    count(*) filter (where k.has_close) as with_close
from games g left join kinds k using (game_id)
where g.season_type = 'regular' and g.season >= ?
group by g.season
"""


def odds_report(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # Per season: regular-season games with an open, decision and close snapshot, and
    # Odds API events that matched no game (preseason events are expected and skipped)
    games = con.execute(GAMES_SQL, [FIRST_ODDS_SEASON]).df()
    events = con.execute(
        "select commence_time_utc, match_status from odds_events "
        "where match_status <> 'preseason'"
    ).df()
    events["season"] = [
        season_for_date(ts.tz_localize("UTC").tz_convert("America/New_York").date())
        for ts in events["commence_time_utc"]
    ]
    by_season = events.groupby("season").agg(
        events=("match_status", "size"),
        unmatched_events=("match_status", lambda s: int((s != "matched").sum())),
    ).reset_index()
    report = games.merge(by_season, on="season", how="outer").sort_values("season")
    count_cols = report.columns.drop("season")
    report[count_cols] = report[count_cols].fillna(0).astype(int)
    return report.reset_index(drop=True)


def check_odds(report: pd.DataFrame, today: date) -> list[str]:
    # Phase 2 done-when for finished seasons from 2020-21; one message per failure
    if report.empty:
        return ["no odds snapshots ingested"]
    failures: list[str] = []
    for row in report.to_dict("records"):
        season = str(row["season"])
        if season_start_year(season) < season_start_year(FIRST_ODDS_SEASON):
            continue
        if not is_finished(season, today):
            continue
        games = row["regular_games"]
        for kind in KINDS:
            if row[f"with_{kind}"] != games:
                failures.append(
                    f"{season}: {row[f'with_{kind}']} of {games} regular-season games "
                    f"have a {kind} snapshot"
                )
        events, unmatched = row["events"], row["unmatched_events"]
        if events and unmatched / events >= MAX_UNMATCHED_RATE:
            failures.append(
                f"{season}: {unmatched} of {events} events unmatched "
                f"({unmatched / events:.2%}, limit < 1%)"
            )
    return failures


def reconcile_run(con: duckdb.DuckDBPyConnection, run_id: str) -> tuple[int, int]:
    # (credits in the ledger, change in x-requests-used across the run); equal when the
    # ledger accounts for every credit the API charged
    row = con.execute(
        """
        select coalesce(sum(actual_cost), 0),
            coalesce(max(requests_used), 0) - coalesce(min(requests_used), 0)
        from api_usage where run_id = ?
        """,
        [run_id],
    ).fetchone()
    return (int(row[0]), int(row[1])) if row else (0, 0)


def usage_report(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # Credits per calendar month (UTC) and status, plus the latest usage headers
    return con.execute(
        """
        select strftime(ts_utc, '%Y-%m') as month, status, count(*) as calls,
            coalesce(sum(actual_cost), 0) as credits, sum(est_cost) as estimated,
            arg_max(requests_used, id) as last_used,
            arg_max(requests_remaining, id) as last_remaining
        from api_usage group by all order by month, status
        """
    ).df()
