// node tests/web/live.mjs [web dir]
// web/live.js (a round anyone can watch) and web/cache.js (what a tab keeps of what it read), in headless Chromium against
// a mocked GitHub API and a mocked Solana devnet, with the page's clock held by the test: nothing here waits on real time.
// The rounds are the three a visitor can meet: one just paid, one long ago (never shown as live), one in progress and
// watched to its end. Needs the `playwright` package, as tests/web/site.mjs does; without it or a browser it says SKIP.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = process.argv[2] || join(here, "..", "..", "web");
let chromium;
try { ({ chromium } = (await import("playwright")).default); } catch { console.log("SKIP the playwright package is not installed"); process.exit(0); }
const check = (name, cond, detail) => { if (!cond) { console.error("FAIL", name, detail === undefined ? "" : detail); process.exitCode = 1; } else console.log("ok  ", name); };

// ---- cache.js by itself: storage that refuses, values JSON has no word for, the two passes --------------------------------
{
  const lib = await import(pathToFileURL(join(root, "cache.js")).href);
  const box = () => { const m = new Map(); return { m, getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); }, removeItem: (k) => { m.delete(k); } }; };
  const keysOf = (b) => new Proxy(b, { ownKeys: () => [...b.m.keys()], getOwnPropertyDescriptor: () => ({ enumerable: true, configurable: true }) });
  let t = 1_000_000;
  const store = box(), a = lib.makeCache({ storage: keysOf(store), now: () => t });
  a.set("k", { n: 5n, b: Uint8Array.of(1, 2, 255), s: "x" });
  const again = lib.makeCache({ storage: keysOf(store), now: () => t + 5000 }).get("k");
  check("cache: what one page kept, the next page of the tab reads: a bigint and bytes come back as they were, with when they were read", again.at === t && again.value.n === 5n && again.value.b instanceof Uint8Array && [...again.value.b].join() === "1,2,255" && again.value.s === "x");
  const refusing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); }, removeItem() { throw new Error("denied"); } };
  const r = lib.makeCache({ storage: refusing, now: () => t });
  r.set("k", 1);
  check("  a browser that refuses storage: nothing throws, and the page's own memory still holds it", r.get("k").value === 1 && lib.makeCache({ storage: refusing }).get("k") === null && lib.makeCache({ storage: null }).get("k") === null);
  store.m.set(lib.PREFIX + "bad", "{not json"); store.m.set(lib.PREFIX + "future", JSON.stringify({ value: 1, at: t + 10 ** 9 }));
  check("  an entry that is not JSON, or says it was read in the future, is as if nothing was kept", a.get("bad") === null && a.get("future") === null);
  a.set("big", "x".repeat(lib.MAX_CHARS + 1));
  check("  an answer too large for the tab's storage stays in memory only", a.get("big").value.length > lib.MAX_CHARS && !store.m.has(lib.PREFIX + "big"));
  for (let i = 0; i < lib.MAX_ENTRIES + 10; i++) { t += 1; a.set(`n${i}`, i); }
  check("  the tab's storage holds a bounded number of entries, the oldest gone first", [...store.m.keys()].filter((k) => k.startsWith(lib.PREFIX)).length <= lib.MAX_ENTRIES + 2 && !store.m.has(lib.PREFIX + "n0") && store.m.has(lib.PREFIX + `n${lib.MAX_ENTRIES + 9}`));
  const c = lib.makeCache({ storage: null, now: () => t }), drawn = [];
  let answer = 1, loads = 0;
  const view = (read, pass) => read("a", async () => { loads++; return answer; }).then((v) => { if (!pass.same()) drawn.push(`${pass.kept ? "kept" : "now"}:${v}`); });
  const first = await c.twice(view);
  check("  twice: nothing kept, so the view is drawn once, from what is read now", JSON.stringify(first) === '{"shown":false,"changed":true}' && drawn.join() === "now:1" && loads === 1);
  const second = await c.twice(view);
  check("  seen before and unchanged: drawn at once from what was kept, read again, and not drawn a second time", JSON.stringify(second) === '{"shown":true,"changed":false}' && drawn.join() === "now:1,kept:1" && loads === 2);
  answer = 2;
  const third = await c.twice(view);
  check("  seen before and changed: what was kept first, then what is true now in its place", JSON.stringify(third) === '{"shown":true,"changed":true}' && drawn.join() === "now:1,kept:1,kept:1,now:2" && loads === 3, drawn.join());
  const failing = await c.twice((read) => read("a", async () => { throw new Error("offline"); })).catch((e) => e);
  check("  the second read fails: the error says since when the view still on the page is old", failing.message === "offline" && failing.kept === c.get("a").at);
  check("  ages are said in the unit a person would use", lib.ago(4_400) === "4 s" && lib.ago(119_000) === "119 s" && lib.ago(600_000) === "10 min" && lib.ago(3 * 3600_000) === "3 h" && lib.asOf(1000, 13_000) === "as of 12 s ago");
}

