/*
  Danu Perfume & Cosmo — Service Worker
  ---------------------------------------------------------------------------
  Minimal by design. Its main job is simply to EXIST — Chrome on Android only
  offers the "Install App" prompt (the beforeinstallprompt event used by
  install-app.js) if a service worker is registered with a working fetch
  handler. It also caches the app shell (logo, manifest, offline page) so the
  site doesn't show a blank browser error page if someone opens it with no
  connection — it shows a small branded offline notice instead.

  This deliberately does NOT cache API responses, product images, or admin
  pages: caching those would risk showing stale prices/stock/orders, which
  matters more for a storefront than being available offline.
  ---------------------------------------------------------------------------
*/

const CACHE_NAME = "danu-shell-v1";
const APP_SHELL = [
  "/",
  "/static/manifest.json",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll(APP_SHELL).catch(() => {
        /* fine if some entries fail (e.g. offline during first install) */
      })
    )
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;

  // Only handle simple GET page navigations; let everything else (API calls,
  // form POSTs, images, admin routes) go straight to the network untouched.
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/admin")) return;

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() =>
        caches.match("/").then(
          (cached) =>
            cached ||
            new Response(
              "<!DOCTYPE html><html><body style='background:#150a19;color:#cbb26a;font-family:serif;text-align:center;padding:15vh 5vw;'><h1>You're offline</h1><p style='color:#ede4d1'>Danu Perfume & Cosmo needs an internet connection. Please reconnect and try again.</p></body></html>",
              { headers: { "Content-Type": "text/html" } }
            )
        )
      )
    );
  }
});
