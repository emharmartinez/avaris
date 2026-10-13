import { teamLabel } from "@/lib/format";
import { winSplit } from "@/lib/today";
import type { Team } from "@/lib/types";

// Two-sided bar: away share on the left, home share on the right
export function WinBar({ pHome, home, away }: { pHome: number; home: Team; away: Team }) {
  const s = winSplit(pHome);
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-sm">
        <span>
          <span className="text-muted-foreground">{teamLabel(away)} </span>
          <span className="font-semibold tabular-nums">{s.awayText}</span>
        </span>
        <span className="text-xs text-muted-foreground">Win probability</span>
        <span>
          <span className="font-semibold tabular-nums">{s.homeText}</span>
          <span className="text-muted-foreground"> {teamLabel(home)}</span>
        </span>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div className="bg-muted-foreground/40" style={{ width: `${s.away * 100}%` }} />
        <div className="bg-primary" style={{ width: `${s.home * 100}%` }} />
      </div>
    </div>
  );
}
