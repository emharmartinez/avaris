"use client";

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { axisTick } from "@/lib/format";
import type { HistoryPoint } from "@/lib/teams";

const eloConfig = { elo: { label: "Elo", color: "var(--chart-2)" } } satisfies ChartConfig;
const netPaceConfig = {
  net: { label: "Net rating", color: "var(--chart-2)" },
  pace: { label: "Pace", color: "var(--chart-4)" },
} satisfies ChartConfig;

export function EloChart({ points }: { points: HistoryPoint[] }) {
  return (
    <ChartContainer config={eloConfig} className="aspect-auto h-56 w-full">
      <LineChart data={points} margin={{ left: 4, right: 12, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={24} />
        <YAxis domain={["auto", "auto"]} tickLine={false} axisLine={false} width={44}
          tickFormatter={axisTick} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <Line dataKey="elo" type="monotone" stroke="var(--color-elo)" strokeWidth={2} dot={false} />
      </LineChart>
    </ChartContainer>
  );
}

// Net rating (left axis) and pace (right axis) sit on different scales
export function NetPaceChart({ points }: { points: HistoryPoint[] }) {
  return (
    <ChartContainer config={netPaceConfig} className="aspect-auto h-56 w-full">
      <LineChart data={points} margin={{ left: 4, right: 4, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={24} />
        <YAxis yAxisId="net" domain={["auto", "auto"]} tickLine={false} axisLine={false} width={36}
          tickFormatter={axisTick} />
        <YAxis yAxisId="pace" orientation="right" domain={["auto", "auto"]} tickLine={false}
          axisLine={false} width={36} tickFormatter={axisTick} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <Line yAxisId="net" dataKey="net" type="monotone" stroke="var(--color-net)" strokeWidth={2}
          dot={false} connectNulls />
        <Line yAxisId="pace" dataKey="pace" type="monotone" stroke="var(--color-pace)" strokeWidth={2}
          dot={false} connectNulls />
      </LineChart>
    </ChartContainer>
  );
}
