"use client";

import { useMutation } from "@tanstack/react-query";
import { Power } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useHealth } from "@/hooks/use-api";
import { api } from "@/lib/api";

// Stops `avaris serve` (POST /api/server/stop); asks inline first, never with a browser dialog.
// The server refuses while a job runs, so the button is off then too
export function StopServerButton() {
  const health = useHealth();
  const [confirming, setConfirming] = useState(false);
  const stop = useMutation({ mutationFn: api.stopServer, onSettled: () => setConfirming(false) });
  const busy = health.data?.job?.status === "running";
  // Stopped until the server answers again (restarted from the launcher)
  const stopped = stop.isSuccess && health.dataUpdatedAt <= stop.submittedAt;

  if (stopped) {
    return (
      <span role="status" className="truncate text-sm text-muted-foreground">
        Server stopped. Open Avaris from the Avaris Launcher to start it again.
      </span>
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-2">
      {stop.error && (
        <span role="alert" className="truncate text-sm text-destructive" title={stop.error.message}>
          {stop.error.message}
        </span>
      )}
      {confirming ? (
        <>
          <span className="text-sm text-muted-foreground">Stop the server?</span>
          <Button size="sm" variant="destructive" onClick={() => stop.mutate()} disabled={stop.isPending}>
            Stop
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
        </>
      ) : (
        <Button
          size="icon-sm" variant="ghost" aria-label="Stop server" title="Stop server"
          disabled={busy} onClick={() => { stop.reset(); setConfirming(true); }}
        >
          <Power />
        </Button>
      )}
    </div>
  );
}
