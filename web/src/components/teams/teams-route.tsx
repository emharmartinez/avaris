"use client";

import { useSearchParams } from "next/navigation";
import { parseTeamId } from "@/lib/teams";
import { TeamsView } from "./teams-view";

// Reads ?id= (client-only in the static export) and hands it to the view
export function TeamsRoute() {
  return <TeamsView id={parseTeamId(useSearchParams().get("id"))} />;
}
