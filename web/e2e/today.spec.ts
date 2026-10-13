import { expect, test } from "@playwright/test";

// The fixture league's clock is frozen at 2021-11-27T17:00:00Z: today's two games
// (tip 00:00Z) are provisional, the previous day's two are final at 110-100

test("today lists the provisional games with win probabilities", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();
  await expect(page.getByText("Sat, Nov 27, 2021")).toBeVisible();
  await expect(page.getByRole("link", { name: "ATL @ DEN" })).toBeVisible();
  await expect(page.getByRole("link", { name: "BOS @ BKN" })).toBeVisible();
  await expect(page.getByText("Provisional", { exact: true })).toHaveCount(2);
  await expect(page.getByText("84%", { exact: true })).toBeVisible();
  await expect(page.getByText("final in 6h 00m", { exact: true })).toHaveCount(2);
  const dates = page.getByRole("navigation", { name: "Dates" });
  await expect(dates.getByRole("link", { name: "Next day" })).toHaveAttribute("href", "/?date=2021-11-28");
  await expect(dates.getByRole("link", { name: "Today", exact: true })).toHaveCount(0);
});

test("the previous day shows the finals with their scores", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Previous day" }).click();
  await expect(page).toHaveURL(/\/\?date=2021-11-26$/);
  await expect(page.getByText("Fri, Nov 26, 2021")).toBeVisible();
  await expect(page.getByRole("link", { name: "BKN @ ATL" })).toBeVisible();
  await expect(page.getByRole("link", { name: "DEN @ BOS" })).toBeVisible();
  await expect(page.getByText("Final", { exact: true })).toHaveCount(2);
  await expect(page.getByText("110", { exact: true })).toHaveCount(2);
  await expect(page.getByText("100", { exact: true })).toHaveCount(2);
  await expect(page.getByText(/^final in/)).toHaveCount(0);

  // Back to today from a pinned date
  await page.getByRole("navigation", { name: "Dates" }).getByRole("link", { name: "Today", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: "ATL @ DEN" })).toBeVisible();
});

test("a game opens its detail page with drivers and distributions", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "ATL @ DEN" }).click();
  await expect(page).toHaveURL(/\/game\/\?id=0022100047$/);
  await expect(page.getByRole("heading", { name: "ATL @ DEN", level: 1 })).toBeVisible();
  const drivers = page.getByRole("table", { name: "Win probability drivers" });
  await expect(drivers).toBeVisible();
  await expect(drivers.getByRole("cell", { name: "Form", exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "Margin drivers" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Total drivers" })).toBeVisible();
  await expect(page.locator(".recharts-surface").first()).toBeVisible();
  await expect(page.locator(".recharts-surface").nth(1)).toBeVisible();
  await expect(page.getByRole("region", { name: "DEN injuries" })).toBeVisible();
});

test("a final game shows its actual outcome and score", async ({ page }) => {
  await page.goto("/game/?id=0022100045");
  await expect(page.getByRole("heading", { name: "BKN @ ATL", level: 1 })).toBeVisible();
  await expect(page.getByText("Actual +10.0")).toBeVisible();
  await expect(page.getByText("Actual 210.0")).toBeVisible();
  await expect(page.getByRole("region", { name: "Score" })).toBeVisible();
  await expect(page.getByText("No injury report used (preseason or no report)")).toBeVisible();
});

test("Refresh runs the daily job and reports the outcome", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "ATL @ DEN" })).toBeVisible();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("status"))
    .toHaveText("Done: 0 provisional, 0 final, 2 unchanged, 0 scored", { timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  await expect(page.getByRole("link", { name: "ATL @ DEN" })).toBeVisible();
});
