# Deterministic synthetic league for feature and model tests: 4 teams, 3 seasons
# (2019-20 with a bubble, 2020-21 with no injury reports and a playoff round, 2021-22 with
# reports), preseason games (one at an unknown venue, one with no tip-off), a traded player,
# a long injury and unplayed games at the end
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from avaris.db import connect, upsert

ATL, BOS, BKN, DEN = 1610612737, 1610612738, 1610612751, 1610612743
TEAMS = [ATL, BOS, BKN, DEN]
ARENA = {ATL: "State Farm Arena", BOS: "TD Garden", BKN: "Barclays Center", DEN: "Ball Arena"}
CITY = {ATL: "Atlanta", BOS: "Boston", BKN: "Brooklyn", DEN: "Denver"}
BUBBLE = "AdventHealth Arena"
UNKNOWN_VENUE = "Preseason Fieldhouse"
PAIRINGS = [((ATL, BOS), (BKN, DEN)), ((ATL, BKN), (BOS, DEN)), ((ATL, DEN), (BOS, BKN))]
GAPS = [1, 2, 1, 3]  # days between rounds: back-to-backs and 3 games in 4 nights
ROUNDS = 24
BASE_MINUTES = [36, 34, 32, 30, 28, 24, 20, 16]

TRADED_PLAYER = 1004  # ATL's 5th man, plays for BOS from 2021-22 round 8
TRADE_ROUND = 8
INJURED_STAR = 2001  # BOS's best player, out 2021-22 rounds 4-17 (listed on every report)
INJURY_ROUNDS = range(4, 18)
SEASONS = {
    "2019-20": date(2019, 10, 23),
    "2020-21": date(2020, 12, 22),
    "2021-22": date(2021, 10, 19),
}
BUBBLE_FROM_ROUND = 20
BUBBLE_START = date(2020, 7, 30)
LAST_SEASON = "2021-22"
PLAYOFF_SEASON = "2020-21"  # one extra round of playoff games
UNPLAYED_ROUNDS = 2  # last regular-season rounds of 2021-22 are still scheduled


@dataclass
class Player:
    player_id: int
    team_id: int
    quality: float  # Game Score per minute
    minutes: float


@dataclass
class League:
    games: list[dict[str, object]] = field(default_factory=list)
    team_games: list[dict[str, object]] = field(default_factory=list)
    player_games: list[dict[str, object]] = field(default_factory=list)
    report_files: list[dict[str, object]] = field(default_factory=list)
    reports: list[dict[str, object]] = field(default_factory=list)


def _players() -> list[Player]:
    rng = np.random.default_rng(11)
    players = []
    for t, team in enumerate(TEAMS):
        for i, minutes in enumerate(BASE_MINUTES):
            quality = 0.75 - 0.04 * i + 0.05 * t + rng.normal(0, 0.03)
            players.append(Player(1000 * (t + 1) + i, team, float(quality), float(minutes)))
    return players


def tip_off(day: date) -> datetime:
    # 7-8 pm ET on day (naive UTC)
    return datetime.combine(day + timedelta(days=1), time(0, 0))


def _round_days(season: str) -> list[date]:
    days, day = [], SEASONS[season]
    for r in range(ROUNDS + (1 if season == PLAYOFF_SEASON else 0)):
        if season == "2019-20" and r == BUBBLE_FROM_ROUND:
            day = BUBBLE_START
        days.append(day)
        day += timedelta(days=GAPS[r % len(GAPS)])
    return days


def _game_id(prefix: str, season: str, n: int) -> str:
    return f"{prefix}{season[2:4]}{n:05d}"


def _stat_line(rng: np.random.Generator, pts: int, minutes: float) -> dict[str, int]:
    fga = max(round(pts * 0.8 + rng.normal(0, 1)), 0)
    fgm = min(round(pts * 0.38), fga)
    fta = max(round(pts * 0.2), 0)
    share = minutes / 48
    return {
        "pts": pts, "fgm": fgm, "fga": fga, "fg3m": fgm // 3, "fg3a": fga // 3,
        "ftm": round(fta * 0.75), "fta": fta, "oreb": int(rng.poisson(2 * share)),
        "dreb": int(rng.poisson(7 * share)), "ast": int(rng.poisson(5 * share)),
        "stl": int(rng.poisson(1.5 * share)), "blk": int(rng.poisson(1 * share)),
        "tov": int(rng.poisson(2.5 * share)), "pf": int(rng.poisson(3 * share)),
    }


