/* App-shell-only cache: warnings and private/API responses are NEVER cached. */
const CACHE = "suraksha-shell-v3";
const SHELL = ["/", "/app.js", "/styles.css", "/manifest.webmanifest", "/icon.svg"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith("suraksha-shell-") && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/webhook/")) return;
  const shellPath = event.request.mode === "navigate" && url.pathname === "/" ? "/" : url.pathname;
  if (!SHELL.includes(shellPath)) return;
  event.respondWith(fetch(event.request).then(response => {
    if (response.ok) {
      const copy = response.clone();
      event.waitUntil(caches.open(CACHE).then(cache => cache.put(shellPath, copy)));
    }
    return response;
  }).catch(async () => {
    const cached = await caches.match(shellPath);
    return cached || new Response("Offline app shell unavailable", { status: 503 });
  }));
});
