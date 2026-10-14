import { describe, expect, it } from "vitest";
import { game } from "@/test/data";
import { activeGames, injuryText, isDay, todayHref, topDrivers, winSplit } from "./today";

describe("winSplit", () => {
  it("splits the home win probability into home and away percentages", () => {
    const s = winSplit(0.8367);
    expect(s.home).toBe(0.8367);
    expect(s.away).toBeCloseTo(0.1633);
    expect([s.homeText, s.awayText]).toEqual(["84%", "16%"]);
  });

  it("rounds both labels so they add to 100%", () => {
    const s = winSplit(0.505);
    expect(s.homeText).toBe("51%");
    expect(s.awayText).toBe("49%");
  });
});

describe("injuryText", () => {
  it("formats the share of strength lost", () => {
    expect(injuryText({ full_strength: 88.1, lost: 12.3, lost_share: 0.1397 })).toBe("14% strength lost");
    expect(injuryText({ full_strength: 100.5, lost: 0, lost_share: 0 })).toBe("0% strength lost");
  });

  it("says when there is no report", () => {
    expect(injuryText(null)).toBe("no report");
    expect(injuryText({ full_strength: 100, lost: null, lost_share: null })).toBe("no report");
  });
});

describe("topDrivers", () => {
  it("keeps the first three drivers", () => {
    const d = [1, 2, 3, 4].map((v) => ({ family: `f${v}`, value: v }));
    expect(topDrivers(d).map((x) => x.family)).toEqual(["f1", "f2", "f3"]);
    expect(topDrivers(undefined)).toEqual([]);
  });
});

describe("todayHref", () => {
  it("links to a date, or to today without one", () => {
    expect(todayHref("2021-11-26")).toBe("/?date=2021-11-26");
    expect(todayHref(null)).toBe("/");
  });
});

describe("isDay", () => {
  it("accepts only real YYYY-MM-DD dates", () => {
    expect(isDay("2021-11-27")).toBe(true);
    expect(isDay("2021-13-45")).toBe(false);
    expect(isDay("nope")).toBe(false);
    expect(isDay(null)).toBe(false);
  });
});

describe("activeGames", () => {
  it("keeps scheduled and in-progress games and drops finished ones", () => {
    const games = [
      game({ game_id: "a", game_status: "scheduled" }),
      game({ game_id: "b", game_status: "in_progress" }),
      game({ game_id: "c", game_status: "final", result: { home_pts: 110, away_pts: 100 } }),
    ];
    expect(activeGames(games).map((g) => g.game_id)).toEqual(["a", "b"]);
  });

  it("keeps a game whose prediction is final but which has not tipped off", () => {
    const g = game({ game_status: "scheduled" });
    const finalPrediction = { ...g, prediction: { ...g.prediction!, status: "final" as const } };
    expect(activeGames([finalPrediction])).toHaveLength(1);
  });
});
