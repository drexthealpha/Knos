// node tests/web/close30.mjs <site dir> [--write [file]]
// Close one invoice in 30 seconds: a build of web/ in headless Chromium, opened at #approve, from the navigation to the
// accounting file saved. The path is the one a finance owner takes the first time, on the sample statement:
//   mouse      Try the sample; click the name box, type your name, Tab, type your role; Approve; Download accounting file
//   keyboard   Tab to Try the sample, Enter; Tab to Go to approval, Enter; your name, Tab, your role, Enter (approves);
//              Tab to Download accounting file, Enter
// Two profiles, each with the mouse and with the keyboard alone:
//   android   360 x 740, processor 4 times slower, slow 4G (1.6 Mbps down, 750 kbps up, 150 ms round trip), cache empty
//             (the profile of tests/web/android.mjs)
//   desktop   1280 x 800, no slowing
// Each run counts the clicks and the key presses, and times the script from the navigation's start to the download.
// A script presses keys faster than a person, so the run also states the time with a person's pace added: 300 ms a key
// (40 words a minute) and 1 s a click. No person was timed. Held: at most 4 clicks, and at most 30 s with a person's pace
// on the android profile, mouse and keyboard alike. --write puts the table in docs/perf.json under "close" (or the file
// named), the rest of the file kept. No `playwright` package or no browser: a skip (tests/web/overflow.mjs, `owed`).
import { createServer } from "node:http";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { cpus } from "node:os";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const root = process.argv[2], wr = process.argv.indexOf("--write");
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/close30.mjs <site dir> [--write [file]]"); process.exit(2); }
const out = wr < 0 ? null : process.argv[wr + 1] || join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "perf.json");
const RUNS = 3, LIMIT_MS = 30_000, MOST_CLICKS = 4, KEY_MS = 300, CLICK_MS = 1000;
const NAME = "Dana Reyes", ROLE = "controller";
const PROFILES = {
  android: { viewport: { width: 360, height: 740 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, cpu: 4,
    net: { offline: false, latency: 150, downloadThroughput: Math.round(1.6e6 / 8), uploadThroughput: Math.round(750e3 / 8) } },
  desktop: { viewport: { width: 1280, height: 800 }, cpu: 1, net: null },
};
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };

const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

/** One close: { ms, clicks, keys, typed, file, said, strangers, errors }. */
async function close(profile, how) {
  const pr = PROFILES[profile];
  const ctx = await browser.newContext({ viewport: pr.viewport, deviceScaleFactor: pr.deviceScaleFactor || 1, isMobile: Boolean(pr.isMobile), hasTouch: Boolean(pr.hasTouch), acceptDownloads: true });
  const strangers = [], errors = [];
  await ctx.route("**/*", (route) => { const u = route.request().url(); if (u.startsWith(base)) return route.continue(); strangers.push(u); return route.abort(); });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  if (pr.net) await cdp.send("Network.emulateNetworkConditions", pr.net);
  if (pr.cpu > 1) await cdp.send("Emulation.setCPUThrottlingRate", { rate: pr.cpu });
  let clicks = 0, keys = 0, typed = 0;
  const click = async (sel) => { clicks++; await page.click(sel); };
  const press = async (key) => { keys++; await page.keyboard.press(key); };
  const type = async (text) => { typed += text.length; await page.keyboard.type(text); };
  const at = () => page.evaluate(() => { const e = document.activeElement; return e ? e.dataset.ap || e.dataset.file || e.id || e.tagName : ""; });
  const tabTo = async (want, most) => { for (let i = 0; i < most; i++) { await press("Tab"); if ((await at()) === want) return true; } throw new Error(`Tab did not reach ${want} in ${most} presses`); };
  const t0 = Date.now();
  await page.goto(`${base}#approve`, { waitUntil: "commit" });
  await page.waitForSelector("#approve [data-ap=sample]", { state: "visible", timeout: 30_000 });
  let download;
  if (how === "mouse") {
    await click("#approve [data-ap=sample]");
    await page.waitForSelector("#approve tr.ap-row[data-line='7']");
    await click("#ap-by"); await type(NAME); await press("Tab"); await type(ROLE); await click("#approve [data-ap=approve]");
    await page.waitForSelector("#approve tr.ap-row[data-approved]");
    [download] = await Promise.all([page.waitForEvent("download"), click("#approve [data-file=accounting]")]);
  } else {
    // from the top of the page: the page's own focus order, nothing clicked
    await page.evaluate(() => { document.activeElement?.blur?.(); document.getElementById("approve").setAttribute("tabindex", "-1"); document.getElementById("approve").focus(); });
    await tabTo("sample", 12); await press("Enter");
    await page.waitForSelector("#approve tr.ap-row[data-line='7']");
    await tabTo("skip", 4); await press("Enter");
    check(`${profile}, keyboard: "Go to approval" puts the focus on the name`, (await at()) === "ap-by", await at());
    await type(NAME); await press("Tab"); await type(ROLE); await press("Enter");
    await page.waitForSelector("#approve tr.ap-row[data-approved]");
    await tabTo("accounting", 3);
    [download] = await Promise.all([page.waitForEvent("download"), press("Enter")]);
  }
  await download.path();
  const ms = Date.now() - t0;
  await page.waitForFunction(() => /^Approved and exported/.test(document.querySelector("#approve [data-ap=filed]")?.textContent || ""));
  const said = await page.textContent("#approve [data-ap=filed]");
  const text = readFileSync(await download.path(), "utf8");
  await ctx.close();
  return { ms, clicks, keys, typed, file: download.suggestedFilename(), text, said, strangers, errors, person_ms: ms + (keys + typed) * KEY_MS + clicks * CLICK_MS };
}

