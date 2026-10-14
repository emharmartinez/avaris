import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { game, health } from "@/test/data";
import { renderWithQuery } from "@/test/render";
import { TodayLoader } from "./today-loader";

describe("TodayLoader", () => {
  it("lists today's games with links to the neighbouring days", async () => {
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.get("*/api/predictions/today", () =>
        HttpResponse.json({ date: "2021-11-27", games: [game()] })),
    );
    renderWithQuery(<TodayLoader date={null} />);
    expect(await screen.findByRole("link", { name: "ATL @ DEN" })).toBeInTheDocument();
    expect(screen.getByText("Sat, Nov 27, 2021")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Previous day" })).toHaveAttribute("href", "/?date=2021-11-26");
    expect(screen.getByRole("link", { name: "Next day" })).toHaveAttribute("href", "/?date=2021-11-28");
    expect(screen.queryByRole("link", { name: "Today" })).not.toBeInTheDocument();
    expect(await screen.findByText("final in 6h 00m")).toBeInTheDocument();
  });

  it("fetches a given date, links back to today and handles an empty slate", async () => {
    let asked: string | null = null;
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.get("*/api/predictions", ({ request }) => {
        asked = new URL(request.url).searchParams.get("date");
        return HttpResponse.json({ date: "2021-12-24", games: [] });
      }),
    );
    renderWithQuery(<TodayLoader date="2021-12-24" />);
    expect(await screen.findByText("No games on this date.")).toBeInTheDocument();
    expect(asked).toBe("2021-12-24");
    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("href", "/");
  });

  it("hides today's finished games and keeps the ones not started or live", async () => {
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.get("*/api/predictions/today", () =>
        HttpResponse.json({ date: "2021-11-27", games: [
          game(),
          game({ game_id: "0022100048", game_status: "in_progress",
            home: { team_id: 1610612751, abbreviation: "BKN", name: "Brooklyn Nets" },
            away: { team_id: 1610612738, abbreviation: "BOS", name: "Boston Celtics" } }),
          game({ game_id: "0022100049", game_status: "final", result: { home_pts: 110, away_pts: 100 },
            home: { team_id: 1610612744, abbreviation: "GSW", name: "Golden State Warriors" },
            away: { team_id: 1610612747, abbreviation: "LAL", name: "Los Angeles Lakers" } }),
        ] })),
    );
    renderWithQuery(<TodayLoader date={null} />);
    expect(await screen.findByRole("link", { name: "ATL @ DEN" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BOS @ BKN" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "LAL @ GSW" })).not.toBeInTheDocument();
  });

  it("says when every game today has finished", async () => {
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.get("*/api/predictions", () =>
        HttpResponse.json({ date: "2021-11-27", games: [
          game({ game_status: "final", result: { home_pts: 110, away_pts: 100 } }),
        ] })),
    );
    renderWithQuery(<TodayLoader date="2021-11-27" />);
    expect(await screen.findByText("All of today's games have finished.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "ATL @ DEN" })).not.toBeInTheDocument();
  });

  it("still shows the finals on a past date", async () => {
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.get("*/api/predictions", () =>
        HttpResponse.json({ date: "2021-11-26", games: [
          game({ game_date_et: "2021-11-26", game_status: "final",
            result: { home_pts: 110, away_pts: 100 } }),
        ] })),
    );
    renderWithQuery(<TodayLoader date="2021-11-26" />);
    expect(await screen.findByRole("link", { name: "ATL @ DEN" })).toBeInTheDocument();
  });

  it("shows an error when the predictions cannot be loaded", async () => {
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.get("*/api/predictions", () =>
        HttpResponse.json({ detail: "bad date" }, { status: 422 })),
    );
    renderWithQuery(<TodayLoader date="nope" />);
    expect(await screen.findByText("Could not load games")).toBeInTheDocument();
    expect(screen.getByText("bad date")).toBeInTheDocument();
  });
});
