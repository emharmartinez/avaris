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
  raw_p_home_win: number;
  raw_margin_mu: number;
  raw_total_mu: number;
}

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
  driver_scale: Record<Target, DriverSet["scale"]>; // home_win is "points" in preseason (ADR-023)
  injury_impact: { home: InjuryImpact | null; away: InjuryImpact | null };
  rest: Rest | null; // null for every non-preseason game and vs non-NBA clubs
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
  rest: RestList | null;  // preseason only: ESPN's out list (no NBA report exists)
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
