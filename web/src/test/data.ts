import type { Game, Health, Job, Rest } from "@/lib/types";

// API payloads for component tests, shaped like the fixture league's responses
export const NOW = "2021-11-27T17:00:00Z";

export const health = (job: Job | null = null): Health => ({
  status: "ok", schema_version: 7, now: NOW, today: "2021-11-27", job,
});

export const job = (status: Job["status"], extra: Partial<Job> = {}): Job => ({
  job_id: "j1", kind: "daily", status, params: {}, created_at: NOW, finished_at: null,
  message: null, log: [], ...extra,
});

export const game = (extra: Partial<Game> = {}): Game => ({
  game_id: "0022100047",
  season: "2021-22",
  season_type: "regular",
  game_date_et: "2021-11-27",
  tip_off_utc: "2021-11-28T00:00:00Z",
  game_status: "scheduled",
  neutral_site: false,
  venue: "Ball Arena",
  home: { team_id: 1610612743, abbreviation: "DEN", name: "Denver Nuggets" },
  away: { team_id: 1610612737, abbreviation: "ATL", name: "Atlanta Hawks" },
  result: null,
  prediction: {
    status: "provisional",
    decision_ts: "2021-11-27T16:00:00Z",
    report_ts: "2021-11-27T16:00:00Z",
    predicted_at: NOW,
    runs: { home_win: "r1", margin: "r1", total: "r1" },
    p_home_win: 0.8367,
    margin: { mu: 9.41, sigma: 14.85, lo: -9.62, hi: 28.44 },
    total: { mu: 223.68, sigma: 19.18, lo: 199.1, hi: 248.26 },
    top_drivers: {
      home_win: [{ family: "form", value: 1.81 }, { family: "elo", value: -0.53 },
        { family: "availability", value: -0.48 }],
      margin: [{ family: "form", value: 3.08 }],
      total: [{ family: "league", value: -4.7 }],
    },
    driver_scale: { home_win: "log_odds", margin: "points", total: "points" },
    injury_impact: {
      home: { full_strength: 100.5, lost: 0, lost_share: 0 },
      away: { full_strength: 88.1, lost: 12.3, lost_share: 0.1397 },
    },
    rest: null,
  },
  ...extra,
});

// NYK resting its starters at TOR on 2026-10-13: ESPN listed them Day-To-Day, the rest only
// in the note; one listed player matched no roster entry
export const rest = (extra: Partial<Rest> = {}): Rest => ({
  adjusted: true,
  note: null,
  snapshot_ts: "2026-10-13T20:05:00Z",
  k: { margin: 0.25, total: 0.2, win: 0.03 },
  home: { lost: 0, players: [] },
  away: {
    lost: 29.4,
    players: [
      { name: "Jalen Brunson", player_id: 1628973, status: "Day-To-Day", value: 12.1, matched: true,
        comment: "Brunson won't play Tuesday against Toronto for rest purposes." },
      { name: "Karl-Anthony Towns", player_id: 1626157, status: "Day-To-Day", value: 9.8, matched: true,
        comment: "Towns won't play Tuesday against Toronto for rest purposes." },
      { name: "OG Anunoby", player_id: 1628384, status: "Day-To-Day", value: 7.5, matched: true,
        comment: "Anunoby won't play Tuesday against Toronto for rest purposes." },
      { name: "Kevin McCullar Jr.", player_id: null, status: "Out", value: 0, matched: false,
        comment: null },
    ],
  },
  raw_p_home_win: 0.379,
  raw_margin_mu: -3.4,
  raw_total_mu: 221.0,
  ...extra,
});

// A season opener (ADR-025): the report is in force but cannot be valued before the team's
// first game, so ESPN's list is shown beside it, never applied
export const FALLBACK = "before a team's first game: ESPN's list shown; model values unchanged";

export const fallbackRest = (extra: Partial<Rest> = {}): Rest => rest({
  adjusted: false, note: FALLBACK, k: { margin: 0, total: 0, win: 0 }, win_from_margin: false,
  raw_p_home_win: null, raw_margin_mu: null, raw_total_mu: null, ...extra,
});

export const openerGame = (r: Rest | null = fallbackRest()): Game => {
  const base = preseasonGame(null);
  return {
    ...base,
    game_id: "0022600005",
    season_type: "regular",
    game_date_et: "2026-10-21",
    tip_off_utc: "2026-10-21T23:30:00Z",
    prediction: {
      ...game().prediction!,
      decision_ts: "2026-10-21T22:30:00Z",
      report_ts: "2026-10-21T22:30:00Z",
      injury_impact: { home: null, away: null },
      rest: r,
    },
  };
};

export const preseasonGame = (r: Rest | null = rest()): Game => {
  const base = game();
  return {
    ...base,
    game_id: "0012600012",
    season: "2026-27",
    season_type: "preseason",
    game_date_et: "2026-10-13",
    tip_off_utc: "2026-10-13T23:30:00Z",
    venue: "Scotiabank Arena",
    home: { team_id: 1610612761, abbreviation: "TOR", name: "Toronto Raptors" },
    away: { team_id: 1610612752, abbreviation: "NYK", name: "New York Knicks" },
    prediction: {
      ...base.prediction!,
      decision_ts: "2026-10-13T22:30:00Z",
      report_ts: null,
      predicted_at: "2026-10-13T20:10:00Z",
      // The headline values are the adjusted ones when the rest block says so
      p_home_win: r?.adjusted ? 0.612 : 0.379,
      margin: r?.adjusted
        ? { mu: 3.9, sigma: 15.2, lo: -15.58, hi: 23.38 }
        : { mu: -3.4, sigma: 15.2, lo: -22.88, hi: 16.08 },
      total: r?.adjusted
        ? { mu: 214.6, sigma: 20.1, lo: 188.84, hi: 240.36 }
        : { mu: 221.0, sigma: 20.1, lo: 195.24, hi: 246.76 },
      // ADR-023: the preseason win probability is read off the margin, so are its drivers
      top_drivers: { ...base.prediction!.top_drivers, home_win: base.prediction!.top_drivers.margin },
      driver_scale: { home_win: "points", margin: "points", total: "points" },
      injury_impact: { home: null, away: null },
      rest: r,
    },
  };
};
