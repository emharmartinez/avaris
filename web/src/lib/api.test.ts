import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, SERVER_DOWN, api, apiUrl, isBusy } from "./api";

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
  it("posts the stop request", async () => {
    const fetchMock = mockFetch(202, { status: "stopping" });
    expect(await api.stopServer()).toEqual({ status: "stopping" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/server/stop");
    expect(init.method).toBe("POST");
  });
  it("puts the bankroll and posts bets as JSON", async () => {
    const fetchMock = mockFetch(200, {});
    await api.setBankroll(1000, 1);
    await api.placeBet({ game_id: "0022100047", market: "total", side: "over", line: 220.5, odds: 1.91, stake: 10 });
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([url, init]) => [url, init.method, init.body])).toEqual([
      ["/api/bankroll", "PUT", '{"starting":1000,"unit_pct":1}'],
      ["/api/bets", "POST", '{"game_id":"0022100047","market":"total","side":"over","line":220.5,"odds":1.91,"stake":10}'],
    ]);
  });
  it("deletes a bet without reading a body", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await api.deleteBet(7)).toBeUndefined();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect([url, init.method]).toEqual(["/api/bets/7", "DELETE"]);
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

  it("says the server is not running when the request never reaches it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = await api.health().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(0);
    expect((err as ApiError).message).toBe(SERVER_DOWN);
    expect(SERVER_DOWN).toMatch(/Avaris Launcher/);
  });

  it("passes an aborted request through untouched", async () => {
    const abort = new DOMException("The operation was aborted.", "AbortError");
    vi.stubGlobal("fetch", vi.fn(async () => { throw abort; }));
    await expect(api.health()).rejects.toBe(abort);
  });
});
