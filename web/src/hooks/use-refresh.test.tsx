import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { health, job } from "@/test/data";
import { server } from "@/test/server";
import { useRefresh } from "./use-refresh";

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => {
    // A page's query next to the button: it must refetch once the job ends
    const teams = useQuery({ queryKey: ["teams"], queryFn: () => fetch("/api/teams").then((r) => r.json()) });
    return { refresh: useRefresh(), teams };
  }, { wrapper });
  return { ...hook, client };
}

describe("useRefresh", () => {
  it("refetches the other queries once, after the job ends", async () => {
    let teamCalls = 0;
    let jobState: "running" | "succeeded" = "running";
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.get("*/api/teams", () => HttpResponse.json(++teamCalls)),
      http.post("*/api/jobs/daily", () => HttpResponse.json(job("running"), { status: 202 })),
      http.get("*/api/jobs/j1", () => HttpResponse.json(job(jobState))),
    );
    const { result } = setup();
    await waitFor(() => expect(result.current.teams.data).toBe(1));
    act(() => result.current.refresh.refresh());
    await waitFor(() => expect(result.current.refresh.job?.status).toBe("running"));
    expect(teamCalls).toBe(1);
    jobState = "succeeded";
    await waitFor(() => expect(result.current.teams.data).toBe(2), { timeout: 3000 });
    expect(result.current.refresh.running).toBe(false);
  });

  it("follows a newer job the server is running after its own job ended", async () => {
    let current: ReturnType<typeof job> | null = null;
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health(current))),
      http.get("*/api/teams", () => HttpResponse.json(1)),
      http.post("*/api/jobs/daily", () => HttpResponse.json(job("running"), { status: 202 })),
      http.get("*/api/jobs/j1", () => HttpResponse.json(job("succeeded", { message: "done" }))),
      http.get("*/api/jobs/j2", () => HttpResponse.json(job("running", { job_id: "j2", log: ["startup daily"] }))),
    );
    const { result, client } = setup();
    act(() => result.current.refresh.refresh());
    await waitFor(() => expect(result.current.refresh.job?.status).toBe("succeeded"));
    // e.g. `avaris daily` from the CLI, seen by the next health check
    current = job("running", { job_id: "j2" });
    await act(() => client.invalidateQueries({ queryKey: ["health"] }));
    await waitFor(() => expect(result.current.refresh.job?.job_id).toBe("j2"), { timeout: 3000 });
    expect(result.current.refresh.running).toBe(true);
  });
});
