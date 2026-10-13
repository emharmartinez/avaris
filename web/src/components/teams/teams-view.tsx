"use client";

import Link from "next/link";
import { PageHeader, QueryState } from "@/components/query-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useTeamHistory, useTeams } from "@/hooks/use-api";
import { formatMetric, signed, teamLabel, teamName } from "@/lib/format";
import { historySeries } from "@/lib/teams";
import type { TeamHistory, TeamRatings } from "@/lib/types";
import { EloChart, NetPaceChart } from "./team-charts";

const DASH = "–";
const signedOrDash = (x: number | null) => (x == null ? DASH : signed(x));

export function TeamsView({ id }: { id: number | null }) {
  const teams = useTeams();
  return (
    <div className="space-y-6">
      <PageHeader title="Teams" description="Current ratings, strongest Elo first" />
      {id != null && <TeamPanel id={id} />}
      <QueryState query={teams} label="teams">
        {(data) => <TeamsTable teams={data} selected={id} />}
      </QueryState>
    </div>
  );
}

function TeamsTable({ teams, selected }: { teams: TeamRatings[]; selected: number | null }) {
  if (teams.length === 0) return <p className="text-sm text-muted-foreground">No team ratings yet.</p>;
  return (
    <Card>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">#</TableHead>
              <TableHead>Team</TableHead>
              <TableHead className="text-right">Elo</TableHead>
              <TableHead className="text-right">Net</TableHead>
              <TableHead className="text-right">ORtg</TableHead>
              <TableHead className="text-right">DRtg</TableHead>
              <TableHead className="text-right">Pace</TableHead>
              <TableHead className="text-right">Net L10</TableHead>
              <TableHead className="text-right">GP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className="tabular-nums">
            {teams.map((t, i) => (
              <TableRow key={t.team_id} data-state={t.team_id === selected ? "selected" : undefined}>
                <TableCell className="text-muted-foreground">{i + 1}</TableCell>
                <TableCell>
                  <Link href={`/teams/?id=${t.team_id}`} className="hover:underline">
                    <span className="font-medium">{teamName(t)}</span>{" "}
                    <span className="text-muted-foreground">{teamLabel(t)}</span>
                  </Link>
                </TableCell>
                <TableCell className="text-right">{t.elo.toFixed(0)}</TableCell>
                <TableCell className="text-right">{signedOrDash(t.net)}</TableCell>
                <TableCell className="text-right">{formatMetric(t.ortg, 1)}</TableCell>
                <TableCell className="text-right">{formatMetric(t.drtg, 1)}</TableCell>
                <TableCell className="text-right">{formatMetric(t.pace, 1)}</TableCell>
                <TableCell className="text-right">{signedOrDash(t.net_l10)}</TableCell>
                <TableCell className="text-right">{t.gp}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function TeamPanel({ id }: { id: number }) {
  const history = useTeamHistory(id);
  return (
    <QueryState query={history} label="team history">
      {(data) => <TeamHistoryPanel history={data} />}
    </QueryState>
  );
}

function TeamHistoryPanel({ history }: { history: TeamHistory }) {
  const points = historySeries(history.ratings);
  const headingId = `team-${history.team.team_id}`;
  return (
    <section aria-labelledby={headingId} className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h2 id={headingId} className="text-xl font-semibold tracking-tight">{teamName(history.team)}</h2>
        <span className="text-sm text-muted-foreground">
          {teamLabel(history.team)} · {history.season} season · {points.length} snapshots
        </span>
      </div>
      {points.length < 2 ? (
        <p className="text-sm text-muted-foreground">
          Not enough rating snapshots this season to draw a chart.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Elo</CardTitle>
              <CardDescription>Before each game</CardDescription>
            </CardHeader>
            <CardContent><EloChart points={points} /></CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Net rating and pace</CardTitle>
              <CardDescription>Net per 100 possessions (left), pace (right)</CardDescription>
            </CardHeader>
            <CardContent><NetPaceChart points={points} /></CardContent>
          </Card>
        </div>
      )}
    </section>
  );
}
