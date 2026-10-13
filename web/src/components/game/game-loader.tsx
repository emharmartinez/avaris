"use client";

import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { useGame } from "@/hooks/use-api";
import { GameView } from "./game-view";

export function GameLoader({ id }: { id: string | null }) {
  // Without an id the query stays disabled (pending forever), so answer before QueryState
  const query = useGame(id);
  if (!id) {
    return (
      <div className="space-y-2 text-sm">
        <p>No game selected.</p>
        <Link href="/" className="font-medium underline-offset-4 hover:underline">Back to Today</Link>
      </div>
    );
  }
  return (
    <QueryState query={query} label="game">
      {(game) => <GameView game={game} />}
    </QueryState>
  );
}
