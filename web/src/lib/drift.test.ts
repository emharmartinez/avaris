import { describe, expect, it } from "vitest";
import { driftRows, driftSummary } from "./drift";
import type { Performance } from "./types";

const check = (live: number, lo: number, hi: number) => ({ live, lo, hi, drift: live < lo || live > hi });
const drift: Performance["drift"] = {
  reference: "evaluation_2021-22_2024-25",
  scopes: {
    regular: { n: 30, log_loss: check(0.7, 0.55, 0.66), margin_mae: check(10, 9, 12), total_mae: null },
    preseason: null,
    postseason: null,
  },
};

describe("drift", () => {
  it("lists one row per metric of scopes with live games", () => {
    const rows = driftRows(drift);
    expect(rows.map((r) => [r.scope, r.metric, r.drift])).toEqual([
      ["regular", "log_loss", true],
      ["regular", "margin_mae", false],
    ]);
    expect(rows[0]).toMatchObject({ n: 30, label: "Log loss", live: 0.7, lo: 0.55, hi: 0.66 });
  });
  it("summarizes: drift, ok, or nothing to compare", () => {
    expect(driftSummary(drift)).toEqual({ state: "drift", metrics: ["regular log loss"] });
    expect(driftSummary({ ...drift, scopes: { ...drift.scopes, regular: { n: 30, log_loss: check(0.6, 0.55, 0.66), margin_mae: null, total_mae: null } } }))
      .toEqual({ state: "ok", metrics: [] });
    expect(driftSummary({ ...drift, scopes: { regular: null, preseason: null, postseason: null } }))
      .toEqual({ state: "none", metrics: [] });
    expect(driftSummary(null)).toEqual({ state: "unavailable", metrics: [] });
  });
});
