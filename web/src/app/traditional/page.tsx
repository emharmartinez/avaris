import { Suspense } from "react";
import { TraditionalRoute } from "@/components/traditional/traditional-route";
import { Skeleton } from "@/components/ui/skeleton";

// useSearchParams needs a Suspense boundary in a static export
export default function TraditionalPage() {
  return (
    <Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <TraditionalRoute />
    </Suspense>
  );
}
