import type { Game, Health, Job } from "@/lib/types";

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
    injury_impact: {
      home: { full_strength: 100.5, lost: 0, lost_share: 0 },
      away: { full_strength: 88.1, lost: 12.3, lost_share: 0.1397 },
    },
  },
  ...extra,
});
