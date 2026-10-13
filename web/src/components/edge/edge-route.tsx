"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { parseDate } from "@/lib/injuries";
import { EdgeView } from "./edge-view";

// Reads ?date= and ?game= (client-only in the static export); picking a game navigates to it
export function EdgeRoute() {
  const router = useRouter();
  const params = useSearchParams();
  const date = parseDate(params.get("date"));
  return (
    <EdgeView
      date={date}
      gameId={params.get("game") || null}
      onGameChange={(id) => {
        const query = new URLSearchParams({ ...(date ? { date } : {}), game: id });
        router.replace(`/edge/?${query.toString()}`);
      }}
    />
  );
}