// ---- the world the page sees ----------------------------------------------------------------------------------------------
const REPO = "octo/canary", NOW = Date.UTC(2026, 9, 5, 12, 10, 0);
const iso = (t) => new Date(t).toISOString().replace(".000Z", "Z");
const ESCROW = "7".repeat(44), FUND_TX = "2".repeat(88), PAY_TX = "3".repeat(88), VERIFY_TX = "4".repeat(88), SHA = "e".repeat(40);
const stampOf = (t) => iso(t).replace(/[-:]/g, "").replace("T", "-").slice(0, 15);
// one round as GitHub and devnet would hold it `upTo` a stage: ask < fund < open < merge < sign < pay
// `states`: Knos's one comment on the pull request as 0.3.16 writes it, posted at "received" and edited through the
// five states (`knos-states`); "upTo" a state, the comment has reached that one and no later
const FIVE = ["received", "accepted", "submitted", "confirmed", "finalized"];
function world(start, upTo, n = 40, { held = false, refused = false, states = null } = {}) {
  const at = { ask: start, fund: start + 41_000, open: start + 44_000, merge: start + 95_000, sign: start + 99_000, pay: start + 121_000 };
  const has = (stage) => ["ask", "fund", "open", "merge", "sign", "pay"].indexOf(stage) <= ["ask", "fund", "open", "merge", "sign", "pay"].indexOf(upTo);
  const title = `knos canary ${stampOf(start)}`, w = { items: [], comments: {}, pulls: {}, runs: {}, sigs: {} };
  const issue = { number: n, title, state: "open", created_at: iso(at.ask), html_url: `https://github.com/${REPO}/issues/${n}`, user: { login: "canary" } };
  w.items.push(issue);
  w.comments[n] = refused ? [{ body: "Knos: nothing was funded. The faucet did not answer.", created_at: iso(at.fund), html_url: `https://github.com/${REPO}/issues/${n}#issuecomment-1` }]
    : has("fund") ? [{ body: `Knos: 5.00 test USDC from the devnet faucet is in escrow for issue #${n} ([job on Solana](https://explorer.solana.com/address/${ESCROW}?cluster=devnet)), 41 s after the comment.\n\n<img src=x onerror=alert(1)>`,
      created_at: iso(at.fund), html_url: `https://github.com/${REPO}/issues/${n}#issuecomment-1` }] : [];
  if (has("fund") && !refused) w.sigs[ESCROW] = [{ signature: FUND_TX, blockTime: Math.floor((at.fund - 3000) / 1000), err: null }];
  if (has("open") && !refused) {
    const pull = { number: n + 1, title, state: has("merge") ? "closed" : "open", created_at: iso(at.open), html_url: `https://github.com/${REPO}/pull/${n + 1}`, merged_at: has("merge") ? iso(at.merge) : null, merge_commit_sha: has("merge") ? SHA : null };
    w.pulls[n + 1] = pull;
    w.items.unshift({ ...pull, pull_request: { merged_at: pull.merged_at } });
    w.comments[n + 1] = [];
  }
  if (has("sign")) w.runs[SHA] = [{ name: "knos check", path: ".github/workflows/knos-check.yml", status: "completed", conclusion: "success", run_started_at: iso(at.merge + 1000), html_url: `https://github.com/${REPO}/actions/runs/1` },
    { name: "knos", path: ".github/workflows/knos.yml", status: has("pay") ? "completed" : "in_progress", conclusion: has("pay") ? "success" : null, run_started_at: iso(at.sign), html_url: `https://github.com/${REPO}/actions/runs/2` }];
  if (has("pay")) {
    w.comments[n + 1] = [{ body: held ? `Knos: held for @canary. 5.00 test USDC for issue #${n} waits for them ([transaction](https://explorer.solana.com/tx/${PAY_TX}?cluster=devnet), 26 s after the merge).`
      : `Knos: paid. @canary received 4.60 test USDC for issue #${n}: the bounty of 5.00 less Knos's fee of 0.40. It went to \`W\` ([verified](https://explorer.solana.com/tx/${VERIFY_TX}?cluster=devnet), [transaction](https://explorer.solana.com/tx/${PAY_TX}?cluster=devnet), 26 s after the merge).`,
      created_at: iso(at.pay + 4000), html_url: `https://github.com/${REPO}/pull/${n + 1}#issuecomment-2` }];
    w.sigs[ESCROW] = [{ signature: PAY_TX, blockTime: Math.floor(at.pay / 1000), err: null }, ...w.sigs[ESCROW]];
  }
  if (states && has("merge")) {
    // received 4 s after the merge (the run began), accepted 2 s on, submitted 1 s on, confirmed 19 s on (the paying block), finalized 13 s on
    const when = { received: at.merge + 4000, accepted: at.merge + 6000, submitted: at.merge + 7000, confirmed: at.pay, finalized: at.pay + 13_000 };
    const reached = FIVE.slice(0, FIVE.indexOf(states) + 1), paid = reached.includes("confirmed");
    if (!paid) w.sigs[ESCROW] = w.sigs[ESCROW].filter((x) => x.signature !== PAY_TX);
    const words = paid ? w.comments[n + 1][0]?.body || `Knos: paid. @canary received 4.60 test USDC for issue #${n} ([transaction](https://explorer.solana.com/tx/${PAY_TX}?cluster=devnet), 26 s after the merge).`
      : reached.includes("accepted") ? "Knos: accepted, settling. Everything the bounty asks for holds and GitHub signed this run. The payment to @canary is on its way to Solana; this comment is edited when it lands."
      : `Knos: received. Pull request #${n + 1} is being checked against what was funded for it. This comment is edited as the payment moves.`;
    w.comments[n + 1] = [{ body: `${words}\n\n<!-- knos-status -->\n<sub><img src=x onerror=alert(2)></sub>\n<!-- knos-states since=${at.merge / 1000}.0 ${reached.map((k) => `${k}=${(when[k] / 1000).toFixed(1)}`).join(" ")}${paid ? ` tx=${PAY_TX}` : ""}\n-->`,
      created_at: iso(when.received), updated_at: iso(when[reached.at(-1)]), html_url: `https://github.com/${REPO}/pull/${n + 1}#issuecomment-2` }];
  }
  return { w, at, title };
}

