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

test("unknown API paths are JSON 404s, unknown pages the 404 page", async ({ request }) => {
  const api = await request.get("/api/nope");
  expect(api.status()).toBe(404);
  expect(api.headers()["content-type"]).toContain("application/json");
  const page = await request.get("/nope/");
  expect(page.status()).toBe(404);
  expect(page.headers()["content-type"]).toContain("text/html");
});
