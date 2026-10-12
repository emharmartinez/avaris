from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import duckdb
import pandas as pd

from avaris.config import OddsSettings
from avaris.db import upsert
from avaris.features.decision_time import decision_ts
from avaris.ingest.odds_api import CreditRefused, OddsApiClient
from avaris.ingest.odds_slots import Slot, SlotGame, plan_day
from avaris.ingest.teams import team_ids_by_name
from avaris.seasons import ET

Progress = Callable[[str], None]
# When one snapshot serves several roles, the guard sees the most important one
PURPOSE_PRIORITY = ("decision", "close", "open")
EVENT_COLUMNS = ["event_id", "home_team", "away_team", "commence_time_utc"]
ODDS_EVENT_COLUMNS = [*EVENT_COLUMNS, "home_team_id", "away_team_id", "game_id", "match_status"]
OUTCOME_COLUMNS = ["event_id", "book", "book_last_update", "market", "name", "line", "price"]


def _utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class ParsedSnapshot:
    snapshot_ts: datetime
    events: pd.DataFrame  # EVENT_COLUMNS
    outcomes: pd.DataFrame  # OUTCOME_COLUMNS


def parse_historical(payload: dict[str, Any]) -> ParsedSnapshot:
    events, outcomes = [], []
    for e in payload.get("data", []):
        events.append({
            "event_id": e["id"],
            "home_team": e["home_team"],
            "away_team": e["away_team"],
            "commence_time_utc": _utc(e["commence_time"]),
        })
        for b in e.get("bookmakers", []):
            last_update = _utc(b["last_update"]) if b.get("last_update") else None
            for m in b.get("markets", []):
                for o in m.get("outcomes", []):
                    outcomes.append({
                        "event_id": e["id"],
                        "book": b["key"],
                        "book_last_update": last_update,
                        "market": m["key"],
                        "name": o["name"],
                        "line": o.get("point"),
                        "price": float(o["price"]),
                    })
    return ParsedSnapshot(
        _utc(payload["timestamp"]),
        pd.DataFrame(events, columns=EVENT_COLUMNS),
        pd.DataFrame(outcomes, columns=OUTCOME_COLUMNS),
    )


def match_events(
    con: duckdb.DuckDBPyConnection, events: pd.DataFrame, window_min: int
) -> pd.DataFrame:
    # An event is a game when both teams match (either way round) and commence_time is
    # within window_min of tip-off; preseason games are never matched. Adds the stored
    # game's own home and away teams, since an event may list them the other way round
    ids = team_ids_by_name()
    window = timedelta(minutes=window_min)
    out = events.copy()
    out["home_team_id"] = out["home_team"].map(ids).astype("Int64")
    out["away_team_id"] = out["away_team"].map(ids).astype("Int64")
    matches = []
    for e in out.itertuples():
        match = {"game_id": None, "match_status": "unknown_team",
                 "game_home_team_id": None, "game_away_team_id": None}
        if not (pd.isna(e.home_team_id) or pd.isna(e.away_team_id)):
            commence: datetime = e.commence_time_utc  # type: ignore[assignment]
            teams = [int(e.home_team_id), int(e.away_team_id)]  # type: ignore[arg-type]
            row = con.execute(
                """
                select game_id, season_type, home_team_id, away_team_id from games
                where list_sort([home_team_id, away_team_id]) = list_sort(?::integer[])
                    and tip_off_utc between ? and ?
                order by abs(epoch(tip_off_utc) - epoch(?::timestamp)) limit 1
                """,
                [teams, commence - window, commence + window, commence],
            ).fetchone()
            if row is None:
                match["match_status"] = "no_game"
            elif row[1] == "preseason":
                match["match_status"] = "preseason"
            else:
                match = {"game_id": row[0], "match_status": "matched",
                         "game_home_team_id": row[2], "game_away_team_id": row[3]}
        matches.append(match)
    return pd.concat([out, pd.DataFrame(matches, index=out.index)], axis=1)


def snapshot_rows(
    parsed: ParsedSnapshot, matched: pd.DataFrame, kinds: dict[str, str]
) -> pd.DataFrame:
    # odds_snapshots rows for pregame odds of the games in kinds; moneyline and spread
    # sides follow the stored game's home team, not the event's
    names = team_ids_by_name()
    games = {
        str(r["event_id"]): r for r in matched[matched["match_status"] == "matched"].to_dict(
            "records"
        )
    }
    rows = []
    for o in parsed.outcomes.itertuples():
        ev = games.get(str(o.event_id))
        if ev is None:
            continue
        game_id = str(ev["game_id"])
        if game_id not in kinds or ev["commence_time_utc"] <= parsed.snapshot_ts:
            continue
        if o.market == "totals":
            side = str(o.name).lower()
        else:
            team = names.get(str(o.name))
            side = ("home" if team == ev["game_home_team_id"]
                    else "away" if team == ev["game_away_team_id"] else None)
        if side not in ("home", "away", "over", "under"):
            continue
        rows.append({
            "game_id": game_id,
            "event_id": o.event_id,
            "snapshot_ts": parsed.snapshot_ts,
            "book": o.book,
            "market": o.market,
            "side": side,
            "line": None if pd.isna(o.line) else float(o.line),  # type: ignore[arg-type]
            "price": o.price,
            "book_last_update": o.book_last_update,
            "kind": kinds[game_id],
        })
    return pd.DataFrame(rows)


