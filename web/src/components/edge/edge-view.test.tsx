import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { GamesOnDate } from "@/lib/types";
import { game, preseasonGame, rest } from "@/test/data";
import { renderWithQuery } from "@/test/render";
import { server } from "@/test/server";
import { EdgeView } from "./edge-view";

const BOS = { team_id: 1610612738, abbreviation: "BOS", name: "Boston Celtics" };
const BKN = { team_id: 1610612751, abbreviation: "BKN", name: "Brooklyn Nets" };
const unpredicted = game({ game_id: "0022100048", home: BKN, away: BOS, prediction: null });
const second = game({ game_id: "0022100049", home: BOS, away: BKN });

const serve = (body: GamesOnDate, onRequest?: (url: URL) => void) => server.use(
  http.get("*/api/predictions/today", ({ request }) => {
    onRequest?.(new URL(request.url));
    return HttpResponse.json(body);
  }),
  http.get("*/api/predictions", ({ request }) => {
    onRequest?.(new URL(request.url));
    return HttpResponse.json(body);
  }),
);

const cells = (row: HTMLElement) => within(row).getAllByRole("cell").map((c) => c.textContent);
const row = (table: HTMLElement, side: string) => within(table).getByRole("row", { name: new RegExp(`^${side}`) });

describe("EdgeView", () => {
  it("defaults to today's first predicted game and shows the model's fair moneyline", async () => {
    serve({ date: "2021-11-27", games: [unpredicted, game(), second] });
    renderWithQuery(<EdgeView date={null} gameId={null} onGameChange={vi.fn()} />);
    expect(await screen.findByRole("combobox", { name: "Game" })).toHaveTextContent("ATL @ DEN");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Edge");
    expect(screen.getByText("Sat, Nov 27, 2021")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Previous day" })).toHaveAttribute("href", expect.stringMatching(/^\/edge\/?\?date=2021-11-26$/));
    expect(screen.getByText(/provisional/i)).toBeInTheDocument();

    // Without odds: model probability and fair price only
    const ml = screen.getByRole("table", { name: "Moneyline" });
    expect(cells(row(ml, "DEN"))).toEqual(["DEN", "83.7%", "–", "–", "–", "−512"]);
    expect(cells(row(ml, "ATL"))).toEqual(["ATL", "16.3%", "–", "–", "–", "+512"]);
  });

  it("de-vigs typed moneyline odds into edge and EV", async () => {
    const user = userEvent.setup();
    serve({ date: "2021-11-27", games: [game()] });
    renderWithQuery(<EdgeView date={null} gameId={null} onGameChange={vi.fn()} />);
    await user.type(await screen.findByLabelText("ATL moneyline"), "-110");
    await user.type(screen.getByLabelText("DEN moneyline"), "-110");
    const ml = screen.getByRole("table", { name: "Moneyline" });
    expect(cells(row(ml, "DEN"))).toEqual(["DEN", "83.7%", "50.0%", "+33.7 pp", "+59.73", "−512"]);
    expect(cells(row(ml, "ATL"))).toEqual(["ATL", "16.3%", "50.0%", "−33.7 pp", "−68.82", "+512"]);
    expect(screen.getByText(/vig 4\.8%, removed/i)).toBeInTheDocument();

    // An invalid price is flagged and drops out
    await user.clear(screen.getByLabelText("ATL moneyline"));
    await user.type(screen.getByLabelText("ATL moneyline"), "50");
    expect(screen.getByLabelText("ATL moneyline")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/one price: implied probability includes the vig/i)).toBeInTheDocument();
    expect(cells(row(ml, "DEN"))[2]).toBe("52.4%");
    expect(screen.getByLabelText("ATL moneyline")).toHaveAccessibleDescription(/not a valid american price/i);
  });

  it("switching to decimal converts the typed odds", async () => {
    const user = userEvent.setup();
    serve({ date: "2021-11-27", games: [game()] });
    renderWithQuery(<EdgeView date={null} gameId={null} onGameChange={vi.fn()} />);
    await user.type(await screen.findByLabelText("DEN moneyline"), "+150");
    await user.click(screen.getByRole("button", { name: "Decimal" }));
    expect(screen.getByRole("button", { name: "Decimal" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("DEN moneyline")).toHaveValue("2.50");
    const ml = screen.getByRole("table", { name: "Moneyline" });
    expect(cells(row(ml, "DEN"))[5]).toBe("1.20");
  });

  it("toggling the format back and forth keeps the exact typed price", async () => {
    const user = userEvent.setup();
    serve({ date: "2021-11-27", games: [game()] });
    renderWithQuery(<EdgeView date={null} gameId={null} onGameChange={vi.fn()} />);
    const fields = { "ATL moneyline": "-600", "DEN moneyline": "-150" };
    for (const [label, value] of Object.entries(fields)) {
      await user.type(await screen.findByLabelText(label), value);
    }
    const ml = screen.getByRole("table", { name: "Moneyline" });
    const before = cells(row(ml, "DEN"));
    await user.click(screen.getByRole("button", { name: "Decimal" }));
    expect(screen.getByLabelText("DEN moneyline")).toHaveValue("1.67");
    expect(cells(row(ml, "DEN"))).toEqual([...before.slice(0, 5), "1.20"]); // same edge and EV
    await user.click(screen.getByRole("button", { name: "American" }));
    expect(screen.getByLabelText("ATL moneyline")).toHaveValue("-600");
    expect(screen.getByLabelText("DEN moneyline")).toHaveValue("-150");
    expect(cells(row(ml, "DEN"))).toEqual(before);
  });

  it("a new game clears the odds but keeps the format", async () => {
    const user = userEvent.setup();
    serve({ date: "2021-11-27", games: [game(), second] });
    const { rerender } = renderWithQuery(
      <EdgeView date={null} gameId="0022100047" onGameChange={vi.fn()} />);
    await user.type(await screen.findByLabelText("DEN moneyline"), "2.5");
    await user.click(screen.getByRole("button", { name: "Decimal" }));
    rerender(<EdgeView date={null} gameId="0022100049" onGameChange={vi.fn()} />);
    expect(await screen.findByLabelText("BOS moneyline")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Decimal" })).toHaveAttribute("aria-pressed", "true");
  });

  it("replaces a game id that is not on the date with the first game", async () => {
    const onGameChange = vi.fn();
    serve({ date: "2021-11-27", games: [game(), second] });
    renderWithQuery(<EdgeView date={null} gameId="0099999999" onGameChange={onGameChange} />);
    expect(await screen.findByRole("combobox", { name: "Game" })).toHaveTextContent("ATL @ DEN");
    expect(onGameChange).toHaveBeenCalledWith("0022100047");
  });

  it("prices the spread from the home line and the total from its line", async () => {
    const user = userEvent.setup();
    serve({ date: "2021-11-27", games: [game()] });
    renderWithQuery(<EdgeView date={null} gameId={null} onGameChange={vi.fn()} />);

    const spread = await screen.findByRole("region", { name: "Spread" });
    expect(within(spread).queryByRole("table")).toBeNull();
    await user.type(within(spread).getByLabelText("DEN line"), "-3.5");
    const st = within(spread).getByRole("table", { name: "Spread" });
    // margin N(9.41, 14.85) without the tie band: DEN covers -3.5 when it wins by 4+
    expect(cells(row(st, "DEN −3.5"))[1]).toBe("66.9%");
    expect(cells(row(st, "ATL \\+3.5"))[1]).toBe("33.1%");

    const total = screen.getByRole("region", { name: "Total" });
    await user.type(within(total).getByLabelText("Total line"), "224");
    const tt = within(total).getByRole("table", { name: "Total" });
    expect(cells(row(tt, "Over 224"))[1]).toBe("49.3%");
    expect(cells(row(tt, "Under 224"))[1]).toBe("50.7%");
    expect(total).toHaveTextContent(/push 2\.1%/i);
  });

  it("opens the game named in the URL and fetches the given date", async () => {
    let asked: string | null = null;
    serve({ date: "2021-11-26", games: [game(), second] }, (u) => { asked = u.searchParams.get("date"); });
    renderWithQuery(<EdgeView date="2021-11-26" gameId="0022100049" onGameChange={vi.fn()} />);
    expect(await screen.findByRole("combobox", { name: "Game" })).toHaveTextContent("BKN @ BOS");
    expect(asked).toBe("2021-11-26");
    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("href", expect.stringMatching(/^\/edge\/?$/));
  });

  it("says when no game on the date has a prediction", async () => {
    serve({ date: "2021-11-27", games: [unpredicted] });
    renderWithQuery(<EdgeView date={null} gameId={null} onGameChange={vi.fn()} />);
    expect(await screen.findByText("No predicted games on this date.")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Game" })).toBeNull();
  });

  it("notes a rest-adjusted preseason prediction with the raw win probability", async () => {
    serve({ date: "2026-10-13", games: [preseasonGame()] });
    renderWithQuery(<EdgeView date={null} gameId={null} onGameChange={vi.fn()} />);
    expect(await screen.findByText(/^Preseason: rest-adjusted from ESPN list \(raw TOR 37\.9%, margin −3\.4, total 221\.0\)$/))
      .toBeInTheDocument();
    // The calculator prices the adjusted values
    const ml = screen.getByRole("table", { name: "Moneyline" });
    expect(cells(row(ml, "TOR"))[1]).toBe("61.2%");
  });

  it("has no rest note for a regular game or an unadjusted preseason one", async () => {
    const unadjusted = preseasonGame(rest({ adjusted: false, note: "no ESPN snapshot before decision time" }));
    serve({ date: "2021-11-27", games: [game(), { ...unadjusted, game_id: "0012600013" }] });
    const { rerender } = renderWithQuery(<EdgeView date={null} gameId={null} onGameChange={vi.fn()} />);
    expect(await screen.findByRole("combobox", { name: "Game" })).toHaveTextContent("ATL @ DEN");
    expect(screen.queryByText(/rest-adjusted/i)).toBeNull();
    rerender(<EdgeView date={null} gameId="0012600013" onGameChange={vi.fn()} />);
    expect(await screen.findByRole("combobox", { name: "Game" })).toHaveTextContent("NYK @ TOR");
    expect(screen.queryByText(/rest-adjusted/i)).toBeNull();
  });
});
