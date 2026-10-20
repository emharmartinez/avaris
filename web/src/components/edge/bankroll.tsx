"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import {
  betLabel, defaultStake, formatMoney, parseMoney, parsePct, signedMoney, toWin, units,
} from "@/lib/bankroll";
import { formatOdds, type OddsFormat } from "@/lib/edge";
import { formatDate, pct, teamLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Bankroll, Bet, BetResult, NewBet } from "@/lib/types";
import { TextInput } from "./text-input";

// Bet tracking (ADR-026): the bankroll and its unit, the bet form under each market, and the
// bets recorded. The API grades bets from final scores; the bankroll moves with them

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function BankrollCard({ bankroll }: { bankroll: Bankroll }) {
  const [editing, setEditing] = useState(false);
  const unset = bankroll.starting == null;
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2">
        <div className="space-y-1.5">
          <CardTitle>Bankroll</CardTitle>
          <CardDescription>
            {unset
              ? "Set a bankroll to size bets in units and track the bets you place."
              : `Started at ${formatMoney(bankroll.starting)}. Settled bets move the bankroll, and the unit with it.`}
          </CardDescription>
        </div>
        {!unset && !editing && (
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>Edit bankroll</Button>
        )}
      </CardHeader>
      <CardContent>
        {unset || editing ? (
          <BankrollForm bankroll={bankroll} onDone={editing ? () => setEditing(false) : undefined} />
        ) : (
          <BankrollStats bankroll={bankroll} />
        )}
      </CardContent>
    </Card>
  );
}

function BankrollForm({ bankroll, onDone }: { bankroll: Bankroll; onDone?: () => void }) {
  const client = useQueryClient();
  const [starting, setStarting] = useState(bankroll.starting?.toString() ?? "");
  const [unitPct, setUnitPct] = useState((bankroll.unit_pct ?? 1).toString());
  const amount = parseMoney(starting);
  const share = parsePct(unitPct);
  const save = useMutation({
    mutationFn: () => api.setBankroll(amount!, share!),
    onSuccess: (data) => {
      client.setQueryData(["bankroll"], data);
      onDone?.();
    },
  });
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (amount != null && share != null) save.mutate();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <TextInput
          label="Starting bankroll" value={starting} onChange={setStarting} placeholder="1000"
          error={starting !== "" && amount == null ? "Not a valid amount: above 0." : null}
        />
        <TextInput
          label="Unit size (% of bankroll)" value={unitPct} onChange={setUnitPct} placeholder="1"
          error={unitPct !== "" && share == null ? "Not a valid share: above 0, up to 100." : null}
        />
      </div>
      {amount != null && share != null && (
        <p className="text-sm text-muted-foreground">1 unit = {formatMoney(amount * share / 100)}</p>
      )}
      {save.error && <p role="alert" className="text-sm text-destructive">{errorText(save.error)}</p>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={amount == null || share == null || save.isPending}>
          Save
        </Button>
        {onDone && <Button type="button" variant="ghost" size="sm" onClick={onDone}>Cancel</Button>}
      </div>
    </form>
  );
}

function BankrollStats({ bankroll: b }: { bankroll: Bankroll }) {
  const { won, lost, push } = b.record;
  return (
    <dl className="grid gap-4 sm:grid-cols-5">
      <Stat label="Bankroll" value={formatMoney(b.current)} />
      <Stat label="1 unit" value={formatMoney(b.unit)} note={`${b.unit_pct}% of the bankroll`} />
      <Stat
        label="Profit" value={signedMoney(b.profit)} className={profitClass(b.profit)}
        note={b.roi == null ? undefined : `ROI ${b.roi > 0 ? "+" : ""}${pct(b.roi, 1).replace("-", "−")}`}
      />
      <Stat label="Record" value={`${won}-${lost}-${push}`} note="won-lost-push" />
      <Stat label="In play" value={formatMoney(b.in_play)} note={`${b.record.pending} pending`} />
    </dl>
  );
}

function Stat({ label, value, note, className }: {
  label: string;
  value: string;
  note?: string;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className="space-y-0.5">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className={cn("text-lg font-semibold tabular-nums", className)}>{value}</dd>
      {note && <dd className="text-xs text-muted-foreground">{note}</dd>}
    </div>
  );
}

function profitClass(x: number | null): string {
  if (x == null || Math.abs(x) < 0.005) return "";
  return x > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive";
}

// A side the user can bet: the market, side and line it covers and the odds typed for it
export type BetDraft = Omit<NewBet, "stake" | "game_id">;

