import bisect
import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

import duckdb
import pandas as pd

from avaris.features.availability import (
    AVAIL_HALF_LIFE,
    REPORT_ABSENCE,
    PlayerTracker,
    game_score,
)
from avaris.features.decision_time import decision_times
from avaris.features.elo import (
    ELO_SEASON_TYPES,
    EloRatings,
    expected_margin,
    home_advantage,
    win_prob,
)
from avaris.features.schedule import ScheduleTracker
from avaris.features.team_form import EwMean, TeamForm, game_ratings
from avaris.ingest.espn import OUT_WINDOW_HOURS, is_out
from avaris.ingest.teams import Venue, Venues, load_teams
from avaris.seasons import season_label, season_start_year

# A game's result counts as known this long after tip-off (ADR-015)
RESULT_LAG = timedelta(hours=3)
LEAGUE_HALF_LIFE = 200.0  # games
NO_FANS_SEASON = "2020-21"
POSTSEASON = frozenset({"playoffs", "play_in"})

# Bump when feature semantics change: artifacts trained on another version are refused
FEATURE_VERSION = 2
MODEL_FEATURES = [
    "home_court", "no_fans", "is_preseason", "is_postseason",
    "elo_diff", "elo_prob", "elo_margin",
    "home_ortg", "away_ortg", "home_drtg", "away_drtg", "net_diff",
    "home_pace", "away_pace", "net_l10_diff", "home_gp", "away_gp",
    "league_total", "league_pace", "exp_total",
    "home_rest_days", "away_rest_days", "home_b2b", "away_b2b", "home_3in4", "away_3in4",
    "home_travel_km", "away_travel_km", "home_tz_shift", "away_tz_shift", "altitude_m",
    "home_full_strength", "away_full_strength", "home_lost", "away_lost", "lost_diff",
]
AvailabilityMode = Literal["actual", "report"]
REST_COLUMNS = [
    "game_id", "decision_ts", "snapshot_ts", "home_players", "home_lost_espn",
    "home_lost_actual", "away_players", "away_lost_espn", "away_lost_actual",
]


def feature_hash() -> str:
    payload = f"{FEATURE_VERSION}:{','.join(MODEL_FEATURES)}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class FeatureSet:
    features: pd.DataFrame  # one row per game with a tip-off, as of its decision_ts
    team_ratings: pd.DataFrame  # one row per team and game
    availability: pd.DataFrame  # per team, game and player: rate, minutes, absences
    venues: pd.DataFrame  # game_id, venue
    # Preseason NBA-v-NBA games only, never model inputs (ADR-022): per side, value of the
    # players ESPN lists out as of decision_ts (lost_espn, NaN without a snapshot) and of
    # the players who sat out the box score (lost_actual, for the fit only)
    rest: pd.DataFrame


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): v for k, v in r.items()} for r in df.to_dict("records")]


def _nan(x: float | None) -> float:
    return math.nan if x is None else float(x)


