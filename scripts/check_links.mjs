// Every link of the public text leads somewhere: node scripts/check_links.mjs [--site <dir>] [--no-external]
//
// (a) A relative link in a tracked .md or .html file (git ls-files) whose target file is missing is dead. Links inside
//     fenced code blocks and inline code are not links. #anchors and ?queries are stripped; a target resolves against
//     the file's folder, and a link starting with "/" against the repository root (web/: against web/).
// (b) An external http(s) link is fetched once (GET, 10 s, a browser's User-Agent, 8 at a time and 2 to one host): a
//     status of 400 or more, or a network error, is dead. A 403 or 429 (sites that turn bots away) is tried once more,
//     after the Retry-After it names (5 s when none, 30 s at most), before it counts.
// (c) --site <dir> also checks every .html and .md file of a built Pages site the same way, its relative links
//     resolved inside <dir>.
// Prints `DEAD <file>:<line> <url> <status>` for each dead link and a last line `PASS check_links: 0 dead of N` or
// `FAIL check_links: D dead of N`. Exit 1 on any dead link.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const siteAt = args.indexOf("--site");
const SITE = siteAt >= 0 ? resolve(args[siteAt + 1] || ".") : null;
const EXTERNAL = !args.includes("--no-external");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const TIMEOUT_MS = 10_000, CONCURRENCY = 8;

function lineOf(text, index) {
  let n = 1;
  for (let i = 0; i < index; i++) if (text.charCodeAt(i) === 10) n++;
  return n;
}

// the same length, so offsets keep their lines: code is blanked, newlines stay
const blank = (s) => s.replace(/[^\n]/g, " ");