def _team_of(player: Player, season: str, rnd: int) -> int:
    if player.player_id == TRADED_PLAYER and season == LAST_SEASON and rnd >= TRADE_ROUND:
        return BOS
    return player.team_id


def _absent(player: Player, season: str, rnd: int, rng: np.random.Generator) -> bool:
    if player.player_id == INJURED_STAR and season == LAST_SEASON and rnd in INJURY_ROUNDS:
        return True
    return bool(rng.random() < 0.08)


def _play_game(
    league: League,
    rng: np.random.Generator,
    players: list[Player],
    game: dict[str, object],
    rnd: int,
) -> None:
    season = str(game["season"])
    home, away = int(game["home_team_id"]), int(game["away_team_id"])  # type: ignore[call-overload]
    lineups: dict[int, list[Player]] = {}
    for team in (home, away):
        roster = [p for p in players if _team_of(p, season, rnd) == team]
        lineups[team] = [p for p in roster if not _absent(p, season, rnd, rng)]
    strength = {t: sum(p.quality * p.minutes for p in lineups[t]) for t in lineups}
    home_edge = 0.0 if game["neutral_site"] else 3.0
    margin = (strength[home] - strength[away]) * 0.4 + home_edge + rng.normal(0, 11)
    total = 215 + rng.normal(0, 15)
    pts = {home: round((total + margin) / 2), away: round((total - margin) / 2)}
    if pts[home] == pts[away]:
        pts[home] += 1
    game.update(home_pts=pts[home], away_pts=pts[away], status="final")
    for team, opp in ((home, away), (away, home)):
        lineup = lineups[team]
        scale = 240 / sum(p.minutes for p in lineup)
        weights = np.array([p.quality * p.minutes for p in lineup])
        split = np.floor(pts[team] * weights / weights.sum()).astype(int)
        split[0] += pts[team] - int(split.sum())
        rows = []
        for p, p_pts in zip(lineup, split, strict=True):
            minutes = round(p.minutes * scale, 1)
            line = _stat_line(rng, int(p_pts), minutes)
            rows.append(line)
            league.player_games.append({
                "game_id": game["game_id"], "player_id": p.player_id, "team_id": team,
                "player_name": f"Player {p.player_id}", "season": season,
                "season_type": game["season_type"], "game_date_et": game["game_date_et"],
                "minutes": minutes, "plus_minus": float(pts[team] - pts[opp]), **line,
            })
        totals = {k: sum(r[k] for r in rows) for k in rows[0]}
        league.team_games.append({
            "game_id": game["game_id"], "team_id": team, "opp_team_id": opp,
            "is_home": team == home, "season": season, "season_type": game["season_type"],
            "game_date_et": game["game_date_et"], "wl": "W" if pts[team] > pts[opp] else "L",
            "minutes": 240.0, "reb": totals["oreb"] + totals["dreb"],
            "plus_minus": float(pts[team] - pts[opp]), **totals,
        })
    _write_reports(league, rng, players, game, rnd, lineups)


def _write_reports(
    league: League,
    rng: np.random.Generator,
    players: list[Player],
    game: dict[str, object],
    rnd: int,
    lineups: dict[int, list[Player]],
) -> None:
    # 2021-22 only: an early report, the decision report (tip - 90 min) and a report after
    # the decision cutoff (tip - 30 min) that adds a late scratch. Like real reports, each
    # also lists the next day: there the team's first player is out
    season = str(game["season"])
    if season != LAST_SEASON or game["season_type"] == "preseason":
        return
    tip: datetime = game["tip_off_utc"]  # type: ignore[assignment]
    played = {p.player_id for lineup in lineups.values() for p in lineup}
    for offset, kind in ((timedelta(hours=6), "early"), (timedelta(minutes=90), "decision"),
                         (timedelta(minutes=30), "late")):
        report_ts = tip - offset
        entries = 0
        for team in (int(game["home_team_id"]), int(game["away_team_id"])):  # type: ignore[call-overload]
            roster = [p for p in players if _team_of(p, season, rnd) == team]
            for p in roster:
                absent = p.player_id not in played
                status = None
                if absent and (kind != "early" or p.player_id == INJURED_STAR):
                    # Some random absences are late scratches the decision report misses
                    if kind == "late" or p.player_id == INJURED_STAR or p.player_id % 5 != rnd % 5:
                        status = "out"
                elif not absent and kind == "decision" and p.player_id % 7 == rnd % 7:
                    status = "questionable"
                if status is None:
                    continue
                entries += 1
                league.reports.append({
                    "report_ts": report_ts, "game_date_et": game["game_date_et"],
                    "matchup": str(game["game_id"]), "game_id": game["game_id"],
                    "team_id": team, "player_name": f"Player, {p.player_id}",
                    "player_id": p.player_id, "status": status, "reason": "Injury",
                })
            first = roster[0]
            league.reports.append({
                "report_ts": report_ts,
                "game_date_et": game["game_date_et"] + timedelta(days=1),  # type: ignore[operator]
                "matchup": "next day", "game_id": None, "team_id": team,
                "player_name": f"Player, {first.player_id}", "player_id": first.player_id,
                "status": "out", "reason": "Rest",
            })
        league.report_files.append({
            "slot_ts": report_ts, "report_ts": report_ts, "url": f"synthetic/{report_ts}",
            "status": "ok", "n_entries": entries, "fetched_at": report_ts, "message": None,
        })
    del rng


