import type { DriftCheck, DriftMetric, Performance } from "./types";

export const DRIFT_METRICS: Record<DriftMetric, string> = {
  log_loss: "Log loss",
  margin_mae: "Margin MAE",
  total_mae: "Total MAE",
};

export interface DriftRow extends DriftCheck {
  scope: string;
  metric: DriftMetric;
  label: string;
  n: number;
}

export function driftRows(drift: Performance["drift"]): DriftRow[] {
  if (!drift) return [];
  return Object.entries(drift.scopes).flatMap(([scope, s]) =>
    s == null ? [] : (Object.keys(DRIFT_METRICS) as DriftMetric[]).flatMap((metric) => {
      const c = s[metric];
      return c == null ? [] : [{ ...c, scope, metric, label: DRIFT_METRICS[metric], n: s.n }];
    }));
}

export type DriftState = "drift" | "ok" | "none" | "unavailable";

export function driftSummary(drift: Performance["drift"]): { state: DriftState; metrics: string[] } {
  if (!drift) return { state: "unavailable", metrics: [] };
  const rows = driftRows(drift);
  if (rows.length === 0) return { state: "none", metrics: [] };
  const metrics = rows.filter((r) => r.drift).map((r) => `${r.scope} ${r.label.toLowerCase()}`);
  return { state: metrics.length ? "drift" : "ok", metrics };
}
