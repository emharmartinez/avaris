import { useId } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatTimestamp, teamLabel } from "@/lib/format";
import { restComparison, restLostText, restStatus } from "@/lib/rest";
import type { Prediction, Rest, RestPlayer, RestSide, Team } from "@/lib/types";

// Preseason only (ADR-022): who ESPN listed out, and the model's raw values beside the
// rest-adjusted ones. ESPN's notes are untrusted and rendered as plain text
export function RestSection({ prediction, home, away }: {
  prediction: Prediction | null;
  home: Team;
  away: Team;
}) {
  const titleId = useId();
  const rest = prediction?.rest;
  if (prediction == null || rest == null) return null;
  return (
    <section aria-labelledby={titleId} className="space-y-4">
      <h2 id={titleId} className="text-lg font-semibold tracking-tight">Preseason rest</h2>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
        {rest.adjusted ? <Badge variant="secondary">{restStatus(rest)}</Badge> : <span>{restStatus(rest)}</span>}
        <span>
          {rest.snapshot_ts ? `ESPN list as of ${formatTimestamp(rest.snapshot_ts)}` : "No ESPN list"}
        </span>
      </div>
      {rest.adjusted && <Comparison prediction={prediction} rest={rest} />}
      <div className="grid gap-4 lg:grid-cols-2">
        <TeamRest team={away} side={rest.away} />
        <TeamRest team={home} side={rest.home} />
      </div>
    </section>
  );
}

function Comparison({ prediction, rest }: { prediction: Prediction; rest: Rest }) {
  const { k } = rest;
  return (
    <Card>
      <CardContent className="space-y-2">
        <Table aria-label="Raw and rest-adjusted">
          <TableHeader>
            <TableRow>
              <TableHead />
              <TableHead className="text-right">Model (raw)</TableHead>
              <TableHead className="text-right">Rest-adjusted</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className="tabular-nums">
            {restComparison(prediction, rest).map((r) => (
              <TableRow key={r.label}>
                <TableCell>{r.label}</TableCell>
                <TableCell className="text-right">{r.raw}</TableCell>
                <TableCell className="text-right font-medium">{r.adjusted}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <p className="text-xs text-muted-foreground tabular-nums">
          Coefficients (0 = off): margin {k.margin}, total {k.total}, win {k.win}
        </p>
      </CardContent>
    </Card>
  );
}

function TeamRest({ team, side }: { team: Team; side: RestSide }) {
  const label = teamLabel(team);
  return (
    <section aria-label={`${label} rest`}>
      <Card>
        <CardHeader>
          <CardTitle>{label}</CardTitle>
          <CardDescription>{restLostText(side)}</CardDescription>
        </CardHeader>
        <CardContent>
          <PlayersTable label={label} players={side.players} />
        </CardContent>
      </Card>
    </section>
  );
}

function PlayersTable({ label, players }: { label: string; players: RestPlayer[] }) {
  if (players.length === 0) return <p className="text-sm text-muted-foreground">No players listed out</p>;
  return (
    <Table aria-label={`${label} out`}>
      <TableHeader>
        <TableRow>
          <TableHead>Player</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Note</TableHead>
          <TableHead className="text-right">Value</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {players.map((p, i) => (
          <TableRow key={p.player_id ?? `${p.name}-${i}`}>
            <TableCell>
              <span className="flex flex-wrap items-center gap-1.5">
                <span>{p.name}</span>
                {!p.matched && <Badge variant="outline">unmatched</Badge>}
              </span>
            </TableCell>
            <TableCell>{p.status}</TableCell>
            <TableCell className="whitespace-normal">{p.comment ?? "–"}</TableCell>
            <TableCell className="text-right tabular-nums">{p.value.toFixed(1)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
