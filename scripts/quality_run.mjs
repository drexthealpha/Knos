// The quality numbers of a build: Lighthouse (mobile and desktop, its four categories) and axe-core (in light and in
// dark) on the front door, /demo/, /check/, How we test Knos, /proof/ (this build, served from its folder), one result page
// of the app and the app itself (live). Written to <site>/quality/quality.json with the commit and the time; /quality/ draws them.
// Run by the pages workflow before the site is published, with lighthouse, chrome-launcher, axe-core and playwright
// installed for that step only.
//   node scripts/quality_run.mjs <site dir> <commit sha>
import { chromium } from "playwright";
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { extname, join } from "node:path";
import lighthouse from "lighthouse";
import desktop from "lighthouse/core/config/desktop-config.js";
import * as launcher from "chrome-launcher";

const [SITE, SHA] = process.argv.slice(2);
const AXE = readFileSync(createRequire(import.meta.url).resolve("axe-core/axe.min.js"), "utf8");
const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2", ".xml": "application/xml", ".txt": "text/plain" };
// served as Pages serves it: under /Knos/, a folder answers with its index.html
const server = createServer((q, r) => {
  let p = join(SITE, decodeURIComponent(new URL(q.url, "http://x").pathname).replace(/^\/Knos/, ""));
  if (existsSync(p) && statSync(p).isDirectory()) p = join(p, "index.html");
  if (!existsSync(p)) { r.writeHead(404); return r.end(); }
  r.writeHead(200, { "content-type": TYPES[extname(p)] || "application/octet-stream", "cache-control": "max-age=600" });
  r.end(readFileSync(p));
});
await new Promise((ok) => server.listen(8090, "127.0.0.1", ok));
const BASE = "http://127.0.0.1:8090/Knos/";
const PAGES = [["landing", BASE], ["demo", BASE + "demo/"], ["check", BASE + "check/"], ["how", BASE + "how-we-test.html"], ["proof", BASE + "proof/"],
  ["r", "https://knos.onrender.com/r/14d68eb782caff05"], ["app", "https://knos.onrender.com/app/"]];
const CATS = ["performance", "accessibility", "best-practices", "seo"];
const out = { commit: SHA, at: new Date().toISOString().replace(/\.\d+Z$/, "Z"), lighthouse: [], axe: [],
  how: "Lighthouse 12 (mobile and desktop presets, simulated throttling) on this build served by the workflow, and on the live app for the result page; axe-core in Chromium, light and dark" };
try {
  const chrome = await launcher.launch({ chromePath: chromium.executablePath(), chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu"] });
  try {
    for (const [page, url] of PAGES) {
      for (const form of ["mobile", "desktop"]) {
        try {
          const r = await lighthouse(url, { port: chrome.port, output: "json", logLevel: "error", onlyCategories: CATS }, form === "desktop" ? desktop : undefined);
          const scores = Object.fromEntries(CATS.map((c) => [c, r.lhr.categories[c]?.score ?? null]));
          out.lighthouse.push({ page, url: url.replace(BASE, "https://drexthealpha.github.io/Knos/"), form, scores });
          console.log(`lighthouse ${page} ${form} ${JSON.stringify(scores)}`);
        } catch (e) {
          out.lighthouse.push({ page, form, error: String(e.message || e).slice(0, 160) });
          console.log(`lighthouse ${page} ${form} failed: ${e.message}`);
        }
      }
    }
  } finally {
    await chrome.kill();
  }
  const browser = await chromium.launch();
  try {
    for (const [page, url] of PAGES) {
      for (const scheme of ["light", "dark"]) {
        const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: scheme });
        const p = await ctx.newPage();
        try {
          await p.goto(url, { waitUntil: "load", timeout: 90000 });
          await p.waitForTimeout(1000);
          await p.addScriptTag({ content: AXE });
          const v = await p.evaluate(async () => (await window.axe.run(document, { resultTypes: ["violations"] })).violations.map((x) => ({ id: x.id, impact: x.impact, nodes: x.nodes.length })));
          out.axe.push({ page, scheme, violations: v.length, ids: v });
          console.log(`axe ${page} ${scheme}: ${v.length} violations ${v.map((x) => x.id).join(", ")}`);
        } catch (e) {
          out.axe.push({ page, scheme, error: String(e.message || e).slice(0, 160) });
        }
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
  }
} finally {
  server.close();
}
mkdirSync(join(SITE, "quality"), { recursive: true });
writeFileSync(join(SITE, "quality", "quality.json"), JSON.stringify(out, null, 1) + "\n");
console.log(`quality.json: ${out.lighthouse.length} Lighthouse runs, ${out.axe.length} axe runs, for ${SHA.slice(0, 7)}`);
