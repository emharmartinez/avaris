"use client";

import { useSearchParams } from "next/navigation";
import { parseDate } from "@/lib/injuries";
import { InjuriesView } from "./injuries-view";

// Reads ?date= (client-only in the static export); a malformed date falls back to today
export function InjuriesRoute() {
  return <InjuriesView date={parseDate(useSearchParams().get("date"))} />;
}
