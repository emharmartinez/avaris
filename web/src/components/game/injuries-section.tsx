import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatTimestamp, teamLabel } from "@/lib/format";
import { groupReport } from "@/lib/game";
import { injuryText } from "@/lib/today";
import type { GameDetail, InjuredPlayer, InjuryEntry, InjuryImpactFull, Team } from "@/lib/types";

// The players behind each side's strength lost, and the decision report the prediction used
export function InjuriesSection({ game }: { game: GameDetail }) {
  const { prediction } = game;
  // Without a prediction the API still returns the report entries of the game's features
  if (!prediction?.report_ts && game.injury_report.length === 0) {
    return <p className="text-sm text-muted-foreground">No injury report used (preseason or no report)</p>;
  }
  const report = groupReport(game.injury_report, game.home.team_id, game.away.team_id);
  return (
    <div className="space-y-3">
      {prediction?.report_ts && (
        <p className="text-sm text-muted-foreground">Report as of {formatTimestamp(prediction.report_ts)}</p>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {(["away", "home"] as const).map((side) => (
          <TeamInjuries key={side} team={game[side]} impact={prediction?.injuries[side] ?? null}
            entries={report[side]} reported={prediction?.report_ts != null} />
        ))}
      </div>
    </div>
  );
}

// reported with no impact: the team has not played yet, so its report cannot be valued; the
// ESPN list, if any, follows in its own section (ADR-025)
function TeamInjuries({ team, impact, entries, reported }: {
  team: Team;
  impact: InjuryImpactFull | null;
  entries: InjuryEntry[];
  reported: boolean;
}) {
  const label = teamLabel(team);
  return (
    <section aria-label={`${label} injuries`}>
      <Card>
        <CardHeader>
          <CardTitle>{label}</CardTitle>
          <CardDescription>{injuryText(impact, reported)}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h3 className="mb-1 text-xs font-medium text-muted-foreground">Strength lost</h3>
            {impact == null && reported
              ? <p className="text-sm text-muted-foreground">Not valued before the team&apos;s first game</p>
              : <PlayersTable players={impact?.players ?? []} />}
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium text-muted-foreground">Report entries</h3>
            <EntriesTable entries={entries} />
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

function PlayersTable({ players }: { players: InjuredPlayer[] }) {
  if (players.length === 0) return <p className="text-sm text-muted-foreground">No players out</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Player</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Lost</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {players.map((p) => (
          <TableRow key={p.player_id}>
            <TableCell>{p.name ?? `Player ${p.player_id}`}</TableCell>
            <TableCell>{p.status ?? "–"}</TableCell>
            <TableCell className="text-right tabular-nums">{p.lost.toFixed(1)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function EntriesTable({ entries }: { entries: InjuryEntry[] }) {
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">No report entries</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Player</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Reason</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((e, k) => (
          <TableRow key={`${e.player_id ?? e.player_name}-${k}`}>
            <TableCell>{e.player_name}</TableCell>
            <TableCell>{e.status}</TableCell>
            <TableCell className="whitespace-normal">{e.reason ?? "–"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
