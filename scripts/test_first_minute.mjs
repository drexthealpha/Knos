// test_first_minute, live: the front door's first screen, with no click, at 390 px and 1280 px in light and dark. On it:
// the line that names who Knos is for, a finished real result (the recorded sample whose verdict is Open), both proof
// lines with links that answer 200, the Proof link in the top bar, "about 2 s" beside Check demand, and no Sign in.
//   node scripts/test_first_minute.mjs <commit sha under test>
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const [SHA] = process.argv.slice(2);
const OUT = `${process.env.KNOS_WORLD || `${process.env.KNOS_PRIVATE_DIR || "."}/v0328/world`}/test_first_minute.txt`;
const SITE = process.env.KNOS_SITE || "https://drexthealpha.github.io/Knos/";
const BUYER = "For anyone about to build or fund a product: see who wants it and where, then get paid only on proof.";
const PROOF = ["Cheating pull requests caught: Knos 60 of 60, plain CI 31 of 60", "Ready briefs passed 70% vs 5% for vague ones"];
const lines = []; let fails = 0;
const ok = (c, what) => { lines.push(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails++; };

const dep = JSON.parse(execFileSync("gh", ["api", "repos/drexthealpha/Knos/deployments?environment=github-pages&per_page=1"], { encoding: "utf8" }))[0];
ok(dep && dep.sha === SHA, `Pages deployed at ${dep && dep.sha.slice(0, 7)} (commit under test ${SHA.slice(0, 7)})`);
const py = process.env.KNOS_PY || fileURLToPath(new URL("../.venv/Scripts/python.exe", import.meta.url));
const render = execFileSync(py, ["-I", process.env.KNOS_RENDER_LATEST], { encoding: "utf8" }).trim().split(/\s+/);
ok(render[1] === "live" && SHA.startsWith(render[2]), `Render live at ${render[2]} (${render[1]})`);

const status = async (u) => { try { return (await fetch(u, { redirect: "follow" })).status; } catch { return 0; } };
const browser = await chromium.launch();
const errors = [], links = new Set();
let screens = 0;
try {
  // the free server wakes first, so the first screen is measured and not its cold start
  await (await fetch("https://knos.onrender.com/healthz").catch(() => null));
  for (const [w, h, scheme] of [[390, 844, "light"], [390, 844, "dark"], [1280, 800, "light"], [1280, 800, "dark"]]) {
    const cx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: scheme });
    const p = await cx.newPage();
    p.on("pageerror", (e) => errors.push(`${w} ${scheme}: ${e.message}`));
    await p.goto(SITE + "?t=" + Date.now(), { waitUntil: "load" });
    await p.waitForSelector("#k-card > .k-card .k-verdict", { timeout: 60000 }).catch(() => {});
    const s = await p.evaluate(() => {
      const H = innerHeight, on = (el) => { if (!el || !el.checkVisibility()) return false; const r = el.getBoundingClientRect(); return r.top < H && r.bottom > 0; };
      const card = document.querySelector("#k-card > .k-card"), proof = [...document.querySelectorAll("[data-proof-lines] a[data-proof-line]")];
      const bar = document.querySelector("#k-bar"), pl = bar?.querySelector("a[data-proof]");
      return { buyer: document.querySelector("#k-for")?.textContent.trim() || "", buyerOn: on(document.querySelector("#k-for")),
        card: !!card, cardOn: on(card), verdict: card?.querySelector(".k-verdict")?.firstChild?.textContent.trim() || "", kick: card?.querySelector(".k-kick")?.textContent.trim() || "",
        proof: proof.map((a) => ({ text: a.textContent.trim(), href: a.href, on: on(a) })), proofLink: pl ? { href: pl.href, on: on(pl), text: pl.textContent.trim() } : null,
        signIn: [...(bar?.querySelectorAll("a, button") || [])].some((x) => /sign in/i.test(x.textContent) && x.checkVisibility()),
        wait: (() => { const x = document.querySelector("#k-ask [data-wait]"); return x && on(x) ? x.textContent.trim() : ""; })() };
    });
    const good = s.buyer === BUYER && s.buyerOn && s.card && s.cardOn && s.verdict === "Open for pre-orders"
      && s.proof.length === 2 && s.proof.every((x, i) => x.text === PROOF[i] && x.on) && s.proofLink && s.proofLink.on && s.proofLink.text === "Proof"
      && !s.signIn && s.wait === "about 2 s";
    s.proof.forEach((x) => links.add(x.href)); if (s.proofLink) links.add(s.proofLink.href);
    screens += good;
    lines.push(`${good ? "ok  " : "FAIL"} ${w} ${scheme}: buyer line ${s.buyerOn ? "on screen" : "off screen"}; card "${s.verdict}" (${s.kick.slice(0, 50)}) ${s.cardOn ? "on screen" : "off screen"}; proof lines ${s.proof.filter((x) => x.on).length} of 2 on screen; Proof link ${s.proofLink?.on ? "on screen" : "missing"}; Sign in ${s.signIn ? "shown" : "absent"}; "${s.wait}"`);
    await cx.close();
  }
} finally {
  await browser.close();
}
ok(screens === 4, `first screens with every part: ${screens} of 4`);
let good = 0;
for (const u of links) { const c = await status(u); good += c === 200; lines.push(`${c === 200 ? "ok  " : "FAIL"} ${c} ${u}`); if (c !== 200) fails++; }
ok(errors.length === 0, `page errors: ${errors.length}${errors.length ? ` (${errors.slice(0, 3).join("; ")})` : ""}`);
lines.push(fails ? `FAIL test_first_minute: ${fails} check(s) failed`
  : `PASS test_first_minute: 4 of 4 first screens (390 and 1280, light and dark) with the buyer line, a finished Open card, both proof lines, the Proof link and no Sign in; ${good} links 200; 0 page errors`);
console.log(lines.join("\n"));
writeFileSync(OUT, lines.join("\n") + "\n", { flag: "a" });
process.exit(fails ? 1 : 0);
