// node tests/web/walk.mjs <site dir> [--max-pages N]
//
// The stranger walk as a test (IQ PLAN.md L41; UX/ROUND8-ITEMS.md:150, MISSION build_system_package.py:18 S12): on the
// site as built locally (scripts/build_site.sh, composed by scripts/site_pages.py and served with the local app by
// tests/web/law_lib.mjs), every page of the build is opened and every button on it is pressed, once by mouse and once
// by keyboard (focused, then Enter), with every folded part (details) opened first. Every link of the page must answer with a page, not the 404 page. It fails on:
//   - a page, or a link's target, that answers 404 or 5xx, or shows the site's 404 page;
//   - an unhandled error in the page (pageerror) or a console error, on load or after any press;
//   - a press that leaves the browser on an error page.
// The old addresses /near/ and /check/ must land on a working page. Outside addresses are not followed (law_lib refuses
// them), so a console line about a refused outside request is not counted. Each press runs on a fresh load of its page.
// No node, no playwright package or no browser: SKIP (tests/web/overflow.mjs chromiumOrSkip).
import { readdirSync, statSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { setup } from "./law_lib.mjs";

const args = process.argv.slice(2);
const site = args.find((a) => !a.startsWith("--"));
const maxAt = args.indexOf("--max-pages");
const MAX = maxAt >= 0 ? Number(args[maxAt + 1]) : Infinity;
const L = await setup(site);
const { ORIGIN, root } = L;
const NOT_FOUND = readFileSync(join(root, "404.html"), "utf8").match(/<title>([^<]*)<\/title>/i)?.[1] || "\u0000";
// console lines that are the walk's own refusals of outside addresses, not the page's errors
const OUTSIDE = /net::ERR_FAILED|net::ERR_BLOCKED|Failed to load resource|ERR_ABORTED/;

function pages(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...pages(p));
    else if (name.endsWith(".html") && name !== "404.html") out.push(relative(root, p).split(sep).join("/"));
  }
  return out.sort();
}

const fails = [];
const fail = (where, what) => { fails.push(`${where}: ${what}`); console.log(`FAIL ${where}: ${what}`); };
const errorsOf = (page) => [...page.law.errors, ...page.law.console.filter((c) => !OUTSIDE.test(c))];
// every folded part opened, so the buttons inside it can be pressed too (not the menu: its open panel covers the page)
const unfold = (page) => page.$$eval("details:not(.kmenu)", (ds) => ds.forEach((d) => { d.open = true; })).catch(() => {});
const isErrorPage = async (page) => {
  const t = await page.title().catch(() => "");
  return t === NOT_FOUND || /^(404|500|502|503)\b/.test(t);
};

const checked = new Map();   // link target -> status
async function linkStatus(url) {
  if (checked.has(url)) return checked.get(url);
  const r = await fetch(url, { redirect: "follow" }).catch(() => null);
  const s = r ? r.status : 0;
  checked.set(url, s);
  return s;
}

// a redirect page (meta refresh to the front door) is checked as a link, not walked
const isRedirect = (rel) => /http-equiv=["']?refresh/i.test(readFileSync(join(root, rel), "utf8").slice(0, 3000));
const list = pages(root).filter((p) => !isRedirect(p)).slice(0, MAX);
let presses = 0;

for (const rel of list) {
  const url = `${ORIGIN}/Knos/${rel.replace(/(^|\/)index\.html$/, "$1")}`;
  const page = await L.open(url, { w: 1280, h: 900, settle: 500 });
  const st = page.law.response ? page.law.response.status() : 0;
  if (st >= 400 || st === 0 || (await isErrorPage(page))) { fail(rel, `opens with ${st || "no answer"}`); await page.context().close(); continue; }
  for (const e of errorsOf(page)) fail(rel, `on load: ${e.slice(0, 200)}`);
  const links = await page.$$eval("a[href]", (as) => as.map((a) => a.href).filter((h) => h.startsWith(location.origin)));
  for (const h of new Set(links.map((h) => h.split("#")[0]))) {
    const s = await linkStatus(h);
    if (s >= 400 || s === 0) fail(rel, `link ${h.slice(ORIGIN.length)} answers ${s || "nothing"}`);
  }
  await unfold(page);
  const n = await page.$$eval("button", (bs) => bs.filter((b) => b.offsetParent !== null && !b.disabled).length);
  await page.context().close();
  for (let i = 0; i < n; i++) {
    for (const how of ["mouse", "keyboard"]) {
      const p = await L.open(url, { w: 1280, h: 900, settle: 300 });
      await unfold(p);
      const b = (await p.$$("button")).filter(Boolean);
      const vis = [];
      for (const x of b) if (await x.isVisible().catch(() => false) && await x.isEnabled().catch(() => false)) vis.push(x);
      const btn = vis[i];
      if (!btn) { await p.context().close(); continue; }
      const name = ((await btn.innerText().catch(() => "")) || (await btn.getAttribute("aria-label")) || `button ${i}`).trim().slice(0, 40);
      const before = errorsOf(p).length;
      try {
        if (how === "mouse") await btn.click({ timeout: 3000 });
        else {
          if ((await btn.evaluate((b) => b.tabIndex)) < 0) fail(rel, `"${name}" cannot be reached with Tab (tabindex -1)`);
          await btn.focus(); await p.keyboard.press("Enter");
        }
      } catch (e) {
        const lines = String(e.message).split("\n");
        const why = lines.filter((l) => /intercepts pointer events|not visible|outside of the viewport|not stable/.test(l)).pop() || "";
        fail(rel, `${how} press on "${name}": ${lines[0]} ${why.trim().slice(0, 200)}`);
      }
      presses++;
      await p.waitForTimeout(600);
      for (const e of errorsOf(p).slice(before)) fail(rel, `after a ${how} press on "${name}": ${e.slice(0, 200)}`);
      if (await isErrorPage(p)) fail(rel, `a ${how} press on "${name}" leads to an error page (${p.url()})`);
      await p.context().close();
    }
  }
}

for (const old of ["near/", "check/"]) {
  const p = await L.open(`${ORIGIN}/Knos/${old}`, { w: 1280, h: 900, settle: 1500 });
  const st = p.law.response ? p.law.response.status() : 0;
  const words = (await p.innerText("body").catch(() => "")).trim().split(/\s+/).length;
  if (st >= 400 || st === 0 || (await isErrorPage(p)) || words < 5) fail(`/${old}`, `the old address does not land on a working page (${st}, ${p.url()})`);
  await p.context().close();
}

console.log(`${fails.length ? "FAIL" : "ok"} walked ${list.length} pages, ${presses} presses, ${checked.size} link targets: ${fails.length} failures`);
await L.close();
process.exit(fails.length ? 1 : 0);
