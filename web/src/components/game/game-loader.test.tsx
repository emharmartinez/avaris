import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeAll, describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { game, rest } from "@/test/data";
import { renderWithQuery } from "@/test/render";
import type { GameDetail, PredictionFull, Ratings } from "@/lib/types";
import { GameLoader } from "./game-loader";

beforeAll(() => {
  // Recharts' ResponsiveContainer observes its size; jsdom has no ResizeObserver
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

const rating = (as_of_ts: string, elo: number): Ratings => ({
  game_id: "g", as_of_ts, elo, ortg: 110, drtg: 108, net: 2, pace: 99, net_l10: null, gp: 10,
});

function detail(extra: Partial<GameDetail> = {}, pred: Partial<PredictionFull> = {}): GameDetail {
  const base = game();
  const prediction: PredictionFull = {
    ...base.prediction!,
    drivers: {
      home_win: { base: 0.96, scale: "log_odds", top: [], families: {
        league: 0.01, availability: -0.48, form: 1.81, elo: -0.53, home_court: 0.21,
      } },
      margin: { base: 3.27, scale: "points", top: [], families: { form: 3.08, rest_travel: 2.91 } },
      total: { base: 221.5, scale: "points", top: [], families: { elo: 6.75, league: -4.7 } },
    },
    injuries: {
      home: { full_strength: 100.5, lost: 0, lost_share: 0, players: [] },
      away: { full_strength: 88.1, lost: 12.3, lost_share: 0.1397, players: [
        { player_id: 7, name: null, status: "Out", value: 12.3, lost: 12.3 },
      ] },
    },
    ...pred,
  };
  return {
    ...base,
    prediction,
    injury_report: [
      { team_id: 1610612743, player_id: 1, player_name: "Jamal Murray", status: "Out", reason: "Knee" },
      { team_id: 1610612737, player_id: 7, player_name: "Trae Young", status: "Out", reason: "Ankle" },
    ],
    ratings: {
      home: [rating("2021-11-20T00:00:00Z", 1600), rating("2021-11-27T16:00:00Z", 1611)],
      away: [rating("2021-11-21T00:00:00Z", 1370), rating("2021-11-27T16:00:00Z", 1361)],
    },
    score: null,
    ...extra,
  };
}

const serve = (body: GameDetail) =>
  server.use(http.get("*/api/games/0022100047", () => HttpResponse.json(body)));

describe("GameLoader", () => {
  it("shows the matchup, prediction and distribution charts", async () => {
    serve(detail());
    const { container } = renderWithQuery(<GameLoader id="0022100047" />);
    expect(await screen.findByRole("heading", { name: "ATL @ DEN" })).toBeInTheDocument();
    expect(screen.getByText(/Ball Arena/)).toBeInTheDocument();
    expect(screen.getByText("84%")).toBeInTheDocument();
    expect(screen.getByText("μ +9.4 · σ 14.8 · 80% −9.6 to +28.4")).toBeInTheDocument();
    expect(screen.getByText("μ 223.7 · σ 19.2 · 80% 199.1 to 248.3")).toBeInTheDocument();
    // jsdom has no layout, so Recharts draws no SVG here; e2e checks the plotted surfaces
    expect(container.querySelectorAll('[data-slot="chart"]').length).toBeGreaterThanOrEqual(2);
  });

  it("lists every driver family sorted by magnitude, with base and scale", async () => {
    serve(detail());
    renderWithQuery(<GameLoader id="0022100047" />);
    const table = await screen.findByRole("table", { name: "Win probability drivers" });
    const families = within(table).getAllByRole("row").slice(1)
      .map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(families).toEqual(["Form", "Elo", "Availability", "Home court", "League"]);
    expect(screen.getByText("Base 0.96 log-odds")).toBeInTheDocument();
    expect(screen.getByText("Base 221.5 points")).toBeInTheDocument();
    expect(within(table).getByText("+1.81")).toBeInTheDocument();
  });

  it("groups the decision report entries and lost players per team", async () => {
    serve(detail());
    renderWithQuery(<GameLoader id="0022100047" />);
    const home = await screen.findByRole("region", { name: "DEN injuries" });
    const away = screen.getByRole("region", { name: "ATL injuries" });
    expect(within(home).getByText("Jamal Murray")).toBeInTheDocument();
    expect(within(home).queryByText("Trae Young")).not.toBeInTheDocument();
    expect(within(home).getByText("Knee")).toBeInTheDocument();
    expect(within(away).getByText("Trae Young")).toBeInTheDocument();
    expect(within(away).getByText("Player 7")).toBeInTheDocument();
    expect(within(away).getByText("14% strength lost")).toBeInTheDocument();
    expect(within(home).getByText("No players out")).toBeInTheDocument();
  });

  it("shows the preseason rest section after the injuries, only with a rest block", async () => {
    serve(detail({}, { rest: rest() }));
    const { unmount } = renderWithQuery(<GameLoader id="0022100047" />);
    const section = await screen.findByRole("region", { name: "Preseason rest" });
    const injuries = screen.getByRole("region", { name: "DEN injuries" });
    expect(injuries.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    unmount();

    serve(detail());
    renderWithQuery(<GameLoader id="0022100047" />);
    expect(await screen.findByRole("region", { name: "DEN injuries" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Preseason rest" })).toBeNull();
  });

  it("says when no injury report was used", async () => {
    serve(detail({ injury_report: [] }, { report_ts: null }));
    renderWithQuery(<GameLoader id="0022100047" />);
    expect(await screen.findByText("No injury report used (preseason or no report)"))
      .toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "DEN injuries" })).not.toBeInTheDocument();
  });

  it("shows the result, the actual outcome and the game's score once final", async () => {
    const base = detail();
    serve(detail({
      result: { home_pts: 112, away_pts: 104 },
      prediction: { ...base.prediction!, status: "final" },
      score: { log_loss: 0.1783, brier: 0.0267, correct: true, margin_error: -1.41,
        margin_in_80: true, total_error: -7.68, total_in_80: false },
    }));
    renderWithQuery(<GameLoader id="0022100047" />);
    expect(await screen.findByText("Actual +8.0")).toBeInTheDocument();
    expect(screen.getByText("Actual 216.0")).toBeInTheDocument();
    const score = screen.getByRole("region", { name: "Score" });
    expect(within(score).getByText("0.178")).toBeInTheDocument();
    expect(within(score).getByText("0.027")).toBeInTheDocument();
    expect(within(score).getByText("−1.4")).toBeInTheDocument();
    expect(within(score).getByText("−7.7")).toBeInTheDocument();
    expect(within(score).getAllByText("Yes")).toHaveLength(2);
    expect(within(score).getByText("No")).toBeInTheDocument();
  });

  it("shows the ratings trend only with at least two points", async () => {
    serve(detail({ ratings: { home: [rating("2021-11-27T16:00:00Z", 1611)], away: [] } }));
    renderWithQuery(<GameLoader id="0022100047" />);
    expect(await screen.findByText("Not enough ratings history yet")).toBeInTheDocument();
  });

  it("says when there is no prediction", async () => {
    serve(detail({ prediction: null }));
    renderWithQuery(<GameLoader id="0022100047" />);
    expect(await screen.findByText("No prediction yet")).toBeInTheDocument();
    // The report entries of the game's features still show
    const home = screen.getByRole("region", { name: "DEN injuries" });
    expect(within(home).getByText("Jamal Murray")).toBeInTheDocument();
  });

  it("shows an error for an unknown game", async () => {
    server.use(http.get("*/api/games/0022100047", () =>
      HttpResponse.json({ detail: "game 0022100047 not found" }, { status: 404 })));
    renderWithQuery(<GameLoader id="0022100047" />);
    expect(await screen.findByText("Could not load game")).toBeInTheDocument();
    expect(screen.getByText("game 0022100047 not found")).toBeInTheDocument();
  });

  it("links back to Today without an id", () => {
    renderWithQuery(<GameLoader id={null} />);
    expect(screen.getByText("No game selected.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Today" })).toHaveAttribute("href", "/");
  });
});
