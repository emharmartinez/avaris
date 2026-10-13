import { expect, test } from "@playwright/test";

test("serves an installable app shell", async ({ page, request }) => {
  const manifest = await (await request.get("/manifest.webmanifest")).json();
  expect(manifest).toMatchObject({ name: "Avaris", display: "standalone", start_url: "/" });
  const sizes = manifest.icons.map((i: { sizes: string }) => i.sizes);
  expect(sizes).toEqual(expect.arrayContaining(["192x192", "512x512"]));
  for (const icon of manifest.icons) {
    expect((await request.get(icon.src)).status()).toBe(200);
  }

  await page.goto("/");
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/manifest.webmanifest");
  const scope = await page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
  expect(scope).toBe(new URL("/", page.url()).href);
});

test("renders in dark mode, with a dark splash and title bar", async ({ page, request }) => {
  const manifest = await (await request.get("/manifest.webmanifest")).json();
  expect(manifest).toMatchObject({ background_color: "#0a0a0a", theme_color: "#0a0a0a" });

  await page.goto("/");
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute("content", "#0a0a0a");
  const style = await page.evaluate(() => {
    // The built CSS may express colors as lab() or hex, so paint the background to read RGB
    const ctx = document.createElement("canvas").getContext("2d")!;
    ctx.fillStyle = getComputedStyle(document.body).backgroundColor;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return { scheme: getComputedStyle(document.documentElement).colorScheme, rgb: [r, g, b] };
  });
  expect(style.scheme).toBe("dark");
  // oklch(0.145 0 0), the shadcn dark background, is about #0a0a0a
  for (const c of style.rgb) expect(c).toBeLessThan(20);
});

test("unknown API paths are JSON 404s, unknown pages the 404 page", async ({ request }) => {
  const api = await request.get("/api/nope");
  expect(api.status()).toBe(404);
  expect(api.headers()["content-type"]).toContain("application/json");
  const page = await request.get("/nope/");
  expect(page.status()).toBe(404);
  expect(page.headers()["content-type"]).toContain("text/html");
});

test("the service worker opens pages offline but never caches the API", async ({ page, context }) => {
  await page.goto("/teams/");
  await expect(page.getByRole("heading", { name: "Teams", level: 1 })).toBeVisible();
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload(); // now controlled by the worker
  await expect(page.getByRole("cell", { name: /BOS/ }).first()).toBeVisible();
  const cached = await page.evaluate(async () => {
    const names = await caches.keys();
    const urls = await Promise.all(names.map(async (n) =>
      (await (await caches.open(n)).keys()).map((r) => new URL(r.url).pathname)));
    return { names, urls: urls.flat() };
  });
  expect(cached.names).toHaveLength(1);
  expect(cached.names[0]).toMatch(/^avaris-shell-(?!__BUILD_ID__)/);
  expect(cached.urls).toContain("/teams/");
  expect(cached.urls.filter((u) => u.startsWith("/api/"))).toEqual([]);

  await context.setOffline(true);
  await page.goto("/teams/?id=1610612738");
  await expect(page.getByRole("heading", { name: "Teams", level: 1 })).toBeVisible();
  await expect(page.getByText(/Could not load/).first()).toBeVisible(); // data stays live-only
  await expect(page.getByText(/Server not running/).first()).toBeVisible();
  await context.setOffline(false);
});
