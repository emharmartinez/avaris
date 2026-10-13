import type { Driver, DriverSet, Game, InjuryEntry, Ratings } from "./types";

export function sortedDrivers(set: DriverSet): Driver[] {
  return Object.entries(set.families)
    .map(([family, value]) => ({ family, value }))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}

export function actualOutcome(result: Game["result"]): { margin: number; total: number } | null {
  // Home perspective, like the margin prediction
  if (!result) return null;
  return { margin: result.home_pts - result.away_pts, total: result.home_pts + result.away_pts };
}

export interface RatingPoint {
  ts: string;
  homeElo: number | null;
  awayElo: number | null;
  homeNet: number | null;
  awayNet: number | null;
}

export function mergeRatings(home: Ratings[], away: Ratings[]): RatingPoint[] {
  const points = new Map<string, RatingPoint>();
  const at = (ts: string) => {
    let p = points.get(ts);
    if (!p) {
      p = { ts, homeElo: null, awayElo: null, homeNet: null, awayNet: null };
      points.set(ts, p);
    }
    return p;
  };
  for (const r of home) Object.assign(at(r.as_of_ts), { homeElo: r.elo, homeNet: r.net });
  for (const r of away) Object.assign(at(r.as_of_ts), { awayElo: r.elo, awayNet: r.net });
  return [...points.values()].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
}

export function groupReport(entries: InjuryEntry[], homeId: number, awayId: number) {
  return {
    home: entries.filter((e) => e.team_id === homeId),
    away: entries.filter((e) => e.team_id === awayId),
  };
}
