// node tests/web/console_faucet.mjs <site dir>
// The Console's way to test money, on a build of web/ in headless Chromium: "Get test USDC" is in the Console's top line
// for every visitor, before any wallet or passkey exists (the passkey wallet's own button shows only once a wallet holds
// none, and a browser without WebAuthn never gets there); it opens the playground's faucet issue (docs/reference/FAUCET.md) in a
// new tab; nothing runs off the side at 390 or 1280. No browser: a failure in CI, a skip elsewhere (tests/web/overflow.mjs).
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const root = process.argv[2];
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/console_faucet.mjs <site dir>"); process.exit(2); }
const FAUCET = "https://github.com/drexthealpha/knos-playground/issues?q=is%3Aissue+is%3Aopen+label%3Afaucet";
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
try {
  for (const width of [390, 1280]) {
    const ctx = await browser.newContext({ viewport: { width, height: 844 } });
    await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : route.abort()));
    const page = await ctx.newPage();
    await page.goto(`${base}#buy`);
    await page.waitForSelector("#buy-get-usdc", { state: "attached", timeout: 30_000 }).catch(() => {});
    const a = await page.evaluate(() => { const e = document.getElementById("buy-get-usdc"); if (!e) return null; const r = e.getBoundingClientRect();
      return { text: e.textContent.trim(), href: e.href, target: e.target, rel: e.rel, shown: !!e.offsetParent && r.width > 0, top: e.closest(".buy-top") !== null, inView: r.top < innerHeight }; });
    check(`${width}px: the Console's top line offers "Get test USDC" before any wallet exists`, a && a.text === "Get test USDC" && a.shown && a.top && a.inView, a);
    check(`${width}px: it opens the playground's faucet issue in a new tab`, a && a.href === FAUCET && a.target === "_blank" && a.rel.includes("noopener"), a);
    check(`${width}px: nothing runs off the side`, await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
    await ctx.close();
  }
} finally { await browser.close(); server.close(); }
console.log(fails ? `${fails} failed` : "all passed");
process.exit(fails ? 1 : 0);
