import { Suspense } from "react";
import { TeamsRoute } from "@/components/teams/teams-route";
import { Skeleton } from "@/components/ui/skeleton";

// useSearchParams needs a Suspense boundary in a static export
export default function TeamsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <TeamsRoute />
    </Suspense>
  );
}
