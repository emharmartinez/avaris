import { expect, test } from "@playwright/test";

// Synthetic league, server clock frozen at 2021-11-27T17:00:00Z (today = 2021-11-27)

test("teams: ratings table, then a team's history panel", async ({ page }) => {
  await page.goto("/teams/");
  const table = page.getByRole("table");
  for (const name of ["Denver Nuggets", "Brooklyn Nets", "Boston Celtics", "Atlanta Hawks"]) {
    await expect(table.getByRole("link", { name: new RegExp(name) })).toBeVisible();
  }
  await expect(table.getByRole("row")).toHaveCount(5);

  await table.getByRole("link", { name: /Boston Celtics/ }).click();
  await expect(page).toHaveURL(/\/teams\/\?id=1610612738$/);
  const panel = page.getByRole("region", { name: "Boston Celtics" });
  await expect(panel).toContainText("2021-22");
  await expect(panel.locator('[data-slot="chart"]')).toHaveCount(2);
  await expect(panel.locator('[data-slot="chart"] svg.recharts-surface').first()).toBeVisible();
});

test("performance: regular-season metrics and the drift flag", async ({ page }) => {
  await page.goto("/performance/");
  await expect(page.getByRole("combobox", { name: "Season" })).toHaveText("2021-22");
  const regular = page.getByRole("table", { name: "Metrics by scope" })
    .getByRole("row", { name: /^Regular season/ });
  await expect(regular.getByRole("cell").nth(1)).toHaveText("2");

  const drift = page.getByRole("region", { name: "Drift" });
  const summary = drift.getByRole("status");
  await expect(summary).toContainText("Drift");
  await expect(summary).toContainText("regular log loss");
  await expect(drift).toContainText("evaluation_2021-22_2024-25");
});

test("backtests: list, then a report rendered without running its HTML", async ({ page }) => {
  await page.goto("/backtests/");
  await page.getByRole("link", { name: "Evaluation 2021-22 to 2024-25" }).click();
  await expect(page).toHaveURL(/\/backtests\/\?name=evaluation_2021-22_2024-25$/);

  const article = page.getByRole("article");
  await expect(article.getByRole("table")).toBeVisible();
  await expect(article).toContainText("<script>window.__injected = true</script>");
  expect(await page.evaluate(() => (window as unknown as { __injected?: boolean }).__injected))
    .toBeUndefined();

  const chart = page.getByRole("img", { name: "reliability_report.svg" });
  await chart.scrollIntoViewIfNeeded();
  await expect.poll(() => chart.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);
});

test("injuries: today's report lists the BOS player out", async ({ page }) => {
  await page.goto("/injuries/");
  await expect(page.getByText("Sat, Nov 27, 2021")).toBeVisible();
  const game = page.getByRole("region", { name: "BOS @ BKN" });
  const row = game.getByRole("row", { name: /Player, 2001/ });
  await expect(row.getByRole("cell").nth(0)).toHaveText("BOS");
  await expect(row.getByRole("cell").nth(2)).toHaveText("out");
  await expect(game.getByRole("group", { name: "BOS impact" })).toContainText("Player 2001");
});
