// CyberGuard Service Worker v1.0
const CACHE = "cyberguard-v1";
const OFFLINE_URL = "/offline";

// Assets to cache on install
const PRECACHE = [
  "/",
  "/home",
  "/login",
  "/register",
  "/static/style.css",
  "/static/logo.svg",
  "/static/logo-icon.svg",
  "/static/app-icon.svg",
  "/static/manifest.json"
];

// Install: pre-cache core assets
self.addEventListener("install", function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(cache) {
      return cache.addAll(PRECACHE);
    }).then(function() {
      return self.skipWaiting();
    })
  );
});

// Activate: clean old caches
self.addEventListener("activate", function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE; })
            .map(function(k) { return caches.delete(k); })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

// Fetch: network-first for API/dynamic, cache-first for static
self.addEventListener("fetch", function(e) {
  var url = new URL(e.request.url);

  // Skip non-GET and cross-origin
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  // Static assets: cache-first
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(
      caches.match(e.request).then(function(cached) {
        return cached || fetch(e.request).then(function(res) {
          var clone = res.clone();
          caches.open(CACHE).then(function(c) { c.put(e.request, clone); });
          return res;
        });
      })
    );
    return;
  }

  // Pages: network-first, fallback to cache
  e.respondWith(
    fetch(e.request).then(function(res) {
      var clone = res.clone();
      caches.open(CACHE).then(function(c) { c.put(e.request, clone); });
      return res;
    }).catch(function() {
      return caches.match(e.request).then(function(cached) {
        return cached || caches.match("/login");
      });
    })
  );
});
