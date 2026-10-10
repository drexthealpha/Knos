// Sharing a check (web/share.js), first with no browser, then in headless Chromium on web/ as it stands:
// node tests/web/share.mjs. The link carries the pull request (#check=owner/repo/123) and reads back to it; "Copy the
// result" puts the verdict, the claim, the counts and the link on the clipboard; "Post on X" is a link to X's compose box
// with the words and the link, within 280 characters, and posts nothing; "Download the card" saves a 1200 x 630 PNG;
// the badge is offered only to a repository that merged in the last 30 days, and its file is checkedBadgeSvg's bytes.
// Pressed by keyboard, each control keeps the focus, the clipboard refused too.
// Every statement is 12 words or fewer; nothing runs off the side at 320, 360 and 1280 px; nobody is asked but the
// page's own server and GitHub's API (mocked here). No `playwright` or no browser: the browser half is SKIPPED.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web");
const share = await import(pathToFileURL(join(web, "share.js")).href);
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const words = (s) => s.trim().split(/\s+/).filter(Boolean).length;

// ---- no browser -----------------------------------------------------------------------------------------------------------
const NOW = Date.parse("2026-10-09T12:00:00Z");
// what web/check.js readPr answers (the detail of its "knos:check" event)
const V = { ref: { owner: "octo", repo: "widgets", number: 12 }, url: "https://github.com/octo/widgets/pull/12", title: "Parser", sha: "c".repeat(40),
  claim: { phrase: "All tests pass", line: "- [x] All tests pass locally (`npm test`)" }, cls: "failed", failed: ["jest", "eslint", "vercel"],
  split: { test: ["jest", "eslint"], other: ["vercel"] }, line: "Claims tests pass; a test or build check failed.", merged: false };
const PR = V.ref;
ok("the link carries the pull request", share.shareHash(PR) === "#check=octo/widgets/12" && share.shareUrl(PR) === "https://drexthealpha.github.io/Knos/#check=octo/widgets/12");
ok("the link reads back", JSON.stringify(share.readShareHash("#check=octo/widgets/12")) === JSON.stringify(PR)
  && JSON.stringify(share.readShareHash("#check=octo/widgets")) === JSON.stringify({ owner: "octo", repo: "widgets" }));
for (const bad of ["#check=../x/1", "#check=octo/widgets/0", "#check=octo/<b>/1", "#check=octo", "#fund=octo/widgets/1", "#check=%E0%A4%A"]) ok(`refused: ${bad}`, share.readShareHash(bad) === null);
ok("failed checks counted by the index's two classes", JSON.stringify(share.counts(V)) === JSON.stringify({ test: 2, other: 1 }) && JSON.stringify(share.counts({})) === JSON.stringify({ test: 0, other: 0 }));
ok("the counts in one line", share.countsLine(V) === "Failed checks: 2 test, build, lint or type; 1 other." && share.countsLine({ split: { test: [], other: [] } }) === "No check failed.");
ok("the claim quoted, or nothing claimed", share.claimLine(V) === "Claimed: “- [x] All tests pass locally (`npm test`)”" && share.claimLine({ claim: null }) === "Claimed nothing about tests.");
ok("coloured as #check colours it", share.tone(V) === "bad" && share.tone({ ...V, claim: null }) === "ink" && share.tone({ ...V, cls: "passed" }) === "ok");
const TEXT = share.resultText(V);
ok("the copied result", TEXT === "octo/widgets#12: Claims tests pass; a test or build check failed.\nClaimed: “- [x] All tests pass locally (`npm test`)”\nFailed checks: 2 test, build, lint or type; 1 other.\nchecked by Knos: https://drexthealpha.github.io/Knos/#check=octo/widgets/12", TEXT);
for (const v of [V, { ...V, line: "w".repeat(400) + " long", ref: { owner: "o".repeat(39), repo: "r".repeat(100), number: 123456789 } }]) {
  const u = new URL(share.postUrl(v)), text = u.searchParams.get("text");
  ok(`X's compose box, filled, within 280 (${text.length} + link)`, u.origin + u.pathname === "https://x.com/intent/tweet" && u.searchParams.get("url") === share.shareUrl(v.ref)
    && [...text].length + 1 + share.LINK_LENGTH <= 280 && text.includes(`${v.ref.owner}/${v.ref.repo}#${v.ref.number}`));
}
ok("brand/checked.svg is checkedBadgeSvg's bytes", readFileSync(join(web, "brand/checked.svg"), "utf8") === share.checkedBadgeSvg());
ok("the badge links to the repository's check", share.badgeSnippet(PR) === "[![agent PR claims checked by Knos](https://drexthealpha.github.io/Knos/brand/checked.svg)](https://drexthealpha.github.io/Knos/#check=octo/widgets)");
const fake = (status, body, remaining = "59") => async () => ({ status, ok: status === 200, headers: { get: (h) => (h === "x-ratelimit-remaining" ? remaining : null) }, json: async () => body });
ok("active: this pull request merged 3 days ago", (await share.repoActive({ ...V, merged_at: "2026-10-06T00:00:00Z" }, NOW, () => { throw new Error("no read"); })) === "yes");
ok("active: another merged 29 days ago", (await share.repoActive(V, NOW, fake(200, [{ merged_at: null }, { merged_at: "2026-09-10T13:00:00Z" }]))) === "yes");
ok("not active: the last merge 31 days ago", (await share.repoActive(V, NOW, fake(200, [{ merged_at: "2026-09-08T00:00:00Z" }]))) === "no");
ok("GitHub's limit is said as such", (await share.repoActive(V, NOW, fake(403, {}, "0"))) === "limit");

