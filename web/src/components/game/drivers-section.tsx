import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { driverLabel, formatDriver, teamLabel } from "@/lib/format";
import { sortedDrivers } from "@/lib/game";
import type { DriverSet, PredictionFull, Target, Team } from "@/lib/types";

const TITLES: Record<Target, string> = { home_win: "Win probability", margin: "Margin", total: "Total" };

// Feature-family contributions per target, largest first
export function DriversSection({ drivers, home }: { drivers: PredictionFull["drivers"]; home: Team }) {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      {(Object.keys(TITLES) as Target[]).map((t) => (
        <DriverCard key={t} title={TITLES[t]} set={drivers[t]}
          note={t === "total" ? "Positive means a higher total" : `Positive favors ${teamLabel(home)}`} />
      ))}
    </div>
  );
}

function DriverCard({ title, set, note }: { title: string; set: DriverSet; note: string }) {
  const rows = sortedDrivers(set);
  const max = Math.max(...rows.map((d) => Math.abs(d.value)), 1e-9);
  const base = set.scale === "log_odds" ? `${set.base.toFixed(2)} log-odds` : `${set.base.toFixed(1)} points`;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          <span className="block">{`Base ${base}`}</span>
          <span className="block">{note}</span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table aria-label={`${title} drivers`}>
          <TableHeader>
            <TableRow>
              <TableHead>Driver</TableHead>
              <TableHead className="w-1/3"><span className="sr-only">Contribution</span></TableHead>
              <TableHead className="text-right">Value</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((d) => (
              <TableRow key={d.family}>
                <TableCell>{driverLabel(d.family)}</TableCell>
                <TableCell><Bar value={d.value} max={max} /></TableCell>
                <TableCell className="text-right tabular-nums">{formatDriver(d.value, set.scale)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function Bar({ value, max }: { value: number; max: number }) {
  // Centered bar: negative grows left, positive grows right
  const width = `${(Math.abs(value) / max) * 50}%`;
  return (
    <div className="relative h-2 w-full rounded-full bg-muted" aria-hidden="true">
      <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
      <div
        className={value >= 0 ? "absolute inset-y-0 left-1/2 rounded-r-full bg-primary" : "absolute inset-y-0 right-1/2 rounded-l-full bg-muted-foreground/60"}
        style={{ width }}
      />
    </div>
  );
}
