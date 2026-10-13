"use client";

import { Area, AreaChart, CartesianGrid, ReferenceLine, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import { normalCurve } from "@/lib/distribution";
import { formatInterval, signed } from "@/lib/format";
import type { Interval } from "@/lib/types";

const config = {
  density: { label: "Density", color: "var(--chart-3)" },
  band: { label: "80% interval", color: "var(--chart-2)" },
} satisfies ChartConfig;

// N(mu, sigma) with the 80% interval shaded; margins are signed, totals are not
export function DistributionChart({ title, interval, signedScale, actual, zeroLine = false }: {
  title: string;
  interval: Interval;
  signedScale: boolean;
  actual: number | null;
  zeroLine?: boolean;
}) {
  const f = (x: number) => (signedScale ? signed(x) : x.toFixed(1));
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription className="tabular-nums">
          <span className="block">
            {`μ ${f(interval.mu)} · σ ${interval.sigma.toFixed(1)} · 80% ${formatInterval(interval, signedScale)}`}
          </span>
          {actual != null && <span className="block font-medium text-foreground">{`Actual ${f(actual)}`}</span>}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="aspect-[2/1] w-full">
          <AreaChart data={normalCurve(interval)} margin={{ left: 0, right: 8, top: 24, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]}
              tickFormatter={(x: number) => Math.round(x).toString()} tickLine={false} />
            <YAxis hide />
            <Area dataKey="density" type="monotone" stroke="var(--color-density)" fill="none"
              strokeWidth={2} isAnimationActive={false} />
            <Area dataKey="band" type="monotone" stroke="none" fill="var(--color-band)"
              fillOpacity={0.35} isAnimationActive={false} />
            {zeroLine && <ReferenceLine x={0} stroke="var(--muted-foreground)" strokeDasharray="4 4"
              ifOverflow="extendDomain" />}
            {actual != null && <ReferenceLine x={actual} stroke="var(--foreground)" strokeWidth={2}
              ifOverflow="extendDomain" label={{ value: "Actual", position: "top", fontSize: 11 }} />}
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
