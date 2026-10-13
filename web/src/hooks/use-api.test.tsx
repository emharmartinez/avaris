import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { health } from "@/test/data";
import { server } from "@/test/server";
import { useHealth } from "./use-api";

afterEach(() => {
  vi.useRealTimers();
  focusManager.setFocused(undefined);
});

describe("useHealth", () => {
  it("keeps polling while the app is minimized, so idle shutdown leaves the server up", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    server.use(http.get("*/api/health", () => { calls += 1; return HttpResponse.json(health()); }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderHook(() => useHealth(), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    });
    await waitFor(() => expect(calls).toBe(1));
    focusManager.setFocused(false); // minimized or in the background
    await vi.advanceTimersByTimeAsync(60_000);
    await waitFor(() => expect(calls).toBe(2));
  });
});
