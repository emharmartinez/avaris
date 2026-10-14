import { pct, signed } from "./format";
import { winSplit } from "./today";
import type { Prediction, Rest, RestSide } from "./types";

// Preseason rest adjustment from ESPN's out list (ADR-022)
export const REST_LABEL = "Rest-adjusted (ESPN)";

export function restStatus(rest: Rest): string {
  return rest.adjusted ? REST_LABEL : (rest.note ?? "Not rest-adjusted");
}

// The rest block when the headline values are the adjusted ones, else null
export function adjustedRest(p: Prediction): Rest | null {
  return p.rest?.adjusted ? p.rest : null;
}

export interface RestRow {
  label: string;
  raw: string;
  adjusted: string;
}

export function restComparison(p: Prediction, rest: Rest): RestRow[] {
  return [
    { label: "Home win", raw: pct(rest.raw_p_home_win, 1), adjusted: pct(p.p_home_win, 1) },
    { label: "Margin (home)", raw: signed(rest.raw_margin_mu), adjusted: signed(p.margin.mu) },
    { label: "Total", raw: rest.raw_total_mu.toFixed(1), adjusted: p.total.mu.toFixed(1) },
  ];
}

const NAME_SUFFIXES = new Set(["jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"]);
const OUT_NAMES = 3;

function lastName(name: string): string {
  const parts = name.trim().split(/\s+/);
  while (parts.length > 1 && NAME_SUFFIXES.has(parts[parts.length - 1].toLowerCase())) parts.pop();
  return parts[parts.length - 1];
}

// The card's preseason injuries line: the most valuable players ESPN lists out
export function restOutText(side: RestSide): string {
  if (side.lost == null) return "no ESPN list";
  if (side.players.length === 0) return "none out (ESPN)";
  const sorted = [...side.players].sort((a, b) => b.value - a.value);
  const names = sorted.slice(0, OUT_NAMES).map((p) => lastName(p.name)).join(", ");
  const more = sorted.length > OUT_NAMES ? ` +${sorted.length - OUT_NAMES}` : "";
  return `${names}${more} out (ESPN)`;
}

export function restLostText(side: RestSide): string {
  return side.lost == null ? "No ESPN list (unknown)" : `${side.lost.toFixed(1)} Game Score lost`;
}

// The model's own margin and total, for the outputs whose coefficient is on
function rawPointParts(rest: Rest): string[] {
  return [
    ...(rest.k.margin ? [`margin ${signed(rest.raw_margin_mu)}`] : []),
    ...(rest.k.total ? [`total ${rest.raw_total_mu.toFixed(1)}`] : []),
  ];
}

// The model's own values of the adjusted outputs, in one string so they never collide with
// the adjusted ones; the win split away first, like the WinBar
export function rawText(rest: Rest, home: string, away: string): string {
  const s = winSplit(rest.raw_p_home_win);
  const win = rest.k.win ? [`${away} ${s.awayText} · ${home} ${s.homeText}`] : [];
  return `raw ${[...win, ...rawPointParts(rest)].join(", ")}`;
}

export function edgeRestNote(p: Prediction, home: string): string | null {
  const rest = adjustedRest(p);
  if (!rest) return null;
  const win = rest.k.win ? [`${home} ${pct(rest.raw_p_home_win, 1)}`] : [];
  return `Preseason: rest-adjusted from ESPN list (raw ${[...win, ...rawPointParts(rest)].join(", ")})`;
}
