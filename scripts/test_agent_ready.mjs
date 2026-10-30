// G1 test_agent_ready, live: the files agents read answer 200 with valid bodies, a trace page shows its verdict with
// JavaScript off, /app/?q= runs the check, /start/ answers 301, an unknown page asked by a browser is an HTML 404.
//
//   node scripts/test_agent_ready.mjs [result file]
import { chromium } from "playwright";
import { appendFileSync } from "node:fs";

const APP = "https://knos.onrender.com";
const OUT = process.argv[2] || "";
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const get = (path, opts = {}) => fetch(APP + path, { redirect: "manual", headers: { "User-Agent": "knos-g1-test", ...(opts.headers || {}) } });

// 1. each file answers 200 with a valid body
for (const [path, kind] of [["/llms.txt", "md"], ["/robots.txt", "robots"], ["/sitemap.xml", "xml"], ["/.well-known/ai-catalog.json", "json"], ["/mcp/server-card", "card"]]) {
  const r = await get(path);
  const body = await r.text();
  let valid = false, said = "";
  try {
    if (kind === "md") { valid = /^# /m.test(body) && /^> /m.test(body) && /\]\(https:\/\/knos\.onrender\.com/.test(body); said = `${body.split("\n").length} lines`; }
    if (kind === "robots") { valid = /User-agent: OAI-SearchBot/i.test(body) && /Sitemap: https:\/\/knos\.onrender\.com\/sitemap\.xml/.test(body); said = "bots and sitemap named"; }
    if (kind === "xml") { valid = /^<\?xml/.test(body.trim()) && (body.match(/<loc>/g) || []).length >= 1 && /<lastmod>/.test(body) && !/&(?!amp;|lt;|gt;|quot;|apos;)/.test(body); said = `${(body.match(/<loc>/g) || []).length} urls`; }
    if (kind === "json") { const j = JSON.parse(body); valid = !!(j.specVersion || j.entries); said = `${(j.entries || []).length} entries`; }
    if (kind === "card") { const j = JSON.parse(body); const rm = (j.remotes || []).find((x) => x.url === APP + "/mcp");
      valid = !!rm && (rm.supportedProtocolVersions || []).length >= 1; said = `remote ${rm?.url}, versions ${(rm?.supportedProtocolVersions || []).join(" ")}, cors ${r.headers.get("access-control-allow-origin")}`; }
  } catch (e) { said = `${e.name}: ${e.message}`; }
  ok(r.status === 200 && valid, `${path}: HTTP ${r.status}, ${said}`);
}
// 2. /start/ answers 301 to the Start page; an unknown page asked by a browser is an HTML 404 with the way back
for (const p of ["/start/", "/start"]) {
  const r = await get(p);
  ok(r.status === 301 && /drexthealpha\.github\.io\/Knos\/start\//.test(r.headers.get("location") || ""), `${p}: HTTP ${r.status} to ${r.headers.get("location")}`);
}
const nf = await get("/no-such-page-" + Date.now(), { headers: { Accept: "text/html" } });
const nfBody = await nf.text();
ok(nf.status === 404 && /text\/html/.test(nf.headers.get("content-type") || "") && nfBody.includes("/app/") && nfBody.includes("/Knos/start/"),
  `an unknown page asked by a browser: HTTP ${nf.status}, ${nf.headers.get("content-type")}, links to /app/ and Start`);
// 3. a trace page with JavaScript off shows its verdict
const proof = await (await get("/api/proof")).json();
const hash = proof?.proof?.hash || "2b93c7bc52db6cd819655c021e9186d4bdcaaaf32544512b141e3bb60fe48722";
const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto(`${APP}/trace.html?hash=${hash}`, { waitUntil: "domcontentloaded", timeout: 120000 });
  const ssr = await page.$eval("#k-trace-ssr", (e) => e.innerText).catch(() => "");
  const ld = await page.$$eval('script[type="application/ld+json"]', (s) => s.length).catch(() => 0);
  const md = await page.$eval('link[rel="alternate"][type="text/markdown"]', (e) => e.getAttribute("href")).catch(() => "");
  ok(/Open|Not yet|Not enough evidence|Queued|OPEN|REFUSE/.test(ssr), `trace ${hash.slice(0, 12)} with JavaScript off: "${ssr.split("\n")[0].slice(0, 80)}", JSON-LD ${ld}, Markdown twin ${md}`);
  await ctx.close();
  // 4. /app/?q= prefills and runs the check
  const p2 = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await p2.goto(`${APP}/app/?q=a%20late%20night%20ramen%20spot`, { waitUntil: "domcontentloaded", timeout: 120000 });
  const q = await p2.$eval("#k-q", (e) => e.value).catch(() => "");
  const card = await p2.waitForSelector("#k-card [data-which], #k-card .k-card:not([data-confirm])", { timeout: 120000 }).catch(() => null);
  ok(q === "a late night ramen spot" && !!card, `/app/?q=a%20late%20night%20ramen%20spot: the box reads "${q}", ${card ? "a card came (the check ran)" : "no card"}`);
  const jsonld = await p2.$$eval('script[type="application/ld+json"]', (s) => s.map((x) => x.textContent).join(" ")).catch(() => "");
  ok(/SoftwareApplication/.test(jsonld) && /SearchAction/.test(jsonld), "/app/ carries SoftwareApplication and a WebSite SearchAction");
} finally { await browser.close(); }
log(fails.length ? `FAIL test_agent_ready: ${fails.length} of ${lines.length} checks failed; first: ${fails[0].slice(0, 140)}`
  : `PASS test_agent_ready: ${lines.length} of ${lines.length} checks: 5 files valid, /start/ 301, HTML 404, the trace readable with JavaScript off, /app/?q= runs the check`);
if (OUT) appendFileSync(OUT, `\n${new Date().toISOString()}\n` + lines.join("\n") + "\n");
process.exit(fails.length ? 1 : 0);
