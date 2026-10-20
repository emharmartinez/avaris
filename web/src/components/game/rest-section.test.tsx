import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FALLBACK, game, openerGame, preseasonGame, rest } from "@/test/data";
import { RestSection } from "./rest-section";

const cells = (row: HTMLElement) => within(row).getAllByRole("cell").map((c) => c.textContent);

describe("RestSection", () => {
  it("renders nothing without a rest block", () => {
    const g = game();
    const { container } = render(<RestSection prediction={g.prediction} home={g.home} away={g.away} seasonType={g.season_type} />);
    expect(container).toBeEmptyDOMElement();
    const none = render(<RestSection prediction={null} home={g.home} away={g.away} seasonType={g.season_type} />);
    expect(none.container).toBeEmptyDOMElement();
  });

  it("shows the label, raw against adjusted values and the snapshot time", () => {
    const g = preseasonGame();
    render(<RestSection prediction={g.prediction} home={g.home} away={g.away} seasonType={g.season_type} />);
    const section = screen.getByRole("region", { name: "Preseason rest" });
    expect(within(section).getByRole("heading", { name: "Preseason rest" })).toBeInTheDocument();
    expect(within(section).getByText("Rest-adjusted (ESPN)")).toBeInTheDocument();
    expect(within(section).getByText(/ESPN list as of Oct 13, 4:05 PM ET/)).toBeInTheDocument();
    const table = within(section).getByRole("table", { name: "Raw and rest-adjusted" });
    const rows = within(table).getAllByRole("row").slice(1).map(cells);
    expect(rows).toEqual([
      ["Home win", "37.9%", "61.2%"],
      ["Margin (home)", "−3.4", "+3.9"],
      ["Total", "221.0", "214.6"],
    ]);
  });

  it("titles a season opener's list as ESPN's, with no comparison table", () => {
    const g = openerGame();
    render(<RestSection prediction={g.prediction} home={g.home} away={g.away} seasonType={g.season_type} />);
    const section = screen.getByRole("region", { name: "ESPN injury list" });
    expect(within(section).getByText(FALLBACK)).toBeInTheDocument();
    expect(within(section).queryByRole("table", { name: "Raw and rest-adjusted" })).toBeNull();
    expect(within(section).getByRole("region", { name: "NYK rest" })).toHaveTextContent("29.4 Game Score lost");
  });

  it("lists each side's out players with status, note, value and an unmatched flag", () => {
    const g = preseasonGame();
    render(<RestSection prediction={g.prediction} home={g.home} away={g.away} seasonType={g.season_type} />);
    const nyk = screen.getByRole("region", { name: "NYK rest" });
    expect(within(nyk).getByText("29.4 Game Score lost")).toBeInTheDocument();
    const players = within(nyk).getByRole("table", { name: "NYK out" });
    const rows = within(players).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);
    expect(cells(rows[0])).toEqual([
      "Jalen Brunson", "Day-To-Day", "Brunson won't play Tuesday against Toronto for rest purposes.", "12.1",
    ]);
    expect(within(rows[3]).getByText("Kevin McCullar Jr.")).toBeInTheDocument();
    expect(within(rows[3]).getByText("unmatched")).toBeInTheDocument();
    expect(within(rows[0]).queryByText("unmatched")).toBeNull();
    expect(cells(rows[3]).slice(1)).toEqual(["Out", "–", "0.0"]);

    const tor = screen.getByRole("region", { name: "TOR rest" });
    expect(within(tor).getByText("0.0 Game Score lost")).toBeInTheDocument();
    expect(within(tor).getByText("No players listed out")).toBeInTheDocument();
  });

  it("says the win follows the margin instead of printing a win coefficient (ADR-023)", () => {
    const g = preseasonGame(rest({ k: { margin: 0.108, total: 0, win: 0 }, win_from_margin: true }));
    render(<RestSection prediction={g.prediction} home={g.home} away={g.away} seasonType={g.season_type} />);
    expect(screen.getByText(/Coefficients \(0 = off\): margin 0.108, total 0.000, win follows margin/))
      .toBeInTheDocument();
  });

  it("renders an ESPN note as plain text", () => {
    const r = rest();
    r.away.players[0] = { ...r.away.players[0], comment: "<b>rest</b> **day**" };
    const g = preseasonGame(r);
    const { container } = render(<RestSection prediction={g.prediction} home={g.home} away={g.away} seasonType={g.season_type} />);
    expect(screen.getByText("<b>rest</b> **day**")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
  });

  it("gives the reason when the values are not adjusted", () => {
    const g = preseasonGame(rest({
      adjusted: false, note: "no ESPN snapshot before decision time", snapshot_ts: null,
      home: { lost: null, players: [] }, away: { lost: null, players: [] },
    }));
    render(<RestSection prediction={g.prediction} home={g.home} away={g.away} seasonType={g.season_type} />);
    expect(screen.getByText("no ESPN snapshot before decision time")).toBeInTheDocument();
    expect(screen.queryByText("Rest-adjusted (ESPN)")).toBeNull();
    expect(screen.queryByRole("table", { name: "Raw and rest-adjusted" })).toBeNull();
    expect(screen.getAllByText("No ESPN list (unknown)")).toHaveLength(2);
  });
});
