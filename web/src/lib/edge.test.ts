import { describe, expect, it } from "vitest";
import { normalCdf } from "./distribution";
import {
  evaluateMarket, formatOdds, lineOutcomes, moneylineMarket, parseLine, parseOdds, spreadMarket,
  totalMarket,
} from "./edge";

const N = { mu: 0, sigma: 10 };

describe("odds", () => {
  it("parses American odds to decimal", () => {
    expect(parseOdds("-110", "american")).toBeCloseTo(1.909091, 6);
    expect(parseOdds("+150", "american")).toBe(2.5);
    expect(parseOdds("150", "american")).toBe(2.5);
    expect(parseOdds(" −200 ", "american")).toBe(1.5); // typographic minus
    expect(parseOdds("100", "american")).toBe(2);
    expect(parseOdds("-100", "american")).toBe(2);
  });

  it("rejects American odds inside (-100, 100) and non-numbers", () => {
    for (const raw of ["99", "-99.5", "0", "", "abc", "-", "1e3x"]) {
      expect(parseOdds(raw, "american"), raw).toBeNull();
    }
  });

  it("parses decimal odds above 1", () => {
    expect(parseOdds("1.91", "decimal")).toBe(1.91);
    expect(parseOdds("3", "decimal")).toBe(3);
    for (const raw of ["1", "0.5", "-2", "", "x"]) expect(parseOdds(raw, "decimal"), raw).toBeNull();
  });

  it("formats decimal odds in either format", () => {
    expect(formatOdds(2.5, "american")).toBe("+150");
    expect(formatOdds(1 + 100 / 110, "american")).toBe("−110");
    expect(formatOdds(2, "american")).toBe("+100");
    expect(formatOdds(2.5, "decimal")).toBe("2.50");
  });

  it("parses lines, including pick'em and a typographic minus", () => {
    expect(parseLine("-5.5")).toBe(-5.5);
    expect(parseLine("+3")).toBe(3);
    expect(parseLine("−7")).toBe(-7);
    expect(parseLine("pk")).toBe(0);
    expect(parseLine("")).toBeNull();
    expect(parseLine("abc")).toBeNull();
  });
});

describe("line outcomes", () => {
  it("has no push on a half-point line", () => {
    const over = lineOutcomes(N, 5.5, "over");
    expect(over.push).toBe(0);
    expect(over.win).toBeCloseTo(1 - normalCdf(5.5, 0, 10), 9);
    expect(over.win + over.lose).toBeCloseTo(1, 9);
    const under = lineOutcomes(N, 5.5, "under");
    expect(under.win).toBeCloseTo(over.lose, 9);
  });

  it("pushes on the integer itself for a whole-number line", () => {
    // Scores are integers: the line 5 pushes on 5, wins on 6+ (above 5.5), loses on 4- (below 4.5)
    const over = lineOutcomes(N, 5, "over");
    expect(over.win).toBeCloseTo(1 - normalCdf(5.5, 0, 10), 9);
    expect(over.lose).toBeCloseTo(normalCdf(4.5, 0, 10), 9);
    expect(over.push).toBeCloseTo(normalCdf(5.5, 0, 10) - normalCdf(4.5, 0, 10), 9);
    expect(lineOutcomes(N, 5, "under")).toEqual({ win: over.lose, push: over.push, lose: over.win });
  });
});

describe("markets", () => {
  it("de-vigs both prices and finds no edge on a fair coin at -110/-110", () => {
    const d = parseOdds("-110", "american");
    const m = evaluateMarket([
      { outcome: { win: 0.5, push: 0, lose: 0.5 }, odds: d },
      { outcome: { win: 0.5, push: 0, lose: 0.5 }, odds: d },
    ]);
    expect(m.devigged).toBe(true);
    expect(m.vig).toBeCloseTo(2 / d! - 1, 9);
    for (const s of m.sides) {
      expect(s.implied).toBeCloseTo(0.5, 9);
      expect(s.edge).toBeCloseTo(0, 9);
      expect(s.ev).toBeCloseTo(0.5 * (d! - 1) - 0.5, 9);
      expect(s.fairOdds).toBeCloseTo(2, 9);
    }
  });

  it("uses the vigged implied probability when only one price is entered", () => {
    const m = evaluateMarket([
      { outcome: { win: 0.6, push: 0, lose: 0.4 }, odds: 2 },
      { outcome: { win: 0.4, push: 0, lose: 0.6 }, odds: null },
    ]);
    expect(m.devigged).toBe(false);
    expect(m.vig).toBeNull();
    expect(m.sides[0]).toMatchObject({ implied: 0.5, model: 0.6 });
    expect(m.sides[0].edge).toBeCloseTo(0.1, 9);
    expect(m.sides[0].ev).toBeCloseTo(0.2, 9);
    expect(m.sides[1]).toMatchObject({ implied: null, edge: null, ev: null });
    expect(m.sides[1].fairOdds).toBeCloseTo(2.5, 9);
  });

  it("returns the stake on a push: model probability and EV exclude it", () => {
    const m = evaluateMarket([
      { outcome: { win: 0.45, push: 0.1, lose: 0.45 }, odds: 2.1 },
      { outcome: { win: 0.45, push: 0.1, lose: 0.45 }, odds: 1.8 },
    ]);
    expect(m.sides[0].model).toBeCloseTo(0.5, 9);
    expect(m.sides[0].push).toBeCloseTo(0.1, 9);
    expect(m.sides[0].ev).toBeCloseTo(0.45 * 1.1 - 0.45, 9);
    expect(m.sides[1].ev).toBeCloseTo(0.45 * 0.8 - 0.45, 9);
  });

  it("moneyline uses the calibrated win probability, away side first", () => {
    const [away, home] = moneylineMarket(0.8);
    expect(home).toMatchObject({ win: 0.8, push: 0 });
    expect(home.lose).toBeCloseTo(0.2, 9);
    expect(away.win).toBeCloseTo(0.2, 9);
    expect(away.lose).toBeCloseTo(0.8, 9);
  });

  it("spread: the home line is negative when home is favored; margin is home minus away", () => {
    const margin = { mu: 4, sigma: 12 };
    const [away, home] = spreadMarket(margin, -3.5);
    expect(home.win).toBeCloseTo(1 - normalCdf(3.5, 4, 12), 9); // home wins by 4+
    expect(away.win).toBeCloseTo(normalCdf(3.5, 4, 12), 9);
    expect(spreadMarket(margin, 2.5)[1].win).toBeCloseTo(1 - normalCdf(-2.5, 4, 12), 9);
  });

  it("spread: a pick'em never pushes, since NBA games cannot tie", () => {
    const [away, home] = spreadMarket({ mu: 0, sigma: 10 }, 0);
    expect(home.push).toBe(0);
    expect(home.win).toBeCloseTo(0.5, 9);
    expect(away.win + home.win).toBeCloseTo(1, 9);
  });

  it("total: over then under at the same line", () => {
    const [over, under] = totalMarket({ mu: 220, sigma: 18 }, 224);
    expect(over.win).toBeCloseTo(1 - normalCdf(224.5, 220, 18), 9);
    expect(under.win).toBeCloseTo(normalCdf(223.5, 220, 18), 9);
    expect(over.push).toBeGreaterThan(0);
  });
});