const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };
const served = { stats: { latency: { merge_to_paid: { n: 39, p50: 25, p95: 164 } } }, operations: { canary: { runs: 0, note: "The canary workflow has not run yet." } } };
const PAGE = `<!doctype html><meta charset="utf-8"><title>live</title><section id="status"></section>
<script type="module">import { renderLive } from "./live.js"; window.live = renderLive(document.getElementById("status"), { repo: "${REPO}" });</script>`;
const server = createServer((req, res) => {
  const path = req.url.split("?")[0];
  if (path === "/live.html") { res.writeHead(200, { "Content-Type": "text/html" }); return res.end(PAGE); }
  if (path === "/stats.json" || path === "/operations.json") { const o = served[path.slice(1, -5)]; if (!o) { res.writeHead(404); return res.end(); } res.writeHead(200, { "Content-Type": "application/json" }); return res.end(JSON.stringify(o)); }
  const file = join(root, path);
  if (!existsSync(file) || !types[extname(file)]) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "Content-Type": types[extname(file)] }); res.end(readFileSync(file));
});
await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
const base = `http://127.0.0.1:${server.address().port}/`;

let browser;
try { browser = await chromium.launch(); } catch (e) { console.log(`SKIP no browser: ${String(e.message).split("\n")[0]}`); server.close(); process.exit(0); }
const errors = [], strangers = [];
// `net`: the world, every request made, and a gate that holds GitHub's and devnet's answers until the test lets them go
async function open(w, { hold = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 900, height: 900 } });
  const net = { w, github: [], devnet: [], answered: 0, down: false, release: () => {}, held: hold };
  const gate = hold ? new Promise((ok) => { net.release = () => { net.held = false; ok(); }; }) : Promise.resolve();
  net.gate = gate;
  await ctx.route((url) => !url.href.startsWith(base), async (route) => {
    const url = new URL(route.request().url());
    const json = async (o, status = 200) => { await net.gate; net.answered++; return route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(o) }); };
    if (url.host === "api.github.com") {
      net.github.push(url.pathname + url.search);
      if (net.down) return json({ message: "down" }, 502);
      let m;
      if (url.pathname === `/repos/${REPO}/issues`) return json(net.w.items);
      if ((m = /^\/repos\/octo\/canary\/issues\/(\d+)\/comments$/.exec(url.pathname))) return json(net.w.comments[m[1]] || []);
      if ((m = /^\/repos\/octo\/canary\/pulls\/(\d+)$/.exec(url.pathname))) return net.w.pulls[m[1]] ? json(net.w.pulls[m[1]]) : json({ message: "Not Found" }, 404);
      if (url.pathname === `/repos/${REPO}/actions/runs`) return json({ workflow_runs: net.w.runs[url.searchParams.get("head_sha")] || [] });
      return json({ message: "Not Found" }, 404);
    }
    if (url.host === "api.devnet.solana.com") {
      const body = route.request().postDataJSON();
      net.devnet.push(body.method);
      return json({ jsonrpc: "2.0", id: body.id, result: body.method === "getSignaturesForAddress" ? (net.w.sigs[body.params[0]] || []) : null });
    }
    strangers.push(url.href);
    return route.abort();
  });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  // install() alone leaves the page's clock running with real time (and each new document adds the real time since);
  // paused, it moves only by runFor, so a slow runner looks as often and reads the same times as a fast one
  await page.clock.install({ time: new Date(NOW - 1000) });
  await page.clock.pauseAt(new Date(NOW));
  return { ctx, page, net };
}
const text = async (page, sel) => ((await page.textContent(sel)) || "").replace(/\s+/g, " ").trim();
const settled = (page) => page.waitForFunction(() => !document.getElementById("live-head").textContent.includes("Reading the canary") && !document.getElementById("live-asof"));
const stages = (page) => page.$$eval("#live-line li", (l) => l.map((x) => `${x.dataset.stage}:${x.dataset.state}`).join(" "));