// ---- in a browser ---------------------------------------------------------------------------------------------------------
let chromium;
try { ({ chromium } = (await import("playwright")).default); } catch (e) { console.log(`SKIP the playwright package is not installed (${e.code || e.message})`); process.exit(failed ? 1 : 0); }
const TYPES = { ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".html": "text/html", ".woff2": "font/woff2", ".svg": "image/svg+xml" };
const PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Check</title>
<link rel="stylesheet" href="/app.css"></head><body><main id="page"><section id="share"></section></main>
<script type="module">import { renderShare } from "/share.js";
window.show = (verdict) => renderShare(document.getElementById("share"), { verdict, now: ${NOW} });
window.ready = true;</script></body></html>`;
const server = createServer((req, res) => {
  const path = normalize(decodeURIComponent(req.url.split("?")[0])).replace(/^([/\\])+/, "");
  if (!path) { res.writeHead(200, { "content-type": "text/html" }); return res.end(PAGE); }
  const file = join(web, path);
  if (!existsSync(file)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`;
// GitHub, as the badge's one read finds it: widgets merged 9 days ago, old merged last in July, busy is out of reads
const GH = { "octo/widgets": [200, [{ merged_at: "2026-09-30T08:00:00Z" }]], "octo/old": [200, [{ merged_at: "2026-07-01T08:00:00Z" }]], "octo/busy": [403, { message: "API rate limit exceeded" }] };
let browser;
try { browser = await chromium.launch(); } catch (e) { console.log(`SKIP no browser for playwright here (${String(e.message).split("\n")[0]})`); server.close(); process.exit(failed ? 1 : 0); }
try {
  for (const width of [320, 360, 1280]) {
    const context = await browser.newContext({ viewport: { width, height: 800 }, acceptDownloads: true });
    await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin });
    const page = await context.newPage(), asked = [];
    page.on("request", (r) => { if (!r.url().startsWith(origin)) asked.push(new URL(r.url()).host); });
    await page.route("https://api.github.com/**", (route) => {
      const repo = /\/repos\/([^/]+\/[^/]+)\/pulls/.exec(route.request().url())?.[1], [status, body] = GH[repo] || [404, {}];
      route.fulfill({ status, contentType: "application/json", headers: { "x-ratelimit-remaining": status === 403 ? "0" : "58", "access-control-allow-origin": "*", "access-control-expose-headers": "x-ratelimit-remaining" }, body: JSON.stringify(body) });
    });
    await page.goto(origin);
    await page.waitForFunction(() => window.ready === true);
    await page.evaluate((v) => window.show(v), V);
    ok(`${width}px: the address carries the pull request`, (await page.evaluate(() => location.hash)) === "#check=octo/widgets/12");
    const post = await page.$('[data-act="post"]');
    ok(`${width}px: Post on X opens X's box in a new tab; nothing is posted`, (await post.getAttribute("href")) === share.postUrl(V) && (await post.getAttribute("target")) === "_blank");
    // copy: the status line paints at once
    const copied = await page.evaluate(async () => { const t = performance.now(); document.querySelector('[data-act="copy"]').click();
      while (!document.querySelector("[data-share-said]").textContent) await new Promise((r) => requestAnimationFrame(r)); return performance.now() - t; });
    ok(`${width}px: Copy the result says so in ${Math.round(copied)} ms (300 at most)`, copied <= 300, copied);
    ok(`${width}px: the clipboard holds the result and its link`, (await page.evaluate(() => navigator.clipboard.readText())) === TEXT);
    // the card
    const [download] = await Promise.all([page.waitForEvent("download"), page.click('[data-act="card"]')]);
    const png = readFileSync(await download.path());
    ok(`${width}px: the card is a 1200 x 630 PNG named for the pull request`, download.suggestedFilename() === "knos-check-octo-widgets-12.png"
      && png.subarray(1, 4).toString() === "PNG" && png.readUInt32BE(16) === 1200 && png.readUInt32BE(20) === 630, [download.suggestedFilename(), png.length]);
    // BY KEYBOARD the focus stays on the control pressed, so the next Tab goes on from it: with the clipboard refused (the
    // hidden box that copies instead takes the focus to select its text) and on the card (a button disabled while it is
    // drawn drops the focus to <body>; the next Tab was then the page's first link)
    const where = () => page.evaluate(() => document.activeElement?.dataset?.act || document.activeElement?.tagName);
    const refuse = () => page.evaluate(() => { navigator.clipboard.writeText = () => Promise.reject(new DOMException("refused", "NotAllowedError")); document.querySelector("[data-share-said]").textContent = ""; });
    const allow = () => page.evaluate(() => { delete navigator.clipboard.writeText; });
    await refuse();
    await page.focus('[data-act="copy"]');
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.querySelector("[data-share-said]").textContent.length > 0);
    const afterCopy = await where();
    await allow();
    ok(`${width}px: by keyboard, the clipboard refused: the focus stays on Copy the result`, afterCopy === "copy", afterCopy);
    await page.focus('[data-act="card"]');
    const [byKey] = await Promise.all([page.waitForEvent("download"), page.keyboard.press("Enter")]);
    await page.waitForFunction(() => !document.querySelector('[data-act="card"]').hasAttribute("aria-busy"));
    const afterCard = await where();
    ok(`${width}px: by keyboard, the card saved: the focus stays on Download the card`, byKey.suggestedFilename() === "knos-check-octo-widgets-12.png" && afterCard === "card", afterCard);
    const inks = await page.evaluate(async (v) => { const { drawCard } = await import("/share.js"); const c = drawCard(document.createElement("canvas"), v);
      const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data, seen = new Set(); for (let i = 0; i < d.length; i += 4 * 97) seen.add(`${d[i]},${d[i + 1]},${d[i + 2]}`); return seen.size; }, V);
    ok(`${width}px: the card has words on it (${inks} colours)`, inks > 20, inks);
    // the badge, for an active repository, an inactive one, and when GitHub's reads are spent
    for (const [repo, want] of [["widgets", "snippet"], ["old", "Offered only to repositories that merged in the last 30 days."], ["busy", "Wait an hour: GitHub's 60 reads from here are spent."]]) {
      await page.evaluate((v) => window.show(v), { ...V, ref: { ...PR, repo } });
      await page.click('[data-act="badge"] summary');
      await page.waitForFunction(() => { const t = document.querySelector("[data-badge]").textContent; return t && !/Reading/.test(t); });
      const said = (await page.textContent("[data-badge]")).trim();
      if (want === "snippet") {
        ok(`${width}px: the badge for a repository that merged 9 days ago`, said.includes(share.badgeSnippet({ owner: "octo", repo })) && (await page.$('[data-badge] img[src="brand/checked.svg"]')) !== null, said);
        await page.click('[data-act="copy-badge"]');
        ok(`${width}px: Copy the badge`, (await page.evaluate(() => navigator.clipboard.readText())) === share.badgeSnippet({ owner: "octo", repo }));
        await refuse();
        await page.focus('[data-act="copy-badge"]');
        await page.keyboard.press("Enter");
        await page.waitForFunction(() => document.querySelector("[data-share-said]").textContent.length > 0);
        const afterBadge = await where();
        await allow();
        ok(`${width}px: by keyboard, the clipboard refused: the focus stays on Copy the badge`, afterBadge === "copy-badge", afterBadge);
      } else ok(`${width}px: octo/${repo}: ${want}`, said === want, said);
    }
    const lines = await page.evaluate(() => [...document.querySelectorAll("#share button, #share a, #share summary, #share p")].map((e) => e.textContent.trim()).filter((t) => t && !t.startsWith("[!")));
    ok(`${width}px: every statement is 12 words or fewer`, lines.every((t) => words(t) <= 12), lines.filter((t) => words(t) > 12));
    ok(`${width}px: nothing runs off the side`, await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
    ok(`${width}px: nobody is asked but the page's server and GitHub's API`, asked.every((h) => h === "api.github.com"), asked);
    await context.close();
  }
} finally { await browser.close(); server.close(); }
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
