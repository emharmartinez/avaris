"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";
import { PageHeader, QueryState } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useGames } from "@/hooks/use-api";
import {
  evaluateMarket, formatOdds, moneylineMarket, parseLine, parseOdds, spreadMarket, totalMarket,
  type MarketResult, type OddsFormat, type Outcome, type Pair,
} from "@/lib/edge";
import { formatDate, formatTip, pct, shiftDate, signed, teamLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Game, GamesOnDate, Prediction } from "@/lib/types";

type PredictedGame = Game & { prediction: Prediction };

const dayHref = (day: string) => `/edge/?date=${day}`;

export function EdgeView({ date, gameId, onGameChange }: {
  date: string | null;
  gameId: string | null;
  onGameChange: (id: string) => void;
}) {
  const query = useGames(date);
  const day = date ?? query.data?.date ?? null;
  return (
    <div className="space-y-6">
      <PageHeader title="Edge" description={day ? formatDate(day) : undefined}>
        {day && (
          <nav aria-label="Dates" className="flex items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href={dayHref(shiftDate(day, -1))} aria-label="Previous day"><ChevronLeft /></Link>
            </Button>
            {date && (
              <Button asChild variant="outline" size="sm"><Link href="/edge/">Today</Link></Button>
            )}
            <Button asChild variant="outline" size="sm">
              <Link href={dayHref(shiftDate(day, 1))} aria-label="Next day"><ChevronRight /></Link>
            </Button>
          </nav>
        )}
      </PageHeader>
      <QueryState query={query} label="predictions">
        {(data) => <GamePicker data={data} gameId={gameId} onGameChange={onGameChange} />}
      </QueryState>
    </div>
  );
}