// ---- a round paid ten minutes ago -----------------------------------------------------------------------------------------
{
  const { w, at } = world(NOW - 600_000, "pay"), { ctx, page, net } = await open(w);
  await page.goto(`${base}live.html`);
  await settled(page);
  const head = await text(page, "#live-head"), line = await text(page, "#live-line");
  check("live: the latest round, paid: when it started, how long ago, and how long it took whole and from the merge", head === "The latest round started 2026-10-05 12:00:00 UTC (10 min ago) and was paid 2 min 01 s later, 26 s after the merge." && await page.isVisible("#live-head.ok"), head);
  check("  six stages, each done, in order", (await stages(page)) === "ask:done fund:done open:done merge:done sign:done pay:done");
  check("  every stage has GitHub's or devnet's own time, and the seconds it took", line.includes("In escrow on devnet 2026-10-05 12:00:41 UTC, 41 s") && line.includes("Pull request opened 2026-10-05 12:00:44 UTC, 3 s") && line.includes("Checks passed, merged 2026-10-05 12:01:35 UTC, 51 s")
    && line.includes("GitHub ran the workflow that signs 2026-10-05 12:01:39 UTC, 4 s") && line.includes("Paid on devnet 2026-10-05 12:02:01 UTC, 26 s") && line.includes("the time devnet confirmed it"), line);
  const links = await page.$$eval("#live-line a", (a) => a.map((x) => [x.textContent, x.getAttribute("href"), x.target, x.rel]));
  const want = [["issue #40", `https://github.com/${REPO}/issues/40`], ["funding comment", `https://github.com/${REPO}/issues/40#issuecomment-1`], ["escrow account", `https://explorer.solana.com/address/${ESCROW}?cluster=devnet`],
    ["funding transaction", `https://explorer.solana.com/tx/${FUND_TX}?cluster=devnet`], ["pull request #41", `https://github.com/${REPO}/pull/41`], ["the signed run", `https://github.com/${REPO}/actions/runs/2`],
    ["payment comment", `https://github.com/${REPO}/pull/41#issuecomment-2`], ["the verifier transaction", `https://explorer.solana.com/tx/${VERIFY_TX}?cluster=devnet`], ["the payment", `https://explorer.solana.com/tx/${PAY_TX}?cluster=devnet`]];
  check("  the links: the funding comment, the pull request, the signed run (the workflow that pays, not the check), the verifier transaction and the payment", JSON.stringify(links.map((l) => l.slice(0, 2))) === JSON.stringify(want) && links.every((l) => l[2] === "_blank" && l[3] === "noopener"), JSON.stringify(links));
  check("  a comment's markup is never the page's", (await page.$$("#status img")).length === 0);
  check("  the countdown is to the next half hour, and says GitHub may be late", (await text(page, "#live-next")) === "Next round: 12:30 UTC, in 20 min 00 s. GitHub often starts a timer some minutes late.", await text(page, "#live-next"));
  await page.clock.runFor(61_000);
  check("  and it counts down by the clock", (await text(page, "#live-next")).includes("in 18 min 59 s"), await text(page, "#live-next"));
  await page.waitForFunction(() => document.getElementById("live-measured").textContent.length > 0);
  check("  what was measured over many rounds is the site's own file, named", (await text(page, "#live-measured")) === "Over 39 timed payments on devnet, the wait from merge to payment had a median of 25 s and a 95th percentile of 2 min 44 s (stats.json).", await text(page, "#live-measured"));
  check("  it took five reads of GitHub and one of devnet", net.github.length === 5 && net.devnet.join() === "getSignaturesForAddress", `${net.github.length} ${net.devnet.join()}`);
  check("  nobody is asked to connect or sign anything", !(await text(page, "#status")).toLowerCase().includes("connect a wallet") && (await page.$$("#status input")).length === 0);

  // the second view in the same tab: on the page before GitHub or devnet has answered anything, with its age; then replaced by what changed
  const again = await ctx.newPage();
  await again.clock.install({ time: new Date(NOW + 61_000) });
  const before = net.answered;
  let letGo; net.gate = new Promise((ok) => { letGo = ok; });
  w.sigs[ESCROW][0] = { signature: PAY_TX, blockTime: Math.floor(at.pay / 1000) + 9, err: null };       // devnet now gives the payment another time
  await again.goto(`${base}live.html`);
  await again.evaluate((kept) => { for (const [k, v] of kept) sessionStorage.setItem(k, v); }, await page.evaluate(() => Object.entries(sessionStorage)));
  await again.reload();
  await again.waitForSelector("#live-asof");
  check("live, seen before: the round is on the page with no answer from GitHub or devnet yet, and says how old it is", net.answered === before && (await stages(again)) === "ask:done fund:done open:done merge:done sign:done pay:done"
    && (await text(again, "#live-asof")).startsWith("Shown as of 61 s ago. Reading it again") && (await text(again, "#live-line")).includes("Paid on devnet 2026-10-05 12:02:01 UTC, 26 s"), `${net.answered - before} ${await text(again, "#live-asof")}`);
  letGo();
  await again.waitForFunction(() => !document.getElementById("live-asof"));
  check("  then what devnet says now replaces it, and the note of its age is gone", (await text(again, "#live-line")).includes("Paid on devnet 2026-10-05 12:02:10 UTC, 35 s") && net.answered > before, await text(again, "#live-line"));
  net.down = true;
  await again.reload();
  await again.waitForFunction(() => document.getElementById("live-asof")?.textContent.includes("could not be read again"));
  check("  GitHub not answering: the kept round stays, and says it could not be read again", (await text(again, "#live-asof")).startsWith("Shown as of") && (await text(again, "#live-asof")).includes("It could not be read again just now: GitHub said 502") && (await stages(again)).endsWith("pay:done"));
  await ctx.close();
}

