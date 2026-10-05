// node tests/web/overflow.mjs <site dir> [screenshot dir]
// No page of the site scrolls sideways: every view (each hash the menu and the router know), with its details open, at
// the widths of a small phone, two common phones, a tablet and a laptop, in light and in dark. A page that runs off the
// side fails, and the elements that stick out are named. Everything outside the site's own files is refused, so this
// is the page as it stands before any answer arrives; tests/web/site.mjs holds the same line for the answers (a
// result, a wallet, a transaction's accounts) at the same widths. With a screenshot dir, the first screen is saved at
// 1280 and 390 in both schemes. No `playwright` package or no browser: says so and exits 0 (tests/test_site_overflow.py
// reports that as a skip).
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname } from "node:path";

export const WIDTHS = [320, 360, 390, 768, 1280];
export const PAGES = ["", "#protect", "#fund", "#money", "#task", "#anyissue", "#claim", "#pricing", "#records", "#u=alice", "#r=octo/widgets", "#rank=earners",
  "#network", "#build", "#buy", "#install", "#capabilities", "#status", "#index", "#pilot", "#reproduce", "#demo", "#shadow", "#verifier", "#playground", "#terms"];
export const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const skip = (why) => { console.log(`SKIP ${why}`); process.exit(0); };

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
    await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : route.abort()));
    // one page a width, all at once: every page is still loaded anew at its own width, and the waiting is shared
    const lines = await Promise.all(WIDTHS.map(async (width) => {
      const page = await ctx.newPage(), said = [];
      await page.setViewportSize({ width, height: 800 });
      for (const hash of scheme === "light" ? PAGES : [""]) {      // the scheme changes colours, not sizes: dark is held on the first screen
        await page.goto("about:blank"); await page.goto(base + hash, { waitUntil: "load" });
        await page.evaluate(() => document.fonts.ready);
        await page.waitForTimeout(150);
        await page.evaluate(() => document.querySelectorAll("details").forEach((d) => { d.open = true; }));
        const { over, culprits } = await measure(page);
        // a page whose scripts did not run shows the first screen at every hash, and would pass for the wrong reason
        if (!(await page.isVisible("#theme"))) said.push([false, `FAIL ${scheme} ${width}px ${hash || "(first screen)"}: the page's scripts did not run`]);
        else if (over > 1) said.push([false, `FAIL ${scheme} ${width}px ${hash || "(first screen)"}: ${over}px off the side`, culprits]);
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
  console.log(fails ? `${fails} of ${looked} pages scroll sideways` : `${looked} pages, none scrolls sideways`);
  process.exit(fails ? 1 : 0);
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split(/[\\/]/).pop())) await main();
