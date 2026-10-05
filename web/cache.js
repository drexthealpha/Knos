// What the page has read before, kept so that a view seen once is shown again at once: an account read from devnet, an
// answer of GitHub's API, a file of the site. It is kept in memory and in sessionStorage (this tab, until it is closed;
// a browser that refuses storage keeps the memory alone), and it is never the last word: a view shows what was kept,
// says how old it is, and reads everything again behind it. What comes back replaces what was shown.
//
// Nothing that decides money is read from here. The checks before a transaction is built (a balance, whether an order
// exists, the simulation) ask devnet every time; this file is for what a person looks at.
export const PREFIX = "knos:kept:1:";       // the 1 is the shape of an entry: change it and old entries are never read
export const MAX_ENTRIES = 80, MAX_CHARS = 200_000;     // of one tab: the oldest goes first, and one large answer is kept in memory only

// JSON, with the two things an account's reader gives that JSON has no word for
const pack = (v) => JSON.stringify(v, (_, x) => (typeof x === "bigint" ? { $big: String(x) } : x instanceof Uint8Array ? { $bytes: btoa(String.fromCharCode(...x)) } : x));
const unpack = (s) => JSON.parse(s, (_, x) => (x && typeof x === "object" && typeof x.$big === "string" ? BigInt(x.$big)
  : x && typeof x === "object" && typeof x.$bytes === "string" ? Uint8Array.from(atob(x.$bytes), (c) => c.charCodeAt(0)) : x));
export const same = (a, b) => { try { return pack(a) === pack(b); } catch { return false; } };

// "12 s", "3 min", "2 h": how long ago, to the unit a person would say
export const ago = (ms) => { const s = Math.max(0, Math.round(ms / 1000)); return s < 120 ? `${s} s` : s < 7200 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`; };

const tabStorage = () => { try { return globalThis.sessionStorage ?? null; } catch { return null; } };      // reading the property itself can throw (a sandboxed frame)

export function makeCache({ storage = tabStorage(), now = () => Date.now(), prefix = PREFIX } = {}) {
  const memory = new Map();       // key -> { value, at }
  const stored = () => { try { return Object.keys(storage).filter((k) => k.startsWith(prefix)); } catch { return []; } };
  const drop = (k) => { try { storage.removeItem(k); } catch { /* storage is refused: memory holds it */ } };

  // what was kept under a key, as { value, at (ms since 1970, when it was read) }, or null
  function get(key) {
    if (memory.has(key)) return memory.get(key);
    let hit = null;
    try {
      const raw = storage?.getItem(prefix + key);
      const got = raw ? unpack(raw) : null;
      if (got && Number.isFinite(got.at) && got.at <= now() + 1000 && "value" in got) hit = { value: got.value, at: got.at };
    } catch { /* not ours, or not JSON: as if nothing was kept */ }
    if (hit) memory.set(key, hit);
    return hit;
  }

  function set(key, value) {
    const entry = { value, at: now() };
    memory.set(key, entry);
    if (memory.size > MAX_ENTRIES) memory.delete(memory.keys().next().value);
    if (!storage) return entry;
    let text;
    try { text = pack(entry); } catch { return entry; }
    if (text.length > MAX_CHARS) { drop(prefix + key); return entry; }
    const write = () => storage.setItem(prefix + key, text);
    try {
      const keys = stored();
      if (keys.length >= MAX_ENTRIES) oldest(keys, keys.length - MAX_ENTRIES + 1).forEach(drop);
      write();
    } catch {       // full, or refused: make room once, then leave it to memory
      try { oldest(stored(), 20).forEach(drop); write(); } catch { drop(prefix + key); }
    }
    return entry;
  }

  const oldest = (keys, n) => keys.map((k) => { try { return [k, unpack(storage.getItem(k)).at || 0]; } catch { return [k, 0]; } }).sort((a, b) => a[1] - b[1]).slice(0, n).map(([k]) => k);
  const forget = (key) => { memory.delete(key); drop(prefix + key); };

  // Show a view twice: first from what was kept, then from what is read now.
  //
  // `draw(read, pass)` is the view. It reads everything it shows through `read(key, load)` and writes the page.
  //   The first pass gives it only what was kept, and stops quietly at the first thing that was not: then nothing was
  //   drawn from memory and the second pass is the first the reader sees. In it `pass.kept` is true and `pass.at()` is
  //   when the oldest thing shown was read.
  //   The second pass calls every `load`, keeps the answers, and `pass.same()` says whether everything read so far is
  //   what the first pass showed: a view that is the same need not be written again.
  //   `pass.peek(key)` is what was kept under a key, or null, in either pass: for a part of the view that may come later.
  // Resolves to { shown: whether the first pass drew, changed: whether the second read anything different }.
  // A second pass that fails throws what it failed with, with `kept` set to when the view still on the page was read
  // (or null when nothing was drawn), so the caller can say that it is old instead of taking it away.
  async function twice(draw) {
    const MISS = {};
    let at = Infinity, shown = false;
    try {
      await draw(async (key) => { const hit = get(key); if (!hit) throw MISS; at = Math.min(at, hit.at); return hit.value; }, { kept: true, at: () => at, same: () => false, peek: get });
      shown = true;
    } catch (e) { if (e !== MISS) shown = false; }
    let changed = false;
    try {
      await draw(async (key, load) => {
        const had = get(key), value = await load();
        if (!had || !same(had.value, value)) changed = true;
        set(key, value);
        return value;
      }, { kept: false, at: () => now(), same: () => shown && !changed, peek: get });
    } catch (e) {
      if (e && typeof e === "object") e.kept = shown ? at : null;
      throw e;
    }
    return { shown, changed };
  }

  return { get, set, forget, twice, now };
}

export const cache = makeCache();
// the keys, so that two views reading the same thing share what was kept
export const ghKey = (path) => `gh:${path}`;
export const fileKey = (path) => `file:${path}`;
export const rpcKey = (rpc, method, params) => `rpc:${rpc}:${method}:${JSON.stringify(params)}`;
// The sentence beside a view drawn from what was kept, and the one for a view that could not be read again.
export const asOf = (at, now = Date.now()) => `as of ${ago(now - at)} ago`;
