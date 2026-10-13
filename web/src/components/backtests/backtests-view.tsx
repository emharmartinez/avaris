"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { Markdown } from "@/components/markdown";
import { PageHeader, QueryState } from "@/components/query-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBacktest, useBacktests } from "@/hooks/use-api";
import { api } from "@/lib/api";
import type { Backtest, BacktestSummary } from "@/lib/types";

export function BacktestsView({ name }: { name: string | null }) {
  return name ? <BacktestDetail name={name} /> : <BacktestList />;
}

function BacktestList() {
  const query = useBacktests();
  return (
    <div className="space-y-6">
      <PageHeader title="Backtests" description="Walk-forward evaluation reports" />
      <QueryState query={query} label="backtests">
        {(list) => <ReportList reports={list} />}
      </QueryState>
    </div>
  );
}

function ReportList({ reports }: { reports: BacktestSummary[] }) {
  if (reports.length === 0) {
    return <p className="text-sm text-muted-foreground">No backtest reports yet.</p>;
  }
  return (
    <Card>
      <CardContent>
        <ul className="divide-y">
          {reports.map((r) => (
            <li key={r.name} className="py-3 first:pt-0 last:pb-0">
              <Link href={`/backtests/?name=${encodeURIComponent(r.name)}`} className="font-medium hover:underline">
                {r.title}
              </Link>
              <p className="font-mono text-xs text-muted-foreground">{r.name}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function BacktestDetail({ name }: { name: string }) {
  const query = useBacktest(name);
  return (
    <div className="space-y-6">
      <Link href="/backtests/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" /> All reports
      </Link>
      <QueryState query={query} label="backtest">
        {(report) => <Report report={report} />}
      </QueryState>
    </div>
  );
}

function Report({ report }: { report: Backtest }) {
  return (
    <div className="space-y-6">
      <p className="font-mono text-xs text-muted-foreground">{report.name}</p>
      <Card>
        <CardContent>
          <article><Markdown>{report.markdown}</Markdown></article>
        </CardContent>
      </Card>
      {report.charts.length > 0 && (
        <section aria-labelledby="charts-title" className="space-y-3">
          <h2 id="charts-title" className="text-lg font-semibold">Charts</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            {report.charts.map((chart) => (
              <Card key={chart}>
                <CardHeader><CardTitle className="font-mono text-xs">{chart}</CardTitle></CardHeader>
                <CardContent>
                  {/* Served as SVG with a default-src 'none' CSP; <img> never runs script */}
                  {/* eslint-disable-next-line @next/next/no-img-element -- static export, no image optimizer */}
                  <img src={api.chartUrl(report.name, chart)} alt={chart} loading="lazy" className="h-auto w-full" />
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
