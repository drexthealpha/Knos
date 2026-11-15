// The app works offline: its shell (page, styles, scripts) is kept here and served when the network is not there.
// API answers are never cached (money and proofs are read live); a brief edit made offline waits in IndexedDB and is
// sent by Background Sync when the connection is back (static/ux.js queues it).
const SHELL = "knos-shell-v2";
const FILES = ["/app/", "/static/style.css", "/static/i18n.js", "/static/passkey_wallet.js", "/static/valley.js", "/static/app.js",
  "/static/ux.js", "/static/ux_more.js", "/static/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (e) => { e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/") || u.pathname.startsWith("/auth/")) return;
  // network first, so a deploy is seen at once; the kept shell when offline
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok && FILES.includes(u.pathname)) { const copy = r.clone(); caches.open(SHELL).then((c) => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request).then((m) => m || caches.match("/app/"))));
});

function db() {
  return new Promise((ok, bad) => { const r = indexedDB.open("knos-queue", 1); r.onupgradeneeded = () => r.result.createObjectStore("q", { autoIncrement: true });
    r.onsuccess = () => ok(r.result); r.onerror = () => bad(r.error); });
}
async function flush() {
  const d = await db();
  const all = await new Promise((ok) => { const out = []; const c = d.transaction("q").objectStore("q").openCursor();
    c.onsuccess = () => { const cur = c.result; if (cur) { out.push([cur.key, cur.value]); cur.continue(); } else ok(out); }; });
  for (const [k, v] of all) {
    const r = await fetch(v.path, { method: "POST", headers: { "Content-Type": "application/json", ...(v.auth ? { Authorization: v.auth } : {}) }, body: JSON.stringify(v.body) });
    if (r.ok || (r.status >= 400 && r.status < 500)) await new Promise((ok) => { const t = d.transaction("q", "readwrite"); t.objectStore("q").delete(k); t.oncomplete = ok; });
  }
}
self.addEventListener("sync", (e) => { if (e.tag === "knos-queue") e.waitUntil(flush()); });
