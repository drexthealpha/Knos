// test_tour (T1), live: /start/ at 390 and 1280, light and dark. Each of the four blocks' links opens (HTTP 200 or the
// page loads), the five status rows equal /api/status's deps, 0 page errors, the front door's bar links it as Start,
// and every command on the page runs as printed (claude mcp add in a throwaway folder, removed after; pip install knos
// into a throwaway venv; the devnet program check with curl).
//
//   node scripts/test_tour.mjs [result dir]
import { chromium } from "playwright";
import { execSync } from "node:child_process";
import { appendFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SITE = "https://drexthealpha.github.io/Knos/", APP = "https://knos.onrender.com";
const DIR = process.argv[2] || "C:/Users/zulab/knos-v1-private/v0328/world";
const lines = [], fails = [];
const ok = (c, w) => { lines.push(`${c ? "ok  " : "FAIL"} ${w}`); console.log(lines.at(-1)); if (!c) fails.push(w); };
const status = await fetch(APP + "/api/status").then((r) => r.json());
const deps = status.deps || {};
const browser = await chromium.launch();
const errors = [];
let cmds = [];
try {
  for (const width of [390, 1280]) for (const scheme of ["light", "dark"]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, colorScheme: scheme });
    page.on("pageerror", (e) => errors.push(`${width} ${scheme}: ${e.message}`));
    await page.goto(SITE + "start/?t=" + Date.now(), { waitUntil: "load", timeout: 90000 });
    await page.waitForFunction(() => [...document.querySelectorAll("[data-dep] [data-state]")].every((e) => e.dataset.state), null, { timeout: 90000 }).catch(() => {});
    const rows = await page.$$eval("[data-dep]", (ls) => ls.map((l) => ({ dep: l.dataset.dep, state: l.querySelector("[data-state]").dataset.state, down: l.querySelector("[data-down]").textContent })));
    const same = rows.every((r) => deps[r.dep] && deps[r.dep].state === r.state && r.down.includes(deps[r.dep].when_down));
    ok(rows.length === 5 && same, `${width} ${scheme}: 5 status rows equal /api/status (${rows.map((r) => `${r.dep} ${r.state}`).join(", ")})`);
    const sideways = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    ok(!sideways, `${width} ${scheme}: nothing scrolls sideways`);
    if (width === 1280 && scheme === "light") {
      const links = await page.$$eval(".s-block a", (as) => as.map((a) => a.href));
      for (const href of links) {
        let r = await fetch(href, { redirect: "follow" }).catch(() => null), how = "";
        const tx = href.match(/explorer\.solana\.com\/tx\/([1-9A-HJ-NP-Za-km-z]{64,90})/);
        if (tx && r && r.status === 429) {      // the explorer limits scripts: the transaction is read from devnet itself
          const j = await fetch("https://api.devnet.solana.com", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "getTransaction", params: [tx[1], { maxSupportedTransactionVersion: 1 }] }) }).then((x) => x.json()).catch(() => ({}));
          r = { status: j.result ? 200 : 404 }; how = " (the explorer answered 429; devnet holds the transaction)";
        }
        ok(r && r.status < 400, `block link ${href.slice(0, 90)}: HTTP ${r ? r.status : "no answer"}${how}`);
      }
      cmds = await page.$$eval("[data-cmd]", (cs) => cs.map((c) => ({ k: c.dataset.cmd, t: c.textContent })));
    }
    await page.close();
  }
  const front = await browser.newPage();
  await front.goto(SITE + "?t=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 90000 });
  const start = await front.$eval("#go-start", (a) => [a.textContent.trim(), a.getAttribute("href")]).catch(() => null);
  ok(start && start[0] === "Start" && /start\/$/.test(start[1]), `the front door's bar links it as ${start ? `"${start[0]}" (${start[1]})` : "nothing"}`);
} finally { await browser.close(); }
ok(errors.length === 0, `${errors.length} page errors${errors.length ? ": " + errors.slice(0, 2).join(" | ") : ""}`);
// every command as printed
const tmp = mkdtempSync(join(tmpdir(), "knos-t1-"));
try {
  for (const c of cmds) {
    try {
      if (c.k === "mcp") { const out = execSync(c.t, { cwd: tmp, encoding: "utf8", shell: true, timeout: 120000 }); execSync("claude mcp remove knos -s local", { cwd: tmp, shell: true, timeout: 120000 }); ok(/knos/i.test(out), `ran: ${c.t} (then removed)`); }
      else if (c.k === "pip") { execSync(`py -3 -m venv "${join(tmp, "v")}"`, { shell: true, timeout: 300000 }); execSync(`"${join(tmp, "v", "Scripts", "python.exe")}" -m ${c.t}`, { shell: true, timeout: 600000, stdio: "ignore" });
        const v = execSync(`"${join(tmp, "v", "Scripts", "python.exe")}" -m pip show knos`, { shell: true, encoding: "utf8" }); ok(/Name: knos/.test(v), `ran: ${c.t} (${(v.match(/Version: (\S+)/) || [])[1]})`); }
      else { const out = execSync(c.t, { encoding: "utf8", shell: "bash", timeout: 120000 }); ok(/"executable":\s*true/.test(out), `ran: the devnet program check: executable ${/"executable":\s*true/.test(out)}`); }
    } catch (e) { ok(false, `ran: ${c.t.slice(0, 60)}: ${String(e.message).slice(0, 160)}`); }
  }
} finally { rmSync(tmp, { recursive: true, force: true }); }
const line = fails.length ? `FAIL test_tour: ${fails.length} check(s) failed` : `PASS test_tour: 4 blocks at 2 widths in light and dark, 5 status rows equal /api/status, ${cmds.length} commands ran as printed, 0 page errors`;
lines.push(line); console.log(line);
appendFileSync(`${DIR}/test_tour.txt`, lines.join("\n") + "\n");
process.exit(fails.length ? 1 : 0);
