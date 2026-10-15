// Avaris app shell: pages open offline from the last visit; /api is never cached, so data
// is always live. Hashed build assets are cache-first; pages are network-first.
const CACHE = "avaris-shell-__BUILD_ID__"; // stamped by scripts/stamp-sw.mjs
const SHELL = ["/", "/teams/", "/performance/", "/backtests/", "/injuries/", "/edge/",
  "/traditional/", "/game/",
  "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  // One missing page must not block the worker: cache what loads
  event.waitUntil(caches.open(CACHE).then((cache) =>
    Promise.allSettled(SHELL.map((url) => cache.add(url)))));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    // Revalidate past the HTTP cache: a stale page asks for chunks a rebuild deleted
    const response = await fetch(request, { cache: "no-cache" });
    // One entry per page: /game/?id=... is cached as /game/
    if (response.ok && !response.redirected) {
      cache.put(new URL(request.url).pathname, response.clone());
    }
    return response;
  } catch {
    // Offline: the page without its query string (/game/?id=... is /game/), else Today
    return (await cache.match(request, { ignoreSearch: true })) ?? (await cache.match("/"));
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;
  if (event.request.mode === "navigate") {
    event.respondWith(networkFirst(event.request));
  } else if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(event.request));
  }
});
