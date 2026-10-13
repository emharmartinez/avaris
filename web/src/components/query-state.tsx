import type { UseQueryResult } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";

// Loading skeleton, error alert, or the data
export function QueryState<T>({ query, children, label = "data" }: {
  query: Pick<UseQueryResult<T>, "data" | "error" | "isPending">;
  children: (data: T) => React.ReactNode;
  label?: string;
}) {
  if (query.error) {
    return (
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>Could not load {label}</AlertTitle>
        <AlertDescription>{query.error.message}</AlertDescription>
      </Alert>
    );
  }
  if (query.isPending || query.data === undefined) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label={`Loading ${label}`}>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  return <>{children(query.data)}</>;
}

export function PageHeader({ title, description, children }: {
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </div>
  );
}
