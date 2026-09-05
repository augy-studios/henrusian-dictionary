const CACHE = "henrusian-v6";

const ASSETS = [
  "/",
  "/index.html",
  "/style.css",
  "/script.js",
  "/js/icons.js",
  "/js/ui.js",
  "/js/theme.js",
  "/js/sync.js",
  "/js/account.js",
  "/link",
  "/link.html",
  "/link.css",
  "/hrd-main.png",
  "/hrd-192.png",
  "/hrd-512.png",
  "/favicon.ico",
  "/manifest.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// Sync state must never be answered from the cache: a stale copy would show the wrong link
// or the wrong favourites. The entry catalogue is different, and stays cache first.
const NEVER_CACHE = ["/api/link", "/api/codes", "/api/favourites", "/api/recover"];

function bypassCache(request) {
  if (request.method !== "GET") return true;
  const path = new URL(request.url).pathname;
  return NEVER_CACHE.some((prefix) => path.startsWith(prefix));
}

self.addEventListener("fetch", (event) => {
  if (bypassCache(event.request)) {
    event.respondWith(fetch(event.request));
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetched = fetch(event.request).then((response) => {
        const clone = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, clone));
        return response;
      }).catch(() => cached);
      return cached || fetched;
    })
  );
});
