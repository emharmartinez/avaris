import { Suspense } from "react";
import { EdgeRoute } from "@/components/edge/edge-route";
import { Skeleton } from "@/components/ui/skeleton";

// useSearchParams needs a Suspense boundary in a static export
export default function EdgePage() {
  return (
    <Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <EdgeRoute />
    </Suspense>
  );
}
