import { describe, expect, it } from "vitest";
import { actualOutcome, groupReport, mergeRatings, sortedDrivers } from "./game";
import type { InjuryEntry, Ratings } from "./types";

describe("sortedDrivers", () => {
  it("sorts families by absolute value, largest first", () => {
    const set = { base: 0.1, scale: "log_odds" as const, top: [],
      families: { elo: -0.53, form: 1.81, availability: -0.48, home_court: 0.9 } };
    expect(sortedDrivers(set)).toEqual([
      { family: "form", value: 1.81 },
      { family: "home_court", value: 0.9 },
      { family: "elo", value: -0.53 },
      { family: "availability", value: -0.48 },
    ]);
  });
});

describe("actualOutcome", () => {
  it("returns the home margin and the total of a final game", () => {
    expect(actualOutcome({ home_pts: 110, away_pts: 100 })).toEqual({ margin: 10, total: 210 });
    expect(actualOutcome({ home_pts: 95, away_pts: 101 })).toEqual({ margin: -6, total: 196 });
  });

  it("is null before the game is played", () => {
    expect(actualOutcome(null)).toBeNull();
  });
});

const rating = (as_of_ts: string, elo: number, net: number | null): Ratings => ({
  game_id: "g", as_of_ts, elo, ortg: null, drtg: null, net, pace: null, net_l10: null, gp: 1,
});

describe("mergeRatings", () => {
  it("merges both teams' series by as_of_ts, sorted in time", () => {
    const home = [rating("2021-11-20T00:00:00Z", 1510, 2.5), rating("2021-11-10T00:00:00Z", 1500, 1)];
    const away = [rating("2021-11-10T00:00:00Z", 1490, -1), rating("2021-11-15T00:00:00Z", 1480, null)];
    expect(mergeRatings(home, away)).toEqual([
      { ts: "2021-11-10T00:00:00Z", homeElo: 1500, awayElo: 1490, homeNet: 1, awayNet: -1 },
      { ts: "2021-11-15T00:00:00Z", homeElo: null, awayElo: 1480, homeNet: null, awayNet: null },
      { ts: "2021-11-20T00:00:00Z", homeElo: 1510, awayElo: null, homeNet: 2.5, awayNet: null },
    ]);
  });

  it("is empty with no ratings", () => {
    expect(mergeRatings([], [])).toEqual([]);
  });
});

describe("groupReport", () => {
  it("splits the decision report entries by team", () => {
    const entry = (team_id: number, player_name: string): InjuryEntry =>
      ({ team_id, player_id: null, player_name, status: "Out", reason: null });
    const groups = groupReport([entry(1, "A"), entry(2, "B"), entry(1, "C")], 1, 2);
    expect(groups.home.map((e) => e.player_name)).toEqual(["A", "C"]);
    expect(groups.away.map((e) => e.player_name)).toEqual(["B"]);
  });
});
