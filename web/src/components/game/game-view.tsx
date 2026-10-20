import { SeasonTypeBadge, StatusBadge } from "@/components/badges";
import { PageHeader } from "@/components/query-state";
import { WinBar } from "@/components/today/win-bar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate, formatTimestamp, formatTip, teamLabel, teamName } from "@/lib/format";
import { actualOutcome } from "@/lib/game";
import type { GameDetail } from "@/lib/types";
import { DistributionChart } from "./distribution-chart";
import { DriversSection } from "./drivers-section";
import { InjuriesSection } from "./injuries-section";
import { RatingsChart } from "./ratings-chart";
import { RestSection } from "./rest-section";
import { ScoreCard } from "./score-card";

export function GameView({ game }: { game: GameDetail }) {
  const { home, away, prediction, result } = game;
  const actual = actualOutcome(result);
  const where = [formatDate(game.game_date_et), formatTip(game.tip_off_utc), game.venue]
    .filter(Boolean).join(" · ");
  return (
    <div className="space-y-8">
      <PageHeader
        title={`${teamLabel(away)} @ ${teamLabel(home)}`}
        description={
          <>
            <span className="block">{teamName(away)} at {teamName(home)}</span>
            <span className="block">{where}</span>
          </>
        }
      >
        <div className="flex flex-wrap items-center justify-end gap-2">
          {result && (
            <span className="mr-2 flex items-baseline gap-2 text-lg font-semibold tabular-nums">
              <span>{teamLabel(away)}</span>
              <span>{result.away_pts}</span>
              <span className="text-muted-foreground">–</span>
              <span>{result.home_pts}</span>
              <span>{teamLabel(home)}</span>
            </span>
          )}
          <SeasonTypeBadge type={game.season_type} />
          {game.neutral_site && <Badge variant="outline">Neutral site</Badge>}
          <StatusBadge status={prediction?.status ?? null} />
        </div>
      </PageHeader>

      {prediction ? (
        <>
          <Section title="Prediction">
            <Card>
              <CardHeader>
                <CardTitle>Win probability</CardTitle>
                <CardDescription>
                  Predicted {formatTimestamp(prediction.predicted_at)}
                  {prediction.decision_ts && <> · decision time {formatTimestamp(prediction.decision_ts)}</>}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <WinBar pHome={prediction.p_home_win} home={home} away={away} />
              </CardContent>
            </Card>
            <div className="grid gap-4 lg:grid-cols-2">
              <DistributionChart title={`Margin (${teamLabel(home)})`} interval={prediction.margin}
                signedScale actual={actual?.margin ?? null} zeroLine />
              <DistributionChart title="Total" interval={prediction.total} signedScale={false}
                actual={actual?.total ?? null} />
            </div>
          </Section>
          {game.score && <ScoreCard score={game.score} />}
          <Section title="Drivers">
            <DriversSection drivers={prediction.drivers} home={home} />
          </Section>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">No prediction yet</p>
      )}

      <Section title="Injuries">
        <InjuriesSection game={game} />
      </Section>

      <RestSection prediction={prediction} home={home} away={away} seasonType={game.season_type} />

      <RatingsChart game={game} />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {children}
    </div>
  );
}
