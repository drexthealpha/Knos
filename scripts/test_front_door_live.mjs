// test_front_door_live: the live front door and the pages beside it raise no page error.
// Run by the pages workflow after each deploy (--ci:
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

try {
  for (const u of PAGES) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e.message || e).slice(0, 120)));
    const open = new Map();
    page.on("request", (r) => open.set(r, Date.now()));
    page.on("requestfinished", (r) => open.delete(r));
    page.on("requestfailed", (r) => open.delete(r));
    await page.goto(u + (u.includes("?") ? "&" : "?") + "t=" + Date.now(), { waitUntil: "domcontentloaded", timeout: 90000 }).catch((e) => errors.push(`load: ${String(e.message).slice(0, 60)}; still open: ${[...open.keys()].map((r) => r.url().split("?")[0]).join(" ")}`));
    await page.waitForTimeout(5000);
    ok(errors.length === 0, `${u}: ${errors.length} page errors${errors.length ? ` ${JSON.stringify(errors.slice(0, 2))}` : ""}`);
    await page.close();
  }
} finally {
  await browser.close();
}
lines.push(fails ? `FAIL test_front_door_live: ${fails} check(s) failed` : `PASS test_front_door_live: 0 page errors on ${PAGES.length} pages`);
console.log(lines.join("\n"));
if (OUT) writeFileSync(OUT, lines.join("\n") + "\n");
process.exit(fails ? 1 : 0);
