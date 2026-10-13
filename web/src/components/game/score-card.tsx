import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatMetric, signed } from "@/lib/format";
import type { GameScore } from "@/lib/types";

const yesNo = (b: boolean) => (b ? "Yes" : "No");

// How the frozen prediction scored against the result
export function ScoreCard({ score }: { score: GameScore }) {
  const rows: [string, string][] = [
    ["Log loss", formatMetric(score.log_loss)],
    ["Brier", formatMetric(score.brier)],
    ["Correct pick", yesNo(score.correct)],
    ["Margin error", signed(score.margin_error)],
    ["Margin in 80%", yesNo(score.margin_in_80)],
    ["Total error", signed(score.total_error)],
    ["Total in 80%", yesNo(score.total_in_80)],
  ];
  return (
    <section aria-label="Score">
      <Card>
        <CardHeader>
          <CardTitle>Score</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 xl:grid-cols-7">
            {rows.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-lg font-semibold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
    </section>
  );
}
