import { describe, expect, it } from "vitest";
import { preseasonGame, rest } from "@/test/data";
import {
  adjustedRest, edgeRestNote, rawText, REST_LABEL, restComparison, restLostText, restOutText, restStatus,
} from "./rest";

const adjusted = preseasonGame().prediction!;
const notAdjusted = preseasonGame(rest({
  adjusted: false, note: "no ESPN snapshot before decision time", snapshot_ts: null,
})).prediction!;

describe("restStatus", () => {
  it("labels an adjusted prediction and otherwise gives the reason", () => {
    expect(restStatus(adjusted.rest!)).toBe(REST_LABEL);
    expect(REST_LABEL).toBe("Rest-adjusted (ESPN)");
    expect(restStatus(notAdjusted.rest!)).toBe("no ESPN snapshot before decision time");
    expect(restStatus(rest({ adjusted: false, note: null }))).toBe("Not rest-adjusted");
  });
});

describe("adjustedRest", () => {
  it("is the rest block only when the headline values are adjusted", () => {
    expect(adjustedRest(adjusted)).toBe(adjusted.rest);
    expect(adjustedRest(notAdjusted)).toBeNull();
    expect(adjustedRest({ ...adjusted, rest: null })).toBeNull();
  });
});

describe("restComparison", () => {
  it("formats raw and adjusted win, margin and total like the headline", () => {
    expect(restComparison(adjusted, adjusted.rest!)).toEqual([
      { label: "Home win", raw: "37.9%", adjusted: "61.2%" },
      { label: "Margin (home)", raw: "−3.4", adjusted: "+3.9" },
      { label: "Total", raw: "221.0", adjusted: "214.6" },
    ]);
  });
});

describe("restLostText", () => {
  it("gives the points lost, or unknown without an ESPN list", () => {
    expect(restLostText({ lost: 29.4, players: [] })).toBe("29.4 Game Score lost");
    expect(restLostText({ lost: 0, players: [] })).toBe("0.0 Game Score lost");
    expect(restLostText({ lost: null, players: [] })).toBe("No ESPN list (unknown)");
  });
});

const marginOnly = preseasonGame(rest({ k: { margin: 0.11, total: 0, win: 0 } })).prediction!;
const fromMargin = preseasonGame(rest({ k: { margin: 0.11, total: 0, win: 0 }, win_from_margin: true }))
  .prediction!;

describe("rawText", () => {
  it("gives the raw value of each adjusted output in one string, the split away first", () => {
    expect(rawText(adjusted.rest!, "TOR", "NYK")).toBe("raw NYK 62% · TOR 38%, margin −3.4, total 221.0");
  });

  it("leaves out outputs whose coefficient is off", () => {
    expect(rawText(marginOnly.rest!, "TOR", "NYK")).toBe("raw margin −3.4");
  });

  it("gives the raw split when the win followed the adjusted margin (ADR-023)", () => {
    expect(rawText(fromMargin.rest!, "TOR", "NYK")).toBe("raw NYK 62% · TOR 38%, margin −3.4");
    expect(edgeRestNote(fromMargin, "TOR"))
      .toBe("Preseason: rest-adjusted from ESPN list (raw TOR 37.9%, margin −3.4)");
  });
});

describe("edgeRestNote", () => {
  it("names the raw values only for an adjusted prediction", () => {
    expect(edgeRestNote(adjusted, "TOR"))
      .toBe("Preseason: rest-adjusted from ESPN list (raw TOR 37.9%, margin −3.4, total 221.0)");
    expect(edgeRestNote(marginOnly, "TOR")).toBe("Preseason: rest-adjusted from ESPN list (raw margin −3.4)");
    expect(edgeRestNote(notAdjusted, "TOR")).toBeNull();
    expect(edgeRestNote({ ...adjusted, rest: null }, "TOR")).toBeNull();
  });
});

describe("restOutText", () => {
  it("names the most valuable players ESPN lists out, by last name", () => {
    expect(restOutText(rest().away)).toBe("Brunson, Towns, Anunoby +1 out (ESPN)");
    expect(restOutText({ lost: 19.4, players: [
      { name: "Jimmy Butler III", player_id: 1, status: "Out", comment: null, value: 19.4, matched: true },
    ] })).toBe("Butler out (ESPN)");
  });

  it("says when nobody is listed or there is no ESPN list", () => {
    expect(restOutText({ lost: 0, players: [] })).toBe("none out (ESPN)");
    expect(restOutText({ lost: null, players: [] })).toBe("no ESPN list");
  });
});
