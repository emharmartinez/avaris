import { Suspense } from "react";
import { PageHeader } from "@/components/query-state";
import { Skeleton } from "@/components/ui/skeleton";
import { TodayRoute } from "@/components/today/today-route";

// useSearchParams needs a Suspense boundary in a static export
export default function TodayPage() {
  return (
    <Suspense fallback={<PageFallback />}>
      <TodayRoute />
    </Suspense>
  );
}

function PageFallback() {
  return (
    <>
      <PageHeader title="Today" />
      <Skeleton className="h-48 w-full" />
    </>
  );
}
