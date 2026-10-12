from datetime import UTC, date, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from avaris.config import OddsSettings
from avaris.ingest.odds_slots import SlotGame, plan_day
from avaris.seasons import ET

CFG = OddsSettings()
DAY = date(2022, 1, 15)


def et(hour: int, minute: int = 0) -> datetime:
    # Naive UTC for an ET wall time on DAY
    return datetime(2022, 1, 15, hour, minute, tzinfo=ET).astimezone(UTC).replace(tzinfo=None)


def game(gid: str, tip: tuple[int, int], decision: tuple[int, int]) -> SlotGame:
    return SlotGame(gid, et(*tip), et(*decision))


def slots_of(kind: str, slots: list) -> list:
    return [(s.ts, s.game_ids) for s in slots if s.kind == kind]


def test_weekday_has_open_two_decision_and_closing_slots() -> None:
    games = [
        game("a", (19, 0), (17, 30)),
        game("b", (19, 0), (17, 30)),
        game("c", (19, 30), (18, 30)),
        game("d", (20, 0), (18, 30)),
        game("e", (22, 0), (20, 30)),
        game("f", (22, 30), (21, 30)),
    ]
    slots = plan_day(DAY, games, CFG)
    assert slots_of("open", slots) == [(et(9, 0), ("a", "b", "c", "d", "e", "f"))]
    assert slots_of("decision", slots) == [
        (et(17, 30), ("a", "b", "c", "d")),
        (et(20, 30), ("e", "f")),
    ]
    # Each closing slot sits 2 min before its first tip and covers tips within 35 min
    # (45 min less the 10-minute historical snapshot gap)
    assert slots_of("close", slots) == [
        (et(18, 58), ("a", "b", "c")),
        (et(19, 58), ("d",)),
        (et(21, 58), ("e", "f")),
    ]


def test_matinee_games_get_their_own_decision_slot() -> None:
    games = [
        game("m1", (13, 0), (11, 30)),
        game("m2", (15, 30), (14, 30)),
        game("n", (19, 0), (17, 30)),
    ]
    decisions = slots_of("decision", plan_day(DAY, games, CFG))
    assert decisions == [(et(11, 30), ("m1", "m2")), (et(17, 30), ("n",))]


def test_open_moves_before_an_early_decision_slot() -> None:
    games = [game("m", (10, 0), (8, 30))]
    opens = slots_of("open", plan_day(DAY, games, CFG))
    assert opens == [(et(7, 30), ("m",))]


def test_close_slot_cap_keeps_the_slots_covering_most_games() -> None:
    games = [
        game("a", (19, 0), (17, 30)),
        game("b", (19, 0), (17, 30)),
        game("c", (20, 0), (18, 30)),
        game("d", (21, 0), (19, 30)),
        game("e", (22, 0), (20, 30)),
        game("f", (22, 0), (20, 30)),
    ]
    closes = slots_of("close", plan_day(DAY, games, CFG, max_close_slots=2))
    assert closes == [(et(18, 58), ("a", "b")), (et(21, 58), ("e", "f"))]


def test_no_games_no_slots() -> None:
    assert plan_day(DAY, [], CFG) == []


tip_minutes = st.lists(st.integers(min_value=12 * 60, max_value=23 * 60), min_size=1, max_size=15)


@settings(max_examples=200, deadline=None)
@given(tip_minutes, st.lists(st.integers(min_value=0, max_value=180), min_size=15, max_size=15))
def test_slot_invariants(tips: list[int], extra_leads: list[int]) -> None:
    games = []
    for i, m in enumerate(tips):
        tip = et(m // 60, m % 60)
        games.append(SlotGame(f"g{i}", tip, tip - timedelta(minutes=60 + extra_leads[i])))
    slots = plan_day(DAY, games, CFG)
    by_id = {g.game_id: g for g in games}
    close_window = timedelta(minutes=CFG.close_window_min - 10)
    for kind in ("open", "decision", "close"):
        covered = [gid for s in slots if s.kind == kind for gid in s.game_ids]
        assert sorted(covered) == sorted(by_id), kind  # every game exactly once per kind
    for s in slots:
        for gid in s.game_ids:
            g = by_id[gid]
            if s.kind in ("open", "decision"):
                assert s.ts <= g.decision_ts
            else:
                assert g.tip_off_utc - close_window <= s.ts < g.tip_off_utc
    assert len([s for s in slots if s.kind == "decision"]) <= 3
