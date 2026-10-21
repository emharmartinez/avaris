import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Bet } from "@/lib/types";
import { bankroll, bet } from "@/test/data";
import { renderWithQuery } from "@/test/render";
import { server } from "@/test/server";
import { BankrollCard, BetsTable } from "./bankroll";

const cells = (row: HTMLElement) => within(row).getAllByRole("cell").map((c) => c.textContent);

describe("BankrollCard", () => {
  it("asks for a bankroll and a unit size, then shows what one unit is", async () => {
    const user = userEvent.setup();
    let put: unknown = null;
    server.use(http.put("*/api/bankroll", async ({ request }) => {
      put = await request.json();
      return HttpResponse.json(bankroll());
    }));
    renderWithQuery(<BankrollCard bankroll={bankroll({ starting: null, unit_pct: null, current: null, unit: null })} />);
    const start = screen.getByLabelText("Starting bankroll");
    const unit = screen.getByLabelText("Unit size (% of bankroll)");
    expect(unit).toHaveValue("1");
    await user.type(start, "0");
    expect(start).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.clear(start);
    await user.type(start, "1000");
    expect(screen.getByText("1 unit = 10.00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(put).toEqual({ starting: 1000, unit_pct: 1 });
  });

  it("shows the bankroll after settled bets, the unit, profit and record", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BankrollCard bankroll={bankroll()} />);
    const stat = (name: string) => screen.getByRole("group", { name }).textContent;
    expect(stat("Bankroll")).toContain("988.00");
    expect(stat("1 unit")).toContain("9.88");
    expect(stat("1 unit")).toContain("1% of the bankroll");
    expect(stat("Profit")).toContain("−12.00");
    expect(stat("Profit")).toContain("ROI −40.0%");
    expect(stat("Record")).toContain("1-1-1");
    expect(stat("In play")).toContain("30.00");

    // Edit: the form opens on the saved values
    await user.click(screen.getByRole("button", { name: "Edit bankroll" }));
    expect(screen.getByLabelText("Starting bankroll")).toHaveValue("1000");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Starting bankroll")).not.toBeInTheDocument();
  });
});

describe("BetsTable", () => {
  const bets: Bet[] = [
    bet({ bet_id: 2, market: "total", side: "under", line: 221.5, odds: 1.9, stake: 30, result: "pending", profit: null }),
    bet({ bet_id: 1, market: "spread", side: "away", line: 9.5, odds: 2, stake: 20, result: "lost", profit: -20 }),
  ];

  it("lists each bet with its result and profit in the chosen odds format", () => {
    renderWithQuery(<BetsTable bets={bets} format="american" />);
    const table = screen.getByRole("table", { name: "Bets" });
    const [pending, lost] = within(table).getAllByRole("row").slice(1);
    expect(cells(pending)).toEqual(["Sat, Nov 27, 2021", "ATL @ DEN", "Under 221.5", "−111", "30.00", "Pending", "–", ""]);
    expect(cells(lost)).toEqual(["Sat, Nov 27, 2021", "ATL @ DEN", "ATL +9.5", "+100", "20.00", "Lost", "−20.00", ""]);
    expect(within(pending).getByRole("link", { name: "ATL @ DEN" }))
      .toHaveAttribute("href", expect.stringMatching(/^\/edge\/?\?date=2021-11-27&game=0022100047$/));
  });

  it("deletes a bet after a confirmation", async () => {
    const user = userEvent.setup();
    const deleted: string[] = [];
    server.use(http.delete("*/api/bets/:id", ({ params }) => {
      deleted.push(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }));
    renderWithQuery(<BetsTable bets={bets} format="decimal" />);
    const table = screen.getByRole("table", { name: "Bets" });
    const row = within(table).getAllByRole("row")[2];
    await user.click(within(row).getByRole("button", { name: "Delete bet" }));
    expect(deleted).toEqual([]);
    await user.click(within(row).getByRole("button", { name: "Keep" }));
    await user.click(within(row).getByRole("button", { name: "Delete bet" }));
    await user.click(within(row).getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(deleted).toEqual(["1"]));
  });
});
