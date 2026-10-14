"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { PageHeader, QueryState } from "@/components/query-state";
import { Button } from "@/components/ui/button";
import { useGames, useHealth } from "@/hooks/use-api";
import { formatDate, shiftDate } from "@/lib/format";
import { activeGames, isDay, todayHref } from "@/lib/today";
import type { Game } from "@/lib/types";
import { GameCard } from "./game-card";

// Today's slate, or the given date's; the header shows the date the API resolved
export function TodayLoader({ date }: { date: string | null }) {
  const games = useGames(date);
  const health = useHealth().data;
  const now = health?.now ?? null;
  const day = games.data?.date ?? date;
  // Today's slate drops finished games; other dates keep them so past results stay browsable
  const isToday = date == null || (health != null && day === health.today);
  return (
    <>
      <PageHeader
        title={date && isDay(day) ? formatDate(day) : "Today"}
        description={!date && isDay(day) ? formatDate(day) : undefined}
      >
        {isDay(day) && <DayNav day={day} pinned={date != null} />}
      </PageHeader>
      <QueryState query={games} label="games">
        {(data) => isToday
          ? <GameList games={activeGames(data.games)} now={now}
              empty={data.games.length > 0 ? "All of today's games have finished." : undefined} />
          : <GameList games={data.games} now={now} />}
      </QueryState>
    </>
  );
}

function DayNav({ day, pinned }: { day: string; pinned: boolean }) {
  return (
    <nav className="flex items-center gap-2" aria-label="Dates">
      <Button asChild variant="outline" size="icon-sm">
        <Link href={todayHref(shiftDate(day, -1))} aria-label="Previous day"><ChevronLeft /></Link>
      </Button>
      {pinned && (
        <Button asChild variant="outline" size="sm">
          <Link href={todayHref(null)}>Today</Link>
        </Button>
      )}
      <Button asChild variant="outline" size="icon-sm">
        <Link href={todayHref(shiftDate(day, 1))} aria-label="Next day"><ChevronRight /></Link>
      </Button>
    </nav>
  );
}

export function GameList(
  { games, now, empty = "No games on this date." }: { games: Game[]; now: string | null; empty?: string },
) {
  if (games.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
      {games.map((g) => <GameCard key={g.game_id} game={g} now={now} />)}
    </div>
  );
}
