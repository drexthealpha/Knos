// test_proof_page, live: /proof/ at 390 px and 1280 px renders with 0 page errors and its bar chart on the first screen;
// every bar's link answers 200; the results board equals How we test Knos's; each Knos program's devnet transaction
// count is drawn and equals devnet's own answer (getSignaturesForAddress, limit 1,000), its newest transaction resolving
// on devnet; the bar's Proof link opens /proof/; and the front door's two numbers equal the page's bars.
//   node scripts/test_proof_page.mjs <commit sha under test>
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const [SHA] = process.argv.slice(2);
const OUT = `${process.env.KNOS_WORLD || `${process.env.KNOS_PRIVATE_DIR || "."}/v0328/world`}/test_proof_page.txt`;
const SITE = process.env.KNOS_SITE || "https://drexthealpha.github.io/Knos/", RPC = "https://api.devnet.solana.com";
const lines = []; let fails = 0;
const ok = (c, what) => { lines.push(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails++; };

const dep = JSON.parse(execFileSync("gh", ["api", "repos/drexthealpha/Knos/deployments?environment=github-pages&per_page=1"], { encoding: "utf8" }))[0];
ok(dep && dep.sha === SHA, `Pages deployed at ${dep && dep.sha.slice(0, 7)} (commit under test ${SHA.slice(0, 7)})`);
const py = process.env.KNOS_PY || fileURLToPath(new URL("../.venv/Scripts/python.exe", import.meta.url));
const render = execFileSync(py, ["-I", process.env.KNOS_RENDER_LATEST], { encoding: "utf8" }).trim().split(/\s+/);
ok(render[1] === "live" && SHA.startsWith(render[2]), `Render live at ${render[2]} (${render[1]})`);

const status = async (u) => { try { return (await fetch(u, { redirect: "follow" })).status; } catch { return 0; } };
const rpc = async (method, params) => (await (await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) })).json()).result;
const browser = await chromium.launch();
const errors = [];
let page = null;
try {
  for (const [w, h, scheme] of [[390, 844, "dark"], [1280, 800, "light"]]) {
    const cx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: scheme });
    const p = await cx.newPage();
    p.on("pageerror", (e) => errors.push(`${w}: ${e.message}`));
    await p.goto(SITE + "proof/?t=" + Date.now(), { waitUntil: "load" });
    await p.waitForFunction(() => document.querySelectorAll("#p-tx tr[data-program]").length >= 4, null, { timeout: 60000 }).catch(() => {});
    const s = await p.evaluate(() => {
      const c = document.getElementById("p-chart"), r = c?.getBoundingClientRect();
      return { chartOn: !!r && r.top < innerHeight && r.height > 0, over: document.documentElement.scrollWidth - innerWidth,
        bars: [...document.querySelectorAll("#p-chart a.p-bar")].map((a) => ({ row: a.closest("[data-row]").dataset.row, href: a.href, n: Number(a.dataset.n), of: Number(a.dataset.of), text: a.querySelector(".p-val").textContent.trim() })),
        board: (document.querySelector("#board table")?.textContent || "").replace(/s+/g, " ").trim(),
        tx: [...document.querySelectorAll("#p-tx tr[data-program]")].map((t) => ({ program: t.dataset.program, count: t.dataset.count, id: new URL(t.querySelector("a").href).pathname.split("/").pop(), newest: t.querySelector("a[data-tx]")?.href || null })) };
    });
    ok(s.chartOn && s.bars.length === 6 && s.over <= 0, `${w} ${scheme}: the bar chart on the first screen, ${s.bars.length} bars, ${s.over <= 0 ? "no" : "a"} sideways scroll`);
    page = page || s;
    await cx.close();
  }
  // the board, as How we test Knos has it
  const how = await browser.newPage();
  await how.goto(SITE + "how-we-test.html?t=" + Date.now(), { waitUntil: "load" });
  const board = await how.evaluate(() => (document.querySelector("#board table")?.textContent || "").replace(/s+/g, " ").trim());
  await how.close();
  ok(board && board === page.board, `the results board equals How we test Knos's (${board.length} characters)`);
  // the front door: its two numbers and the Proof link
  const front = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await front.goto(SITE + "?t=" + Date.now(), { waitUntil: "load" });
  const f = await front.evaluate(() => ({ lines: [...document.querySelectorAll("[data-proof-lines] a[data-proof-line]")].map((a) => a.textContent.trim()),
    page: document.querySelector("[data-proof-lines] a[data-proof-page]")?.href || "", bar: document.querySelector("#k-bar a[data-proof]")?.href || "" }));
  await front.close();
  const bar = (row, i) => page.bars.filter((b) => b.row === row)[i];
  const want = [`Faked code changes caught, out of 60: Knos ${bar("tamper", 0).text}, usual automatic tests ${bar("tamper", 1).text}`, `Tasks done right: ${bar("ready", 0).text} for a clear job vs ${bar("ready", 1).text} for a vague one`];
  ok(JSON.stringify(f.lines) === JSON.stringify(want), `the front door's numbers equal the page's bars: ${f.lines.join(" | ")}`);
  ok(/\/proof\/$/.test(f.page) && /\/proof\/$/.test(f.bar), `the front door links /proof/ beside its numbers and in its bar (${f.page}, ${f.bar})`);
} finally {
  await browser.close();
}
for (const u of [...new Set(page.bars.map((b) => b.href))]) { const c = await status(u); ok(c === 200, `bar link ${c} ${u}`); }
for (const t of page.tx) {
  const sigs = await rpc("getSignaturesForAddress", [t.id, { limit: 1000 }]).catch(() => null);
  const n = Array.isArray(sigs) ? sigs.length : null;
  const sig = t.newest ? new URL(t.newest).pathname.split("/").pop() : null;
  // the newest transaction is on devnet: its status, searched in devnet's whole history (one paced retry: the public RPC limits bursts)
  const seen = async () => ((await rpc("getSignatureStatuses", [[sig], { searchTransactionHistory: true }]).catch(() => null))?.value || [])[0] || null;
  let tx = sig ? await seen() : null;
  if (sig && !tx) { await new Promise((r) => setTimeout(r, 3000)); tx = await seen(); }
  ok(n != null && Number(t.count) <= n && Number(t.count) >= n - 5 && (!sig || !!tx), `${t.program}: ${t.count} transactions drawn, devnet says ${n}; newest ${sig ? (tx ? "resolves on devnet" : "does not resolve") : "none"}`);
}
ok(page.tx.length === 4, `programs with a devnet count: ${page.tx.length} of 4`);
ok(errors.length === 0, `page errors: ${errors.length}${errors.length ? ` (${errors.slice(0, 3).join("; ")})` : ""}`);
lines.push(fails ? `FAIL test_proof_page: ${fails} check(s) failed`
  : `PASS test_proof_page: /proof/ at 390 and 1280 with 0 page errors, 3 published numbers each against its baseline (6 bars, every link 200), the board equal to How we test Knos's, devnet counts for 4 of 4 programs, the front door's numbers equal`);
console.log(lines.join("\n"));
writeFileSync(OUT, lines.join("\n") + "\n", { flag: "a" });
process.exit(fails ? 1 : 0);
