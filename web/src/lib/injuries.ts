import { pct, teamLabel } from "./format";
import type { InjuredPlayer, InjuryEntry, InjuryGame, InjuryImpact } from "./types";

export interface EntryGroup {
  team_id: number;
  label: string;
  entries: InjuryEntry[];
}

export function groupEntries(game: InjuryGame): EntryGroup[] {
  // Away first, then home, then any other team the report names
  const labels = new Map([
    [game.away.team_id, teamLabel(game.away)],
    [game.home.team_id, teamLabel(game.home)],
  ]);
  const order = [game.away.team_id, game.home.team_id];
  const groups = new Map<number, InjuryEntry[]>();
  for (const e of game.entries) {
    if (!groups.has(e.team_id)) groups.set(e.team_id, []);
    groups.get(e.team_id)!.push(e);
  }
  const rank = (id: number) => (order.includes(id) ? order.indexOf(id) : order.length);
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b))
    .map(([team_id, entries]) => ({
      team_id, label: labels.get(team_id) ?? teamLabel({ team_id, abbreviation: null, name: null }), entries,
    }));
}

export function impactText(impact: InjuryImpact | null): string {
  if (impact == null || impact.lost_share == null) return "no report";
  return `${pct(impact.lost_share)} of full strength lost`;
}

export function playerName(p: InjuredPlayer): string {
  return p.name ?? `Player ${p.player_id}`;
}

export function parseDate(raw: string | null): string | null {
  if (!raw || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
  const d = new Date(`${raw}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === raw ? raw : null;
}
