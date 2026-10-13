import Link from "next/link";
import { SeasonTypeBadge, StatusBadge } from "@/components/badges";
import { Badge } from "@/components/ui/badge";
import {
  Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  countdownToFinal, driverLabel, formatDriver, formatInterval, formatTip, signed, teamLabel,
  teamName,
} from "@/lib/format";
import { injuryText, topDrivers } from "@/lib/today";
import type { Game, Prediction } from "@/lib/types";
import { WinBar } from "./win-bar";

export function gameHref(id: string): string {
  return `/game/?id=${encodeURIComponent(id)}`;
}

export function GameCard({ game, now }: { game: Game; now: string | null }) {
  const { home, away, prediction, result } = game;
  const countdown = prediction?.status === "provisional" && now
    ? countdownToFinal(game.tip_off_utc, now)
    : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">
          <Link href={gameHref(game.game_id)} className="hover:underline">
            {teamLabel(away)} @ {teamLabel(home)}
          </Link>
        </CardTitle>
        <CardDescription>
          <span className="block">{teamName(away)} at {teamName(home)}</span>
          <span className="block">
            {formatTip(game.tip_off_utc)}
            {countdown && <> · <span>{countdown}</span></>}
          </span>
        </CardDescription>
        <CardAction className="flex flex-wrap justify-end gap-1">
          <SeasonTypeBadge type={game.season_type} />
          {game.neutral_site && <Badge variant="outline">Neutral site</Badge>}
          <StatusBadge status={prediction?.status ?? null} />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        {result && (
          <div className="flex items-center justify-between rounded-md bg-muted px-3 py-2 text-sm">
            <span className="text-muted-foreground">Final score</span>
            <span className="flex items-baseline gap-2 font-semibold tabular-nums">
              <span>{teamLabel(away)}</span>
              <span>{result.away_pts}</span>
              <span className="text-muted-foreground">–</span>
              <span>{result.home_pts}</span>
              <span>{teamLabel(home)}</span>
            </span>
          </div>
        )}
        {prediction
          ? <PredictionSummary game={game} prediction={prediction} />
          : <p className="text-sm text-muted-foreground">No prediction yet</p>}
      </CardContent>
      <CardFooter className="border-t py-3">
        <Link href={gameHref(game.game_id)} className="text-sm font-medium hover:underline">
          Details
        </Link>
      </CardFooter>
    </Card>
  );
}

function PredictionSummary({ game, prediction }: { game: Game; prediction: Prediction }) {
  const { home, away } = game;
  const { margin, total, injury_impact: injuries } = prediction;
  return (
    <>
      <WinBar pHome={prediction.p_home_win} home={home} away={away} />
      <div className="grid grid-cols-2 gap-4">
        <Stat label={`Margin (${teamLabel(home)})`} value={signed(margin.mu)}
          detail={`80%: ${formatInterval(margin, true)}`} />
        <Stat label="Total" value={total.mu.toFixed(1)}
          detail={`80%: ${formatInterval(total, false)}`} />
      </div>
      <div className="grid grid-cols-2 gap-4 text-sm">
        {([["away", away], ["home", home]] as const).map(([side, team]) => (
          <div key={side}>
            <div className="text-xs text-muted-foreground">Injuries {teamLabel(team)}</div>
            <div>{injuryText(injuries[side])}</div>
          </div>
        ))}
      </div>
      <div>
        <div className="mb-1 text-xs text-muted-foreground">Top drivers (home win, log-odds)</div>
        <ul className="space-y-0.5 text-sm">
          {topDrivers(prediction.top_drivers.home_win).map((d) => (
            <li key={d.family} className="flex justify-between">
              <span>{driverLabel(d.family)}</span>
              <span className="tabular-nums">{formatDriver(d.value, "log_odds")}</span>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-muted-foreground tabular-nums">{detail}</div>
    </div>
  );
}
