import { Suspense } from "react";
import { PerformanceRoute } from "@/components/performance/performance-route";
import { Skeleton } from "@/components/ui/skeleton";

// useSearchParams needs a Suspense boundary in a static export
export default function PerformancePage() {
  return (
    <Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <PerformanceRoute />
    </Suspense>
  );
}
