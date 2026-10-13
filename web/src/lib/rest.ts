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

export function restLostText(side: RestSide): string {
  return side.lost == null ? "No ESPN list (unknown)" : `${side.lost.toFixed(1)} Game Score lost`;
}

// The model's own split, in one string so it never collides with the adjusted percentages
export function rawWinText(rest: Rest, home: string, away: string): string {
  const s = winSplit(rest.raw_p_home_win);
  return `raw ${away} ${s.awayText} · ${home} ${s.homeText}`;
}

export function edgeRestNote(p: Prediction, home: string): string | null {
  const rest = adjustedRest(p);
  return rest
    ? `Preseason: rest-adjusted from ESPN list (raw ${home} ${pct(rest.raw_p_home_win, 1)})`
    : null;
}
