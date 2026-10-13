import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeAll, describe, expect, it } from "vitest";
import type { Ratings, TeamHistory, TeamRatings } from "@/lib/types";
import { renderWithQuery } from "@/test/render";
import { server } from "@/test/server";
import { TeamsView } from "./teams-view";

beforeAll(() => {
  // Recharts' ResponsiveContainer observes its size; jsdom has no ResizeObserver
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

const ratings = (extra: Partial<Ratings> = {}): Ratings => ({
  game_id: "0022100048", as_of_ts: "2021-11-27T16:00:00Z", elo: 1500, ortg: 110, drtg: 108,
  net: 2, pace: 97, net_l10: 1, gp: 22, ...extra,
});
const team = (team_id: number, abbreviation: string | null, name: string | null,
  extra: Partial<Ratings> = {}): TeamRatings => ({
  team_id, abbreviation, name, season: "2021-22", ...ratings(extra),
});

const TEAMS: TeamRatings[] = [
  team(1610612743, "DEN", "Denver Nuggets", { elo: 1606.53, net: 8.415, ortg: 115.162, drtg: 106.747, pace: 97.375, net_l10: 6.899 }),
  team(1610612738, "BOS", "Boston Celtics", { elo: 1471.53, net: -1.391, net_l10: null }),
  team(99, null, null, { elo: 1360.95, net: null, ortg: null, drtg: null, pace: null, net_l10: null, gp: 0 }),
];

const history = (points: Ratings[]): TeamHistory => ({
  team: { team_id: 1610612738, abbreviation: "BOS", name: "Boston Celtics" },
  season: "2021-22",
  ratings: points,
});

describe("TeamsView", () => {
  it("lists teams in API order with formatted ratings and dashes for nulls", async () => {
    server.use(http.get("*/api/teams", () => HttpResponse.json(TEAMS)));
    renderWithQuery(<TeamsView id={null} />);
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["1", "2", "3"]);
    expect(rows[0]).toHaveTextContent("Denver Nuggets");
    expect(rows[0]).toHaveTextContent("DEN");
    expect(within(rows[0]).getAllByRole("cell").map((c) => c.textContent).slice(2))
      .toEqual(["1607", "+8.4", "115.2", "106.7", "97.4", "+6.9", "22"]);
    expect(within(rows[1]).getAllByRole("cell")[7]).toHaveTextContent("–");
    expect(rows[2]).toHaveTextContent("Team 99");
    expect(within(rows[2]).getAllByRole("cell").map((c) => c.textContent).slice(2))
      .toEqual(["1361", "–", "–", "–", "–", "–", "0"]);
    // next/link adds the trailing slash only in the build (trailingSlash: true)
    expect(within(rows[1]).getByRole("link", { name: /Boston Celtics/ }).getAttribute("href"))
      .toMatch(/^\/teams\/?\?id=1610612738$/);
  });

  it("shows the selected team's history with charts", async () => {
    server.use(
      http.get("*/api/teams", () => HttpResponse.json(TEAMS)),
      http.get("*/api/teams/1610612738", () => HttpResponse.json(history([
        ratings({ as_of_ts: "2021-10-20T23:00:00Z", elo: 1490 }),
        ratings({ as_of_ts: "2021-11-27T16:00:00Z", elo: 1471.5 }),
      ]))),
    );
    const { container } = renderWithQuery(<TeamsView id={1610612738} />);
    const panel = await screen.findByRole("region", { name: "Boston Celtics" });
    expect(panel).toHaveTextContent("2021-22");
    await waitFor(() => expect(container.querySelectorAll('[data-slot="chart"]')).toHaveLength(2));
    expect(within(panel).getByText("Elo")).toBeInTheDocument();
  });

  it("explains a history too short to chart", async () => {
    server.use(
      http.get("*/api/teams", () => HttpResponse.json(TEAMS)),
      http.get("*/api/teams/1610612738", () => HttpResponse.json(history([ratings()]))),
    );
    const { container } = renderWithQuery(<TeamsView id={1610612738} />);
    expect(await screen.findByText(/not enough rating snapshots/i)).toBeInTheDocument();
    expect(container.querySelector('[data-slot="chart"]')).toBeNull();
  });

  it("reports an unknown team", async () => {
    server.use(
      http.get("*/api/teams", () => HttpResponse.json(TEAMS)),
      http.get("*/api/teams/5", () => HttpResponse.json({ detail: "unknown team 5" }, { status: 404 })),
    );
    renderWithQuery(<TeamsView id={5} />);
    expect(await screen.findByText("unknown team 5")).toBeInTheDocument();
  });
});
