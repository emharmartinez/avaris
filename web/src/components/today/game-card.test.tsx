import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { game, NOW } from "@/test/data";
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
});
