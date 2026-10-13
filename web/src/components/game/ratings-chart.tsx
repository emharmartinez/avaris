"use client";

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig,
} from "@/components/ui/chart";
import { teamLabel } from "@/lib/format";
import { mergeRatings } from "@/lib/game";
import type { GameDetail } from "@/lib/types";

const shortDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const tickDate = (ts: string) => shortDate.format(new Date(ts));

// Elo and net rating of both teams up to this game, as of each rating snapshot
export function RatingsChart({ game }: { game: GameDetail }) {
  const data = mergeRatings(game.ratings.home, game.ratings.away);
  const home = teamLabel(game.home);
  const away = teamLabel(game.away);
  const config = {
    homeElo: { label: `${home} Elo`, color: "var(--chart-5)" },
    awayElo: { label: `${away} Elo`, color: "var(--chart-2)" },
    homeNet: { label: `${home} net`, color: "var(--chart-5)" },
    awayNet: { label: `${away} net`, color: "var(--chart-2)" },
  } satisfies ChartConfig;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ratings trend</CardTitle>
        <CardDescription>{`${home} solid, ${away} dashed`}</CardDescription>
      </CardHeader>
      <CardContent>
        {data.length < 2 ? (
          <p className="text-sm text-muted-foreground">Not enough ratings history yet</p>
        ) : (
          <div className="grid gap-6 lg:grid-cols-2">
            {([["Elo", "homeElo", "awayElo"], ["Net rating", "homeNet", "awayNet"]] as const).map(
              ([title, h, a]) => (
                <div key={title}>
                  <h3 className="mb-2 text-xs font-medium text-muted-foreground">{title}</h3>
                  <ChartContainer config={config} className="aspect-[2/1] w-full">
                    <LineChart data={data} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
                      <CartesianGrid vertical={false} />
                      <XAxis dataKey="ts" tickFormatter={tickDate} tickLine={false} minTickGap={24} />
                      <YAxis domain={["auto", "auto"]} width={40} tickLine={false}
                        tickFormatter={(v: number) => Math.round(v).toString()} />
                      <ChartTooltip content={<ChartTooltipContent
                        labelFormatter={(_, payload) => tickDate(String(payload?.[0]?.payload?.ts ?? ""))} />} />
                      <Line dataKey={h} stroke={`var(--color-${h})`} strokeWidth={2} dot={false}
                        connectNulls isAnimationActive={false} />
                      <Line dataKey={a} stroke={`var(--color-${a})`} strokeWidth={2} dot={false}
                        strokeDasharray="5 4" connectNulls isAnimationActive={false} />
                    </LineChart>
                  </ChartContainer>
                </div>
              ),
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
