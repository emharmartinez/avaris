import { describe, expect, it } from "vitest";
import {
  countdownToFinal,
  driverLabel,
  formatDriver,
  formatInterval,
  formatMetric,
  formatTip,
  pct,
  seasonTypeLabel,
  signed,
  teamLabel,
  teamName,
} from "./format";

describe("numbers", () => {
  it("formats probabilities as whole percents", () => {
    expect(pct(0.6234)).toBe("62%");
    expect(pct(null)).toBe("–");
  });
  it("signs margins", () => {
    expect(signed(3.46)).toBe("+3.5");
    expect(signed(-2)).toBe("−2.0");
    expect(signed(0.04)).toBe("0.0");
  });
  it("formats 80% intervals, signed for margins", () => {
    expect(formatInterval({ mu: 2, sigma: 10, lo: -10.84, hi: 14.81 }, true)).toBe("−10.8 to +14.8");
    expect(formatInterval({ mu: 220, sigma: 18, lo: 196.9, hi: 243.06 }, false)).toBe("196.9 to 243.1");
  });
  it("formats metrics with a fixed number of digits, dash when missing", () => {
    expect(formatMetric(0.61314, 4)).toBe("0.6131");
    expect(formatMetric(null)).toBe("–");
    expect(formatMetric(0.8, 0, true)).toBe("80%");
  });
});

describe("teams", () => {
  it("falls back to the team id for non-NBA opponents", () => {
    expect(teamLabel({ team_id: 1610612743, abbreviation: "DEN", name: "Denver Nuggets" })).toBe("DEN");
    expect(teamLabel({ team_id: 50015, abbreviation: null, name: null })).toBe("Team 50015");
    expect(teamName({ team_id: 50015, abbreviation: null, name: null })).toBe("Team 50015");
    expect(teamName({ team_id: 1, abbreviation: "DEN", name: "Denver Nuggets" })).toBe("Denver Nuggets");
  });
});

describe("labels", () => {
  it("names season types and driver families", () => {
    expect(seasonTypeLabel("cup_final")).toBe("Cup final");
    expect(seasonTypeLabel("play_in")).toBe("Play-in");
    expect(driverLabel("rest_travel")).toBe("Rest & travel");
    expect(driverLabel("home_court")).toBe("Home court");
    expect(driverLabel("something_new")).toBe("Something new");
  });
  it("formats driver contributions on their scale", () => {
    expect(formatDriver(0.7912, "log_odds")).toBe("+0.79");
    expect(formatDriver(-3.38, "points")).toBe("−3.4 pts");
  });
});

describe("time", () => {
  it("formats tip-off in the given time zone", () => {
    expect(formatTip("2021-11-28T00:00:00Z", "America/New_York")).toBe("7:00 PM");
    expect(formatTip(null)).toBe("TBD");
  });
  it("counts down to tip-off minus 60 minutes on the server clock", () => {
    const tip = "2021-11-28T00:00:00Z";
    expect(countdownToFinal(tip, "2021-11-27T17:00:00Z")).toBe("final in 6h 00m");
    expect(countdownToFinal(tip, "2021-11-27T22:55:30Z")).toBe("final in 5m");
    expect(countdownToFinal(tip, "2021-11-27T23:00:00Z")).toBeNull();
    expect(countdownToFinal(null, "2021-11-27T17:00:00Z")).toBeNull();
  });
});
