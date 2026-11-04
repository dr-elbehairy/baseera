/* App-shell cache so the technician PWA opens without network. Network-first for the shell (HTML/JS/CSS) so every update
   reaches the phone on the next load; cache only as the offline fallback. API calls are never cached (app.js queues them). */
const CACHE = "baseera-field-v5";
const SHELL = ["/field/", "/field/index.html", "/field/app.js", "/field/manifest.json", "/static/styles.css"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => null)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (u.pathname.startsWith("/api/") || e.request.method !== "GET") return;          // network only
  e.respondWith(fetch(e.request).then((res) => { const cp = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, cp)); return res; })
    .catch(() => caches.match(e.request, { ignoreSearch: true })));
});