// ---- nothing recent: never shown as live ----------------------------------------------------------------------------------
{
  const { w } = world(NOW - 3 * 3600_000, "pay"), { ctx, page } = await open(w);
  await page.goto(`${base}live.html`);
  await settled(page);
  const head = await text(page, "#live-head");
  check("live, stale: a round three hours old is the last round, and the page says the canary has not run since", head === "The canary has not run since 2026-10-05 09:10:00 UTC (3 h ago). This is its last round, not a live one." && !(await page.isVisible("#live-head.ok")), head);
  check("  nothing is drawn as happening now, and the countdown promises nothing", (await page.$$('#live-line li[data-state="now"]')).length === 0 && (await page.$$("[data-since]")).length === 0
    && (await text(page, "#live-next")) === "Next timer: 12:30 UTC, in 20 min 00 s. The canary has not been running. A round may not start then.", await text(page, "#live-next"));
  await page.click("#live-watch");
  await page.waitForFunction(() => document.getElementById("live-watching").textContent.startsWith("Waiting"));
  check("  watching an old round replays nothing: it waits for a new one", (await text(page, "#live-watching")).startsWith("Waiting for the next round to start.") && (await text(page, "#live-head")).startsWith("The canary has not run since") && (await page.$$('#live-line li[data-state="now"]')).length === 0);
  await ctx.close();

  const none = await open({ items: [{ number: 3, title: "A bug", created_at: iso(NOW), html_url: "https://github.com/octo/canary/issues/3" }], comments: {}, pulls: {}, runs: {}, sigs: {} });
  await none.page.goto(`${base}live.html`);
  await settled(none.page);
  check("  a repository with no round: said, with no timeline", (await text(none.page, "#live-head")) === `The canary has not run: ${REPO} has no round among its newest issues. Nothing is shown as live.` && (await none.page.$("#live-line")) === null);
  await none.ctx.close();

  const down = await open(w);
  down.net.down = true;
  await down.page.goto(`${base}live.html`);
  await down.page.waitForSelector("#live-head.bad");
  check("  GitHub not answering and nothing kept: said, and no round is shown", (await text(down.page, "#live-head")) === "The canary's round was not read (GitHub said 502). None is shown." && (await down.page.$("#live-line")) === null);
  await down.ctx.close();

  const old = world(NOW - 40 * 60_000, "open"), unfinished = await open(old.w);
  await unfinished.page.goto(`${base}live.html`);
  await settled(unfinished.page);
  check("  a round that stopped half way 40 minutes ago is not in progress: the stage that did not happen is marked", (await text(unfinished.page, "#live-head")).includes("did not finish within 20 minutes") && (await stages(unfinished.page)) === "ask:done fund:done open:done merge:failed sign:wait pay:wait"
    && await unfinished.page.isVisible("#live-head.bad"), await stages(unfinished.page));
  await unfinished.ctx.close();

  const no = world(NOW - 300_000, "fund", 40, { refused: true }), refused = await open(no.w);
  await refused.page.goto(`${base}live.html`);
  await settled(refused.page);
  check("  a round whose funding was refused: failed, with Knos's own first line", (await text(refused.page, "#live-head")).includes("failed") && (await stages(refused.page)).startsWith("ask:done fund:failed") && (await text(refused.page, "#live-line")).includes("Knos: nothing was funded. The faucet did not answer."));
  await refused.ctx.close();
}

