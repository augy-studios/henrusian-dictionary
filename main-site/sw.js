// The version constant, and the whole trigger for the update bar: the browser
// only sees an update when this file changes byte for byte. Bump it on every
// deploy that changes anything below, not once per release. The app shell is
// served from this cache and nowhere else, so a forgotten bump means nobody
// gets the new code.
const CACHE = "henrusian-v7";

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
  "/js/update.js",
  "/link",
  "/link.html",
  "/link.css",
  "/hrd-main.png",
  "/hrd-192.png",
  "/hrd-512.png",
  "/favicon.ico",
  "/manifest.json"
];

const SHELL = new Set(ASSETS);

// No skipWaiting() here. A new worker installs and then waits until somebody
// presses Reload in the update bar.
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ASSETS))
  );
});

// No clients.claim() here either. Claiming on activation would do silently
// what the update bar exists to ask about.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))
      )
    )
  );
});

self.addEventListener("message", (event) => {
  const type = typeof event.data === "string" ? event.data : event.data?.type;

  // The only place either of these is ever called.
  if (type === "skip-waiting") {
    event.waitUntil(self.skipWaiting().then(() => self.clients.claim()));
  }
});

// Sync state must never be answered from the cache: a stale copy would show the wrong link
// or the wrong favourites. The entry catalogue is different, and stays cache first.
const NEVER_CACHE = ["/api/link", "/api/codes", "/api/favourites", "/api/recover"];

function bypassCache(request) {
  if (request.method !== "GET") return true;
  const path = new URL(request.url).pathname;
  return NEVER_CACHE.some((prefix) => path.startsWith(prefix));
}

// The app shell comes from this worker's own cache only, never refreshed in the
// background, so the page on screen is always one whole version: new HTML never
// meets old JavaScript. Matched on the path alone, so deep links such as
// /?tab=dict&entry=123 open offline too.
function shellPath(request) {
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return null;
  return SHELL.has(url.pathname) ? url.pathname : null;
}

self.addEventListener("fetch", (event) => {
  if (bypassCache(event.request)) {
    event.respondWith(fetch(event.request));
    return;
  }

  const shell = shellPath(event.request);
  if (shell) {
    event.respondWith(
      caches.open(CACHE)
        .then((cache) => cache.match(shell))
        .then((cached) => cached || fetch(event.request))
    );
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
