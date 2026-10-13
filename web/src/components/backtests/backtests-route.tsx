"use client";

import { useSearchParams } from "next/navigation";
import { BacktestsView } from "./backtests-view";

// Reads ?name= (client-only in the static export) and hands it to the view
export function BacktestsRoute() {
  return <BacktestsView name={useSearchParams().get("name") || null} />;
}
