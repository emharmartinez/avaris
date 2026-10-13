"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, isBusy } from "@/lib/api";
import { refreshInterval } from "@/lib/jobs";
import { useHealth } from "./use-api";

// Runs `daily` as a server job and polls it; a job already running (startup daily, the
// CLI) is adopted instead. When it ends, every other query refetches
export function useRefresh() {
  const client = useQueryClient();
  const health = useHealth();
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const running = health.data?.job?.status === "running" ? health.data.job.job_id : null;
  const activeId = jobId ?? running;

  const job = useQuery({
    queryKey: ["job", activeId],
    queryFn: () => api.job(activeId!),
    enabled: !!activeId,
    refetchInterval: (query) => refreshInterval(query.state.data),
  });

  const submit = useMutation({
    mutationFn: () => api.submitJob("daily"),
    onSuccess: (submitted) => setJobId(submitted.job_id),
    onError: async (err) => {
      if (isBusy(err)) {
        const current = (await api.health()).job;
        if (current) return setJobId(current.job_id);
      }
      setError(err instanceof Error ? err.message : String(err));
    },
  });

  const status = job.data?.status;
  useEffect(() => {
    if (status && status !== "running") {
      void client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "job" });
    }
  }, [client, status]);

  return {
    refresh: () => {
      setError(null);
      submit.mutate();
    },
    running: submit.isPending || status === "running" || (!!activeId && !job.data),
    job: job.data,
    error,
  };
}
