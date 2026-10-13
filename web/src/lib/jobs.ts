import type { Job } from "./types";

export function refreshInterval(job: Job | undefined): number | false {
  return job?.status === "running" ? 1000 : false;
}

export function jobSummary(job: Job): string {
  if (job.status === "running") return job.log.at(-1) ?? "Refreshing…";
  const prefix = job.status === "succeeded" ? "Done" : "Failed";
  return job.message ? `${prefix}: ${job.message}` : prefix;
}