const table = {};
for (const profile of Object.keys(PROFILES)) {
  for (const how of ["mouse", "keyboard"]) {
    const runs = [];
    for (let i = 0; i < RUNS; i++) runs.push(await close(profile, how));
    const median = (k) => runs.map((r) => r[k]).sort((a, b) => a - b)[Math.floor(runs.length / 2)];
    const r = runs[0], tag = `${profile}, ${how}`;
    console.log(`${tag}: script ${runs.map((x) => x.ms).join(", ")} ms; ${r.clicks} clicks, ${r.keys} key presses, ${r.typed} letters typed; with a person's pace ${median("person_ms")} ms`);
    check(`${tag}: the accounting file is saved and the page says approved and exported`, runs.every((x) => /^statement-.+-quickbooks\.csv$/.test(x.file) && x.text.startsWith("Bill no.,") && /^Approved and exported/.test(x.said)), runs.map((x) => [x.file, x.said]));
    check(`${tag}: the file bills the two approved lines and nothing held`, runs.every((x) => x.text.trim().split("\n").length === 3), r.text.slice(0, 300));
    check(`${tag}: ${r.clicks} clicks, at most ${MOST_CLICKS}`, runs.every((x) => x.clicks <= MOST_CLICKS), runs.map((x) => x.clicks));
    check(`${tag}: nobody but the site's own host was asked, and no error`, runs.every((x) => !x.strangers.length && !x.errors.length), runs.map((x) => [x.strangers, x.errors]));
    if (profile === "android") check(`${tag}: closed in under 30 s with a person's pace (slowest ${Math.max(...runs.map((x) => x.person_ms))} ms)`, runs.every((x) => x.person_ms < LIMIT_MS), runs.map((x) => x.person_ms));
    table[`${profile}_${how}`] = { clicks: r.clicks, key_presses: r.keys, letters_typed: r.typed, script_ms: { median: median("ms"), max: Math.max(...runs.map((x) => x.ms)) },
      with_person_pace_ms: { median: median("person_ms"), max: Math.max(...runs.map((x) => x.person_ms)) } };
  }
}
await browser.close(); server.close();

if (out && !fails) {
  const doc = existsSync(out) ? JSON.parse(readFileSync(out, "utf8")) : {};
  doc.close = {
    what: "tests/web/close30.mjs: a build of web/ opened at #approve; the sample statement; mouse: Try the sample, name and role typed, Approve, Download accounting file (QuickBooks); keyboard: the same by Tab and Enter, with Go to approval; milliseconds from the navigation's start to the file saved. android: 360 x 740, CPU slowed 4x, 1.6 Mbps down, 750 kbps up, 150 ms round trip, cache empty. desktop: 1280 x 800, no slowing. A script's time; with a person's pace adds 300 ms a key and 1 s a click. No person was timed.",
    machine: `${cpus().length} CPUs (${cpus()[0]?.model || "unknown"}), shared`, limit_ms: LIMIT_MS, most_clicks: MOST_CLICKS, runs: RUNS, key_ms: KEY_MS, click_ms: CLICK_MS, ...table,
  };
  writeFileSync(out, JSON.stringify(doc, null, 1) + "\n", "utf8");
  console.log(`wrote ${out}`);
}
if (fails) { console.error(`${fails} failed`); process.exit(1); }
console.log("close30: all passed");