function markdownLinks(text) {
  let t = text.replace(/^( {0,3})(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^\1?\2[ \t]*$|(?![\s\S]))/gm, blank);   // fenced code
  // indented code: a run of lines indented 4 spaces or a tab, after a blank line, outside a list
  const lines = t.split("\n");
  let code = false;
  for (let i = 0; i < lines.length; i++) {
    const prev = i ? lines[i - 1] : "", indented = /^(?: {4}|\t)/.test(lines[i]);
    if (indented && (code || (!prev.trim() && !/^\s*(?:[-*+]|\d+\.)\s/.test(lines.slice(0, i).reverse().find((l) => l.trim()) || "")))) {
      code = true;
      lines[i] = blank(lines[i]);
    } else if (lines[i].trim()) code = false;
  }
  t = lines.join("\n");
  t = t.replace(/<!--[\s\S]*?-->/g, blank);
  t = t.replace(/(`+)[^`\n]+?\1/g, blank);                                                             // inline code
  const out = [];
  const add = (url, index) => out.push({ url: url.trim(), index });
  for (const m of t.matchAll(/!?\[(?:[^\]\n]|\][^(\n])*?\]\(\s*<?([^)\s>]+)>?(?:\s+["'][^"')]*["'])?\s*\)/g)) add(m[1], m.index);
  for (const m of t.matchAll(/^\s{0,3}\[[^\]\n]+\]:\s*<?(\S+?)>?(?:\s+["'(].*)?$/gm)) add(m[1], m.index);
  for (const m of t.matchAll(/<(https?:\/\/[^>\s]+)>/g)) add(m[1], m.index);
  for (const m of t.matchAll(/\b(?:href|src)\s*=\s*["']([^"']+)["']/gi)) add(m[1], m.index);
  // bare addresses GitHub turns into links, outside the links found above
  const taken = t.replace(/!?\[[^\]\n]*\]\([^)\n]*\)|<[^>\n]*>|^\s{0,3}\[[^\]\n]+\]:.*$/gm, blank);
  for (const m of taken.matchAll(/https?:\/\/[^\s<>()"'`\]|]+/g)) add(m[0].replace(/[.,;:!?*_]+$/, ""), m.index);
  return out;
}

function htmlLinks(text) {
  const t = text.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, blank).replace(/<!--[\s\S]*?-->/g, blank);
  // a preconnect or dns-prefetch hint names an origin to open early, never a page to visit
  const pages = t.replace(/<link\b[^>]*\brel=["'](?:preconnect|dns-prefetch)["'][^>]*>/gi, blank);
  return [...pages.matchAll(/\b(?:href|src)\s*=\s*["']([^"']*)["']/gi)].map((m) => ({ url: m[1].trim(), index: m.index }));
}

const SKIP = /^(?:#|mailto:|javascript:|data:|tel:|about:|blob:|\/\/)|\$\{|\{\{|%7B%7B|^\{[A-Z]+\}|^\s*$/i;
// names no one can visit (RFC 2606 and 6761, a machine's own address): an example in the text, never a page
const RESERVED = /^https?:\/\/(?:[^/@]*@)?(?:[^/:?#]*\.)?(?:invalid|example|test|localhost|example\.com|example\.org|example\.net|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::\d+)?(?:[/?#]|$)/i;
// folders a server serves: a link from a page there that starts with the prefix is a file of the folder; any other
// link starting with "/" is one of the server's routes, not a file, and is not checked here
const SERVED = [["apps/wanted/knos_wanted/static", "/static/"], ["src/knos/game/static", "/static/"]];

function relTarget(url, fileAbs, base, webRoot) {
  let path = url.split("#")[0].split("?")[0];
  try { path = decodeURIComponent(path); } catch { /* keep it as written */ }
  if (!path) return fileAbs;                                 // ?query or #anchor alone: the page itself
  if (path.startsWith("/")) {
    const served = SERVED.find(([dir]) => fileAbs.startsWith(join(ROOT, dir) + sep));
    if (served) return path.startsWith(served[1]) ? join(ROOT, served[0], path.slice(served[1].length)) : "ROUTE";
    const rootDir = webRoot || base;
    const stripped = webRoot && path.startsWith("/Knos/") ? path.slice("/Knos".length) : path;
    return join(rootDir, stripped);
  }
  return resolve(dirname(fileAbs), path);
}

function collect(files, base, label, webRootOf) {
  const rel = [], ext = [];
  for (const abs of files) {
    let text;
    try { text = readFileSync(abs, "utf8"); } catch { continue; }
    const name = label(abs);
    const links = abs.toLowerCase().endsWith(".md") ? markdownLinks(text) : htmlLinks(text);
    for (const { url, index } of links) {
      if (SKIP.test(url)) continue;
      const where = `${name}:${lineOf(text, index)}`;
      if (/^https?:\/\//i.test(url)) { if (!RESERVED.test(url)) ext.push({ where, url }); }
      else if (!/^[a-z][a-z0-9+.-]*:/i.test(url)) rel.push({ where, url, target: relTarget(url, abs, base, webRootOf(abs)) });
    }
  }
  return { rel, ext };
}

function walk(dir) {
  const out = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p));
    else if (/\.(md|html)$/i.test(e.name)) out.push(p);
  }
  return out;
}

async function fetchStatus(url) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(url, { method: "GET", redirect: "follow", signal: ac.signal,
      headers: { "User-Agent": UA, Accept: "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Accept-Language": "en" } });
    try { await r.body?.cancel(); } catch { /* the status is all that is read */ }
    // a bot challenge (Vercel, Cloudflare) is a page a person can open, which a script must not try to pass
    if (/challenge/i.test(r.headers.get("x-vercel-mitigated") || r.headers.get("cf-mitigated") || "")) return "challenge";
    return r.status === 429 || r.status === 403 ? { status: r.status, wait: Number(r.headers.get("retry-after")) } : r.status;
  } catch (e) {
    return e.name === "AbortError" ? "timeout" : `error ${e.cause?.code || e.message}`;
  } finally {
    clearTimeout(timer);
  }
}

// at most PER_HOST requests to one host at a time, so one busy site is not asked eight times at once
const PER_HOST = 2, busy = new Map();
async function slot(host) {
  while ((busy.get(host) || 0) >= PER_HOST) await new Promise((r) => setTimeout(r, 50));
  busy.set(host, (busy.get(host) || 0) + 1);
}
const free = (host) => busy.set(host, busy.get(host) - 1);

async function checkUrl(url) {
  let host = "";
  try { host = new URL(url).host; } catch { return "error bad address"; }
  await slot(host);
  try {
    let s = await fetchStatus(url);
    if (typeof s === "object") {                                // 403 or 429: one more GET, after the wait it asks for
      const wait = Number.isFinite(s.wait) && s.wait > 0 ? Math.min(s.wait, 30) : 5;
      await new Promise((r) => setTimeout(r, wait * 1000));
      s = await fetchStatus(url);
      if (typeof s === "object") s = s.status;
    }
    return s;
  } finally {
    free(host);
  }
}

async function pool(items, n, fn) {
  const out = new Map();
  let i = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (i < items.length) {
      const item = items[i++];
      out.set(item, await fn(item));
    }
  }));
  return out;
}

const tracked = execFileSync("git", ["ls-files", "-z"], { cwd: ROOT, encoding: "utf8", maxBuffer: 1 << 28 })
  .split("\0").filter((f) => /\.(md|html)$/i.test(f)).map((f) => join(ROOT, f)).filter((f) => existsSync(f));
