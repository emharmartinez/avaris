import { pct } from "./format";
import type { Driver, Game, InjuryImpact } from "./types";

export interface WinSplit {
  home: number;
  away: number;
  homeText: string;
  awayText: string;
}

export function winSplit(pHome: number): WinSplit {
  // The away label is derived from the rounded home one so the two add to 100%
  const homePct = Math.round(pHome * 100);
  return { home: pHome, away: 1 - pHome, homeText: `${homePct}%`, awayText: `${100 - homePct}%` };
}

export function injuryText(impact: InjuryImpact | null): string {
  return impact?.lost_share == null ? "no report" : `${pct(impact.lost_share)} strength lost`;
}

export function topDrivers(drivers: Driver[] | undefined, n = 3): Driver[] {
  return (drivers ?? []).slice(0, n);
}

export function activeGames(games: Game[]): Game[] {
  // Games not started or still live; a final prediction (tip-off - 60 min) is not a finished game
  return games.filter((g) => g.game_status !== "final");
}

export function todayHref(date: string | null): string {
  return date ? `/?date=${date}` : "/";
}

export function isDay(day: string | null | undefined): day is string {
  // A real calendar date in YYYY-MM-DD (round-trips through Date, so 2021-02-30 is rejected)
  if (!day || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return false;
  const d = new Date(`${day}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === day;
}