class _Loop:
    # Chronological event loop: a result event (tip-off + RESULT_LAG) updates state, a
    # decision event (decision_ts) snapshots it. At the same instant results apply first
    def __init__(
        self, con: duckdb.DuckDBPyConnection, rest_window_hours: float = OUT_WINDOW_HOURS
    ) -> None:
        self.venues = Venues.load()
        self.games = con.execute("select * from games where tip_off_utc is not null").df()
        self.boxes = self._team_boxes(con)
        self.played = self._played(con)
        self.reports = self._reports(con)
        self.elo = EloRatings()
        self.forms: dict[int, TeamForm] = defaultdict(TeamForm)
        self.schedule = ScheduleTracker()
        self.players = PlayerTracker()
        self.league_total = EwMean(LEAGUE_HALF_LIFE)
        self.league_rtg = EwMean(LEAGUE_HALF_LIFE)
        self.league_pace = EwMean(LEAGUE_HALF_LIFE)
        # Per team and season: the decision reports' lost value so far (lost_usual)
        self.usual_lost: dict[tuple[int, str], EwMean] = defaultdict(
            lambda: EwMean(AVAIL_HALF_LIFE))
        self.feature_rows: list[dict[str, Any]] = []
        self.rating_rows: list[dict[str, Any]] = []
        self.avail_rows: list[dict[str, Any]] = []
        self.rest_window = timedelta(hours=rest_window_hours)
        self.nba_teams = {int(t) for t in load_teams()["team_id"]}
        self.espn_fetches, self.espn_lists = self._espn(con)
        self.preseason_played, self.preseason_pool = self._preseason_played(con)
        self.regular_members = self._regular_members(con)
        self.rest_rows: list[dict[str, Any]] = []

    @staticmethod
    def _espn(
        con: duckdb.DuckDBPyConnection,
    ) -> tuple[list[tuple[datetime, datetime]], dict[tuple[datetime, int], list[dict[str, Any]]]]:
        # Fetches (fetched_at, snapshot_ts) in time order, and each snapshot's entries by team
        fetches = [
            (pd.Timestamp(f).to_pydatetime(), pd.Timestamp(s).to_pydatetime())
            for f, s in con.execute(
                "select fetched_at, snapshot_ts from espn_injury_fetches order by fetched_at"
            ).fetchall()
        ]
        df = con.execute(
            "select fetched_at, team_id, player_name, player_id, status, comment, entry_ts "
            "from espn_injury_snapshots order by fetched_at, team_id, player_name"
        ).df()
        lists: dict[tuple[datetime, int], list[dict[str, Any]]] = defaultdict(list)
        for r in _records(df):
            key = (pd.Timestamp(r["fetched_at"]).to_pydatetime(), int(r["team_id"]))
            lists[key].append(r)
        return fetches, lists

    @staticmethod
    def _preseason_played(
        con: duckdb.DuckDBPyConnection,
    ) -> tuple[dict[str, dict[int, set[int]]], dict[tuple[str, int], set[int]]]:
        # Preseason box scores: game -> team -> players with minutes > 0, and every
        # player who played for the team in the season's preseason
        played: dict[str, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
        pool: dict[tuple[str, int], set[int]] = defaultdict(set)
        for game_id, season, team_id, player_id in con.execute(
            "select game_id, season, team_id, player_id from preseason_player_games "
            "where minutes > 0"
        ).fetchall():
            played[str(game_id)][int(team_id)].add(int(player_id))
            pool[(str(season), int(team_id))].add(int(player_id))
        return played, pool

    @staticmethod
    def _regular_members(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, int], set[int]]:
        # Players with a regular-season game for the team, by season
        members: dict[tuple[str, int], set[int]] = defaultdict(set)
        for season, team_id, player_id in con.execute(
            "select distinct season, team_id, player_id from player_games "
            "where season_type = 'regular' and minutes > 0"
        ).fetchall():
            members[(str(season), int(team_id))].add(int(player_id))
        return members

    @staticmethod
    def _team_boxes(con: duckdb.DuckDBPyConnection) -> dict[str, dict[int, dict[str, Any]]]:
        df = con.execute(
            "select game_id, team_id, pts, fga, fta, oreb, tov, minutes from team_games"
        ).df()
        boxes: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
        for r in _records(df):
            boxes[str(r["game_id"])][int(r["team_id"])] = r
        return boxes

    @staticmethod
    def _played(
        con: duckdb.DuckDBPyConnection,
    ) -> dict[str, dict[int, dict[int, tuple[float, float]]]]:
        # game -> team -> player -> (minutes, Game Score), players with minutes > 0
        df = con.execute(
            "select game_id, team_id, player_id, minutes, pts, fgm, fga, fta, ftm, oreb, "
            "dreb, stl, ast, blk, pf, tov from player_games where minutes > 0"
        ).df()
        df = df.fillna(0)
        played: dict[str, dict[int, dict[int, tuple[float, float]]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        for r in _records(df):
            played[str(r["game_id"])][int(r["team_id"])][int(r["player_id"])] = (
                float(r["minutes"]),
                game_score(r),
            )
        return played

    @staticmethod
    def _reports(
        con: duckdb.DuckDBPyConnection,
    ) -> dict[tuple[datetime, int, date], dict[int, str]]:
        # (report_ts, team, game date) -> player -> status; a report also lists later days
        df = con.execute(
            "select report_ts, team_id, game_date_et, player_id, status from injury_reports "
            "where player_id is not null"
        ).df()
        reports: dict[tuple[datetime, int, date], dict[int, str]] = defaultdict(dict)
        for r in _records(df):
            key = (
                pd.Timestamp(r["report_ts"]).to_pydatetime(), int(r["team_id"]),
                pd.Timestamp(r["game_date_et"]).date(),
            )
            reports[key][int(r["player_id"])] = str(r["status"])
        return reports

    def venue(self, game: dict[str, Any]) -> Venue | None:
        return self.venues.lookup(str(game["venue"] or ""), int(game["home_team_id"]))

    def run(self, times: pd.DataFrame) -> None:
        games = {str(g["game_id"]): g for g in _records(self.games)}
        events: list[tuple[datetime, int, str, Any]] = []
        for t in _records(times):
            game = games[str(t["game_id"])]
            decision = pd.Timestamp(t["decision_ts"]).to_pydatetime()
            report_ts = t["report_ts"]
            report = None if report_ts is None else pd.Timestamp(report_ts).to_pydatetime()
            events.append((decision, 1, str(t["game_id"]), report))
            if (
                game["season_type"] != "preseason"
                and game["status"] == "final"
                and not pd.isna(game["home_pts"])
            ):
                tip = pd.Timestamp(game["tip_off_utc"]).to_pydatetime()
                events.append((tip + RESULT_LAG, 0, str(t["game_id"]), None))
        for ts, kind, game_id, report in sorted(events, key=lambda e: e[:3]):
            if kind == 0:
                self.result(games[game_id])
            else:
                self.decision(games[game_id], ts, report)

    def result(self, game: dict[str, Any]) -> None:
        season = str(game["season"])
        home, away = int(game["home_team_id"]), int(game["away_team_id"])
        home_court, no_fans = _site(game)
        if game["season_type"] in ELO_SEASON_TYPES:
            hca = home_advantage(home_court, no_fans)
            self.elo.update(home, away, season, int(game["home_pts"]), int(game["away_pts"]), hca)
        self.league_total.add(float(game["home_pts"]) + float(game["away_pts"]))
        box = self.boxes.get(str(game["game_id"]), {})
        if home in box and away in box and _usable(box[home]) and _usable(box[away]):
            league_rtg, league_pace = self.league_rtg.value, self.league_pace.value
            for team, opp in ((home, away), (away, home)):
                ortg, drtg, pace = game_ratings(box[team], box[opp])
                self.forms[team].add(season, ortg, drtg, pace, league_rtg, league_pace)
                self.league_rtg.add(ortg)
            self.league_pace.add(game_ratings(box[home], box[away])[2])
        tip = pd.Timestamp(game["tip_off_utc"]).to_pydatetime()
        venue = self.venue(game)
        for team in (home, away):
            self.schedule.add(team, tip, game["game_date_et"], venue)
            played = self.played.get(str(game["game_id"]), {}).get(team, {})
            self.players.add_game(season, team, played)

    def decision(
        self, game: dict[str, Any], decision_ts: datetime, report_ts: datetime | None
    ) -> None:
        game_id, season = str(game["game_id"]), str(game["season"])
        home, away = int(game["home_team_id"]), int(game["away_team_id"])
        home_court, no_fans = _site(game)
        tip = pd.Timestamp(game["tip_off_utc"]).to_pydatetime()
        venue = self.venue(game)
        preseason = game["season_type"] == "preseason"
        row: dict[str, Any] = {
            "game_id": game_id, "decision_ts": decision_ts, "report_ts": report_ts,
            "season": season, "season_type": game["season_type"],
            "game_date_et": game["game_date_et"], "home_team_id": home, "away_team_id": away,
            "home_court": home_court, "no_fans": no_fans, "is_preseason": int(preseason),
            "is_postseason": int(game["season_type"] in POSTSEASON),
        }
        home_elo, away_elo = self.elo.rating(home, season), self.elo.rating(away, season)
        diff = home_elo - away_elo + home_advantage(home_court, no_fans)
        row.update(
            home_elo=home_elo, away_elo=away_elo, elo_prob=win_prob(diff),
            elo_margin=expected_margin(diff),
        )
        league_rtg, league_pace = self.league_rtg.value, self.league_pace.value
        for side, team in (("home", home), ("away", away)):
            form = self.forms[team].snapshot(season, league_rtg, league_pace)
            for key in ("ortg", "drtg", "net", "pace", "net_l10", "ortg_std", "drtg_std",
                        "pace_std"):
                row[f"{side}_{key}"] = _nan(form[key])
            row[f"{side}_gp"] = int(form["gp"] or 0)
            sched = self.schedule.snapshot(team, tip, game["game_date_et"], venue)
            for key, value in sched.items():
                row[f"{side}_{key}"] = _nan(value)
            row[f"{side}_b2b"] = int(sched["b2b"] or 0)
            row[f"{side}_3in4"] = int(sched["3in4"] or 0)
            self.rating_rows.append({
                "team_id": team, "game_id": game_id, "as_of_ts": decision_ts, "season": season,
                "elo": row[f"{side}_elo"], "ortg": row[f"{side}_ortg"],
                "drtg": row[f"{side}_drtg"], "net": row[f"{side}_net"],
                "pace": row[f"{side}_pace"], "net_l10": row[f"{side}_net_l10"],
                "gp": row[f"{side}_gp"],
            })
            # Unknown in preseason and before the team's first game of the season
            full, lost_actual, lost_report = (
                (math.nan,) * 3 if preseason or row[f"{side}_gp"] == 0
                else self.availability(game, team, report_ts)
            )
            row[f"{side}_full_strength"] = full
            row[f"{side}_lost_actual"] = lost_actual
            row[f"{side}_lost_report"] = lost_report
            # What the team usually misses, as of its earlier decisions with a report: already
            # in its ratings. Not a model input; the Traditional model counts lost_report above it
            usual = self.usual_lost[(team, season)]
            row[f"{side}_lost_usual"] = _nan(usual.value)
            if report_ts is not None and not math.isnan(lost_report):
                usual.add(lost_report)
        row["league_total"] = _nan(self.league_total.value)
        row["league_pace"] = _nan(league_pace)
        row["altitude_m"] = venue.altitude_m if venue else math.nan
        self.feature_rows.append(row)
        if preseason and {home, away} <= self.nba_teams:
            self.rest_rows.append(self.rest(game, tip, decision_ts))

    def value(self, player_id: int, season: str) -> float:
        rate, minutes = self.players.rate(player_id, season)
        return rate * minutes

    def snapshot(self, tip: datetime, decision_ts: datetime) -> datetime | None:
        # The list in force at the latest fetch in [tip - window, decision_ts]
        times = [f for f, _ in self.espn_fetches]
        i = bisect.bisect_right(times, decision_ts) - 1
        if i < 0 or self.espn_fetches[i][0] < tip - self.rest_window:
            return None
        return self.espn_fetches[i][1]

    def rest(self, game: dict[str, Any], tip: datetime, decision_ts: datetime) -> dict[str, Any]:
        # Preseason only: what the rest adjustment reads (ADR-022)
        game_id, season = str(game["game_id"]), str(game["season"])
        previous = season_label(season_start_year(season) - 1)
        snapshot_ts = self.snapshot(tip, decision_ts)
        row: dict[str, Any] = {"game_id": game_id, "decision_ts": decision_ts,
                               "snapshot_ts": snapshot_ts}
        box = self.preseason_played.get(game_id, {})
        for side in ("home", "away"):
            team = int(game[f"{side}_team_id"])
            players = []
            if snapshot_ts is not None:
                for e in self.espn_lists.get((snapshot_ts, team), []):
                    entry_ts = None if pd.isna(e["entry_ts"]) else pd.Timestamp(
                        e["entry_ts"]).to_pydatetime()
                    if not is_out(str(e["status"]), e["comment"], entry_ts, tip,
                                  self.rest_window.total_seconds() / 3600):
                        continue
                    pid = None if pd.isna(e["player_id"]) else int(e["player_id"])
                    players.append({
                        "name": str(e["player_name"]), "player_id": pid,
                        "status": str(e["status"]), "comment": e["comment"],
                        "value": 0.0 if pid is None else self.value(pid, season),
                        "matched": pid is not None,
                    })
            row[f"{side}_players"] = players
            row[f"{side}_lost_espn"] = (
                math.nan if snapshot_ts is None else sum(p["value"] for p in players)
            )
            # The team's preseason players who were on its regular-season roster last
            # season or this one, and did not play this game; NaN without a box score
            played = box.get(team)
            if played is None:
                row[f"{side}_lost_actual"] = math.nan
                continue
            pool = self.preseason_pool[(season, team)] & (
                self.regular_members.get((previous, team), set())
                | self.regular_members.get((season, team), set())
            )
            row[f"{side}_lost_actual"] = sum(
                self.value(pid, season) for pid in sorted(pool - played))
        return row

    def availability(
        self, game: dict[str, Any], team: int, report_ts: datetime | None
    ) -> tuple[float, float, float]:
        # The player set: the team's members plus players listed on its decision report
        # (a player hurt since before the season, at last season's rate). Full strength =
        # sum of rate x expected minutes over the set. Actual: set players who did not
        # play. Report: listed Out or Doubtful count 1, Questionable 0.5
        game_id, season = str(game["game_id"]), str(game["season"])
        day = pd.Timestamp(game["game_date_et"]).date()
        listed = self.reports.get((report_ts, team, day), {}) if report_ts else {}
        members = self.players.members(team, season, listed=set(listed))
        played = self.played.get(game_id, {}).get(team)
        full = lost_actual = lost_report = 0.0
        for pid in sorted(members | set(listed)):
            rate, minutes = self.players.rate(pid, season)
            value = rate * minutes
            absent_actual = None if played is None else pid not in played
            absent_report = REPORT_ABSENCE.get(listed.get(pid, ""), 0.0)
            full += value
            lost_actual += value * bool(absent_actual)
            lost_report += value * absent_report
            self.avail_rows.append({
                "game_id": game_id, "team_id": team, "player_id": pid, "rate": rate,
                "minutes": minutes, "member": pid in members, "absent_actual": absent_actual,
                "report_status": listed.get(pid), "absent_report": absent_report,
            })
        return full, lost_actual if played is not None else math.nan, lost_report


def _usable(box: dict[str, Any]) -> bool:
    # A box row with a missing stat or no possessions would poison the running averages
    values = [box[k] for k in ("pts", "fga", "fta", "oreb", "tov", "minutes")]
    if any(pd.isna(v) for v in values):
        return False
    return box["fga"] + 0.44 * box["fta"] - box["oreb"] + box["tov"] > 0 and box["minutes"] > 0


def _site(game: dict[str, Any]) -> tuple[int, int]:
    home_court = 0 if game["neutral_site"] else 1
    no_fans = int(game["season"] == NO_FANS_SEASON and game["season_type"] != "preseason")
    return home_court, no_fans


def build_features(
    con: duckdb.DuckDBPyConnection, rest_window_hours: float = OUT_WINDOW_HOURS
) -> FeatureSet:
    loop = _Loop(con, rest_window_hours)
    loop.run(decision_times(con))
    features = pd.DataFrame(loop.feature_rows).sort_values(["decision_ts", "game_id"])
    features = features.reset_index(drop=True)
    return FeatureSet(
        features=features,
        team_ratings=pd.DataFrame(loop.rating_rows),
        availability=pd.DataFrame(loop.avail_rows),
        venues=loop.games[["game_id", "venue"]].copy(),
        rest=pd.DataFrame(loop.rest_rows, columns=REST_COLUMNS),
    )


def write_features(con: duckdb.DuckDBPyConnection, fs: FeatureSet) -> None:
    # Derived tables: replaced wholesale on every build
    features = fs.features.assign(feature_hash=feature_hash())
    con.begin()
    try:
        for table, df in (("features", features), ("team_ratings", fs.team_ratings)):
            con.execute(f"delete from {table}")
            con.register("_df", df)
            cols = ", ".join(f'"{c}"' for c in df.columns)
            con.execute(f"insert into {table} ({cols}) select {cols} from _df")
            con.unregister("_df")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def model_frame(features: pd.DataFrame, availability: AvailabilityMode) -> pd.DataFrame:
    # Model inputs with neutral availability names: training uses who actually played,
    # live and the Phase 4 re-run use the decision report
    f = features
    x = pd.DataFrame(index=f.index)
    for col in MODEL_FEATURES:
        if col in f.columns:
            x[col] = f[col].astype(float)
    x["elo_diff"] = f["home_elo"] - f["away_elo"]
    x["net_diff"] = f["home_net"] - f["away_net"]
    x["net_l10_diff"] = f["home_net_l10"] - f["away_net_l10"]
    x["exp_total"] = (
        (f["home_pace"] + f["away_pace"]) / 2
        * (f["home_ortg"] + f["away_drtg"] + f["away_ortg"] + f["home_drtg"]) / 200
    )
    x["home_lost"] = f[f"home_lost_{availability}"].astype(float)
    x["away_lost"] = f[f"away_lost_{availability}"].astype(float)
    x["lost_diff"] = x["home_lost"] - x["away_lost"]
    return x[MODEL_FEATURES]
