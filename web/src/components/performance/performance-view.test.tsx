import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { DriftCheck, Performance, ScopeMetrics } from "@/lib/types";
import { renderWithQuery } from "@/test/render";
import { server } from "@/test/server";
import { PerformanceView } from "./performance-view";

const metrics: ScopeMetrics = {
  n: 2, log_loss: 1.70043, brier: 0.468579, accuracy: 0.5, margin_mae: 15.6789,
  margin_rmse: 17.3961, margin_coverage_80: 0.5, total_mae: 9.8858, total_rmse: 10.1843,
  total_coverage_80: 1,
};
const empty: ScopeMetrics = {
  n: 0, log_loss: null, brier: null, accuracy: null, margin_mae: null, margin_rmse: null,
  margin_coverage_80: null, total_mae: null, total_rmse: null, total_coverage_80: null,
};
const check = (live: number, lo: number, hi: number): DriftCheck =>
  ({ live, lo, hi, drift: live < lo || live > hi });

const perf = (drift: Performance["drift"], extra: Partial<Performance> = {}): Performance => ({
  season: "2021-22",
  scopes: { regular: metrics, preseason: empty, postseason: empty, all: metrics },
  seasons: ["2021-22"],
  drift,
  ...extra,
});
const reference = "evaluation_2021-22_2024-25";
const drifting: Performance["drift"] = {
  reference,
  scopes: {
    regular: {
      n: 2,
      log_loss: check(1.70043, 0.597837, 0.597837),
      margin_mae: check(15.6789, 1.5, 11),
      total_mae: check(9.8858, 1.5, 13.5),
    },
    preseason: null,
    postseason: null,
  },
};

const serve = (body: Performance) =>
  server.use(http.get("*/api/performance", () => HttpResponse.json(body)));

describe("PerformanceView", () => {
  it("shows a metrics row per scope, regular season first, dashes without games", async () => {
    serve(perf(drifting));
    renderWithQuery(<PerformanceView season={null} onSeasonChange={() => {}} />);
    const table = await screen.findByRole("table", { name: "Metrics by scope" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent))
      .toEqual(["Regular season", "Preseason", "Postseason", "All"]);
    expect(within(rows[0]).getAllByRole("cell").map((c) => c.textContent).slice(1))
      .toEqual(["2", "1.7004", "0.4686", "50%", "15.68", "17.40", "50%", "9.89", "10.18", "100%"]);
    expect(within(rows[1]).getAllByRole("cell").map((c) => c.textContent).slice(1))
      .toEqual(["0", ...Array(9).fill("–")]);
    expect(screen.getByRole("combobox", { name: "Season" })).toHaveTextContent("2021-22");
  });

  it("flags drift with the flagged metrics and a per-row table", async () => {
    serve(perf(drifting));
    renderWithQuery(<PerformanceView season="2021-22" onSeasonChange={() => {}} />);
    const card = await screen.findByRole("region", { name: "Drift" });
    const summary = within(card).getByRole("status");
    expect(within(summary).getByText("Drift")).toHaveAttribute("data-slot", "badge");
    expect(summary).toHaveTextContent("regular log loss");
    expect(summary).toHaveTextContent("regular margin mae");
    expect(card).toHaveTextContent(reference);
    const rows = within(within(card).getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getAllByRole("cell").map((c) => c.textContent))
      .toEqual(["Regular season", "Log loss", "2", "1.7004", "0.5978 – 0.5978", "Drift"]);
    expect(within(rows[1]).getAllByRole("cell").map((c) => c.textContent))
      .toEqual(["Regular season", "Margin MAE", "2", "15.68", "1.50 – 11.00", "Drift"]);
    expect(within(rows[2]).getAllByRole("cell").at(-1)).toHaveTextContent("In range");
  });

  it("says when live metrics are in range", async () => {
    serve(perf({ reference, scopes: { regular: { n: 30, log_loss: check(0.6, 0.55, 0.66), margin_mae: null, total_mae: null }, preseason: null, postseason: null } }));
    renderWithQuery(<PerformanceView season={null} onSeasonChange={() => {}} />);
    const card = await screen.findByRole("region", { name: "Drift" });
    const summary = within(card).getByRole("status");
    expect(within(summary).getByText("In range")).toHaveAttribute("data-slot", "badge");
    expect(within(card).queryByText("Drift", { selector: "[data-slot=badge]" })).toBeNull();
  });

  it("says when there are not enough games to compare", async () => {
    serve(perf({ reference, scopes: { regular: null, preseason: null, postseason: null } }));
    renderWithQuery(<PerformanceView season={null} onSeasonChange={() => {}} />);
    const card = await screen.findByRole("region", { name: "Drift" });
    expect(within(card).getByRole("status")).toHaveTextContent("Not enough games");
    expect(within(card).queryByRole("table")).toBeNull();
  });

  it("says when there is no reference backtest", async () => {
    serve(perf(null));
    renderWithQuery(<PerformanceView season={null} onSeasonChange={() => {}} />);
    const card = await screen.findByRole("region", { name: "Drift" });
    expect(within(card).getByRole("status")).toHaveTextContent("No reference backtest");
  });

  it("requests the chosen season and offers it even when not listed", async () => {
    let requested: string | null = null;
    server.use(http.get("*/api/performance", ({ request }) => {
      requested = new URL(request.url).searchParams.get("season");
      return HttpResponse.json(perf(null, { season: "2022-23", seasons: ["2021-22"] }));
    }));
    renderWithQuery(<PerformanceView season="2022-23" onSeasonChange={() => {}} />);
    expect(await screen.findByRole("combobox", { name: "Season" })).toHaveTextContent("2022-23");
    expect(requested).toBe("2022-23");
  });
});