// ---- a round in progress, watched to its end ------------------------------------------------------------------------------
{
  const start = NOW - 60_000, { ctx, page, net } = await open(world(start, "open").w);
  await page.goto(`${base}live.html`);
  await settled(page);
  check("live, in progress: a round that started a minute ago is running, and says so", (await text(page, "#live-head")) === "A round is running now: it started at 2026-10-05 12:09:00 UTC." && (await stages(page)) === "ask:done fund:done open:done merge:now sign:wait pay:wait", await stages(page));
  check("  the stage in progress counts its seconds from the stage before it, by the clock", (await text(page, '#live-line li[data-stage="merge"]')).includes("16 s so far") && (await text(page, "#live-next")).startsWith("This round is in progress"), await text(page, '#live-line li[data-stage="merge"]'));
  await page.clock.runFor(5000);
  check("  and keeps counting", (await text(page, '#live-line li[data-stage="merge"]')).includes("21 s so far"));
  check("  a stage that has not happened has no time", (await text(page, '#live-line li[data-stage="pay"]')) === "Paid on devnet not yet");
  await page.click("#live-watch");
  await page.waitForFunction(() => document.getElementById("live-watching").textContent.startsWith("Watching round 40"));
  check("  watching: it says which round, when it looked and how often it looks", /^Watching round 40\. Looked at 12:10:05 UTC; looking again every 30 s\.$/.test(await text(page, "#live-watching")) && (await text(page, "#live-watch")) === "Stop watching", await text(page, "#live-watching"));
  const step = async (upTo, want) => {
    net.w = world(start, upTo).w;
    const before = net.github.length;
    // the line as it was before the clock moves: read after, it may already be the new look's, and nothing would change again
    for (let i = 0; i < 6 && (await stages(page)) !== want; i++) { const was = await text(page, "#live-watching"); await page.clock.runFor(30_000); await page.waitForFunction((n) => document.getElementById("live-watching").textContent.replace(/\s+/g, " ").trim() !== n, was).catch(() => {}); }
    return net.github.length - before;
  };
  const toMerge = await step("merge", "ask:done fund:done open:done merge:done sign:now pay:wait");
  check("  GitHub merges: the stage gets GitHub's time, and the next one starts counting", (await stages(page)) === "ask:done fund:done open:done merge:done sign:now pay:wait" && (await text(page, "#live-line")).includes("Checks passed, merged 2026-10-05 12:10:35 UTC, 51 s"), await stages(page));
  const toPay = await step("pay", "ask:done fund:done open:done merge:done sign:done pay:done");
  // devnet can show the payment a look before GitHub shows Knos's comment about it: the round is watched until that is read too
  for (let i = 0; i < 4 && !(await text(page, "#live-watching")).startsWith("Round 40 ended"); i++) { const was = await text(page, "#live-watching"); await page.clock.runFor(30_000); await page.waitForFunction((n) => document.getElementById("live-watching").textContent.replace(/\s+/g, " ").trim() !== n, was).catch(() => {}); }
  check("  and the comment that says so is on the page when watching ends", (await page.$$eval("#live-line a", (a) => a.map((x) => x.textContent))).includes("payment comment"));
  check("  the payment lands: every stage has its time, the round is paid, and watching ends by itself", (await stages(page)) === "ask:done fund:done open:done merge:done sign:done pay:done" && (await text(page, "#live-head")).includes("was paid 2 min 01 s later, 26 s after the merge")
    && (await text(page, "#live-watching")) === "Round 40 ended (paid). That was a real round: every time above is GitHub's or devnet's." && (await text(page, "#live-watch")) === "Watch it happen", await text(page, "#live-head"));
  check("  each look asked GitHub one thing", toMerge <= 2 && toPay <= 4, `${toMerge} ${toPay}`);
  const quiet = net.github.length;
  await page.clock.runFor(120_000);
  check("  after the round ended nothing more is asked", net.github.length === quiet);
  await ctx.close();
}

