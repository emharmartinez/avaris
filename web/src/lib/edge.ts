import { normalCdf } from "./distribution";
import { signed } from "./format";

// Edge calculator (ADR-020): odds the user types in, compared with the model in the browser.
// Nothing here is stored or fetched. Odds are carried as decimal prices.

export type OddsFormat = "american" | "decimal";
export const DEFAULT_ODDS_FORMAT: OddsFormat = "decimal"; // Edge and Traditional open on it

const MINUS = "−";

function toNumber(raw: string): number | null {
  const text = raw.trim().replaceAll(MINUS, "-");
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(text)) return null;
  return Number(text);
}

export function parseOdds(raw: string, format: OddsFormat): number | null {
  const x = toNumber(raw);
  if (x == null) return null;
  if (format === "decimal") return x > 1 ? x : null;
  if (Math.abs(x) < 100) return null;
  return x > 0 ? 1 + x / 100 : 1 + 100 / -x;
}

export function formatOdds(decimal: number, format: OddsFormat): string {
  if (format === "decimal") return decimal.toFixed(2);
  return decimal >= 2
    ? `+${Math.round((decimal - 1) * 100)}`
    : `${MINUS}${Math.round(100 / (decimal - 1))}`;
}

export function parseLine(raw: string): number | null {
  if (/^\s*(pk|pick|pick'?em)\s*$/i.test(raw)) return 0;
  return toNumber(raw);
}

export function formatLine(x: number): string {
  return x === 0 ? "pk" : signed(x, Number.isInteger(x) ? 0 : 1);
}

export function formatTotal(x: number): string {
  return Number.isInteger(x) ? x.toString() : x.toFixed(1);
}

export function parseTotal(raw: string): number | null {
  const x = toNumber(raw);
  return x != null && x > 0 ? x : null;
}

export interface Outcome {
  win: number;
  push: number;
  lose: number;
}

interface Normal {
  mu: number;
  sigma: number;
}

export function lineOutcomes(x: Normal, line: number, side: "over" | "under"): Outcome {
  // Scores are integers, so N(mu, sigma) is read in unit bands: over a line wins above
  // floor(line) + 0.5 and loses below ceil(line) - 0.5; a whole-number line pushes between
  const above = 1 - normalCdf(Math.floor(line) + 0.5, x.mu, x.sigma);
  const below = normalCdf(Math.ceil(line) - 0.5, x.mu, x.sigma);
  const push = Math.max(0, 1 - above - below);
  return side === "over" ? { win: above, push, lose: below } : { win: below, push, lose: above };
}

// Each market lists its two sides as [away, home] or [over, under]
export type Pair<T> = [T, T];

export function moneylineMarket(pHomeWin: number): Pair<Outcome> {
  return [
    { win: 1 - pHomeWin, push: 0, lose: pHomeWin },
    { win: pHomeWin, push: 0, lose: 1 - pHomeWin },
  ];
}

export function spreadMarket(margin: Normal, homeLine: number): Pair<Outcome> {
  // margin = home - away; home covers homeLine when margin + homeLine > 0. An NBA game cannot
  // end tied, so the margin = 0 band is dropped from whichever outcome holds it and the rest
  // rescaled: -0.5, pk and +0.5 are then the same bet, and a pick'em never pushes
  const raw = lineOutcomes(margin, -homeLine, "over");
  const tie = normalCdf(0.5, margin.mu, margin.sigma) - normalCdf(-0.5, margin.mu, margin.sigma);
  const held: keyof Outcome = homeLine > 0 ? "win" : homeLine < 0 ? "lose" : "push";
  const scale = 1 - tie;
  const home = {
    win: (raw.win - (held === "win" ? tie : 0)) / scale,
    push: Math.max(0, raw.push - (held === "push" ? tie : 0)) / scale,
    lose: (raw.lose - (held === "lose" ? tie : 0)) / scale,
  };
  return [{ win: home.lose, push: home.push, lose: home.win }, home];
}

export function totalMarket(total: Normal, line: number): Pair<Outcome> {
  return [lineOutcomes(total, line, "over"), lineOutcomes(total, line, "under")];
}

export interface Side {
  outcome: Outcome;
  odds: number | null; // decimal
}

export interface SideResult {
  model: number; // P(win | no push), comparable with the implied probability
  push: number;
  implied: number | null; // vig removed when both prices are in, else the raw 1 / odds
  edge: number | null; // model - implied
  ev: number | null; // per 1 unit staked; a push returns the stake
  fairOdds: number | null; // decimal price at the model probability
}

export interface MarketResult {
  sides: Pair<SideResult>;
  devigged: boolean;
  vig: number | null; // overround: sum of the raw implied probabilities - 1
}

export function evaluateMarket(sides: Pair<Side>): MarketResult {
  const raw = sides.map((s) => (s.odds == null ? null : 1 / s.odds));
  const devigged = raw[0] != null && raw[1] != null;
  const book = devigged ? raw[0]! + raw[1]! : null;
  const results = sides.map(({ outcome, odds }, i): SideResult => {
    const decided = outcome.win + outcome.lose;
    const model = decided > 0 ? outcome.win / decided : 0;
    const implied = raw[i] == null ? null : book != null ? raw[i]! / book : raw[i];
    return {
      model,
      push: outcome.push,
      implied,
      edge: implied == null ? null : model - implied,
      ev: odds == null ? null : outcome.win * (odds - 1) - outcome.lose,
      // A certain model has no finite price on one side and a meaningless one on the other
      fairOdds: model > 1e-9 && model < 1 - 1e-9 ? 1 / model : null,
    };
  });
  return { sides: [results[0], results[1]], devigged, vig: book == null ? null : book - 1 };
}
