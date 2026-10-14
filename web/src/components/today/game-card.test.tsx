import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { game, NOW, preseasonGame, rest } from "@/test/data";
import { renderWithQuery } from "@/test/render";
import { GameCard } from "./game-card";

describe("GameCard", () => {
  it("shows the matchup, win split, intervals, status and countdown", () => {
    renderWithQuery(<GameCard game={game()} now={NOW} />);
    // next/link adds the trailing slash only in a build with trailingSlash: true
    expect(screen.getByRole("link", { name: "ATL @ DEN" }))
      .toHaveAttribute("href", expect.stringMatching(/^\/game\/?\?id=0022100047$/));
    expect(screen.getByText("Atlanta Hawks at Denver Nuggets")).toBeInTheDocument();
    expect(screen.getByText("84%")).toBeInTheDocument();
    expect(screen.getByText("16%")).toBeInTheDocument();
    expect(screen.getByText("+9.4")).toBeInTheDocument();
    expect(screen.getByText("80%: −9.6 to +28.4")).toBeInTheDocument();
    expect(screen.getByText("223.7")).toBeInTheDocument();
    expect(screen.getByText("80%: 199.1 to 248.3")).toBeInTheDocument();
    expect(screen.getByText("Provisional")).toBeInTheDocument();
    expect(screen.getByText("final in 6h 00m")).toBeInTheDocument();
  });

  it("shows injury impact per side and the top home-win drivers", () => {
    renderWithQuery(<GameCard game={game()} now={NOW} />);
    expect(screen.getByText("0% strength lost")).toBeInTheDocument();
    expect(screen.getByText("14% strength lost")).toBeInTheDocument();
    expect(screen.getByText("Form")).toBeInTheDocument();
    expect(screen.getByText("+1.81")).toBeInTheDocument();
    expect(screen.getByText("Elo")).toBeInTheDocument();
    expect(screen.getByText("−0.53")).toBeInTheDocument();
    expect(screen.getByText("Availability")).toBeInTheDocument();
  });

  it("says when a side has no injury report", () => {
    const g = game();
    const prediction = { ...g.prediction!, injury_impact: { home: null, away: null } };
    renderWithQuery(<GameCard game={{ ...g, prediction }} now={NOW} />);
    expect(screen.getAllByText("no report")).toHaveLength(2);
  });

  it("labels a non-NBA opponent by team id", () => {
    const away = { team_id: 50015, abbreviation: null, name: null };
    renderWithQuery(<GameCard game={game({ away, season_type: "preseason" })} now={NOW} />);
    expect(screen.getByRole("link", { name: "Team 50015 @ DEN" })).toBeInTheDocument();
    expect(screen.getByText("Preseason")).toBeInTheDocument();
  });

  it("flags a neutral site", () => {
    renderWithQuery(<GameCard game={game({ neutral_site: true })} now={NOW} />);
    expect(screen.getByText("Neutral site")).toBeInTheDocument();
  });

  it("says when there is no prediction yet", () => {
    renderWithQuery(<GameCard game={game({ prediction: null })} now={NOW} />);
    expect(screen.getByText("No prediction yet")).toBeInTheDocument();
    expect(screen.queryByText(/final in/)).not.toBeInTheDocument();
  });

  it("shows the final score and no countdown for a final game", () => {
    const g = game();
    const final = game({
      result: { home_pts: 112, away_pts: 104 },
      game_status: "final",
      prediction: { ...g.prediction!, status: "final" },
    });
    renderWithQuery(<GameCard game={final} now={NOW} />);
    expect(screen.getByText("112")).toBeInTheDocument();
    expect(screen.getByText("104")).toBeInTheDocument();
    expect(screen.getByText("Final")).toBeInTheDocument();
    expect(screen.queryByText(/final in/)).not.toBeInTheDocument();
  });

  it("omits the countdown while the server clock is unknown", () => {
    renderWithQuery(<GameCard game={game()} now={null} />);
    expect(screen.queryByText(/final in/)).not.toBeInTheDocument();
  });

  it("labels a rest-adjusted preseason prediction and shows the raw split beside it", () => {
    renderWithQuery(<GameCard game={preseasonGame()} now={NOW} />);
    expect(screen.getByText("Rest-adjusted (ESPN)")).toBeInTheDocument();
    expect(screen.getByText("raw NYK 62% · TOR 38%, margin −3.4, total 221.0")).toBeInTheDocument();
    // The headline is the adjusted split
    expect(screen.getByText("61%")).toBeInTheDocument();
    expect(screen.getByText("39%")).toBeInTheDocument();
    expect(screen.getByText("+3.9")).toBeInTheDocument();
  });

  it("shows ESPN's out list as the preseason injuries", () => {
    renderWithQuery(<GameCard game={preseasonGame()} now={NOW} />);
    expect(screen.getByText("Brunson, Towns, Anunoby +1 out (ESPN)")).toBeInTheDocument();
    expect(screen.getByText("none out (ESPN)")).toBeInTheDocument();
    expect(screen.queryByText("no report")).toBeNull();
  });

  it("adds nothing without a rest block or when it is not adjusted", () => {
    renderWithQuery(<GameCard game={game()} now={NOW} />);
    expect(screen.queryByText("Rest-adjusted (ESPN)")).toBeNull();
    expect(screen.queryByText(/^raw /)).toBeNull();
    const notAdjusted = preseasonGame(rest({ adjusted: false, note: "no ESPN snapshot before decision time" }));
    renderWithQuery(<GameCard game={notAdjusted} now={NOW} />);
    expect(screen.queryByText("Rest-adjusted (ESPN)")).toBeNull();
    expect(screen.queryByText(/^raw /)).toBeNull();
  });
});
