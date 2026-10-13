import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { health, job } from "@/test/data";
import { renderWithQuery } from "@/test/render";
import { RefreshButton } from "./refresh-button";

describe("RefreshButton", () => {
  it("posts a daily job, polls it and shows the outcome", async () => {
    let polls = 0;
    let posted: unknown = null;
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.post("*/api/jobs/daily", async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json(job("running"), { status: 202 });
      }),
      http.get("*/api/jobs/j1", () => HttpResponse.json(++polls < 2
        ? job("running", { log: ["features: 157 games"] })
        : job("succeeded", { message: "0 provisional, 2 final, 0 unchanged, 2 scored" }))),
    );
    renderWithQuery(<RefreshButton />);
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));
    expect(posted).toEqual({});
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(
      "Done: 0 provisional, 2 final, 0 unchanged, 2 scored"), { timeout: 4000 });
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
  });

  it("adopts the job already running when the server is busy", async () => {
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.post("*/api/jobs/daily", () =>
        HttpResponse.json({ detail: "job train j9 is running" }, { status: 409 })),
      http.get("*/api/jobs/j1", () => HttpResponse.json(job("running", { log: ["training"] }))),
    );
    renderWithQuery(<RefreshButton />);
    // The busy response triggers a health check, which now reports the running job
    server.use(http.get("*/api/health", () => HttpResponse.json(health(job("running")))));
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("training"));
    expect(screen.getByRole("button", { name: /refreshing/i })).toBeDisabled();
  });

  it("shows a job that was running before the page opened", async () => {
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health(job("running")))),
      http.get("*/api/jobs/j1", () => HttpResponse.json(job("running", { log: ["refresh"] }))),
    );
    renderWithQuery(<RefreshButton />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("refresh"));
    expect(screen.getByRole("button", { name: /refreshing/i })).toBeDisabled();
  });

  it("reports a refused submission", async () => {
    server.use(
      http.get("*/api/health", () => HttpResponse.json(health())),
      http.post("*/api/jobs/daily", () =>
        HttpResponse.json({ detail: "cross-site job submission refused" }, { status: 403 })),
    );
    renderWithQuery(<RefreshButton />);
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(
      "Failed: cross-site job submission refused"));
  });
});
