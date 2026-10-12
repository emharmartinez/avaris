from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from avaris.config import OddsSettings
from avaris.seasons import ET

# Historical snapshots are up to 10 minutes apart (5 from Sep 2022), and `date` returns the
# snapshot at or before it, so closing slots plan with a window this much shorter
SNAPSHOT_GAP = timedelta(minutes=10)


@dataclass(frozen=True)
class SlotGame:
    game_id: str
    tip_off_utc: datetime  # naive UTC
    decision_ts: datetime  # naive UTC


@dataclass(frozen=True)
class Slot:
    ts: datetime  # naive UTC snapshot time to request
    kind: str  # open, decision, close
    game_ids: tuple[str, ...]


def _utc(day: date, hhmm: str) -> datetime:
    local = datetime.combine(day, time.fromisoformat(hhmm), tzinfo=ET)
    return local.astimezone(UTC).replace(tzinfo=None)


def _ids(games: list[SlotGame]) -> tuple[str, ...]:
    return tuple(g.game_id for g in sorted(games, key=lambda g: (g.tip_off_utc, g.game_id)))


def _decision_slots(day: date, games: list[SlotGame], cfg: OddsSettings) -> list[Slot]:
    # One slot per tip-time band (matinee, early, late) at the band's earliest decision_ts,
    # so the snapshot is never after any covered game's decision_ts
    early, late = _utc(day, cfg.early_band_from_et), _utc(day, cfg.late_band_from_et)
    bands: dict[int, list[SlotGame]] = {}
    for g in games:
        band = 0 if g.tip_off_utc < early else 1 if g.tip_off_utc < late else 2
        bands.setdefault(band, []).append(g)
    slots = [
        Slot(min(g.decision_ts for g in band), "decision", _ids(band)) for band in bands.values()
    ]
    return sorted(slots, key=lambda s: s.ts)


def _close_slots(
    games: list[SlotGame], cfg: OddsSettings, max_slots: int | None
) -> list[Slot]:
    # Greedy cover: each candidate sits close_lead before a tip and covers the games tipping
    # within the window after it; the candidate covering most games wins, ties go to the
    # later one (closer to tip)
    window = timedelta(minutes=cfg.close_window_min) - SNAPSHOT_GAP
    lead = timedelta(minutes=cfg.close_lead_min)
    candidates = sorted({g.tip_off_utc - lead for g in games})
    uncovered = list(games)
    slots: list[Slot] = []
    while uncovered and (max_slots is None or len(slots) < max_slots):
        best_ts, best = candidates[0], []
        for ts in candidates:
            covered = [g for g in uncovered if ts < g.tip_off_utc <= ts + window]
            if len(covered) >= len(best):
                best_ts, best = ts, covered
        if not best:
            break
        slots.append(Slot(best_ts, "close", _ids(best)))
        uncovered = [g for g in uncovered if g not in best]
    return sorted(slots, key=lambda s: s.ts)


def plan_day(
    day: date, games: list[SlotGame], cfg: OddsSettings, max_close_slots: int | None = None
) -> list[Slot]:
    # Snapshot slots for one ET game day, shared by the backfill and the live scheduler:
    # 1 opening, a decision slot per tip-time band, and closing slots (capped live)
    if not games:
        return []
    decisions = _decision_slots(day, games, cfg)
    open_ts = min(_utc(day, cfg.open_time_et), decisions[0].ts - timedelta(hours=1))
    return [
        Slot(open_ts, "open", _ids(games)),
        *decisions,
        *_close_slots(games, cfg, max_close_slots),
    ]
