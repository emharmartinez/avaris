import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;

// Runs against the built export (`out/`) served by the API on the synthetic league with a
// frozen clock (tests/fixtures/web_server.py); `npm run test:e2e` builds first
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `uv run python -m tests.fixtures.web_server --web web/out --port ${PORT}`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/api/health`,
    timeout: 180_000,
    reuseExistingServer: false,
    stdout: "pipe",
  },
});
