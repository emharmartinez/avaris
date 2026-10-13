"use client";

import { useSearchParams } from "next/navigation";
import { TodayLoader } from "./today-loader";

// Reads ?date= (client-only in the static export) and hands it to the loader
export function TodayRoute() {
  const date = useSearchParams().get("date");
  return <TodayLoader date={date || null} />;
}
