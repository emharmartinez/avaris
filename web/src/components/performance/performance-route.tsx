"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { PerformanceView } from "./performance-view";

// Reads ?season= (client-only in the static export); picking a season navigates to it
export function PerformanceRoute() {
  const router = useRouter();
  const season = useSearchParams().get("season");
  return (
    <PerformanceView
      season={season || null}
      onSeasonChange={(s) => router.push(`/performance/?season=${encodeURIComponent(s)}`)}
    />
  );
}
