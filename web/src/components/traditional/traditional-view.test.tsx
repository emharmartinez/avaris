import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { TraditionalDay, TraditionalGame } from "@/lib/types";
import { renderWithQuery } from "@/test/render";
import { server } from "@/test/server";
import { TraditionalView } from "./traditional-view";

const DEN = { team_id: 1610612743, abbreviation: "DEN", name: "Denver Nuggets" };
const ATL = { team_id: 1610612737, abbreviation: "ATL", name: "Atlanta Hawks" };
const BOS = { team_id: 1610612738, abbreviation: "BOS", name: "Boston Celtics" };
const BKN = { team_id: 1610612751, abbreviation: "BKN", name: "Brooklyn Nets" };
const line = (p: number, margin: number, total: number) => ({
  p_home_win: p,
  margin: { mu: margin, sigma: 12.5, lo: margin - 16, hi: margin + 16 },
  total: { mu: total, sigma: 19.5, lo: total - 25, hi: total + 25 },
});
const pregame = {
  ...line(0.6, 3.2, 222.5),
  inputs: { elo_margin: 4, eff_margin: 1, eff_total: 225, league_total: 220, weight: 0.25,
    home_gp: 10, away_gp: 10, home_b2b: 0, away_b2b: 0 },
};
const scheduled: TraditionalGame = {
  game_id: "0022100047", season_type: "regular", tip_off_utc: "2021-11-28T00:00:00Z",
  home: DEN, away: ATL, status: "scheduled", score: null, pregame, live: null,
};
const liveGame: TraditionalGame = {
  ...scheduled, game_id: "0022100048", home: BKN, away: BOS, status: "in_progress",
  score: { home_pts: 50, away_pts: 45 },
  live: { ...line(0.8367, 7, 230), period: 2, clock: "1:27", label: "2nd Qtr", minutes_left: 25.45 },
};
const day = (games: TraditionalGame[], extra: Partial<TraditionalDay> = {}): TraditionalDay => ({
  date: "2021-11-27", is_today: true, live_at: "2021-11-28T00:30:00Z", live_error: null, games,
  ...extra,
});

const serve = (body: TraditionalDay, urls: URL[] = []) => server.use(
  http.get("*/api/traditional", ({ request }) => {
    urls.push(new URL(request.url));
    return HttpResponse.json(body);
  }),
);
const card = (name: string) => screen.getByRole("group", { name });
const cells = (scope: HTMLElement, market: string) =>
  within(within(scope).getByRole("row", { name: new RegExp(`^${market}`) }))
    .getAllByRole("cell").map((c) => c.textContent);

describe("TraditionalView", () => {
  it("shows pregame and live lines with the score and clock", async () => {
    const urls: URL[] = [];
    serve(day([liveGame, scheduled]), urls);
    renderWithQuery(<TraditionalView date={null} />);
    expect(await screen.findByRole("group", { name: "BOS @ BKN" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Traditional");
    expect(urls[0].search).toBe("");
    expect(screen.getByText(/Live scores as of Nov 27, 7:30 PM ET/)).toBeInTheDocument();

    const live = card("BOS @ BKN");
    expect(within(live).getByText("2nd Qtr · 1:27")).toBeInTheDocument();
    expect(within(live).getByText("Score")).toBeInTheDocument();
    const headers = within(live).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Market", "Pregame", "Live"]);
    expect(cells(live, "Moneyline")).toEqual(["Moneyline", "BKN −150BOS +150", "BKN −512BOS +512"]);
    expect(cells(live, "Spread")[2]).toBe("BKN −7.080% BKN −9.0 to +23.0");
    expect(cells(live, "Total")[1]).toBe("O/U 222.580% 197.5 to 247.5");

    const upcoming = card("ATL @ DEN");
    expect(within(upcoming).getByText("Upcoming")).toBeInTheDocument();
    expect(within(upcoming).getAllByRole("columnheader")).toHaveLength(2);
    expect(within(upcoming).getByText("Elo DEN +4.0 · ratings DEN +1.0 at 25% weight"))
      .toBeInTheDocument();
  });

  it("grades a final against its pregame line", async () => {
    const urls: URL[] = [];
    const final: TraditionalGame = { ...scheduled, status: "final", score: { home_pts: 110, away_pts: 100 } };
    serve(day([final], { is_today: false, live_at: null, date: "2021-11-26" }), urls);
    renderWithQuery(<TraditionalView date="2021-11-26" />);
    const game = await screen.findByRole("group", { name: "ATL @ DEN" });
    expect(urls[0].searchParams.get("date")).toBe("2021-11-26");
    expect(within(game).getByText("Final score")).toBeInTheDocument();
    expect(cells(game, "Moneyline")[2]).toBe("DEN won");
    expect(within(game).getByLabelText("pick won")).toBeInTheDocument();
    expect(cells(game, "Spread")[2]).toBe("DEN by 10 · line DEN −3.2");
    expect(within(game).getByLabelText("line covered")).toBeInTheDocument();
    expect(cells(game, "Total")[2]).toBe("210 · Under 222.5");
    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("href", expect.stringMatching(/^\/traditional\/?$/));
  });

  it("keeps the pregame lines when the live feed fails", async () => {
    serve(day([{ ...liveGame, status: "scheduled", score: null, live: null }], {
      live_at: null, live_error: "Live scores unavailable (ConnectTimeout)",
    }));
    renderWithQuery(<TraditionalView date={null} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Live scores unavailable (ConnectTimeout); showing pregame lines.");
    expect(cells(card("BOS @ BKN"), "Moneyline")).toEqual(["Moneyline", "BKN −150BOS +150"]);
  });

  it("says so when there are no games", async () => {
    serve(day([], { live_at: null }));
    renderWithQuery(<TraditionalView date={null} />);
    expect(await screen.findByText("No games on this date.")).toBeInTheDocument();
  });
});
