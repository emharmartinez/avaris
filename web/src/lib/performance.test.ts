import { describe, expect, it } from "vitest";
import { formatDriftValue, METRIC_COLUMNS, metricCells, SCOPES, scopeLabel, seasonOptions } from "./performance";
import type { ScopeMetrics } from "./types";

const metrics: ScopeMetrics = {
  n: 2, log_loss: 1.70043, brier: 0.468579, accuracy: 0.5, margin_mae: 15.6789,
  margin_rmse: 17.3961, margin_coverage_80: 0.5, total_mae: 9.8858, total_rmse: 10.1843,
  total_coverage_80: 1,
};
const empty: ScopeMetrics = {
  n: 0, log_loss: null, brier: null, accuracy: null, margin_mae: null, margin_rmse: null,
  margin_coverage_80: null, total_mae: null, total_rmse: null, total_coverage_80: null,
};

describe("performance", () => {
  it("orders scopes with the regular season first", () => {
    expect(SCOPES.map((s) => s.scope)).toEqual(["regular", "preseason", "postseason", "all"]);
    expect(SCOPES.map((s) => s.label)).toEqual(["Regular season", "Preseason", "Postseason", "All"]);
    expect(scopeLabel("postseason")).toBe("Postseason");
  });

  it("formats one cell per metric column", () => {
    expect(METRIC_COLUMNS).toHaveLength(10);
    expect(metricCells(metrics)).toEqual([
      "2", "1.7004", "0.4686", "50%", "15.68", "17.40", "50%", "9.89", "10.18", "100%",
    ]);
  });

  it("shows dashes when a scope has no games", () => {
    expect(metricCells(empty)).toEqual(["0", ...Array(9).fill("–")]);
    // n = 0 wins over stray values
    expect(metricCells({ ...metrics, n: 0 })).toEqual(["0", ...Array(9).fill("–")]);
  });

  it("lists seasons newest first, adding the shown season if missing", () => {
    expect(seasonOptions({ season: "2021-22", seasons: ["2021-22"] })).toEqual(["2021-22"]);
    expect(seasonOptions({ season: "2023-24", seasons: ["2021-22", "2022-23"] }))
      .toEqual(["2023-24", "2022-23", "2021-22"]);
  });

  it("formats drift values per metric", () => {
    expect(formatDriftValue("log_loss", 0.597837)).toBe("0.5978");
    expect(formatDriftValue("margin_mae", 15.6789)).toBe("15.68");
    expect(formatDriftValue("total_mae", 1.5)).toBe("1.50");
  });
});
