// Jednoduchý service worker: aplikace jde přidat na plochu; data se vždy berou ze serveru.
const SHELL = "hulmanek-v2";
self.addEventListener("install", (e) => e.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/app.js", "/style.css", "/icon.svg"]))));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname.startsWith("/media/")) return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