function GamePicker({ data, gameId, onGameChange }: {
  data: GamesOnDate;
  gameId: string | null;
  onGameChange: (id: string) => void;
}) {
  // Odds format outlives a change of game; the typed odds do not
  const [format, setFormat] = useState<OddsFormat>("american");
  const games = data.games.filter((g): g is PredictedGame => g.prediction != null);
  if (games.length === 0) {
    return <p className="text-sm text-muted-foreground">No predicted games on this date.</p>;
  }
  const game = games.find((g) => g.game_id === gameId) ?? games[0];
  return (
    <div className="space-y-4">
      <Select value={game.game_id} onValueChange={onGameChange}>
        <SelectTrigger aria-label="Game" className="w-full sm:w-72">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {games.map((g) => (
            <SelectItem key={g.game_id} value={g.game_id}>
              {teamLabel(g.away)} @ {teamLabel(g.home)} · {formatTip(g.tip_off_utc)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Calculator key={game.game_id} game={game} format={format} onFormatChange={setFormat} />
    </div>
  );
}

const ODDS_FIELDS = ["mlAway", "mlHome", "spAway", "spHome", "over", "under"] as const;
type OddsField = (typeof ODDS_FIELDS)[number];
type OddsInputs = Record<OddsField, string>;

const EMPTY: OddsInputs = { mlAway: "", mlHome: "", spAway: "", spHome: "", over: "", under: "" };

// Typed into an input, so the plain hyphen rather than the display minus
const inputOdds = (decimal: number, format: OddsFormat) =>
  formatOdds(decimal, format).replace("−", "-");

function Calculator({ game, format, onFormatChange }: {
  game: PredictedGame;
  format: OddsFormat;
  onFormatChange: (f: OddsFormat) => void;
}) {
  const [odds, setOdds] = useState<OddsInputs>(EMPTY);
  const [spreadLine, setSpreadLine] = useState("");
  const [totalLine, setTotalLine] = useState("");
  const p = game.prediction;
  const away = teamLabel(game.away);
  const home = teamLabel(game.home);
  const price = (field: OddsField) => parseOdds(odds[field], format);
  const set = (field: OddsField) => (value: string) => setOdds((o) => ({ ...o, [field]: value }));

  const switchFormat = (next: OddsFormat) => {
    if (next === format) return;
    // Keep what was typed: convert each valid price, leave the rest as is
    setOdds((o) => Object.fromEntries(ODDS_FIELDS.map((f) => {
      const d = parseOdds(o[f], format);
      return [f, d == null ? o[f] : inputOdds(d, next)];
    })) as OddsInputs);
    onFormatChange(next);
  };

  const spread = parseLine(spreadLine);
  const total = parseLine(totalLine);
  const evaluate = (outcomes: Pair<Outcome>, fields: Pair<OddsField>) => evaluateMarket([
    { outcome: outcomes[0], odds: price(fields[0]) },
    { outcome: outcomes[1], odds: price(fields[1]) },
  ]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {p.status === "final"
            ? "Final prediction, frozen at the decision time."
            : "Provisional prediction: it can change until tip-off minus 60 minutes."}
        </p>
        <div role="group" aria-label="Odds format" className="flex gap-1">
          {(["american", "decimal"] as const).map((f) => (
            <Button
              key={f} size="sm" variant={f === format ? "secondary" : "ghost"}
              aria-pressed={f === format} onClick={() => switchFormat(f)}
            >
              {f === "american" ? "American" : "Decimal"}
            </Button>
          ))}
        </div>
      </div>

      <MarketCard
        title="Moneyline"
        description={`Model: ${home} ${pct(p.p_home_win, 1)} to win`}
        inputs={<>
          <OddsInput label={`${away} moneyline`} value={odds.mlAway} onChange={set("mlAway")} format={format} />
          <OddsInput label={`${home} moneyline`} value={odds.mlHome} onChange={set("mlHome")} format={format} />
        </>}
        result={evaluate(moneylineMarket(p.p_home_win), ["mlAway", "mlHome"])}
        labels={[away, home]}
        format={format}
      />

      <MarketCard
        title="Spread"
        description={`Model margin: ${home} ${signed(p.margin.mu)} (σ ${p.margin.sigma.toFixed(1)})`}
        inputs={<>
          <TextInput
            label={`${home} line`} value={spreadLine} onChange={setSpreadLine}
            invalid={spreadLine !== "" && spread == null} placeholder="-3.5"
          />
          <OddsInput label={`${away} spread odds`} value={odds.spAway} onChange={set("spAway")} format={format} />
          <OddsInput label={`${home} spread odds`} value={odds.spHome} onChange={set("spHome")} format={format} />
        </>}
        result={spread == null ? null : evaluate(spreadMarket(p.margin, spread), ["spAway", "spHome"])}
        labels={spread == null ? null : [`${away} ${formatLine(-spread)}`, `${home} ${formatLine(spread)}`]}
        format={format}
        hint={`Enter ${home}'s line, negative when ${home} is favored.`}
      />

      <MarketCard
        title="Total"
        description={`Model total: ${p.total.mu.toFixed(1)} (σ ${p.total.sigma.toFixed(1)})`}
        inputs={<>
          <TextInput
            label="Total line" value={totalLine} onChange={setTotalLine}
            invalid={totalLine !== "" && total == null} placeholder="224.5"
          />
          <OddsInput label="Over odds" value={odds.over} onChange={set("over")} format={format} />
          <OddsInput label="Under odds" value={odds.under} onChange={set("under")} format={format} />
        </>}
        result={total == null ? null : evaluate(totalMarket(p.total, total), ["over", "under"])}
        labels={total == null ? null : [`Over ${formatTotal(total)}`, `Under ${formatTotal(total)}`]}
        format={format}
        hint="Enter the total points line."
      />

      <p className="text-xs text-muted-foreground">
        Edge is the model probability minus the implied probability; EV is per 100 staked, with a
        push returning the stake. Odds stay in this page and are never saved.
      </p>
    </div>
  );
}

function formatLine(x: number): string {
  return x === 0 ? "pk" : signed(x, Number.isInteger(x) ? 0 : 1);
}

function formatTotal(x: number): string {
  return Number.isInteger(x) ? x.toString() : x.toFixed(1);
}

function MarketCard({ title, description, inputs, result, labels, format, hint }: {
  title: string;
  description: string;
  inputs: React.ReactNode;
  result: MarketResult | null;
  labels: Pair<string> | null;
  format: OddsFormat;
  hint?: string;
}) {
  const titleId = useId();
  const priced = result?.sides.some((s) => s.implied != null);
  const push = result?.sides[0].push ?? 0;
  return (
    <section aria-labelledby={titleId}>
      <Card>
        <CardHeader>
          <CardTitle id={titleId}>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">{inputs}</div>
          {result == null || labels == null ? (
            hint && <p className="text-sm text-muted-foreground">{hint}</p>
          ) : (
            <>
              <Table aria-label={title}>
                <TableHeader>
                  <TableRow>
                    <TableHead>Side</TableHead>
                    <TableHead className="text-right">Model</TableHead>
                    <TableHead className="text-right">Implied</TableHead>
                    <TableHead className="text-right">Edge</TableHead>
                    <TableHead className="text-right">EV / 100</TableHead>
                    <TableHead className="text-right">Fair</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody className="tabular-nums">
                  {result.sides.map((s, i) => (
                    <TableRow key={labels[i]}>
                      <TableCell className="font-medium">{labels[i]}</TableCell>
                      <TableCell className="text-right">{pct(s.model, 1)}</TableCell>
                      <TableCell className="text-right">{pct(s.implied, 1)}</TableCell>
                      <TableCell className={cn("text-right", edgeClass(s.edge))}>
                        {s.edge == null ? "–" : `${signed(s.edge * 100)} pp`}
                      </TableCell>
                      <TableCell className={cn("text-right", edgeClass(s.ev))}>
                        {s.ev == null ? "–" : signed(s.ev * 100, 2)}
                      </TableCell>
                      <TableCell className="text-right">
                        {s.fairOdds == null ? "–" : formatOdds(s.fairOdds, format)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {(priced || push > 0) && (
                <p className="text-xs text-muted-foreground">
                  {priced && (result.devigged
                    ? `Vig ${pct(result.vig, 1)}, removed proportionally.`
                    : "One price: implied probability includes the vig.")}
                  {priced && push > 0 && " "}
                  {push > 0 && `Whole-number line: push ${pct(push, 1)}, stake returned.`}
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function edgeClass(x: number | null): string {
  if (x == null || Math.abs(x) < 5e-4) return "";
  return x > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground";
}

function OddsInput({ label, value, onChange, format }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  format: OddsFormat;
}) {
  return (
    <TextInput
      label={label} value={value} onChange={onChange}
      invalid={value !== "" && parseOdds(value, format) == null}
      placeholder={format === "american" ? "-110" : "1.91"}
    />
  );
}

function TextInput({ label, value, onChange, invalid, placeholder }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  invalid: boolean;
  placeholder: string;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</label>
      <Input
        id={id} value={value} placeholder={placeholder} autoComplete="off" spellCheck={false}
        aria-invalid={invalid || undefined} onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
