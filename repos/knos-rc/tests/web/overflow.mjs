// node tests/web/overflow.mjs <site dir> [screenshot dir]
// No page of the site scrolls sideways: every view (each hash the menu and the router know), with its details open, at
// the widths of a small phone, two common phones, a tablet and a laptop, in light and in dark. A page that runs off the
// side fails, and the elements that stick out are named. Everything outside the site's own files is refused, so this
// is the page as it stands before any answer arrives. Nor is a table squeezed: no row of any table, its folds shut, is
// taller than ROW_MAX px (three columns on a phone once made a sentence a word a line, a refusal 500 px and a page 30,000); tests/web/site.mjs holds the same line for the answers (a
// result, a wallet, a transaction's accounts) at the same widths. With a screenshot dir, the first screen is saved at
// 1280 and 390 in both schemes. No `playwright` package or no browser: a failure in CI, a skip elsewhere (see `owed`).
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname } from "node:path";

export const WIDTHS = [320, 360, 390, 768, 1280];
export const ROW_MAX = 400;
export const PAGES = ["", "#protect", "#fund", "#money", "#task", "#anyissue", "#claim", "#pricing", "#records", "#u=alice", "#r=octo/widgets", "#rank=earners",
  "#network", "#build", "#buy", "#install", "#capabilities", "#status", "#index", "#pilot", "#reproduce", "#demo", "#shadow", "#verifier", "#playground", "#terms",
  "#supplier", "#invoice-statement", "#story", "#keyholder", "#check-a-pull-request", "#record", "#record=codex", "#check=acme/app/7"];
