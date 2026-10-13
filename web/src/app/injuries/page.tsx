import { Suspense } from "react";
import { InjuriesRoute } from "@/components/injuries/injuries-route";
import { Skeleton } from "@/components/ui/skeleton";

// useSearchParams needs a Suspense boundary in a static export
export default function InjuriesPage() {
  return (
    <Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <InjuriesRoute />
    </Suspense>
  );
}
