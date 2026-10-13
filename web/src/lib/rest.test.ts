import { describe, expect, it } from "vitest";
import { preseasonGame, rest } from "@/test/data";
import {
  adjustedRest, edgeRestNote, rawWinText, REST_LABEL, restComparison, restLostText, restStatus,
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

describe("rawWinText", () => {
  it("gives the raw split in one string, away first", () => {
    expect(rawWinText(adjusted.rest!, "TOR", "NYK")).toBe("raw NYK 62% · TOR 38%");
  });
});

describe("edgeRestNote", () => {
  it("names the raw home win probability only for an adjusted prediction", () => {
    expect(edgeRestNote(adjusted, "TOR")).toBe("Preseason: rest-adjusted from ESPN list (raw TOR 37.9%)");
    expect(edgeRestNote(notAdjusted, "TOR")).toBeNull();
    expect(edgeRestNote({ ...adjusted, rest: null }, "TOR")).toBeNull();
  });
});
