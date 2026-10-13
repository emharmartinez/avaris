import { describe, expect, it } from "vitest";
import { groupEntries, impactText, parseDate, playerName } from "./injuries";
import type { InjuryEntry, InjuryGame } from "./types";

const entry = (team_id: number, player_name: string): InjuryEntry => ({
  team_id, player_id: null, player_name, status: "out", reason: null,
});
const game = (entries: InjuryEntry[]): InjuryGame => ({
  game_id: "g1",
  home: { team_id: 1, abbreviation: "BKN", name: "Brooklyn Nets" },
  away: { team_id: 2, abbreviation: "BOS", name: "Boston Celtics" },
  report_ts: "2021-11-27T16:00:00Z",
  impact: { home: null, away: null },
  entries,
});

describe("injuries", () => {
  it("groups report entries by team, away first, keeping report order", () => {
    const groups = groupEntries(game([entry(1, "H1"), entry(2, "A1"), entry(1, "H2"), entry(9, "X")]));
    expect(groups.map((g) => [g.label, g.entries.map((e) => e.player_name)])).toEqual([
      ["BOS", ["A1"]],
      ["BKN", ["H1", "H2"]],
      ["Team 9", ["X"]],
    ]);
  });

  it("returns no groups when the report lists nobody", () => {
    expect(groupEntries(game([]))).toEqual([]);
  });

  it("describes a side's lost strength", () => {
    expect(impactText(null)).toBe("no report");
    expect(impactText({ full_strength: 110.3, lost: 13.8, lost_share: 0.1254 }))
      .toBe("13% of full strength lost");
    expect(impactText({ full_strength: 100, lost: 0, lost_share: 0 }))
      .toBe("0% of full strength lost");
    expect(impactText({ full_strength: 100, lost: null, lost_share: null }))
      .toBe("no report");
  });

  it("names players, falling back to the id", () => {
    expect(playerName({ player_id: 7, name: "Player 7", status: "out", value: 1, lost: 1 })).toBe("Player 7");
    expect(playerName({ player_id: 7, name: null, status: "out", value: 1, lost: 1 })).toBe("Player 7");
    expect(playerName({ player_id: 8, name: null, status: null, value: 1, lost: 1 })).toBe("Player 8");
  });

  it("accepts only real YYYY-MM-DD dates", () => {
    expect(parseDate("2021-11-27")).toBe("2021-11-27");
    expect(parseDate(null)).toBeNull();
    expect(parseDate("2021-13-01")).toBeNull();
    expect(parseDate("2021-02-30")).toBeNull();
    expect(parseDate("27/11/2021")).toBeNull();
  });
});