def assign_kinds(
    roles: list[Slot], snapshot_ts: datetime, tips: dict[str, datetime], close_window_min: int
) -> dict[str, str]:
    # Kind per game for one snapshot: close beats decision beats open, and a closing line
    # needs the actual snapshot within close_window_min before tip-off
    window = timedelta(minutes=close_window_min)
    kinds = dict.fromkeys(tips, "other")
    for kind in ("open", "decision", "close"):
        for role in roles:
            if role.kind != kind:
                continue
            for gid in role.game_ids:
                if kind == "close" and not tips[gid] - window <= snapshot_ts < tips[gid]:
                    continue
                kinds[gid] = kind
    return kinds


@dataclass(frozen=True)
class PlannedCall:
    season: str
    day: date
    ts: datetime  # naive UTC requested snapshot time
    roles: tuple[Slot, ...]
    tips: dict[str, datetime]  # every regular-season game that day

    @property
    def purpose(self) -> str:
        kinds = {r.kind for r in self.roles}
        return next(k for k in PURPOSE_PRIORITY if k in kinds)

    @property
    def window(self) -> tuple[datetime, datetime]:
        # Events commencing on this ET day
        start = datetime.combine(self.day, time(0), tzinfo=ET)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        return (start.astimezone(UTC).replace(tzinfo=None),
                end.astimezone(UTC).replace(tzinfo=None))


def plan_backfill(
    con: duckdb.DuckDBPyConnection, date_from: date, date_to: date, cfg: OddsSettings
) -> list[PlannedCall]:
    games = con.execute(
        """
        select season, game_date_et, game_id, tip_off_utc from games
        where season_type = 'regular' and tip_off_utc is not null
            and game_date_et between ? and ?
        order by game_date_et, tip_off_utc, game_id
        """,
        [date_from, date_to],
    ).fetchall()
    reports = [r[0] for r in con.execute(
        "select report_ts from injury_report_files where status = 'ok' order by report_ts"
    ).fetchall()]
    by_day: dict[tuple[str, date], list[tuple[str, datetime]]] = {}
    for season, day, game_id, tip in games:
        by_day.setdefault((season, day), []).append((game_id, tip))
    plan = []
    for (season, day), day_games in by_day.items():
        day_reports = [r for r in reports if day - timedelta(days=1) <= r.date() <= day
                       + timedelta(days=1)]
        slot_games = [SlotGame(g, tip, decision_ts(tip, day_reports)) for g, tip in day_games]
        slots = plan_day(day, slot_games, cfg)
        tips = dict(day_games)
        for ts in sorted({s.ts for s in slots}):
            roles = tuple(s for s in slots if s.ts == ts)
            plan.append(PlannedCall(season, day, ts, roles, tips))
    return plan


def estimate_plan(plan: list[PlannedCall], client: OddsApiClient) -> pd.DataFrame:
    # Offline: counts the calls not yet cached and their credits; needs no API key
    rows = [{
        "season": c.season,
        "day": c.day,
        "cached": client.is_cached(c.ts, *c.window),
    } for c in plan]
    df = pd.DataFrame(rows, columns=["season", "day", "cached"])
    out = df.groupby("season", as_index=False).agg(
        game_days=("day", "nunique"), calls=("day", "size"), cached=("cached", "sum")
    )
    out["cached"] = out["cached"].astype(int)
    out["credits"] = (out["calls"] - out["cached"]) * client.historical_cost
    return out


@dataclass
class BackfillSummary:
    calls: int = 0
    cached: int = 0
    rows: int = 0
    refused: str | None = None


def run_backfill(
    con: duckdb.DuckDBPyConnection,
    client: OddsApiClient,
    plan: list[PlannedCall],
    cfg: OddsSettings,
    progress: Progress = lambda _msg: None,
) -> BackfillSummary:
    summary = BackfillSummary()
    for i, call in enumerate(plan):
        cached = client.is_cached(call.ts, *call.window)
        try:
            payload = client.historical_odds(call.ts, call.purpose, *call.window)
        except CreditRefused as exc:
            summary.refused = str(exc)
            progress(f"Stopped: {exc}")
            break
        summary.cached += cached
        summary.calls += not cached
        parsed = parse_historical(payload)
        matched = match_events(con, parsed.events, cfg.match_window_min)
        kinds = assign_kinds(list(call.roles), parsed.snapshot_ts, call.tips,
                             cfg.close_window_min)
        rows = snapshot_rows(parsed, matched, kinds)
        con.begin()
        try:
            upsert(con, "odds_events", matched[ODDS_EVENT_COLUMNS])
            summary.rows += upsert(con, "odds_snapshots", rows)
            con.commit()
        except BaseException:
            con.rollback()
            raise
        if i + 1 == len(plan) or plan[i + 1].season != call.season:
            progress(f"{call.season}: {summary.calls} calls, {summary.cached} cached so far")
    return summary
