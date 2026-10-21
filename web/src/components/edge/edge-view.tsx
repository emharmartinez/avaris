"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { OddsFormatToggle } from "@/components/odds-format-toggle";
import { PageHeader, QueryState } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useBankroll, useGames } from "@/hooks/use-api";
import { betLabel, formatMoney } from "@/lib/bankroll";
import {
  DEFAULT_ODDS_FORMAT, evaluateMarket, formatLine, formatOdds, formatTotal, moneylineMarket,
  parseLine, parseOdds, parseTotal, spreadMarket, totalMarket,
  type MarketResult, type OddsFormat, type Outcome, type Pair,
} from "@/lib/edge";
import { formatDate, formatTip, pct, shiftDate, signed, teamLabel } from "@/lib/format";
import { edgeRestNote } from "@/lib/rest";
import { cn } from "@/lib/utils";
import type { Bet, Game, GamesOnDate, Prediction } from "@/lib/types";
import { BankrollCard, BetForm, BetsTable, type BetDraft } from "./bankroll";
import { TextInput } from "./text-input";

type PredictedGame = Game & { prediction: Prediction };

const dayHref = (day: string) => `/edge/?date=${day}`;

export function EdgeView({ date, gameId, onGameChange }: {
  date: string | null;
  gameId: string | null;
  onGameChange: (id: string) => void;
}) {
  const query = useGames(date);
  const book = useBankroll();
  const day = date ?? query.data?.date ?? null;
  const unit = book.data?.unit ?? null;
  // The odds format outlives a change of game or date; the typed odds do not
  const [format, setFormat] = useState<OddsFormat>(DEFAULT_ODDS_FORMAT);
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
      <QueryState query={book} label="bankroll">
        {(data) => <BankrollCard bankroll={data} />}
      </QueryState>
      <QueryState query={query} label="predictions">
        {(data) => (
          <GamePicker
            data={data} gameId={gameId} onGameChange={onGameChange}
            format={format} onFormatChange={setFormat} unit={unit}
          />
        )}
      </QueryState>
      {book.data && book.data.bets.length > 0 && (
        <section aria-labelledby="bets-title" className="space-y-3">
          <h2 id="bets-title" className="text-lg font-semibold">Your bets</h2>
          <BetsTable bets={book.data.bets} format={format} />
        </section>
      )}
    </div>
  );
}

function GamePicker({ data, gameId, onGameChange, format, onFormatChange, unit }: {
  data: GamesOnDate;
  gameId: string | null;
  onGameChange: (id: string) => void;
  format: OddsFormat;
  onFormatChange: (f: OddsFormat) => void;
  unit: number | null;
}) {
  const games = data.games.filter((g): g is PredictedGame => g.prediction != null);
  const game = games.find((g) => g.game_id === gameId) ?? games[0];
  // A ?game= that is not on this date: point the URL at the game actually shown
  const stale = gameId != null && game != null && game.game_id !== gameId;
  useEffect(() => {
    if (stale) onGameChange(game.game_id);
  }, [stale, game, onGameChange]);
  if (game == null) {
    return <p className="text-sm text-muted-foreground">No predicted games on this date.</p>;
  }
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
      <Calculator
        key={game.game_id} game={game} format={format} onFormatChange={onFormatChange} unit={unit}
      />
    </div>
  );
}

const ODDS_FIELDS = ["mlAway", "mlHome", "spAway", "spHome", "over", "under"] as const;
type OddsField = (typeof ODDS_FIELDS)[number];
// What is in the input, plus the exact decimal price while the text is a converted one, so
// switching format back and forth never rounds what was typed
interface OddsInput {
  text: string;
  exact?: number;
}
type OddsInputs = Record<OddsField, OddsInput>;

const EMPTY = Object.fromEntries(ODDS_FIELDS.map((f) => [f, { text: "" }])) as OddsInputs;

// Typed into an input, so the plain hyphen rather than the display minus
const inputOdds = (decimal: number, format: OddsFormat) =>
  formatOdds(decimal, format).replace("−", "-");

