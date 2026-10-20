// Shapes of the local API (src/avaris/api). Timestamps are UTC ISO strings ending in Z;
// dates (game_date_et, today) are plain YYYY-MM-DD in Eastern Time

export type Target = "home_win" | "margin" | "total";
export type SeasonType = "preseason" | "regular" | "cup_final" | "play_in" | "playoffs";
export type PredictionStatus = "provisional" | "final";
export type JobKind = "daily" | "score" | "train";
export type JobStatus = "running" | "succeeded" | "failed";

export interface Team {
  team_id: number;
  abbreviation: string | null; // null for non-NBA preseason opponents
  name: string | null;
}

export interface Interval {
  mu: number;
  sigma: number;
  lo: number; // 80% interval
  hi: number;
}

export interface Driver {
  family: string;
  value: number;
}

export interface DriverSet {
  base: number;
  families: Record<string, number>;
  scale: "log_odds" | "points";
  top: Driver[];
}

export interface InjuryImpact {
  full_strength: number;
  lost: number | null;
  lost_share: number | null;
}

export interface InjuredPlayer {
  player_id: number;
  name: string | null;
  status: string | null;
  value: number;
  lost: number;
}

export interface InjuryImpactFull extends InjuryImpact {
  players: InjuredPlayer[];
}

// Preseason only (ADR-022): players ESPN lists as out or resting, valued in Game Score points
export interface RestPlayer {
  name: string;
  player_id: number | null; // null when the ESPN name matched no roster player
  status: string;
  comment: string | null; // ESPN's note, untrusted plain text
  value: number;
  matched: boolean;
}

export interface RestSide {
  lost: number | null; // null: no ESPN snapshot, so unknown
  players: RestPlayer[];
}

export interface Rest {
  adjusted: boolean; // true: p_home_win, margin.mu and total.mu are the rest-adjusted values
  note: string | null; // why not adjusted; null when adjusted
  snapshot_ts: string | null;
  k: { margin: number; total: number; win: number }; // applied coefficients, 0 = off; win retired (ADR-023)
  win_from_margin?: boolean; // the win was read off the adjusted margin (ADR-023); absent before it
  home: RestSide;
  away: RestSide;
  // The model's own values; null outside preseason, where the list is never applied (ADR-025)
  raw_p_home_win: number | null;
  raw_margin_mu: number | null;
  raw_total_mu: number | null;
}

// A rest block whose values moved: the model's raw ones are always there
export type AdjustedRest = Rest & { raw_p_home_win: number; raw_margin_mu: number; raw_total_mu: number };

export interface Prediction {
  status: PredictionStatus;
  decision_ts: string | null;
  report_ts: string | null;
  predicted_at: string;
  runs: Record<Target, string>;
  p_home_win: number;
  margin: Interval;
  total: Interval;
  top_drivers: Record<Target, Driver[]>;
  // home_win is "points" in preseason (ADR-023); absent from a server older than that
  driver_scale?: Record<Target, DriverSet["scale"]>;
  injury_impact: { home: InjuryImpact | null; away: InjuryImpact | null };
  // ESPN's list: preseason (ADR-022) and before a team's first game of the season (ADR-025);
  // null for every other game and vs non-NBA clubs
  rest: Rest | null;
}

export interface PredictionFull extends Prediction {
  drivers: Record<Target, DriverSet>;
  injuries: { home: InjuryImpactFull | null; away: InjuryImpactFull | null };
}

export interface Game {
  game_id: string;
  season: string;
  season_type: SeasonType;
  game_date_et: string;
  tip_off_utc: string | null;
  game_status: string;
  neutral_site: boolean;
  venue: string | null;
  home: Team;
  away: Team;
  result: { home_pts: number; away_pts: number } | null;
  prediction: Prediction | null;
}

export interface GamesOnDate {
  date: string;
  games: Game[];
}

// The rule-based model (ADR-024): pregame lines, and live lines while a game is on
export type GameStatus = "scheduled" | "in_progress" | "final";

export interface TraditionalLine {
  p_home_win: number;
  margin: Interval;
  total: Interval;
}