// ---- the five states, by name, with their times ---------------------------------------------------------------------------
const five = (page) => page.$$eval("#live-states li.k-step", (l) => l.map((x) => `${x.dataset.step}:${x.dataset.state}`).join(" "));
{
  // a round paid ten minutes ago whose comment went through all five
  const { ctx, page } = await open(world(NOW - 600_000, "pay", 40, { states: "finalized" }).w);
  await page.goto(`${base}live.html`);
  await settled(page);
  check("states: the latest round shows the five states by name, each done", (await five(page)) === "received:done accepted:done submitted:done confirmed:done finalized:done", await five(page));
  const said = await text(page, "#live-states");
  check("  each with the time the workflow wrote and its seconds from the state before (received: from the merge)", said === "received 12:01:39 UTC, 4 s accepted 12:01:41 UTC, 2 s submitted 12:01:42 UTC, 1 s confirmed 12:02:01 UTC, 19 s finalized 12:02:14 UTC, 13 s", said);
  check("  the timeline above it is as it was, and the payment has devnet's time", (await stages(page)) === "ask:done fund:done open:done merge:done sign:done pay:done" && (await text(page, "#live-line")).includes("Paid on devnet 2026-10-05 12:02:01 UTC, 26 s"));
  check("  the comment's markup is still never the page's, and the states are a list of .k-step", (await page.$$("#status img")).length === 0 && (await page.$$("#live-states li.k-step[data-state]")).length === 5);
  await ctx.close();

  // a comment from before 0.3.16 has no states: none is claimed
  const old = await open(world(NOW - 600_000, "pay").w);
  await old.page.goto(`${base}live.html`);
  await settled(old.page);
  check("  a round whose comment carries no states: all five idle, and none has a time", (await five(old.page)) === "received:idle accepted:idle submitted:idle confirmed:idle finalized:idle" && !/\d\d:\d\d/.test(await text(old.page, "#live-states")), await text(old.page, "#live-states"));
  await old.ctx.close();

  // devnet's own time could not be read: the payment's time is the one the workflow recorded, never the comment's creation
  const noChain = world(NOW - 600_000, "pay", 40, { states: "confirmed" });
  noChain.w.sigs = {};
  const blind = await open(noChain.w);
  await blind.page.goto(`${base}live.html`);
  await settled(blind.page);
  check("  with devnet unread, 'paid' is when the workflow saw it confirmed (the comment was created at 'received')", (await text(blind.page, "#live-line")).includes("Paid on devnet 2026-10-05 12:02:01 UTC, 26 s") && (await text(blind.page, "#live-line")).includes("the time Knos's workflow recorded")
    && (await five(blind.page)) === "received:done accepted:done submitted:done confirmed:done finalized:idle", await text(blind.page, "#live-line"));
  await blind.ctx.close();
}

