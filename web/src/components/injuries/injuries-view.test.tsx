import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { InjuriesOnDate, InjuryGame, RestList } from "@/lib/types";
import { health, rest } from "@/test/data";
import { renderWithQuery } from "@/test/render";
import { server } from "@/test/server";
import { InjuriesView } from "./injuries-view";

const BKN = { team_id: 1610612751, abbreviation: "BKN", name: "Brooklyn Nets" };
const BOS = { team_id: 1610612738, abbreviation: "BOS", name: "Boston Celtics" };

const reported: InjuryGame = {
  game_id: "0022100048",
  home: BKN,
  away: BOS,
  season_type: "regular",
  report_ts: "2021-11-27T16:00:00Z",
  rest: null,
  impact: {
    away: {
      full_strength: 110.345, lost: 13.836, lost_share: 0.12539,
      players: [{ player_id: 2001, name: "Player 2001", status: "out", value: 13.836, lost: 13.836 },
        { player_id: 2002, name: null, status: "questionable", value: 4, lost: 2 }],
    },
    home: null,
  },
  entries: [
    { team_id: BKN.team_id, player_id: 3001, player_name: "Player, 3001", status: "probable", reason: "Rest" },
    { team_id: BOS.team_id, player_id: 2001, player_name: "Player, 2001", status: "out", reason: "Injury" },
  ],
};
const unreported: InjuryGame = {
  game_id: "0022100045",
  home: BOS,
  away: BKN,
  season_type: "regular",
  report_ts: null,
  rest: null,
  impact: {
    home: { full_strength: 110.3, lost: 0, lost_share: 0, players: [] },
    away: { full_strength: 100.4, lost: 0, lost_share: 0, players: [] },
  },
  entries: [],
};

const NYK = { team_id: 1610612752, abbreviation: "NYK", name: "New York Knicks" };
const TOR = { team_id: 1610612761, abbreviation: "TOR", name: "Toronto Raptors" };
const r = rest();
const espn: RestList = {
  adjusted: r.adjusted, note: r.note, snapshot_ts: r.snapshot_ts, k: r.k, home: r.home, away: r.away,
};
const preseason: InjuryGame = {
  game_id: "0012600046", home: TOR, away: NYK, season_type: "preseason", report_ts: null,
  impact: { home: null, away: null }, entries: [], rest: espn,
};

const serve = (body: InjuriesOnDate, onRequest?: (date: string | null) => void) => server.use(
  http.get("*/api/health", () => HttpResponse.json(health())),
  http.get("*/api/injuries", ({ request }) => {
    onRequest?.(new URL(request.url).searchParams.get("date"));
    return HttpResponse.json(body);
  }),
);

describe("InjuriesView", () => {
  it("defaults to the server's today and shows impact and report entries per team", async () => {
    let requested: string | null = null;
    serve({ date: "2021-11-27", games: [reported] }, (d) => { requested = d; });
    renderWithQuery(<InjuriesView date={null} />);
    const card = await screen.findByRole("region", { name: "BOS @ BKN" });
    expect(requested).toBe("2021-11-27");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Injuries");
    expect(screen.getByText("Sat, Nov 27, 2021")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Today" })).toBeNull();

    // Away side: share lost and the players behind it; home side had no report
    const away = within(card).getByRole("group", { name: "BOS impact" });
    expect(away).toHaveTextContent("13% of full strength lost");
    expect(away).toHaveTextContent("Player 2001");
    expect(away).toHaveTextContent("13.8");
    expect(away).toHaveTextContent("Player 2002");
    expect(away).toHaveTextContent("questionable");
    expect(within(card).getByRole("group", { name: "BKN impact" })).toHaveTextContent("no report");

    // Entries grouped by team, away first
    const rows = within(within(card).getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell").map((c) => c.textContent))).toEqual([
      ["BOS", "Player, 2001", "out", "Injury"],
      ["BKN", "Player, 3001", "probable", "Rest"],
    ]);
  });

  it("links to the neighbouring days and back to today", async () => {
    serve({ date: "2021-11-26", games: [unreported] });
    renderWithQuery(<InjuriesView date="2021-11-26" />);
    const card = await screen.findByRole("region", { name: "BKN @ BOS" });
    expect(card).toHaveTextContent("No report used");
    expect(within(card).queryByRole("table")).toBeNull();
    expect(card).toHaveTextContent(/no players listed/i);
    const href = (name: string) => screen.getByRole("link", { name }).getAttribute("href");
    expect(href("Previous day")).toMatch(/^\/injuries\/?\?date=2021-11-25$/);
    expect(href("Next day")).toMatch(/^\/injuries\/?\?date=2021-11-27$/);
    expect(href("Today")).toMatch(/^\/injuries\/?$/);
  });

  it("shows ESPN's out list for a preseason game", async () => {
    serve({ date: "2026-10-13", games: [preseason] });
    renderWithQuery(<InjuriesView date="2026-10-13" />);
    const card = await screen.findByRole("region", { name: "NYK @ TOR" });
    expect(card).toHaveTextContent(/ESPN list of/);
    const away = within(card).getByRole("group", { name: "NYK impact" });
    expect(away).toHaveTextContent("29.4 Game Score lost");
    expect(away).toHaveTextContent("Jalen Brunson");
    expect(away).toHaveTextContent("12.1");
    expect(within(card).getByRole("group", { name: "TOR impact" })).toHaveTextContent("0.0 Game Score lost");
    const rows = within(within(card).getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell").map((c) => c.textContent))[0]).toEqual(
      ["NYK", "Jalen Brunson", "Day-To-Day", "Brunson won't play Tuesday against Toronto for rest purposes."]);
    expect(rows).toHaveLength(4);
    expect(card).not.toHaveTextContent("no report");
  });

  it("says when a preseason game had no ESPN list", async () => {
    serve({ date: "2026-10-13", games: [
      { ...preseason, rest: { ...espn, adjusted: false, snapshot_ts: null,
        note: "no ESPN snapshot before decision time",
        home: { lost: null, players: [] }, away: { lost: null, players: [] } } },
      { ...preseason, game_id: "0012600045", rest: null },
    ] });
    renderWithQuery(<InjuriesView date="2026-10-13" />);
    const cards = await screen.findAllByRole("region", { name: "NYK @ TOR" });
    expect(cards[0]).toHaveTextContent("no ESPN snapshot before decision time");
    expect(cards[0]).toHaveTextContent("No ESPN list (unknown)");
    expect(cards[1]).toHaveTextContent("Preseason: no NBA report or ESPN list");
  });

  it("says when there are no games", async () => {
    serve({ date: "2021-07-01", games: [] });
    renderWithQuery(<InjuriesView date="2021-07-01" />);
    expect(await screen.findByText("No games on this date.")).toBeInTheDocument();
  });
});