// THE CHECK OF ONE PULL REQUEST (web/check.js at #check=owner/repo/123, its share row web/share.js) is measured with a
// verdict drawn: GitHub's answers for acme/app#7 are the recorded ones of tests/data/front_verdict.json. Every other
// request outside the site is still refused.
export const CHECKED = "#check=acme/app/7";
const RECORDED = (() => { try { return JSON.parse(readFileSync(new URL("../data/front_verdict.json", import.meta.url), "utf8")).api; } catch { return null; } })();
export function answerGitHub(route) {
  const u = new URL(route.request().url()), at = u.pathname.slice(1);
  const got = !RECORDED || u.origin !== "https://api.github.com" ? null : at === "repos/acme/app/pulls/7" ? RECORDED[at]
    : /^repos\/acme\/app\/commits\/\w+\/check-runs$/.test(at) ? RECORDED["check-runs"] : /^repos\/acme\/app\/commits\/\w+\/status$/.test(at) ? RECORDED.status
      : at === "repos/acme/app/pulls" ? [RECORDED["repos/acme/app/pulls/7"]] : null;
  if (got === null) return route.abort();
  return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(got) });
}
// The pages this build added by name (web/views.js ADDED, as scripts/build_site.sh left it: a page whose module or data
// is not in the build is not in the list). They are held to the same width and the same word budget as the rest.
export const addedPages = (root) => { try { return [...readFileSync(join(root, "views.js"), "utf8").matchAll(/^\s+([\w-]+): \{ file: "/gm)].map((m) => m[1]); } catch { return []; } };
// The menu this build shows at a laptop's width (web/front.js fitBar): the bar is six words; a page added to the bar
// takes its words from Docs, then Install, then Check, which go under More, first there, in the bar's own order.
export function menuOf(root) {
  let text = ""; try { text = readFileSync(join(root, "views.js"), "utf8"); } catch { /* a build without the list */ }
  const added = [...text.matchAll(/^\s+([\w-]+): \{ file: "[^"]+", draw: "\w+", nav: "([^"]+)"(, bar: true)?/gm)].map((m) => ({ name: m[1], nav: m[2], bar: !!m[3] }));
  const bar = ["Check", "Demo", "Console", "Install", ...added.filter((a) => a.bar).map((a) => a.nav), "Pricing", "Docs"], first = [];
  const words = () => bar.join(" ").split(" ").length;
  if (added.some((a) => a.bar)) for (const y of ["Docs", "Install", "Check"]) { if (words() <= 6) break; bar.splice(bar.indexOf(y), 1); first.unshift(y); }
  return { added, bar, first, last: added.filter((a) => !a.bar).map((a) => a.nav) };
}
export const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
// With no browser a run says SKIP and exits 0, except where a browser is owed: in CI (the web job installs Playwright and
// Chromium before these scripts) or with KNOS_REQUIRE_BROWSER=1, where the same thing is a failure. Under pytest
// (tests/test_site_overflow.py) it stays a skip, which pytest reports by name.
const owed = process.env.KNOS_REQUIRE_BROWSER === "1" || (!!process.env.CI && !process.env.PYTEST_CURRENT_TEST);
const skip = (why) => { if (owed) { console.error(`FAIL no browser to measure with: ${why}`); process.exit(1); } console.log(`SKIP ${why}`); process.exit(0); };

export async function chromiumOrSkip() {
  let pw;
  try { pw = await import("playwright"); } catch {
    // an install outside this tree (NODE_PATH, which `import` does not read)
    const paths = (process.env.NODE_PATH || "").split(":").filter(Boolean);
    try { pw = createRequire(import.meta.url)(createRequire(import.meta.url).resolve("playwright", { paths })); } catch { skip("the playwright package is not installed"); }
  }
  const { chromium } = pw.default || pw;
  try { return await chromium.launch(); } catch (e) { skip(`no Chromium to start: ${String(e.message).split("\n")[0]}`); }
}

// What runs off the side of the page: how far, and the first few elements that do it.
export const measure = (page) => page.evaluate(() => {
  const root = document.documentElement, wide = root.clientWidth;
  const out = [...document.querySelectorAll("body *")].filter((e) => e.offsetParent !== null && e.getBoundingClientRect().right > wide + 1
    && !e.closest(".table-wrap, pre, .scroll"));                  // a table or a block of code scrolls inside its own box
  return { over: root.scrollWidth - wide, culprits: out.slice(0, 4).map((e) => `<${e.tagName.toLowerCase()}${e.id ? ` id=${e.id}` : ""}${typeof e.className === "string" && e.className ? ` class=${e.className}` : ""}> ${e.textContent.trim().slice(0, 40)}`) };
});

// The rows of a table that a narrow column has stretched past ROW_MAX: their height and their first words.
export const tallRows = (page) => page.evaluate((max) => [...document.querySelectorAll("tr")].filter((r) => r.offsetParent !== null && r.getBoundingClientRect().height > max)
  .map((r) => `${Math.round(r.getBoundingClientRect().height)}px: ${r.textContent.trim().slice(0, 40)}`), ROW_MAX);

async function main() {
  const root = process.argv[2], shots = process.argv[3];
  if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/overflow.mjs <site dir> [screenshot dir]"); process.exit(2); }
  const browser = await chromiumOrSkip();
  const server = createServer((req, res) => {
    const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
    if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`;
  let fails = 0, looked = 0;
  for (const scheme of ["light", "dark"]) {
    const ctx = await browser.newContext({ colorScheme: scheme, viewport: { width: 1280, height: 800 } });
    await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : answerGitHub(route)));
    // one page a width, all at once: every page is still loaded anew at its own width, and the waiting is shared
    const lines = await Promise.all(WIDTHS.map(async (width) => {
      const page = await ctx.newPage(), said = [];
      await page.setViewportSize({ width, height: 800 });
      for (const hash of scheme === "light" ? [...PAGES, ...addedPages(root).map((n) => `#${n}`)] : [""]) {      // the scheme changes colours, not sizes: dark is held on the first screen
        await page.goto("about:blank"); await page.goto(base + hash, { waitUntil: "load" });
        // a page's code arrives when the page is first opened: measured once it has run (web/front.js marks the root then)
        await page.waitForFunction(() => document.documentElement.dataset.ready !== undefined, null, { timeout: 15000 }).catch(() => {});
        if (hash === CHECKED) await page.waitForSelector("#check-share [data-share]", { timeout: 10000 }).catch(() => {});
        await page.evaluate(() => document.fonts.ready);
        await page.waitForTimeout(150);
        const tall = await tallRows(page);                         // as the reader first sees it: a shut fold is shut
        await page.evaluate(() => document.querySelectorAll("details").forEach((d) => { d.open = true; }));
        const { over, culprits } = await measure(page);
        // a page whose scripts did not run shows the first screen at every hash, and would pass for the wrong reason
        if (!(await page.isVisible("#theme"))) said.push([false, `FAIL ${scheme} ${width}px ${hash || "(first screen)"}: the page's scripts did not run`]);
        else if (over > 1) said.push([false, `FAIL ${scheme} ${width}px ${hash || "(first screen)"}: ${over}px off the side`, culprits]);
        else if (tall.length) said.push([false, `FAIL ${scheme} ${width}px ${hash || "(first screen)"}: ${tall.length} table rows taller than ${ROW_MAX}px`, tall.slice(0, 3)]);
        else said.push([true, `ok   ${scheme} ${width}px ${hash || "(first screen)"}`]);
      }
      if (shots && (width === 1280 || width === 390)) {
        mkdirSync(shots, { recursive: true });
        await page.goto("about:blank"); await page.goto(base, { waitUntil: "load" }); await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(150);
        await page.screenshot({ path: join(shots, `first-${width}-${scheme}.png`) });
        await page.screenshot({ path: join(shots, `first-${width}-${scheme}-full.png`), fullPage: true });
      }
      await page.close();
      return said;
    }));
    for (const [ok, ...words] of lines.flat()) { looked++; if (ok) console.log(...words); else { fails++; console.error(...words); } }
    await ctx.close();
  }
  await browser.close(); server.close();
  console.log(fails ? `${fails} of ${looked} pages scroll sideways or squeeze a table` : `${looked} pages, none scrolls sideways or squeezes a table`);
  process.exit(fails ? 1 : 0);
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split(/[\\/]/).pop())) await main();
