import { formatLine, formatTotal } from "./edge";
import { teamLabel } from "./format";
import type { BetMarket, BetSide, Team } from "./types";

// Bet tracking (ADR-026): the bankroll, its unit and the bets recorded from the Edge tab.
// Grading and the bankroll itself come from the API; this sizes and labels them

const DASH = "–";
const MINUS = "−";
const MONEY = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function toNumber(raw: string, strip: RegExp): number | null {
  const text = raw.trim().replace(strip, "");
  if (!/^(\d+\.?\d*|\.\d+)$/.test(text)) return null;
  return Number(text);
}

export function parseMoney(raw: string): number | null {
  const x = toNumber(raw, /[$,]/g);
  return x != null && x > 0 ? x : null;
}

export function parsePct(raw: string): number | null {
  const x = toNumber(raw, /%$/);
  return x != null && x > 0 && x <= 100 ? x : null;
}

export function formatMoney(x: number | null | undefined): string {
  return x == null ? DASH : MONEY.format(x);
}

export function signedMoney(x: number): string {
  const text = MONEY.format(Math.abs(x));
  if (Number(text.replaceAll(",", "")) === 0) return text;
  return x > 0 ? `+${text}` : `${MINUS}${text}`;
}

// The stake a new bet starts at: one unit, as typed into the stake input
export function defaultStake(unit: number | null): string {
  return unit != null && unit > 0 ? unit.toFixed(2) : "";
}

export function units(stake: number, unit: number | null): number | null {
  return unit != null && unit > 0 ? stake / unit : null;
}

export function toWin(stake: number, odds: number): number {
  return stake * (odds - 1);
}

export function betLabel(
  bet: { market: BetMarket; side: BetSide; line: number | null },
  game: { home: Team; away: Team },
): string {
  if (bet.market === "total") {
    return `${bet.side === "over" ? "Over" : "Under"} ${formatTotal(bet.line ?? 0)}`;
  }
  const team = teamLabel(bet.side === "home" ? game.home : game.away);
  return bet.market === "moneyline" ? `${team} ML` : `${team} ${formatLine(bet.line ?? 0)}`;
}
