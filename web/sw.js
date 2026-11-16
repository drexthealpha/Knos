// The front door with no network (LAWS\UX\U7.md R24): after one visit, opening Knos offline shows the front door, not
// the browser's error page. Registered by the front door only. Network first, so a new build is seen at once; the kept
// copy only when the network fails. Kept: the front door's page (its styles are in it) and its number formatter, nothing
// else; every other request of the site goes to the network untouched, so pages load as before. Never kept: any other
// page, any answer of Knos's server (another site: this worker never sees it) or a person's own file or result, which
// live only on that server.
const KEPT = "knos-door-v1";
const HOME = new URL("./", self.location).href;
const FORMAT = new URL("i18n/format.js", HOME).href;
const isHome = (u) => u.origin === self.location.origin && (u.pathname === new URL(HOME).pathname || u.pathname === new URL(HOME).pathname + "index.html");

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(KEPT).then((c) => c.addAll([HOME, FORMAT])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(Promise.all([
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("knos-door-") && k !== KEPT).map((k) => caches.delete(k)))),
  ]).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== "GET" || u.origin !== self.location.origin) return;
  const page = r.mode === "navigate" && isHome(u), part = r.mode !== "navigate" && u.origin + u.pathname === FORMAT;
  if (!page && !part) return;                       // every other request goes to the network as before
  const key = page ? HOME : FORMAT;                // the front door is one page, whatever its ?lang= or #part
  e.respondWith((async () => {
    try {
      const got = await fetch(r);
      if (got && got.ok && got.type === "basic") { const copy = got.clone(); e.waitUntil(caches.open(KEPT).then((c) => c.put(key, copy))); }
      return got;
    } catch (err) {
      const kept = await caches.match(key, { ignoreVary: true });
      if (kept) return kept;
      throw err;
    }
  })());
});
