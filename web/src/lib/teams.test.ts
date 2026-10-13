import { describe, expect, it } from "vitest";
import { historySeries, parseTeamId } from "./teams";
import type { Ratings } from "./types";

const rating = (as_of_ts: string, extra: Partial<Ratings> = {}): Ratings => ({
  game_id: "g", as_of_ts, elo: 1500, ortg: 110, drtg: 108, net: 2, pace: 98, net_l10: null, gp: 1,
  ...extra,
});

describe("teams", () => {
  it("parses a team id from the query string", () => {
    expect(parseTeamId("1610612738")).toBe(1610612738);
    expect(parseTeamId(null)).toBeNull();
    expect(parseTeamId("")).toBeNull();
    expect(parseTeamId("abc")).toBeNull();
    expect(parseTeamId("12.5")).toBeNull();
    expect(parseTeamId("-3")).toBeNull();
  });

  it("builds chart points in time order with ET dates", () => {
    const points = historySeries([
      rating("2021-11-27T16:00:00Z", { elo: 1520.6, net: null }),
      rating("2021-10-06T03:00:00Z", { elo: 1500 }), // 11 pm ET on Oct 5
    ]);
    expect(points).toEqual([
      { ts: "2021-10-06T03:00:00Z", date: "Oct 5", elo: 1500, net: 2, pace: 98 },
      { ts: "2021-11-27T16:00:00Z", date: "Nov 27", elo: 1520.6, net: null, pace: 98 },
    ]);
  });
});
