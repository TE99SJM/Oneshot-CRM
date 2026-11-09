// Minimal service worker: lets phones install FunnelHub as an app. It never caches, so you always see
// live data and the newest version after an update.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
