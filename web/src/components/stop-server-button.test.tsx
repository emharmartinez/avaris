import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { health, job } from "@/test/data";
import { renderWithQuery } from "@/test/render";
import { server } from "@/test/server";
import { StopServerButton } from "./stop-server-button";

afterEach(() => vi.useRealTimers());

describe("StopServerButton", () => {
  it("asks first, then stops the server and says how to start it again", async () => {
    const user = userEvent.setup();
    let stops = 0;
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.post("*/api/server/stop", () => { stops += 1; return HttpResponse.json({ status: "stopping" }, { status: 202 }); }),
    );
    renderWithQuery(<StopServerButton />);
    await user.click(await screen.findByRole("button", { name: "Stop server" }));
    expect(stops).toBe(0);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Stop server" }));
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/server stopped.*avaris launcher/i);
    expect(stops).toBe(1);
  });

  it("is disabled while a job runs", async () => {
    server.use(http.get("*/api/health", () => HttpResponse.json(health(job("running")))));
    renderWithQuery(<StopServerButton />);
    const button = await screen.findByRole("button", { name: "Stop server" });
    await waitFor(() => expect(button).toBeDisabled());
  });

  it("shows the server's refusal", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.post("*/api/server/stop", () =>
        HttpResponse.json({ detail: "job daily j1 is running" }, { status: 409 })),
    );
    renderWithQuery(<StopServerButton />);
    await user.click(await screen.findByRole("button", { name: "Stop server" }));
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("job daily j1 is running");
  });

  it("comes back once the server answers again (started from the launcher)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.post("*/api/server/stop", () => HttpResponse.json({ status: "stopping" }, { status: 202 })),
    );
    renderWithQuery(<StopServerButton />);
    await user.click(await screen.findByRole("button", { name: "Stop server" }));
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/server stopped/i);
    await vi.advanceTimersByTimeAsync(60_000); // the next health poll succeeds
    expect(await screen.findByRole("button", { name: "Stop server" })).toBeEnabled();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
