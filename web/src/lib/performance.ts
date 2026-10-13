import { formatMetric } from "./format";
import type { DriftMetric, Performance, Scope, ScopeMetrics } from "./types";

export const SCOPES: { scope: Scope; label: string }[] = [
  { scope: "regular", label: "Regular season" }, // headline
  { scope: "preseason", label: "Preseason" },
  { scope: "postseason", label: "Postseason" },
  { scope: "all", label: "All" },
];

export function scopeLabel(scope: string): string {
  return SCOPES.find((s) => s.scope === scope)?.label ?? scope;
}

type MetricKey = Exclude<keyof ScopeMetrics, "n">;

// Column order of the metrics table: digits, and whether the value is a share
export const METRIC_COLUMNS: { key: keyof ScopeMetrics; label: string; digits: number; percent?: boolean }[] = [
  { key: "n", label: "Games", digits: 0 },
  { key: "log_loss", label: "Log loss", digits: 4 },
  { key: "brier", label: "Brier", digits: 4 },
  { key: "accuracy", label: "Accuracy", digits: 0, percent: true },
  { key: "margin_mae", label: "Margin MAE", digits: 2 },
  { key: "margin_rmse", label: "Margin RMSE", digits: 2 },
  { key: "margin_coverage_80", label: "Margin 80% cov.", digits: 0, percent: true },
  { key: "total_mae", label: "Total MAE", digits: 2 },
  { key: "total_rmse", label: "Total RMSE", digits: 2 },
  { key: "total_coverage_80", label: "Total 80% cov.", digits: 0, percent: true },
];

export function metricCells(m: ScopeMetrics): string[] {
  return METRIC_COLUMNS.map(({ key, digits, percent }) => {
    if (key === "n") return String(m.n);
    return formatMetric(m.n === 0 ? null : m[key as MetricKey], digits, percent);
  });
}

export function seasonOptions(p: Pick<Performance, "season" | "seasons">): string[] {
  const all = p.seasons.includes(p.season) ? p.seasons : [...p.seasons, p.season];
  return [...all].sort().reverse();
}

export function formatDriftValue(metric: DriftMetric, x: number): string {
  return formatMetric(x, metric === "log_loss" ? 4 : 2);
}
