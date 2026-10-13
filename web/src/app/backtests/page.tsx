import { Suspense } from "react";
import { BacktestsRoute } from "@/components/backtests/backtests-route";
import { Skeleton } from "@/components/ui/skeleton";

// useSearchParams needs a Suspense boundary in a static export
export default function BacktestsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <BacktestsRoute />
    </Suspense>
  );
}
