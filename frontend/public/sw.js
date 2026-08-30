/**
 * AERP service worker — what turns the site into an installable app.
 *
 * Two caches, deliberately handled differently, because the app shell and the data have
 * opposite requirements:
 *
 *   DOCUMENT (index.html)      NETWORK-FIRST.  It names the hashed bundle, so caching it is
 *                              caching the whole app version. Serving it cache-first pinned
 *                              every returning visitor to the build they first loaded: the
 *                              server had the new bundle, index.html on the server pointed at
 *                              it, and the browser never asked. Three screener columns stayed
 *                              on screen for a user a full day after they were deleted,
 *                              deployed and verified live. Offline still falls back to cache.
 *   ASSETS (hashed js/css)     cache-first, and safely so: the filename contains a content
 *                              hash, so a new build is a new URL and can never be stale.
 *   DATA  (/data/*.json)       network-first, falling back to cache.  A price must never be
 *                              served from cache when the network is available - a stale
 *                              price that LOOKS live is the one failure this whole project
 *                              keeps running into. Offline, a clearly-old number beats a
 *                              blank screen, so the fallback stands.
 *
 * Bump SHELL_VERSION on any change to this file. Old caches are deleted on activate, so a
 * stale shell cannot outlive a deploy. Note this is now a backstop rather than the mechanism:
 * with the document fetched network-first, a deploy reaches the user without needing anyone to
 * remember to bump anything - which is the point, because nobody did for the whole life of v1.
 */

const SHELL_VERSION = "aerp-shell-v2";
const DATA_CACHE = "aerp-data-v1";

// Derived from where the worker itself was served, so the same file works at "/" and at
// "/AERP/". Hardcoding "/" meant every precache entry 404'd under a subpath and the install
// silently cached nothing.
const SCOPE = new URL("./", self.location).pathname;

const SHELL_ASSETS = [
  SCOPE,
  `${SCOPE}index.html`,
  `${SCOPE}manifest.webmanifest`,
  `${SCOPE}icons/icon-192.png`,
  `${SCOPE}icons/icon-512.png`,
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_VERSION)
      // addAll is atomic - one 404 fails the whole install - and the hashed build assets are
      // not known here by name, so only the entry points are precached. Everything else is
      // picked up on first use by the fetch handler below.
      .then((cache) => cache.addAll(SHELL_ASSETS).catch(() => undefined))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== SHELL_VERSION && k !== DATA_CACHE)
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function isData(url) {
  return url.pathname.startsWith(`${SCOPE}data/`);
}

function isDocument(request) {
  return request.mode === "navigate" || request.destination === "document";
}

function isShell(request, url) {
  return (
    request.destination === "script" ||
    request.destination === "style" ||
    request.destination === "font" ||
    url.pathname.startsWith(`${SCOPE}icons/`) ||
    url.pathname.startsWith(`${SCOPE}assets/`)
  );
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Never cache the live-price proxy. Its entire purpose is to be current, and a service
  // worker quietly replaying a two-minute-old quote would defeat it completely.
  if (url.pathname.startsWith("/quote") || url.hostname.includes("price-proxy")) return;

  if (isData(url)) {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          if (resp.ok) {
            const copy = resp.clone();
            caches.open(DATA_CACHE).then((c) => c.put(request, copy));
          }
          return resp;
        })
        .catch(() =>
          caches.match(request).then(
            (hit) =>
              hit ||
              new Response(JSON.stringify({ offline: true }), {
                status: 503,
                headers: { "content-type": "application/json" },
              }),
          ),
        ),
    );
    return;
  }

  // The document decides which bundle runs, so it is always fetched fresh when the network
  // allows. A cached copy is kept only to boot the app offline.
  if (isDocument(request)) {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          if (resp.ok && resp.type === "basic") {
            const copy = resp.clone();
            caches.open(SHELL_VERSION).then((c) => c.put(request, copy));
          }
          return resp;
        })
        .catch(() =>
          caches
            .match(request)
            .then((hit) => hit || caches.match(`${SCOPE}index.html`))
            .then((hit) => hit || new Response("", { status: 504 })),
        ),
    );
    return;
  }

  if (isShell(request, url)) {
    event.respondWith(
      caches.match(request).then((hit) => {
        if (hit) return hit;
        return fetch(request)
          .then((resp) => {
            if (resp.ok && resp.type === "basic") {
              const copy = resp.clone();
              caches.open(SHELL_VERSION).then((c) => c.put(request, copy));
            }
            return resp;
          })
          .catch(() => new Response("", { status: 504 }));
      }),
    );
  }
});