function Calculator({ game, format, onFormatChange, unit }: {
  game: PredictedGame;
  format: OddsFormat;
  onFormatChange: (f: OddsFormat) => void;
  unit: number | null;
}) {
  const [odds, setOdds] = useState<OddsInputs>(EMPTY);
  const [spreadLine, setSpreadLine] = useState("");
  const [totalLine, setTotalLine] = useState("");
  const p = game.prediction;
  const away = teamLabel(game.away);
  const home = teamLabel(game.home);
  const restNote = edgeRestNote(p, home);
  const price = (field: OddsField) => odds[field].exact ?? parseOdds(odds[field].text, format);
  const set = (field: OddsField) => (text: string) => setOdds((o) => ({ ...o, [field]: { text } }));

  const switchFormat = (next: OddsFormat) => {
    if (next === format) return;
    // Convert each valid price and keep its exact value; leave the rest as typed
    setOdds((o) => Object.fromEntries(ODDS_FIELDS.map((f) => {
      const d = o[f].exact ?? parseOdds(o[f].text, format);
      return [f, d == null ? o[f] : { text: inputOdds(d, next), exact: d }];
    })) as OddsInputs);
    onFormatChange(next);
  };

  const spread = parseLine(spreadLine);
  const total = parseTotal(totalLine);
  const evaluate = (outcomes: Pair<Outcome>, fields: Pair<OddsField>) => evaluateMarket([
    { outcome: outcomes[0], odds: price(fields[0]) },
    { outcome: outcomes[1], odds: price(fields[1]) },
  ]);
  // The sides a bet can be recorded on: each priced one, at its own line
  const drafts = (market: BetDraft["market"], sides: Pair<BetDraft["side"]>,
    lines: Pair<number | null>, fields: Pair<OddsField>): Pair<BetDraft | null> => {
    const draft = (i: 0 | 1): BetDraft | null => {
      const odds = price(fields[i]);
      return odds == null ? null : { market, side: sides[i], line: lines[i], odds };
    };
    return [draft(0), draft(1)];
  };
  const betting = { game, unit };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1 text-sm text-muted-foreground">
          <p>
            {p.status === "final"
              ? "Final prediction, frozen at the decision time."
              : "Provisional prediction: it can change until tip-off minus 60 minutes."}
          </p>
          {restNote && <p>{restNote}</p>}
        </div>
        <OddsFormatToggle value={format} onChange={switchFormat} />
      </div>

      <MarketCard
        title="Moneyline"
        description={`Model: ${home} ${pct(p.p_home_win, 1)} to win`}
        inputs={<>
          <OddsInput label={`${away} moneyline`} value={odds.mlAway.text} onChange={set("mlAway")} format={format} />
          <OddsInput label={`${home} moneyline`} value={odds.mlHome.text} onChange={set("mlHome")} format={format} />
        </>}
        result={evaluate(moneylineMarket(p.p_home_win), ["mlAway", "mlHome"])}
        labels={[away, home]}
        format={format}
        bets={drafts("moneyline", ["away", "home"], [null, null], ["mlAway", "mlHome"])}
        betting={betting}
      />

      <MarketCard
        title="Spread"
        description={`Model margin: ${home} ${signed(p.margin.mu)} (σ ${p.margin.sigma.toFixed(1)})`}
        inputs={<>
          <TextInput
            label={`${home} line`} value={spreadLine} onChange={setSpreadLine}
            error={spreadLine !== "" && spread == null ? "Not a valid line, e.g. -3.5 or pk." : null}
            placeholder="-3.5"
          />
          <OddsInput label={`${away} spread odds`} value={odds.spAway.text} onChange={set("spAway")} format={format} />
          <OddsInput label={`${home} spread odds`} value={odds.spHome.text} onChange={set("spHome")} format={format} />
        </>}
        result={spread == null ? null : evaluate(spreadMarket(p.margin, spread), ["spAway", "spHome"])}
        labels={spread == null ? null : [`${away} ${formatLine(-spread)}`, `${home} ${formatLine(spread)}`]}
        format={format}
        bets={spread == null ? null
          : drafts("spread", ["away", "home"], [spread === 0 ? 0 : -spread, spread], ["spAway", "spHome"])}
        betting={betting}
        hint={`Enter ${home}'s line, negative when ${home} is favored.`}
      />

      <MarketCard
        title="Total"
        description={`Model total: ${p.total.mu.toFixed(1)} (σ ${p.total.sigma.toFixed(1)})`}
        inputs={<>
          <TextInput
            label="Total line" value={totalLine} onChange={setTotalLine}
            error={totalLine !== "" && total == null ? "Not a valid total, e.g. 224.5." : null}
            placeholder="224.5"
          />
          <OddsInput label="Over odds" value={odds.over.text} onChange={set("over")} format={format} />
          <OddsInput label="Under odds" value={odds.under.text} onChange={set("under")} format={format} />
        </>}
        result={total == null ? null : evaluate(totalMarket(p.total, total), ["over", "under"])}
        labels={total == null ? null : [`Over ${formatTotal(total)}`, `Under ${formatTotal(total)}`]}
        format={format}
        bets={total == null ? null : drafts("total", ["over", "under"], [total, total], ["over", "under"])}
        betting={betting}
        hint="Enter the total points line."
      />

      <p className="text-xs text-muted-foreground">
        Edge is the model probability minus the implied probability; EV is per 100 staked, with a
        push returning the stake. Odds stay in this page; only the bets you record are saved.
      </p>
    </div>
  );
}

function MarketCard({ title, description, inputs, result, labels, format, hint, bets, betting }: {
  title: string;
  description: string;
  inputs: React.ReactNode;
  result: MarketResult | null;
  labels: Pair<string> | null;
  format: OddsFormat;
  hint?: string;
  bets: Pair<BetDraft | null> | null;
  betting: { game: PredictedGame; unit: number | null };
}) {
  const titleId = useId();
  const [picked, setPicked] = useState<0 | 1 | null>(null);
  const [recorded, setRecorded] = useState<Bet | null>(null);
  const draft = picked == null ? null : bets?.[picked] ?? null;
  // A cleared line or price closes the form, so typing a new one does not reopen it
  if (picked != null && draft == null) setPicked(null);
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
          {draft ? (
            <BetForm
              key={`${draft.side} ${draft.line} ${draft.odds} ${betting.unit}`}
              gameId={betting.game.game_id} draft={draft} label={betLabel(draft, betting.game)}
              unit={betting.unit} format={format}
              onDone={(bet) => {
                setPicked(null);
                setRecorded(bet);
              }}
            />
          ) : bets?.some((b) => b != null) && (
            <div className="flex flex-wrap gap-2">
              {bets.map((b, i) => b && (
                <Button key={b.side} variant="outline" size="sm" onClick={() => {
                  setPicked(i as 0 | 1);
                  setRecorded(null);
                }}>
                  Bet {betLabel(b, betting.game)}
                </Button>
              ))}
            </div>
          )}
          {recorded && (
            <p role="status" className="text-sm text-muted-foreground">
              Recorded {betLabel(recorded, betting.game)}: {formatMoney(recorded.stake)} at{" "}
              {formatOdds(recorded.odds, format)}.
            </p>
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
      error={value !== "" && parseOdds(value, format) == null
        ? (format === "american"
          ? "Not a valid American price: -100 or below, or +100 or above."
          : "Not a valid decimal price: above 1.")
        : null}
      placeholder={format === "american" ? "-110" : "1.91"}
    />
  );
}
