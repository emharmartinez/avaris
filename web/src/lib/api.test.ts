import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, apiUrl, isBusy } from "./api";

function mockFetch(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("builds same-origin URLs by default", () => {
    expect(apiUrl("/api/teams")).toBe("/api/teams");
  });
  it("encodes path and query values", () => {
    const fetchMock = mockFetch(200, { date: "2021-11-27", games: [] });
    void api.predictions("2021-11-27");
    void api.game("0022100047");
    void api.team(1610612743, "2021-22");
    void api.backtest("a b");
    expect(fetchMock.mock.calls.map((c) => (c as unknown[])[0])).toEqual([
      "/api/predictions?date=2021-11-27",
      "/api/games/0022100047",
      "/api/teams/1610612743?season=2021-22",
      "/api/backtests/a%20b",
    ]);
    expect(api.chartUrl("eval", "pit.svg")).toBe("/api/backtests/eval/charts/pit.svg");
  });
  it("posts jobs as JSON", async () => {
    const fetchMock = mockFetch(202, { job_id: "j1", status: "running" });
    const job = await api.submitJob("daily");
    expect(job.job_id).toBe("j1");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/jobs/daily");
    expect(init.method).toBe("POST");
    expect(init.body).toBe("{}");
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
  });
  it("joins FastAPI's validation messages", async () => {
    mockFetch(422, { detail: [{ loc: ["query", "date"], msg: "Input should be a valid date", type: "date_from_datetime_parsing" }] });
    const err = await api.predictions("nope").catch((e: unknown) => e);
    expect((err as ApiError).message).toBe("date: Input should be a valid date");
  });

  it("raises ApiError with the server's detail", async () => {
    mockFetch(409, { detail: "job daily j1 is running" });
    const err = await api.submitJob("daily").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).message).toBe("job daily j1 is running");
    expect(isBusy(err)).toBe(true);
    expect(isBusy(new Error("x"))).toBe(false);
  });
});
