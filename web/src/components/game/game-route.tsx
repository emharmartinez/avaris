"use client";

import { useSearchParams } from "next/navigation";
import { GameLoader } from "./game-loader";

// Reads ?id= (client-only in the static export) and hands it to the loader
export function GameRoute() {
  const id = useSearchParams().get("id");
  return <GameLoader id={id || null} />;
}
