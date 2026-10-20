import { describe, expect, it } from "vitest";
import {
  betLabel, defaultStake, formatMoney, parseMoney, parsePct, signedMoney, toWin, units,
} from "./bankroll";
import type { Team } from "./types";

const DEN: Team = { team_id: 1610612743, abbreviation: "DEN", name: "Denver Nuggets" };
const ATL: Team = { team_id: 1610612737, abbreviation: "ATL", name: "Atlanta Hawks" };
const game = { home: DEN, away: ATL };

describe("bankroll", () => {
  it("parses amounts above 0, with or without thousands separators", () => {
    expect(parseMoney("1000")).toBe(1000);
    expect(parseMoney(" 1,250.50 ")).toBe(1250.5);
    expect(parseMoney("$10")).toBe(10);
    expect(parseMoney("0")).toBeNull();
    expect(parseMoney("-5")).toBeNull();
    expect(parseMoney("ten")).toBeNull();
    expect(parseMoney("")).toBeNull();
  });

  it("parses a unit percentage in (0, 100]", () => {
    expect(parsePct("1")).toBe(1);
    expect(parsePct("2.5%")).toBe(2.5);
    expect(parsePct("100")).toBe(100);
    expect(parsePct("0")).toBeNull();
    expect(parsePct("101")).toBeNull();
  });

  it("formats money with two decimals and a sign for profit", () => {
    expect(formatMoney(1000)).toBe("1,000.00");
    expect(formatMoney(null)).toBe("–");
    expect(signedMoney(8)).toBe("+8.00");
    expect(signedMoney(-20)).toBe("−20.00");
    expect(signedMoney(0)).toBe("0.00");
  });

  it("sizes a stake in units", () => {
    // A 1,000 bankroll with 1% units: 1 unit is 10
    expect(defaultStake(10)).toBe("10.00");
    expect(defaultStake(9.876)).toBe("9.88");
    expect(defaultStake(null)).toBe("");
    expect(defaultStake(0)).toBe("");
    expect(units(25, 10)).toBe(2.5);
    expect(units(25, null)).toBeNull();
    expect(units(25, 0)).toBeNull();
    expect(toWin(10, 1.91)).toBeCloseTo(9.1, 10);
  });

  it("labels a bet by its side and line", () => {
    expect(betLabel({ market: "moneyline", side: "home", line: null }, game)).toBe("DEN ML");
    expect(betLabel({ market: "spread", side: "away", line: 3.5 }, game)).toBe("ATL +3.5");
    expect(betLabel({ market: "spread", side: "home", line: -3 }, game)).toBe("DEN −3");
    expect(betLabel({ market: "spread", side: "home", line: 0 }, game)).toBe("DEN pk");
    expect(betLabel({ market: "total", side: "over", line: 220.5 }, game)).toBe("Over 220.5");
    expect(betLabel({ market: "total", side: "under", line: 221 }, game)).toBe("Under 221");
  });
});