export interface TraditionalInputs {
  elo_margin: number;
  eff_margin: number | null;
  eff_total: number | null;
  league_total: number;
  weight: number; // share of the margin from the efficiency ratings
  home_gp: number;
  away_gp: number;
  home_b2b: number;
  away_b2b: number;
  injury: number; // home margin points from absences beyond each team's usual
  injury_source: "report" | "espn" | null; // NBA injury report, else ESPN's list (preseason, season openers)
  home_lost: number | null; // Game Score lost beyond the usual
  away_lost: number | null;
}

export interface TraditionalLive extends TraditionalLine {
  period: number;
  clock: string | null; // M:SS left in the period
  label: string; // the scoreboard's status, e.g. "2nd Qtr", "Halftime"
  minutes_left: number;
}

export interface TraditionalGame {
  game_id: string;
  season_type: SeasonType;
  tip_off_utc: string | null;
  home: Team;
  away: Team;
  status: GameStatus;
  score: { home_pts: number; away_pts: number } | null;
  pregame: (TraditionalLine & { inputs: TraditionalInputs }) | null;
  live: TraditionalLive | null;
}

export interface TraditionalDay {
  date: string;
  is_today: boolean;
  live_at: string | null;
  live_error: string | null;
  games: TraditionalGame[];
}

export interface InjuryEntry {
  team_id: number;
  player_id: number | null;
  player_name: string;
  status: string;
  reason: string | null;
}

export interface Ratings {
  game_id: string;
  as_of_ts: string;
  elo: number;
  ortg: number | null;
  drtg: number | null;
  net: number | null;
  pace: number | null;
  net_l10: number | null;
  gp: number;
}

export interface GameScore {
  log_loss: number;
  brier: number;
  correct: boolean;
  margin_error: number;
  margin_in_80: boolean;
  total_error: number;
  total_in_80: boolean;
  [key: string]: unknown;
}

export interface GameDetail extends Omit<Game, "prediction"> {
  prediction: PredictionFull | null;
  injury_report: InjuryEntry[];
  ratings: { home: Ratings[]; away: Ratings[] };
  score: GameScore | null;
}

export interface TeamRatings extends Team, Ratings {
  season: string;
}

export interface TeamHistory {
  team: Team;
  season: string;
  ratings: Ratings[];
}

export type Scope = "regular" | "preseason" | "postseason" | "all";

export interface ScopeMetrics {
  n: number;
  log_loss: number | null;
  brier: number | null;
  accuracy: number | null;
  margin_mae: number | null;
  margin_rmse: number | null;
  margin_coverage_80: number | null;
  total_mae: number | null;
  total_rmse: number | null;
  total_coverage_80: number | null;
}

export type DriftMetric = "log_loss" | "margin_mae" | "total_mae";

export interface DriftCheck {
  live: number;
  lo: number; // 95% range of n-game means in the reference backtest
  hi: number;
  drift: boolean;
}

export type DriftScope = { n: number } & Record<DriftMetric, DriftCheck | null>;

export interface Performance {
  season: string;
  scopes: Record<Scope, ScopeMetrics>;
  seasons: string[];
  drift: {
    reference: string;
    scopes: Record<Exclude<Scope, "all">, DriftScope | null>;
  } | null;
}

export interface BacktestSummary {
  name: string;
  title: string;
}

export interface Backtest extends BacktestSummary {
  markdown: string;
  charts: string[];
}

// The rest block without the model's raw values, as /api/injuries returns it
export type RestList = Omit<Rest, "raw_p_home_win" | "raw_margin_mu" | "raw_total_mu">;

export interface InjuryGame {
  game_id: string;
  season_type: SeasonType;
  home: Team;
  away: Team;
  report_ts: string | null;
  // ESPN's out list: preseason (no NBA report exists) and season openers (ADR-025)
  rest: RestList | null;
  impact: { home: InjuryImpactFull | null; away: InjuryImpactFull | null };
  entries: InjuryEntry[];
}

export interface InjuriesOnDate {
  date: string;
  games: InjuryGame[];
}

export interface Job {
  job_id: string;
  kind: JobKind;
  status: JobStatus;
  params: Record<string, unknown>;
  created_at: string;
  finished_at: string | null;
  message: string | null;
  log: string[];
}

export interface Health {
  status: "ok";
  schema_version: number | null;
  now: string;
  today: string;
  job: Job | null;
}
