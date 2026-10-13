import type { Ratings } from "./types";

export interface HistoryPoint {
  ts: string;
  date: string; // ET date of the snapshot, e.g. "Nov 27"
  elo: number;
  net: number | null;
  pace: number | null;
}

const ET_DAY = new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", timeZone: "America/New_York",
});

export function parseTeamId(raw: string | null): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return id > 0 ? id : null;
}

export function historySeries(ratings: Ratings[]): HistoryPoint[] {
  return [...ratings]
    .sort((a, b) => a.as_of_ts.localeCompare(b.as_of_ts))
    .map((r) => ({
      ts: r.as_of_ts, date: ET_DAY.format(new Date(r.as_of_ts)), elo: r.elo, net: r.net, pace: r.pace,
    }));
}
