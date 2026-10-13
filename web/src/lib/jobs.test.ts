import { describe, expect, it } from "vitest";
import { jobSummary, refreshInterval } from "./jobs";
import type { Job } from "./types";

const job = (status: Job["status"], extra: Partial<Job> = {}): Job => ({
  job_id: "j1", kind: "daily", status, params: {}, created_at: "2021-11-27T17:00:00Z",
  finished_at: null, message: null, log: [], ...extra,
});

describe("jobs", () => {
  it("polls every second while a job runs", () => {
    expect(refreshInterval(job("running"))).toBe(1000);
    expect(refreshInterval(job("succeeded"))).toBe(false);
    expect(refreshInterval(undefined)).toBe(false);
  });
  it("summarizes a job by its last log line, then its message", () => {
    expect(jobSummary(job("running"))).toBe("Refreshing…");
    expect(jobSummary(job("running", { log: ["features: 157 games"] }))).toBe("features: 157 games");
    expect(jobSummary(job("succeeded", { message: "0 provisional, 2 final" }))).toBe("Done: 0 provisional, 2 final");
    expect(jobSummary(job("failed", { message: "boom" }))).toBe("Failed: boom");
  });
});
