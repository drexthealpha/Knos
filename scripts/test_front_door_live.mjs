// test_front_door_live: the live front door and the pages beside it raise no page error, and each of the 8 chips,
// pressed at 390 and 1280 px, draws a verdict card within 20 s. Run by the pages workflow after each deploy (--ci:
// the deploy is the commit; Render is whatever is live) and with the commit under test.
//   node scripts/test_front_door_live.mjs [commit sha under test | --ci]
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const ARG = process.argv[2] || "--ci", CI = ARG === "--ci";
const OUT = CI ? null : `${process.env.KNOS_WORLD || `${process.env.KNOS_PRIVATE_DIR || "."}/v0328/world`}/test_front_door_live.txt`;
const SITE = "https://drexthealpha.github.io/Knos/", API = "https://knos.onrender.com";
const lines = []; let fails = 0;
const ok = (c, what) => { lines.push(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails++; };

if (!CI) {
  const dep = JSON.parse(execFileSync("gh", ["api", "repos/drexthealpha/Knos/deployments?environment=github-pages&per_page=1"], { encoding: "utf8" }))[0];
  ok(dep && dep.sha === ARG, `Pages deployed at ${dep && dep.sha.slice(0, 7)} (commit under test ${ARG.slice(0, 7)})`);
  const py = process.env.KNOS_PY || fileURLToPath(new URL("../.venv/Scripts/python.exe", import.meta.url));
  const render = execFileSync(py, ["-I", process.env.KNOS_RENDER_LATEST], { encoding: "utf8" }).trim().split(/\s+/);
  ok(render[1] === "live" && ARG.startsWith(render[2]), `Render live at ${render[2]} (${render[1]})`);
}
// a result page of a recorded sample (the first chip with a recording)
const R = `${API}/r/14d68eb782caff05`;
const PAGES = [SITE, SITE + "demo/", SITE + "check/", SITE + "how-we-test.html", R, API + "/app/"];
const browser = await chromium.launch();
let chips = 0, pressed = 0, more = 0;
try {
  for (const u of PAGES) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e.message || e).slice(0, 120)));
    await page.goto(u + (u.includes("?") ? "&" : "?") + "t=" + Date.now(), { waitUntil: "load", timeout: 90000 }).catch((e) => errors.push(`load: ${String(e.message).slice(0, 80)}`));
    await page.waitForTimeout(2500);
    ok(errors.length === 0, `${u}: ${errors.length} page errors${errors.length ? ` ${JSON.stringify(errors.slice(0, 2))}` : ""}`);
    await page.close();
  }
  for (const [w, h] of [[390, 844], [1280, 900]]) {
    const probe = await browser.newPage({ viewport: { width: w, height: h } });
    await probe.goto(SITE + "?t=" + Date.now(), { waitUntil: "load" });
    const qs = await probe.$$eval(".k-try .k-chip[data-q]", (b) => b.map((x) => x.dataset.q));
    more = await probe.$$eval("[data-more-chips]", (e) => e.length);
    await probe.close();
    chips = qs.length;
    for (const q of qs) {
      const page = await browser.newPage({ viewport: { width: w, height: h } });
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e.message || e).slice(0, 120)));
      await page.goto(SITE + "?t=" + Date.now(), { waitUntil: "load" });
      await page.click("#k-samples summary");      // the chips sit under "Try a sample", closed on the first screen
      const t0 = Date.now();
      await page.click(`.k-try .k-chip[data-q="${q}"]`);
      // a card drawn for this press: not the past result in its fold, and holding a verdict
      const got = await page.waitForFunction(() => {
        const slot = document.getElementById("k-card");
        const card = slot && [...slot.querySelectorAll(".k-card")].find((c) => !c.closest(".k-past") && c.querySelector(".k-verdict"));
        return card ? card.querySelector(".k-verdict").textContent.trim() : null;
      }, null, { timeout: 20000 }).then((x) => x.jsonValue()).catch(() => null);
      const s = ((Date.now() - t0) / 1000).toFixed(1);
      const good = !!got && errors.length === 0;
      pressed += good;
      lines.push(`${good ? "ok  " : "FAIL"} ${w}px ${q.slice(0, 40).padEnd(40)} ${got ? `"${got}" in ${s} s` : "no verdict card in 20 s"}${errors.length ? ` ${JSON.stringify(errors.slice(0, 2))}` : ""}`);
      if (!good) fails++;
      await page.close();
    }
  }
  // 8 chips, or the 6 with a recording and one line for the 2 that wait on Qloo
  ok(chips === 8 || (chips === 6 && more === 1), `the front door holds ${chips} chips${more ? " and the line for the 2 that wait on Qloo" : ""}`);
} finally {
  await browser.close();
}
lines.push(fails ? `FAIL test_front_door_live: ${fails} check(s) failed; ${pressed} of ${chips * 2} chip presses drew a verdict card` :
  `PASS test_front_door_live: 0 page errors on ${PAGES.length} pages, ${pressed} of ${chips * 2} chip presses drew a verdict card within 20 s`);
console.log(lines.join("\n"));
if (OUT) writeFileSync(OUT, lines.join("\n") + "\n");
process.exit(fails ? 1 : 0);
