"use client";

import { Check, ChevronLeft, ChevronRight, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { SeasonTypeBadge } from "@/components/badges";
import { OddsFormatToggle } from "@/components/odds-format-toggle";
import { PageHeader, QueryState } from "@/components/query-state";
import { gameHref } from "@/components/today/game-card";
import { WinBar } from "@/components/today/win-bar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useTraditional } from "@/hooks/use-api";
import { DEFAULT_ODDS_FORMAT, parseTotal, type OddsFormat } from "@/lib/edge";
import {
  formatDate, formatInterval, formatTimestamp, formatTip, shiftDate, teamLabel,
} from "@/lib/format";
import {
  fairMoneyline, finalResult, inputsText, overUnderText, spreadText, statusText, totalText,
  type FinalResult,
} from "@/lib/traditional";
import type { TraditionalDay, TraditionalGame, TraditionalLine } from "@/lib/types";

const dayHref = (day: string) => `/traditional/?date=${day}`;

export function TraditionalView({ date }: { date: string | null }) {
  const query = useTraditional(date);
  const day = date ?? query.data?.date ?? null;
  // Outlives a change of date and every live refetch
  const [format, setFormat] = useState<OddsFormat>(DEFAULT_ODDS_FORMAT);
  return (
    <div className="space-y-6">
      <PageHeader title="Traditional" description={day ? formatDate(day) : undefined}>
        {day && (
          <nav aria-label="Dates" className="flex items-center gap-2">
            <Button asChild variant="outline" size="icon-sm">
              <Link href={dayHref(shiftDate(day, -1))} aria-label="Previous day"><ChevronLeft /></Link>
            </Button>
            {date && (
              <Button asChild variant="outline" size="sm"><Link href="/traditional/">Today</Link></Button>
            )}
            <Button asChild variant="outline" size="icon-sm">
              <Link href={dayHref(shiftDate(day, 1))} aria-label="Next day"><ChevronRight /></Link>
            </Button>
          </nav>
        )}
      </PageHeader>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <p className="max-w-3xl text-sm text-muted-foreground">
          A rule-based model with no machine learning: Elo blended with season-to-date offensive and
          defensive ratings, a fixed home court and a back-to-back penalty. Lines are the
          model&apos;s fair prices, not bookmaker odds. Live games update from the score and the clock.
        </p>
        <OddsFormatToggle value={format} onChange={setFormat} />
      </div>
      <QueryState query={query} label="traditional lines">
        {(data) => <GameList data={data} format={format} />}
      </QueryState>
    </div>
  );
}

function GameList({ data, format }: { data: TraditionalDay; format: OddsFormat }) {
  return (
    <div className="space-y-4">
      {data.live_error && (
        <p role="alert" className="text-sm text-destructive">
          {data.live_error}; showing pregame lines.
        </p>
      )}
      {data.live_at && (
        <p className="text-xs text-muted-foreground">Live scores as of {formatTimestamp(data.live_at)}</p>
      )}
      {data.games.length === 0
        ? <p className="text-sm text-muted-foreground">No games on this date.</p>
        : (
          <div className="grid gap-4 xl:grid-cols-2">
            {data.games.map((g) => <GameCard key={g.game_id} game={g} format={format} />)}
          </div>
        )}
    </div>
  );
}

function StatusBadge({ game }: { game: TraditionalGame }) {
  const text = statusText(game);
  if (game.status === "in_progress") return <Badge variant="destructive">{text}</Badge>;
  return <Badge variant={game.status === "final" ? "secondary" : "outline"}>{text}</Badge>;
}

function GameCard({ game, format }: { game: TraditionalGame; format: OddsFormat }) {
  const { home, away, score, pregame, live } = game;
  const title = `${teamLabel(away)} @ ${teamLabel(home)}`;
  // Typed in the browser only (ADR-024); starts at the pregame total and outlives live refetches
  const [lineText, setLineText] = useState(pregame ? totalText(pregame.total.mu) : "");
  const totalLine = parseTotal(lineText);
  const result = finalResult(game, totalLine);
  return (
    <Card role="group" aria-label={title}>
      <CardHeader>
        <CardTitle className="text-lg">
          <Link href={gameHref(game.game_id)} className="hover:underline">{title}</Link>
        </CardTitle>
        <CardDescription>{formatTip(game.tip_off_utc)}</CardDescription>
        <CardAction className="flex flex-wrap justify-end gap-1">
          <SeasonTypeBadge type={game.season_type} />
          <StatusBadge game={game} />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        {score && (
          <div className="flex items-center justify-between rounded-md bg-muted px-3 py-2 text-sm">
            <span className="text-muted-foreground">{game.status === "final" ? "Final score" : "Score"}</span>
            <span className="flex items-baseline gap-2 font-semibold tabular-nums">
              <span>{teamLabel(away)}</span>
              <span>{score.away_pts}</span>
              <span className="text-muted-foreground">–</span>
              <span>{score.home_pts}</span>
              <span>{teamLabel(home)}</span>
            </span>
          </div>
        )}
        {pregame
          ? (
            <>
              <WinBar pHome={(live ?? pregame).p_home_win} home={home} away={away} />
              <Lines
                game={game} pregame={pregame} live={live} result={result} format={format}
                totalLine={totalLine}
              />
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                Total line
                <Input
                  className="h-7 w-24 tabular-nums" inputMode="decimal" aria-label={`Total line ${title}`}
                  aria-invalid={totalLine == null} value={lineText}
                  onChange={(e) => setLineText(e.target.value)}
                />
              </label>
              <p className="text-xs text-muted-foreground">{inputsText(pregame.inputs, home, away)}</p>
            </>
          )
          : <p className="text-sm text-muted-foreground">No pregame line (no ratings for this game yet)</p>}
      </CardContent>
    </Card>
  );
}

function Verdict({ text, hit, yes, no }: { text: string; hit: boolean; yes: string; no: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      {text}
      {hit
        ? <Check className="size-4 shrink-0 text-emerald-500" aria-label={yes} />
        : <X className="size-4 shrink-0 text-destructive" aria-label={no} />}
    </span>
  );
}

function Lines({ game, pregame, live, result, format, totalLine }: {
  game: TraditionalGame;
  pregame: TraditionalLine;
  live: TraditionalLine | null;
  result: FinalResult | null;
  format: OddsFormat;
  totalLine: number | null;
}) {
  const columns: { name: string; line: TraditionalLine }[] = [{ name: "Pregame", line: pregame }];
  if (live) columns.push({ name: "Live", line: live });
  const { home, away } = game;
  const markets = [
    {
      name: "Moneyline",
      cell: (l: TraditionalLine) => (
        <>
          <span className="block">{teamLabel(home)} {fairMoneyline(l.p_home_win, format)}</span>
          <span className="block">{teamLabel(away)} {fairMoneyline(1 - l.p_home_win, format)}</span>
        </>
      ),
      result: result && (
        <Verdict text={result.moneyline} hit={result.pickHit} yes="pick won" no="pick lost" />
      ),
    },
    {
      name: "Spread",
      cell: (l: TraditionalLine) => (
        <>
          <span className="block">{spreadText(l.margin.mu, home, away)}</span>
          <span className="block text-xs text-muted-foreground">
            80% {teamLabel(home)} {formatInterval(l.margin, true)}
          </span>
        </>
      ),
      result: result && (
        <Verdict text={result.spread} hit={result.covered} yes="line covered" no="line not covered" />
      ),
    },
    {
      name: "Total",
      cell: (l: TraditionalLine) => (
        <>
          <span className="block">O/U {totalText(l.total.mu)}</span>
          <span className="block">{overUnderText(l.total, totalLine)}</span>
          <span className="block text-xs text-muted-foreground">80% {formatInterval(l.total, false)}</span>
        </>
      ),
      result: result?.total,
    },
  ];
  return (
    <Table aria-label="Lines">
      <TableHeader>
        <TableRow>
          <TableHead>Market</TableHead>
          {columns.map((c) => <TableHead key={c.name}>{c.name}</TableHead>)}
          {result && <TableHead>Result</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {markets.map((m) => (
          <TableRow key={m.name}>
            <TableCell className="font-medium">{m.name}</TableCell>
            {columns.map((c) => (
              <TableCell key={c.name} className="tabular-nums">{m.cell(c.line)}</TableCell>
            ))}
            {result && <TableCell className="tabular-nums">{m.result}</TableCell>}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
