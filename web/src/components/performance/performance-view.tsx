"use client";

import { PageHeader, QueryState } from "@/components/query-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePerformance } from "@/hooks/use-api";
import { driftRows, driftSummary } from "@/lib/drift";
import {
  formatDriftValue, METRIC_COLUMNS, metricCells, SCOPES, scopeLabel, seasonOptions,
} from "@/lib/performance";
import type { Performance } from "@/lib/types";

export function PerformanceView({ season, onSeasonChange }: {
  season: string | null;
  onSeasonChange: (season: string) => void;
}) {
  const query = usePerformance(season ?? undefined);
  return (
    <QueryState query={query} label="performance">
      {(data) => (
        <div className="space-y-6">
          <PageHeader title="Performance" description="Live predictions scored against final results">
            <Select value={data.season} onValueChange={onSeasonChange}>
              <SelectTrigger aria-label="Season" className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {seasonOptions(data).map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
              </SelectContent>
            </Select>
          </PageHeader>
          <MetricsCard data={data} />
          <DriftCard drift={data.drift} />
        </div>
      )}
    </QueryState>
  );
}

function MetricsCard({ data }: { data: Performance }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Metrics, {data.season}</CardTitle>
        <CardDescription>
          The regular season is the headline; preseason and postseason are reported separately.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table aria-label="Metrics by scope">
          <TableHeader>
            <TableRow>
              <TableHead>Scope</TableHead>
              {METRIC_COLUMNS.map((c) => <TableHead key={c.key} className="text-right">{c.label}</TableHead>)}
            </TableRow>
          </TableHeader>
          <TableBody className="tabular-nums">
            {SCOPES.map(({ scope, label }) => (
              <TableRow key={scope}>
                <TableCell className={scope === "regular" ? "font-medium" : undefined}>{label}</TableCell>
                {metricCells(data.scopes[scope]).map((cell, i) => (
                  <TableCell key={METRIC_COLUMNS[i].key} className="text-right">{cell}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function DriftSummaryBadge({ drift }: { drift: Performance["drift"] }) {
  const { state, metrics } = driftSummary(drift);
  return (
    <div role="status" className="flex flex-wrap items-center gap-2 text-sm">
      {state === "drift" && (
        <>
          <Badge variant="destructive">Drift</Badge>
          <span>{metrics.join(", ")}</span>
        </>
      )}
      {state === "ok" && <Badge variant="secondary">In range</Badge>}
      {state === "none" && <Badge variant="outline">Not enough games</Badge>}
      {state === "unavailable" && <Badge variant="outline">No reference backtest</Badge>}
    </div>
  );
}

function DriftCard({ drift }: { drift: Performance["drift"] }) {
  const rows = driftRows(drift);
  return (
    <section aria-labelledby="drift-title">
      <Card>
        <CardHeader>
          <CardTitle id="drift-title">Drift</CardTitle>
          <CardDescription>
            Drift when a live mean is worse than the range of n-game means resampled from the
            reference backtest (one-sided, about 1 false alarm in 20 per scope)
            {drift && <> (<code className="text-xs">{drift.reference}</code>)</>}.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <DriftSummaryBadge drift={drift} />
          {rows.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Scope</TableHead>
                  <TableHead>Metric</TableHead>
                  <TableHead className="text-right">Games</TableHead>
                  <TableHead className="text-right">Live</TableHead>
                  <TableHead className="text-right">Reference range</TableHead>
                  <TableHead>Flag</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="tabular-nums">
                {rows.map((r) => (
                  <TableRow key={`${r.scope}-${r.metric}`}>
                    <TableCell>{scopeLabel(r.scope)}</TableCell>
                    <TableCell>{r.label}</TableCell>
                    <TableCell className="text-right">{r.n}</TableCell>
                    <TableCell className="text-right">{formatDriftValue(r.metric, r.live)}</TableCell>
                    <TableCell className="text-right">
                      {formatDriftValue(r.metric, r.lo)} – {formatDriftValue(r.metric, r.hi)}
                    </TableCell>
                    <TableCell>
                      {r.drift
                        ? <Badge variant="destructive">Drift</Badge>
                        : <Badge variant="secondary">In range</Badge>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
