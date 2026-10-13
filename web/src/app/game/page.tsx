import { Suspense } from "react";
import { GameRoute } from "@/components/game/game-route";
import { Skeleton } from "@/components/ui/skeleton";

// useSearchParams needs a Suspense boundary in a static export
export default function GamePage() {
  return (
    <Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <GameRoute />
    </Suspense>
  );
}
