import type {
  Backtest, BacktestSummary, GameDetail, GamesOnDate, Health, InjuriesOnDate, Job, JobKind,
  Performance, TeamHistory, TeamRatings,
} from "./types";

// Empty in production (same origin as the API); `next dev` sets http://localhost:8000
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

// A request that never reached the server (fetch rejects with a TypeError)
export const SERVER_DOWN =
  "Server not running. Open Avaris from the Avaris Launcher, or run `uv run avaris serve`.";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

interface ValidationError {
  loc?: unknown[];
  msg?: string;
}

function errorDetail(detail: unknown): string | null {
  // A string, or FastAPI's validation list: "date: Input should be a valid date"
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return null;
  return (detail as ValidationError[])
    .map((d) => [d.loc?.at(-1), d.msg].filter((part) => part != null).join(": "))
    .join("; ") || null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), init);
  } catch (e) {
    throw e instanceof TypeError ? new ApiError(0, SERVER_DOWN) : e;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new ApiError(response.status, errorDetail(body?.detail) || response.statusText
      || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

const q = encodeURIComponent;

export const api = {
  health: () => request<Health>("/api/health"),
  today: () => request<GamesOnDate>("/api/predictions/today"),
  predictions: (date: string) => request<GamesOnDate>(`/api/predictions?date=${q(date)}`),
  game: (id: string) => request<GameDetail>(`/api/games/${q(id)}`),
  teams: () => request<TeamRatings[]>("/api/teams"),
  team: (id: number, season?: string) =>
    request<TeamHistory>(`/api/teams/${id}${season ? `?season=${q(season)}` : ""}`),
  performance: (season?: string) =>
    request<Performance>(`/api/performance${season ? `?season=${q(season)}` : ""}`),
  backtests: () => request<BacktestSummary[]>("/api/backtests"),
  backtest: (name: string) => request<Backtest>(`/api/backtests/${q(name)}`),
  chartUrl: (name: string, chart: string) => apiUrl(`/api/backtests/${q(name)}/charts/${q(chart)}`),
  injuries: (date: string) => request<InjuriesOnDate>(`/api/injuries?date=${q(date)}`),
  job: (id: string) => request<Job>(`/api/jobs/${q(id)}`),
  submitJob: (kind: JobKind, params: Record<string, unknown> = {}) =>
    request<Job>(`/api/jobs/${kind}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(params),
    }),
};

export function isBusy(err: unknown): boolean {
  // 409: another job holds the single-job lock
  return err instanceof ApiError && err.status === 409;
}
