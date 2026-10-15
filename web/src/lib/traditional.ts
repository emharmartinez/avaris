import { formatOdds, lineOutcomes, type OddsFormat } from "./edge";
import { pct, signed, teamLabel } from "./format";
import type {
  Team, TraditionalDay, TraditionalGame, TraditionalInputs, TraditionalLive,
} from "./types";

// The rule-based model's lines (ADR-024) as fair prices: the moneyline from the win
// probability, the spread from the margin, the total as is, with the chance of going over or
// under a total line the user types (never fetched or stored). No odds are fetched or stored

const DASH = "–";
const MINUS = "−";
const OFF_BOARD = 0.005; // a game this settled has no meaningful price
const LIVE_POLL_MS = 30_000; // the server refetches the scoreboard at most every 30 s
const TODAY_POLL_MS = 60_000;

export function fairMoneyline(p: number, format: OddsFormat): string {
  if (p < OFF_BOARD || p > 1 - OFF_BOARD) return DASH;
  return formatOdds(1 / p, format);
}

export function spreadText(marginMu: number, home: Team, away: Team): string {
  const points = Math.abs(marginMu).toFixed(1);
  if (Number(points) === 0) return "Pick'em";
  return `${teamLabel(marginMu > 0 ? home : away)} ${MINUS}${points}`;
}

export function totalText(mu: number): string {
  return mu.toFixed(1);
}

export interface OverUnder {
  over: number;
  under: number;
  push: number; // only a whole-number line can push
}

export function overUnder(total: { mu: number; sigma: number }, line: number): OverUnder {
  // Integer bands, as on the Edge tab
  const { win, push, lose } = lineOutcomes(total, line, "over");
  return { over: win, under: lose, push };
}

export function overUnderText(total: { mu: number; sigma: number }, line: number | null): string {
  if (line == null) return DASH;
  const { over, under, push } = overUnder(total, line);
  const text = `Over ${pct(over)} · Under ${pct(under)}`;
  return Number.isInteger(line) ? `${text} · Push ${pct(push)}` : text;
}

export function liveText(live: TraditionalLive): string {
  return live.clock && live.clock !== "0:00" ? `${live.label} · ${live.clock}` : live.label;
}

export function statusText(game: TraditionalGame): string {
  if (game.status === "final") return "Final";
  if (game.status === "in_progress") return game.live ? liveText(game.live) : "Live";
  return "Upcoming";
}

export function pollInterval(data: TraditionalDay | undefined): number | false {
  // Fast while a game is on; slowly on game day so a tip-off shows up; never for other days
  if (!data?.is_today) return false;
  if (data.games.some((g) => g.status === "in_progress")) return LIVE_POLL_MS;
  return data.games.some((g) => g.status === "scheduled") ? TODAY_POLL_MS : false;
}

export function inputsText(inputs: TraditionalInputs, home: Team, away: Team): string {
  // What the pregame margin is made of, as home margins
  const h = teamLabel(home);
  const parts = [`Elo ${h} ${signed(inputs.elo_margin)}`];
  parts.push(inputs.eff_margin == null
    ? "ratings not used until both teams have played"
    : `ratings ${h} ${signed(inputs.eff_margin)} at ${pct(inputs.weight)} weight`);
  if (inputs.home_b2b) parts.push(`${h} on a back-to-back`);
  if (inputs.away_b2b) parts.push(`${teamLabel(away)} on a back-to-back`);
  return parts.join(" · ");
}

export interface FinalResult {
  moneyline: string;
  pickHit: boolean; // the pregame favorite won
  spread: string;
  covered: boolean; // the side the line favored won by more than the line
  total: string;
}

export function finalResult(game: TraditionalGame, totalLine: number | null = null): FinalResult | null {
  // The total is graded against the line typed on the card, else the pregame total
  const { score, pregame, home, away } = game;
  if (game.status !== "final" || score == null || pregame == null) return null;
  const margin = score.home_pts - score.away_pts;
  const winner = teamLabel(margin > 0 ? home : away);
  const total = score.home_pts + score.away_pts;
  const line = totalLine ?? pregame.total.mu;
  const side = total > line ? "Over" : total < line ? "Under" : "Push";
  return {
    moneyline: `${winner} won`,
    pickHit: pregame.p_home_win >= 0.5 === margin > 0,
    spread: `${winner} by ${Math.abs(margin)} · line ${spreadText(pregame.margin.mu, home, away)}`,
    covered: pregame.margin.mu >= 0 ? margin > pregame.margin.mu : margin < pregame.margin.mu,
    total: `${total} · ${side} ${totalText(line)}`,
  };
}