export function BetForm({ gameId, draft, label, unit, format, onDone }: {
  gameId: string;
  draft: BetDraft;
  label: string;
  unit: number | null;
  format: OddsFormat;
  onDone: (recorded: Bet | null) => void;
}) {
  const client = useQueryClient();
  const [stakeText, setStakeText] = useState(defaultStake(unit));
  const stake = parseMoney(stakeText);
  const inUnits = stake == null ? null : units(stake, unit);
  const place = useMutation({
    mutationFn: () => api.placeBet({ ...draft, game_id: gameId, stake: stake! }),
    onSuccess: async (recorded) => {
      await client.invalidateQueries({ queryKey: ["bankroll"] });
      onDone(recorded);
    },
  });
  return (
    <form
      aria-label={`Bet ${label}`}
      className="space-y-3 rounded-lg border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (stake != null) place.mutate();
      }}
    >
      <p className="text-sm font-medium">{label} at {formatOdds(draft.odds, format)}</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <TextInput
          label="Stake" value={stakeText} onChange={setStakeText} placeholder="10.00"
          error={stakeText !== "" && stake == null ? "Not a valid stake: above 0." : null}
        />
      </div>
      {stake != null && (
        <p className="text-sm text-muted-foreground">
          {inUnits != null ? `${inUnits.toFixed(2)} units. `
            : unit === 0 ? "The bankroll is used up, so no unit. " : "No bankroll set, so no unit. "}
          To win {formatMoney(toWin(stake, draft.odds))}.
        </p>
      )}
      {place.error && <p role="alert" className="text-sm text-destructive">{errorText(place.error)}</p>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={stake == null || place.isPending}>Record bet</Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => onDone(null)}>Cancel</Button>
      </div>
    </form>
  );
}

const RESULTS: Record<BetResult, { label: string; variant: "default" | "secondary" | "outline" | "destructive" }> = {
  won: { label: "Won", variant: "default" },
  lost: { label: "Lost", variant: "destructive" },
  push: { label: "Push", variant: "secondary" },
  pending: { label: "Pending", variant: "outline" },
};

export function BetsTable({ bets, format }: { bets: Bet[]; format: OddsFormat }) {
  return (
    <Table aria-label="Bets">
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          <TableHead>Game</TableHead>
          <TableHead>Bet</TableHead>
          <TableHead className="text-right">Odds</TableHead>
          <TableHead className="text-right">Stake</TableHead>
          <TableHead>Result</TableHead>
          <TableHead className="text-right">Profit</TableHead>
          <TableHead><span className="sr-only">Actions</span></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody className="tabular-nums">
        {bets.map((b) => <BetRow key={b.bet_id} bet={b} format={format} />)}
      </TableBody>
    </Table>
  );
}

function BetRow({ bet: b, format }: { bet: Bet; format: OddsFormat }) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.deleteBet(b.bet_id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["bankroll"] }),
  });
  const result = RESULTS[b.result];
  const game = `${teamLabel(b.game.away)} @ ${teamLabel(b.game.home)}`;
  return (
    <TableRow>
      <TableCell>{formatDate(b.game.game_date_et)}</TableCell>
      <TableCell>
        <Link className="underline-offset-4 hover:underline"
          href={`/edge/?date=${b.game.game_date_et}&game=${b.game_id}`}>{game}</Link>
      </TableCell>
      <TableCell className="font-medium">{betLabel(b, b.game)}</TableCell>
      <TableCell className="text-right">{formatOdds(b.odds, format)}</TableCell>
      <TableCell className="text-right">{formatMoney(b.stake)}</TableCell>
      <TableCell><Badge variant={result.variant}>{result.label}</Badge></TableCell>
      <TableCell className={cn("text-right", profitClass(b.profit))}>
        {b.profit == null ? "–" : signedMoney(b.profit)}
      </TableCell>
      <TableCell className="text-right">
        {confirming ? (
          <span className="inline-flex gap-1">
            <Button variant="destructive" size="sm" disabled={remove.isPending}
              onClick={() => remove.mutate()}>Confirm delete</Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>Keep</Button>
          </span>
        ) : (
          <Button variant="ghost" size="sm" aria-label="Delete bet" onClick={() => setConfirming(true)}>
            <Trash2 />
          </Button>
        )}
        {remove.error && <p role="alert" className="text-xs text-destructive">{errorText(remove.error)}</p>}
      </TableCell>
    </TableRow>
  );
}
