/**
 * AERP service worker — what turns the site into an installable app.
 *
 * Two caches, deliberately handled differently, because the app shell and the data have
 * opposite requirements:
 *
 *   SHELL (html/js/css/icons)  cache-first.  It only changes when a build ships, and the
 *                              version bump below is what retires the old one.
 *   DATA  (/data/*.json)       network-first, falling back to cache.  A price must never be
 *                              served from cache when the network is available - a stale
 *                              price that LOOKS live is the one failure this whole project
 *                              keeps running into. Offline, a clearly-old number beats a
 *                              blank screen, so the fallback stands.
 *
 * Bump SHELL_VERSION on any change to this file or the app shell. Old caches are deleted on
 * activate, so a stale shell cannot outlive a deploy.
 */

const SHELL_VERSION = "aerp-shell-v1";
const DATA_CACHE = "aerp-data-v1";

const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
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
  return url.pathname.startsWith("/data/");
}

function isShell(request, url) {
  return (
    request.destination === "document" ||
    request.destination === "script" ||
    request.destination === "style" ||
    request.destination === "font" ||
    url.pathname.startsWith("/icons/") ||
    url.pathname.startsWith("/assets/")
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
          .catch(() => {
            // A single-page app: any navigation offline should still boot the shell and let
            // the router take over, rather than showing the browser's dinosaur.
            if (request.destination === "document") return caches.match("/index.html");
            return new Response("", { status: 504 });
          });
      }),
    );
  }
});