def _game(
    game_id: str, season: str, season_type: str, day: date, home: int, away: int,
    venue: str, neutral: bool, tip: datetime | None,
) -> dict[str, object]:
    return {
        "game_id": game_id, "season": season, "season_type": season_type,
        "game_date_et": day, "tip_off_utc": tip, "home_team_id": home, "away_team_id": away,
        "home_pts": None, "away_pts": None, "status": "scheduled", "venue": venue,
        "venue_city": CITY.get(home, ""), "neutral_site": neutral,
    }


def build_league() -> League:
    rng = np.random.default_rng(7)
    players = _players()
    league = League()
    seen_reports: set[datetime] = set()
    for season, start in SEASONS.items():
        # Two preseason rounds two weeks before the season
        for r in range(2):
            day = start - timedelta(days=14 - 2 * r)
            for g, (home, away) in enumerate(PAIRINGS[r]):
                venue = UNKNOWN_VENUE if (r, g) == (1, 1) else ARENA[home]
                tip = None if (season, r, g) == ("2020-21", 1, 0) else tip_off(day)
                game = _game(_game_id("001", season, 2 * r + g + 1), season, "preseason",
                             day, home, away, venue, venue == UNKNOWN_VENUE, tip)
                if tip is not None:
                    game.update(home_pts=int(105 + rng.integers(0, 20)),
                                away_pts=int(100 + rng.integers(0, 20)), status="final")
                league.games.append(game)
        days = _round_days(season)
        n = 0
        for r, day in enumerate(days):
            is_playoff = season == PLAYOFF_SEASON and r == ROUNDS
            pairing = PAIRINGS[r % len(PAIRINGS)]
            if r % 2:
                pairing = tuple((b, a) for a, b in pairing)  # type: ignore[assignment]
            bubble = season == "2019-20" and r >= BUBBLE_FROM_ROUND
            for g, (home, away) in enumerate(pairing):
                n += 1
                prefix, season_type = ("004", "playoffs") if is_playoff else ("002", "regular")
                tip = tip_off(day) - (timedelta(hours=6) if g == 0 and r % 3 == 0 else timedelta())
                venue = BUBBLE if bubble else ARENA[home]
                game = _game(_game_id(prefix, season, n), season, season_type, day, home, away,
                             venue, bubble, tip)
                league.games.append(game)
                unplayed = season == LAST_SEASON and r >= ROUNDS - UNPLAYED_ROUNDS
                if not unplayed:
                    _play_game(league, rng, players, game, r)
    # Two games on one day share report files; keep one row per slot
    files = []
    for f in league.report_files:
        if f["slot_ts"] not in seen_reports:
            seen_reports.add(f["slot_ts"])  # type: ignore[arg-type]
            files.append(f)
    league.report_files = files
    return league


def write_league(path: Path) -> Path:
    league = build_league()
    con = connect(path)
    try:
        upsert(con, "games", pd.DataFrame(league.games))
        upsert(con, "team_games", pd.DataFrame(league.team_games))
        upsert(con, "player_games", pd.DataFrame(league.player_games))
        upsert(con, "injury_report_files", pd.DataFrame(league.report_files))
        upsert(con, "injury_reports", pd.DataFrame(league.reports))
    finally:
        con.close()
    return path
