"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { PageHeader, QueryState } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useHealth, useInjuries } from "@/hooks/use-api";
import { formatDate, formatTimestamp, shiftDate, teamLabel } from "@/lib/format";
import { groupEntries, impactText, playerName } from "@/lib/injuries";
import { restLostText } from "@/lib/rest";
import type { InjuriesOnDate, InjuryGame, InjuryImpactFull, RestList, RestSide, Team } from "@/lib/types";

const dayHref = (day: string) => `/injuries/?date=${day}`;

export function InjuriesView({ date }: { date: string | null }) {
  // Without ?date=, today is the server's ET date, never the browser clock
  const health = useHealth();
  const day = date ?? health.data?.today ?? null;
  const query = useInjuries(day);
  return (
    <div className="space-y-6">
      <PageHeader title="Injuries" description={day ? formatDate(day) : undefined}>
        {day && (
          <nav aria-label="Dates" className="flex items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href={dayHref(shiftDate(day, -1))} aria-label="Previous day"><ChevronLeft /></Link>
            </Button>
            {date && (
              <Button asChild variant="outline" size="sm"><Link href="/injuries/">Today</Link></Button>
            )}
            <Button asChild variant="outline" size="sm">
              <Link href={dayHref(shiftDate(day, 1))} aria-label="Next day"><ChevronRight /></Link>
            </Button>
          </nav>
        )}
      </PageHeader>
      {date == null && health.error ? (
        <QueryState query={health} label="today's date">{() => null}</QueryState>
      ) : (
        <QueryState query={query} label="injuries">
          {(data) => <GameList data={data} />}
        </QueryState>
      )}
    </div>
  );
}

function GameList({ data }: { data: InjuriesOnDate }) {
  if (data.games.length === 0) {
    return <p className="text-sm text-muted-foreground">No games on this date.</p>;
  }
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {data.games.map((g) => <InjuryCard key={g.game_id} game={g} />)}
    </div>
  );
}

function InjuryCard({ game }: { game: InjuryGame }) {
  if (game.rest) return <EspnCard game={game} rest={game.rest} />;
  const titleId = `injuries-${game.game_id}`;
  const groups = groupEntries(game);
  return (
    <section aria-labelledby={titleId}>
      <Card className="h-full">
        <CardHeader>
          <CardTitle id={titleId}>{teamLabel(game.away)} @ {teamLabel(game.home)}</CardTitle>
          <CardDescription>
            {game.report_ts ? `Report of ${formatTimestamp(game.report_ts)}`
              : game.season_type === "preseason" ? "Preseason: no NBA report or ESPN list"
                : "No report used"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <SideImpact team={game.away} impact={game.impact.away} />
            <SideImpact team={game.home} impact={game.impact.home} />
          </div>
          {groups.length === 0 ? (
            <p className="text-sm text-muted-foreground">No players listed on the report.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Team</TableHead>
                  <TableHead>Player</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.flatMap((g) => g.entries.map((e, i) => (
                  <TableRow key={`${g.team_id}-${e.player_id ?? e.player_name}-${i}`}>
                    <TableCell className="font-medium">{g.label}</TableCell>
                    <TableCell>{e.player_name}</TableCell>
                    <TableCell>{e.status}</TableCell>
                    <TableCell className="text-muted-foreground">{e.reason ?? "–"}</TableCell>
                  </TableRow>
                )))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function SideImpact({ team, impact }: { team: Team; impact: InjuryImpactFull | null }) {
  const label = teamLabel(team);
  return (
    <div role="group" aria-label={`${label} impact`} className="space-y-1 text-sm">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">{impactText(impact)}</span>
      </div>
      {impact && impact.players.length > 0 && (
        <ul className="space-y-0.5 tabular-nums">
          {impact.players.map((p) => (
            <li key={p.player_id} className="flex justify-between gap-2">
              <span>{playerName(p)} <span className="text-muted-foreground">{p.status ?? ""}</span></span>
              <span>{p.lost.toFixed(1)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Preseason: no NBA report exists, so the card shows ESPN's out list (ADR-022)
function EspnCard({ game, rest }: { game: InjuryGame; rest: RestList }) {
  const titleId = `injuries-${game.game_id}`;
  const sides = [["away", game.away], ["home", game.home]] as const;
  const players = sides.flatMap(([side, team]) => rest[side].players.map((p) => ({ team, p })));
  return (
    <section aria-labelledby={titleId}>
      <Card className="h-full">
        <CardHeader>
          <CardTitle id={titleId}>{teamLabel(game.away)} @ {teamLabel(game.home)}</CardTitle>
          <CardDescription>
            {rest.snapshot_ts ? `ESPN list of ${formatTimestamp(rest.snapshot_ts)}`
              : (rest.note ?? "No ESPN list")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {sides.map(([side, team]) => <EspnSide key={side} team={team} side={rest[side]} />)}
          </div>
          {players.length === 0 ? (
            <p className="text-sm text-muted-foreground">No players listed out by ESPN.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Team</TableHead>
                  <TableHead>Player</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Note</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {players.map(({ team, p }, i) => (
                  <TableRow key={`${team.team_id}-${p.player_id ?? p.name}-${i}`}>
                    <TableCell className="font-medium">{teamLabel(team)}</TableCell>
                    <TableCell>{p.name}</TableCell>
                    <TableCell>{p.status}</TableCell>
                    <TableCell className="whitespace-normal text-muted-foreground">{p.comment ?? "–"}</TableCell>
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

function EspnSide({ team, side }: { team: Team; side: RestSide }) {
  const label = teamLabel(team);
  return (
    <div role="group" aria-label={`${label} impact`} className="space-y-1 text-sm">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">{restLostText(side)}</span>
      </div>
      {side.players.length > 0 && (
        <ul className="space-y-0.5 tabular-nums">
          {side.players.map((p, i) => (
            <li key={`${p.player_id ?? p.name}-${i}`} className="flex justify-between gap-2">
              <span>{p.name} <span className="text-muted-foreground">{p.status}</span></span>
              <span>{p.value.toFixed(1)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
