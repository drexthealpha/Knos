// test_status_page, live: the front door's /status/ reads its five parts (Qloo, the app, Solana devnet, the Sibyl record,
// GitHub) and says each one's state, with what happens when it fails, at 390 and 1280 px with no page error; the front
// door's footer and /proof/ link to it.
//   node scripts/test_status_page.mjs <commit sha under test>
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { appendFileSync } from "node:fs";

const [SHA] = process.argv.slice(2);
const OUT = `${process.env.KNOS_WORLD || `${process.env.KNOS_PRIVATE_DIR || "."}/v0328/world`}/test_status_page.txt`;
const SITE = process.env.KNOS_SITE || "https://drexthealpha.github.io/Knos/";
const PARTS = ["qloo", "app", "devnet", "sibyl", "github"];
const lines = []; let fails = 0;
const ok = (c, what) => { lines.push(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails++; };

const dep = JSON.parse(execFileSync("gh", ["api", "repos/drexthealpha/Knos/deployments?environment=github-pages&per_page=1"], { encoding: "utf8" }))[0];
ok(dep && dep.sha === SHA, `Pages deployed at ${dep && dep.sha.slice(0, 7)} (commit under test ${SHA.slice(0, 7)})`);
const browser = await chromium.launch();
const errors = [];
let live = 0;
try {
  for (const width of [390, 1280]) {
    const p = await (await browser.newContext({ viewport: { width, height: 844 } })).newPage();
    p.on("pageerror", (e) => errors.push(`${width}: ${e.message}`));
    await p.goto(`${SITE}status/?t=${Date.now()}`, { waitUntil: "domcontentloaded", timeout: 90000 });
    await p.waitForFunction((n) => document.querySelectorAll(".st-row[data-state]").length === n, PARTS.length, { timeout: 45000 }).catch(() => {});
    const rows = await p.evaluate(() => [...document.querySelectorAll(".st-row")].map((r) => ({ part: r.dataset.part, state: r.dataset.state || "",
      now: r.querySelector("[data-now]")?.textContent.trim() || "", fail: r.querySelector(".st-fail")?.textContent.trim() || "" })));
    const wide = await p.evaluate(() => document.documentElement.scrollWidth);
    for (const part of PARTS) {
      const r = rows.find((x) => x.part === part) || {};
      const read = !!r.state && r.now && r.now !== "Reading…";
      live += read;
      ok(read && /^When it is down: /.test(r.fail || ""), `${width} ${part}: ${r.state || "no state"}: "${r.now}"`);
    }
    ok(wide <= width, `${width}: page ${wide} px wide`);
  }
  // linked from the front door's footer and from /proof/
  const p = await (await browser.newContext()).newPage();
  for (const [name, url, where] of [["the front door's footer", SITE, "footer"], ["/proof/", `${SITE}proof/`, "body"]]) {
    await p.goto(`${url}?t=${Date.now()}`, { waitUntil: "domcontentloaded", timeout: 90000 });
    const has = await p.evaluate((w) => [...document.querySelectorAll(`${w} a[href]`)].some((a) => /\/status\/?$/.test(new URL(a.href).pathname)), where);
    ok(has, `${name} links to /status/`);
  }
} catch (e) {
  ok(false, `the browser step stopped: ${String(e.message).split("\n")[0].slice(0, 160)}`);
} finally {
  await browser.close();
}
ok(errors.length === 0, `page errors: ${errors.length}${errors.length ? ` (${errors.slice(0, 2).join("; ").slice(0, 200)})` : ""}`);
lines.push(fails ? `FAIL test_status_page: ${fails} check(s) failed` : `PASS test_status_page: ${live} of 10 rows read live (5 parts at 2 widths), each with its failure line; linked from the footer and /proof/; 0 page errors`);
console.log(lines.join("\n"));
appendFileSync(OUT, lines.join("\n") + "\n");
process.exit(fails ? 1 : 0);