// ---- watched: "accepted" shows before the payment, and the signed stage gets its time without a reload ----------------------
{
  const start = NOW - 60_000, { ctx, page, net } = await open(world(start, "open").w);
  await page.goto(`${base}live.html`);
  await settled(page);
  check("watched states: before the merge nothing is live among the five", (await five(page)) === "received:idle accepted:idle submitted:idle confirmed:idle finalized:idle");
  await page.click("#live-watch");
  await page.waitForFunction(() => document.getElementById("live-watching").textContent.startsWith("Watching round 40"));
  const look = async () => { const was = await text(page, "#live-watching"); await page.clock.runFor(30_000); await page.waitForFunction((n) => document.getElementById("live-watching").textContent.replace(/\s+/g, " ").trim() !== n, was).catch(() => {}); };
  const until = async (want, read = stages) => { for (let i = 0; i < 6 && (await read(page)) !== want; i++) await look(); return read(page); };
  net.w = world(start, "merge").w;
  await until("ask:done fund:done open:done merge:done sign:now pay:wait");
  check("  merged, and Knos has said nothing yet: 'received' is the state awaited", (await five(page)) === "received:live accepted:idle submitted:idle confirmed:idle finalized:idle", await five(page));
  // GitHub is asked for the signing run right after the merge and does not list it yet
  const asked = net.github.filter((p) => p.includes("/actions/runs")).length;
  for (let i = 0; i < 4 && net.github.filter((p) => p.includes("/actions/runs")).length === asked; i++) await look();
  check("  (the signing run was asked for and GitHub did not list it yet)", net.github.filter((p) => p.includes("/actions/runs")).length === asked + 1 && (await stages(page)).includes("sign:now"));
  // the workflow has decided: "accepted" is on the page while the payment is still on its way
  net.w = world(start, "merge", 40, { states: "accepted" }).w;
  await until("received:done accepted:done submitted:live confirmed:idle finalized:idle", five);
  check("  accepted shows as soon as the workflow decided, before any payment: the round is still running", (await five(page)) === "received:done accepted:done submitted:live confirmed:idle finalized:idle"
    && (await text(page, "#live-states")).startsWith("received 12:10:39 UTC, 4 s accepted 12:10:41 UTC, 2 s submitted now") && (await text(page, "#live-head")).startsWith("A round is running now") && (await stages(page)).endsWith("pay:wait"), await text(page, "#live-states"));
  // the payment lands, and by now GitHub lists the run
  net.w = world(start, "pay", 40, { states: "finalized" }).w;
  await until("received:done accepted:done submitted:done confirmed:done finalized:done", five);
  await page.waitForFunction(() => document.getElementById("live-watching").textContent.startsWith("Round 40 ended"));
  const line = await text(page, "#live-line");
  check("  the payment lands: all five states done, and watching ends", (await five(page)) === "received:done accepted:done submitted:done confirmed:done finalized:done" && (await text(page, "#live-head")).includes("26 s after the merge"), await five(page));
  check("  the signed stage has its time without a reload (it was left without one when the run was listed late)", (await stages(page)) === "ask:done fund:done open:done merge:done sign:done pay:done" && line.includes("GitHub ran the workflow that signs 2026-10-05 12:10:39 UTC, 4 s"), `${await stages(page)} | ${line}`);
  await ctx.close();
}

// ---- the defect of the 0.3.15 run, by itself: the signing run listed late, the payment seen at the next look ------------------
{
  const start = NOW - 60_000, { ctx, page, net } = await open(world(start, "open").w);
  await page.goto(`${base}live.html`);
  await settled(page);
  await page.click("#live-watch");
  await page.waitForFunction(() => document.getElementById("live-watching").textContent.startsWith("Watching round 40"));
  const look = async () => { const was = await text(page, "#live-watching"); await page.clock.runFor(30_000); await page.waitForFunction((n) => document.getElementById("live-watching").textContent.replace(/\s+/g, " ").trim() !== n, was).catch(() => {}); };
  const runsAsked = () => net.github.filter((p) => p.includes("/actions/runs")).length;
  net.w = world(start, "merge").w;
  for (let i = 0; i < 6 && (await stages(page)) !== "ask:done fund:done open:done merge:done sign:now pay:wait"; i++) await look();
  for (let i = 0; i < 4 && runsAsked() === 0; i++) await look();          // asked right after the merge: GitHub lists no run yet
  net.w = world(start, "pay").w;                                          // by the next look the run is listed, and Knos has said "paid"
  for (let i = 0; i < 6 && !(await text(page, "#live-watching")).startsWith("Round 40 ended"); i++) await look();
  check("signed, watched: a signing run GitHub listed late still gets its time when the payment is seen (0.3.15 left it blank until a reload)",
    (await stages(page)) === "ask:done fund:done open:done merge:done sign:done pay:done" && (await text(page, '#live-line li[data-stage="sign"]')).includes("2026-10-05 12:10:39 UTC, 4 s"), `${await stages(page)} | ${await text(page, '#live-line li[data-stage="sign"]')}`);
  check("  and it cost one more read of GitHub, once", runsAsked() === 2, runsAsked());
  await ctx.close();
}

await browser.close(); server.close();
check("no console errors", errors.length === 0, errors);
check("nothing was asked of anyone but this page, GitHub and devnet", strangers.length === 0, strangers);
