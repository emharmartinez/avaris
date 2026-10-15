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

test("wide tables scroll inside the page, never the page itself", async ({ page }) => {
  for (const url of ["/backtests/?name=evaluation_2021-22_2024-25", "/performance/", "/teams/"]) {
    await page.setViewportSize({ width: 1024, height: 800 });
    await page.goto(url);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("table").first()).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, url).toBeLessThanOrEqual(0);
    await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeInViewport();
  }
});

test("edge: pick a game from the sidebar tab, type odds, read the edge", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Edge" }).click();
  await expect(page).toHaveURL(/\/edge\/$/);
  await expect(page.getByRole("heading", { name: "Edge", level: 1 })).toBeVisible();

  // The previous day's finals are stable whatever a Refresh test predicts today
  await page.getByRole("link", { name: "Previous day" }).click();
  await expect(page.getByText("Fri, Nov 26, 2021")).toBeVisible();
  await page.getByRole("combobox", { name: "Game" }).click();
  await page.getByRole("option", { name: /DEN @ BOS/ }).click();
  await expect(page).toHaveURL(/\/edge\/\?date=2021-11-26&game=\w+$/);
  await expect(page.getByRole("combobox", { name: "Game" })).toContainText("DEN @ BOS");
  await expect(page.getByText(/^Final prediction/)).toBeVisible();

  await expect(page.getByRole("button", { name: "Decimal" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "American" }).click();
  await page.getByLabel("DEN moneyline").fill("-110");
  await page.getByLabel("BOS moneyline").fill("-110");
  const ml = page.getByRole("table", { name: "Moneyline" });
  await expect(ml.getByRole("row", { name: /^BOS/ }).getByRole("cell").nth(2)).toHaveText("50.0%");
  await expect(ml.getByRole("row", { name: /^BOS/ }).getByRole("cell").nth(3)).toHaveText(/ pp$/);
  await expect(page.getByText(/Vig 4\.8%, removed/)).toBeVisible();

  await page.getByLabel("BOS line").fill("-2.5");
  await expect(page.getByRole("table", { name: "Spread" }).getByRole("row", { name: /^BOS −2\.5/ }))
    .toBeVisible();
});

test("traditional: live lines from the scoreboard, finals graded the day before", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Traditional" }).click();
  await expect(page).toHaveURL(/\/traditional\/$/);
  await expect(page.getByRole("heading", { name: "Traditional", level: 1 })).toBeVisible();

  // BOS @ BKN is in the 3rd quarter on the fixture server's scoreboard
  const live = page.getByRole("group", { name: "BOS @ BKN" });
  await expect(live.getByText("3rd Qtr · 4:12")).toBeVisible();
  await expect(live.getByText("Score", { exact: true })).toBeVisible();
  await expect(live.getByRole("columnheader")).toHaveText(["Market", "Pregame", "Live"]);
  await expect(live.getByRole("row", { name: /^Moneyline/ }).getByRole("cell").nth(2))
    .toHaveText(/^BKN \d+\.\d{2}BOS \d+\.\d{2}$/);
  await expect(page.getByText(/^Live scores as of/)).toBeVisible();
  await expect(page.getByRole("group", { name: "ATL @ DEN" }).getByText("Upcoming")).toBeVisible();

  await page.getByRole("link", { name: "Previous day" }).click();
  await expect(page).toHaveURL(/\/traditional\/\?date=2021-11-26$/);
  const final = page.getByRole("group", { name: "DEN @ BOS" });
  await expect(final.getByText("Final score")).toBeVisible();
  await expect(final.getByRole("row", { name: /^Moneyline/ }).getByRole("cell").nth(2))
    .toHaveText("BOS won");
  await expect(final.getByRole("row", { name: /^Total/ }).getByRole("cell").nth(2))
    .toHaveText(/^210 · (Over|Under) \d+\.\d$/);
});
