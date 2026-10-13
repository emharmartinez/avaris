import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { InjuriesOnDate, InjuryGame } from "@/lib/types";
import { health } from "@/test/data";
import { renderWithQuery } from "@/test/render";
import { server } from "@/test/server";
import { InjuriesView } from "./injuries-view";

const BKN = { team_id: 1610612751, abbreviation: "BKN", name: "Brooklyn Nets" };
const BOS = { team_id: 1610612738, abbreviation: "BOS", name: "Boston Celtics" };

const reported: InjuryGame = {
  game_id: "0022100048",
  home: BKN,
  away: BOS,
  report_ts: "2021-11-27T16:00:00Z",
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
  report_ts: null,
  impact: {
    home: { full_strength: 110.3, lost: 0, lost_share: 0, players: [] },
    away: { full_strength: 100.4, lost: 0, lost_share: 0, players: [] },
  },
  entries: [],
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

  it("says when there are no games", async () => {
    serve({ date: "2021-07-01", games: [] });
    renderWithQuery(<InjuriesView date="2021-07-01" />);
    expect(await screen.findByText("No games on this date.")).toBeInTheDocument();
  });
});