const WEB = join(ROOT, "web");
const repo = collect(tracked, ROOT, (abs) => relative(ROOT, abs).split(sep).join("/"),
  (abs) => (abs.startsWith(WEB + sep) ? WEB : null));
let site = { rel: [], ext: [] };
if (SITE) {
  if (!existsSync(SITE) || !statSync(SITE).isDirectory()) {
    console.log(`FAIL check_links: --site ${SITE} is not a folder`);
    process.exit(1);
  }
  site = collect(walk(SITE), SITE, (abs) => `site/${relative(SITE, abs).split(sep).join("/")}`, () => SITE);
}

const dead = [];
const relAll = [...repo.rel, ...site.rel];
const relChecked = relAll.filter((l) => l.target !== "ROUTE");
for (const l of relChecked) if (!l.target || !existsSync(l.target)) dead.push(`DEAD ${l.where} ${l.url} missing`);

const extAll = EXTERNAL ? [...repo.ext, ...site.ext] : [];
// one address once; the hosts taken in turn, so the eight workers are not all waiting on one host
const byHost = new Map();
for (const u of new Set(extAll.map((l) => l.url))) {
  let h = "";
  try { h = new URL(u).host; } catch { /* an address that does not parse is fetched, and fails, as it is */ }
  byHost.set(h, [...(byHost.get(h) || []), u]);
}
const unique = [];
for (let i = 0, more = true; more; i++) {
  more = false;
  for (const list of byHost.values()) if (i < list.length) { unique.push(list[i]); more = true; }
}
// a transaction on Solana's explorer is checked at its cluster's public RPC (getSignatureStatuses), which answers for
// what the page would show; the explorer itself turns scripts away with a challenge
const RPC = { devnet: "https://api.devnet.solana.com", testnet: "https://api.testnet.solana.com", "mainnet-beta": "https://api.mainnet-beta.solana.com" };
function explorerTx(url) {
  const m = /^https:\/\/explorer\.solana\.com\/tx\/([1-9A-HJ-NP-Za-km-z]{64,90})(?:\?(.*))?$/.exec(url);
  if (!m) return null;
  const cluster = new URLSearchParams(m[2] || "").get("cluster") || "mainnet-beta";
  return RPC[cluster] ? { sig: m[1], rpc: RPC[cluster] } : null;
}
async function rpcStatuses(rpc, sigs) {
  const out = new Map();
  for (let i = 0; i < sigs.length; i += 200) {
    const part = sigs.slice(i, i + 200);
    let answer = null;
    for (let attempt = 0; attempt < 3 && !answer; attempt++) {
      try {
        const r = await fetch(rpc, { method: "POST", headers: { "Content-Type": "application/json" }, signal: AbortSignal.timeout(30_000),
          body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "getSignatureStatuses", params: [part, { searchTransactionHistory: true }] }) });
        if (r.ok) answer = (await r.json()).result?.value;
        else await new Promise((res) => setTimeout(res, 3000));
      } catch { await new Promise((res) => setTimeout(res, 3000)); }
    }
    part.forEach((s, k) => out.set(s, answer ? (answer[k] ? 200 : "not on chain") : "rpc unanswered"));
  }
  return out;
}
const onChain = unique.filter(explorerTx), web = unique.filter((u) => !explorerTx(u));
const status = await pool(web, CONCURRENCY, checkUrl);
const byRpc = new Map();
for (const u of onChain) { const { sig, rpc } = explorerTx(u); byRpc.set(rpc, [...(byRpc.get(rpc) || []), [u, sig]]); }
for (const [rpc, pairs] of byRpc) {
  const got = await rpcStatuses(rpc, [...new Set(pairs.map(([, s]) => s))]);
  for (const [u, s] of pairs) status.set(u, got.get(s));
}
let challenged = 0;
for (const l of extAll) {
  const s = status.get(l.url);
  if (s === "challenge") { challenged++; continue; }
  if (typeof s !== "number" || s >= 400) dead.push(`DEAD ${l.where} ${l.url} ${String(s).replace(/\s+/g, "_")}`);
}

for (const d of dead) console.log(d);
const n = relChecked.length + extAll.length - challenged;
if (challenged) console.log(`note: ${challenged} links answered with a bot challenge, which a script does not pass; not counted`);
console.log(dead.length ? `FAIL check_links: ${dead.length} dead of ${n}` : `PASS check_links: 0 dead of ${n}`);
process.exit(dead.length ? 1 : 0);
