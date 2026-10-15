import { describe, expect, it } from "vitest";
import {
  fairMoneyline, finalResult, inputsText, liveText, pollInterval, spreadText, statusText,
  totalText,
} from "./traditional";
import type { TraditionalDay, TraditionalGame } from "./types";

const DEN = { team_id: 1610612743, abbreviation: "DEN", name: "Denver Nuggets" };
const ATL = { team_id: 1610612737, abbreviation: "ATL", name: "Atlanta Hawks" };
const line = (p: number, margin: number, total: number) => ({
  p_home_win: p,
  margin: { mu: margin, sigma: 12.5, lo: margin - 16, hi: margin + 16 },
  total: { mu: total, sigma: 19.5, lo: total - 25, hi: total + 25 },
});
const inputs = {
  elo_margin: 4, eff_margin: 11.5, eff_total: 225, league_total: 220, weight: 0.25,
  home_gp: 10, away_gp: 10, home_b2b: 0, away_b2b: 0,
};
const game = (extra: Partial<TraditionalGame> = {}): TraditionalGame => ({
  game_id: "0022100047", season_type: "regular", tip_off_utc: "2021-11-28T00:00:00Z",
  home: DEN, away: ATL, status: "scheduled", score: null,
  pregame: { ...line(0.68, 5.9, 222.5), inputs }, live: null, ...extra,
});
const day = (games: TraditionalGame[], isToday = true): TraditionalDay => ({
  date: "2021-11-27", is_today: isToday, live_at: null, live_error: null, games,
});
const live = { ...line(0.8, 9, 230), period: 2, clock: "1:27", label: "2nd Qtr", minutes_left: 25.45 };

describe("fairMoneyline", () => {
  it("prices a probability in American odds", () => {
    expect(fairMoneyline(0.8367)).toBe("−512");
    expect(fairMoneyline(0.1633)).toBe("+512");
    expect(fairMoneyline(0.5)).toBe("+100");
  });

  it("leaves a settled game off the board", () => {
    expect(fairMoneyline(0.999)).toBe("–");
    expect(fairMoneyline(0)).toBe("–");
  });
});

describe("spreadText", () => {
  it("lays the points with the favorite", () => {
    expect(spreadText(5.94, DEN, ATL)).toBe("DEN −5.9");
    expect(spreadText(-3.25, DEN, ATL)).toBe("ATL −3.3");
    expect(spreadText(0.02, DEN, ATL)).toBe("Pick'em");
  });
});

describe("totalText", () => {
  it("shows the total to one decimal", () => {
    expect(totalText(222.46)).toBe("222.5");
  });
});

describe("status", () => {
  it("names the game state, with the clock while live", () => {
    expect(statusText(game())).toBe("Upcoming");
    expect(statusText(game({ status: "final" }))).toBe("Final");
    expect(statusText(game({ status: "in_progress", live }))).toBe("2nd Qtr · 1:27");
    expect(statusText(game({ status: "in_progress" }))).toBe("Live");
  });

  it("drops a stopped clock at a break", () => {
    expect(liveText({ ...live, label: "Halftime", clock: "0:00" })).toBe("Halftime");
    expect(liveText({ ...live, clock: null })).toBe("2nd Qtr");
  });
});

describe("pollInterval", () => {
  it("polls fast while a game is live, slowly while today's games are still to come", () => {
    expect(pollInterval(day([game({ status: "in_progress", live })]))).toBe(30_000);
    expect(pollInterval(day([game()]))).toBe(60_000);
    expect(pollInterval(day([game({ status: "final" })]))).toBe(false);
    expect(pollInterval(day([game()], false))).toBe(false);
    expect(pollInterval(undefined)).toBe(false);
  });
});

describe("inputsText", () => {
  it("lists what the margin is made of", () => {
    expect(inputsText(inputs, DEN, ATL)).toBe("Elo DEN +4.0 · ratings DEN +11.5 at 25% weight");
    expect(inputsText({ ...inputs, eff_margin: null, weight: 0, away_b2b: 1 }, DEN, ATL))
      .toBe("Elo DEN +4.0 · ratings not used until both teams have played · ATL on a back-to-back");
  });
});

describe("finalResult", () => {
  it("grades the pregame line against the final score", () => {
    const g = game({ status: "final", score: { home_pts: 110, away_pts: 100 } });
    expect(finalResult(g)).toEqual({
      moneyline: "DEN won", pickHit: true,
      spread: "DEN by 10 · line DEN −5.9", total: "210 · Under 222.5",
    });
  });

  it("marks a missed pick and an over", () => {
    const g = game({ status: "final", score: { home_pts: 115, away_pts: 120 } });
    const result = finalResult(g);
    expect(result?.moneyline).toBe("ATL won");
    expect(result?.pickHit).toBe(false);
    expect(result?.total).toBe("235 · Over 222.5");
  });

  it("needs a final score and a pregame line", () => {
    expect(finalResult(game())).toBeNull();
    expect(finalResult(game({ status: "final", score: { home_pts: 1, away_pts: 0 }, pregame: null })))
      .toBeNull();
  });
});
