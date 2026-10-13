"use client";

import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRefresh } from "@/hooks/use-refresh";
import { jobSummary } from "@/lib/jobs";

export function RefreshButton() {
  const { refresh, running, job, error } = useRefresh();
  const text = error ? `Failed: ${error}` : job ? jobSummary(job) : null;
  return (
    <div className="flex min-w-0 items-center gap-3">
      {text && (
        <span role="status" className="truncate text-sm text-muted-foreground" title={text}>
          {text}
        </span>
      )}
      <Button size="sm" onClick={refresh} disabled={running}>
        <RefreshCw className={running ? "animate-spin" : undefined} />
        {running ? "Refreshing" : "Refresh"}
      </Button>
    </div>
  );
}
