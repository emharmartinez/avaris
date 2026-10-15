"use client";

import { useSearchParams } from "next/navigation";
import { parseDate } from "@/lib/injuries";
import { TraditionalView } from "./traditional-view";

// Reads ?date= (client-only in the static export)
export function TraditionalRoute() {
  return <TraditionalView date={parseDate(useSearchParams().get("date"))} />;
}
