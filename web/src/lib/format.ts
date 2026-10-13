import type { DriverSet, Interval, SeasonType, Team } from "./types";

const DASH = "–";
const MINUS = "−";
const FINAL_BEFORE_TIP_MS = 60 * 60 * 1000; // predictions turn final at tip-off - 60 min

export function pct(p: number | null | undefined, digits = 0): string {
  return p == null ? DASH : `${(p * 100).toFixed(digits)}%`;
}

export function signed(x: number, digits = 1): string {
  const text = Math.abs(x).toFixed(digits);
  if (Number(text) === 0) return text;
  return x > 0 ? `+${text}` : `${MINUS}${text}`;
}

export function formatInterval(i: Interval, withSign: boolean): string {
  const f = (x: number) => (withSign ? signed(x) : x.toFixed(1));
  return `${f(i.lo)} to ${f(i.hi)}`;
}

export function formatMetric(x: number | null | undefined, digits = 3, percent = false): string {
  if (x == null) return DASH;
  return percent ? pct(x, digits) : x.toFixed(digits);
}

export function teamLabel(team: Team): string {
  return team.abbreviation ?? `Team ${team.team_id}`;
}

export function teamName(team: Team): string {
  return team.name ?? `Team ${team.team_id}`;
}

const SEASON_TYPES: Record<SeasonType, string> = {
  preseason: "Preseason",
  regular: "Regular season",
  cup_final: "Cup final",
  play_in: "Play-in",
  playoffs: "Playoffs",
};

export function seasonTypeLabel(t: SeasonType): string {
  return SEASON_TYPES[t] ?? t;
}

const DRIVERS: Record<string, string> = {
  elo: "Elo",
  form: "Form",
  rest_travel: "Rest & travel",
  availability: "Availability",
  home_court: "Home court",
  game_type: "Game type",
  league: "League",
};

export function driverLabel(family: string): string {
  const label = DRIVERS[family] ?? family.replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function formatDriver(value: number, scale: DriverSet["scale"]): string {
  return scale === "log_odds" ? signed(value, 2) : `${signed(value)} pts`;
}

export function formatTip(iso: string | null, timeZone?: string): string {
  if (!iso) return "TBD";
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone })
    .format(new Date(iso));
}

export function formatDate(day: string): string {
  // A plain ET date: format it as is, without shifting through the local time zone
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}

export function formatTimestamp(iso: string | null, timeZone?: string): string {
  if (!iso) return DASH;
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone,
  }).format(new Date(iso));
}

export function shiftDate(day: string, days: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function countdownToFinal(tip: string | null, now: string): string | null {
  // Time left until the prediction is frozen, on the server's clock; null once passed
  if (!tip) return null;
  const left = new Date(tip).getTime() - FINAL_BEFORE_TIP_MS - new Date(now).getTime();
  if (left <= 0) return null;
  const minutes = Math.ceil(left / 60_000);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `final in ${h}h ${String(m).padStart(2, "0")}m` : `final in ${m}m`;
}
