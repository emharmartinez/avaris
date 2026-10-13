import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Backtest, BacktestSummary } from "@/lib/types";
import { renderWithQuery } from "@/test/render";
import { server } from "@/test/server";
import { BacktestsView } from "./backtests-view";

const NAME = "evaluation_2021-22_2024-25";
const LIST: BacktestSummary[] = [
  { name: NAME, title: "Evaluation 2021-22 to 2024-25" },
  { name: "tuning_2015-16_2019-20", title: "Tuning 2015-16 to 2019-20" },
];
const REPORT: Backtest = {
  name: NAME,
  title: "Evaluation 2021-22 to 2024-25",
  markdown: "# Evaluation 2021-22 to 2024-25\n\n<script>window.__injected = true</script>\n\n"
    + "| model | log_loss |\n|---|---|\n| model | 0.6131 |\n",
  charts: ["reliability_report.svg", "coverage margin.svg"],
};

describe("BacktestsView", () => {
  it("lists reports linking to their detail", async () => {
    server.use(http.get("*/api/backtests", () => HttpResponse.json(LIST)));
    renderWithQuery(<BacktestsView name={null} />);
    const link = await screen.findByRole("link", { name: "Evaluation 2021-22 to 2024-25" });
    expect(link.getAttribute("href")).toMatch(/^\/backtests\/?\?name=evaluation_2021-22_2024-25$/);
    expect(screen.getByRole("link", { name: "Tuning 2015-16 to 2019-20" })).toBeInTheDocument();
  });

  it("says when there are no reports", async () => {
    server.use(http.get("*/api/backtests", () => HttpResponse.json([])));
    renderWithQuery(<BacktestsView name={null} />);
    expect(await screen.findByText(/no backtest reports/i)).toBeInTheDocument();
  });

  it("renders a report's markdown safely and its charts as images", async () => {
    server.use(http.get(`*/api/backtests/${NAME}`, () => HttpResponse.json(REPORT)));
    const { container } = renderWithQuery(<BacktestsView name={NAME} />);
    const article = await screen.findByRole("article");
    expect(article).toHaveTextContent("<script>window.__injected = true</script>");
    expect(container.querySelector("script")).toBeNull();
    expect(within(article).getByRole("table")).toBeInTheDocument();

    const images = screen.getAllByRole("img");
    expect(images.map((i) => i.getAttribute("src"))).toEqual([
      `/api/backtests/${NAME}/charts/reliability_report.svg`,
      `/api/backtests/${NAME}/charts/coverage%20margin.svg`,
    ]);
    expect(images[0]).toHaveAttribute("alt", "reliability_report.svg");
    expect(images[0]).toHaveAttribute("loading", "lazy");
    expect(screen.getByRole("link", { name: /all reports/i }).getAttribute("href"))
      .toMatch(/^\/backtests\/?$/);
  });

  it("reports a missing report", async () => {
    server.use(http.get("*/api/backtests/nope", () =>
      HttpResponse.json({ detail: "unknown backtest nope" }, { status: 404 })));
    renderWithQuery(<BacktestsView name="nope" />);
    expect(await screen.findByText("unknown backtest nope")).toBeInTheDocument();
  });
});
