// The Agent PR Index leaderboard (web/index_board.js): node tests/web/index_board.mjs
// First with no browser: the rows are the ones scripts/agent_pr_board.py wrote into docs/index.json, for every week;
// places, sample sizes, intervals, the dispute link, the disputed mark, the badge and the 12-word budget, from the
// committed docs/agent_weekly.json and from a made-up series (the made-up numbers are in this file only).
// Then, when the `playwright` package and a Chromium are there, in a page that may ask nobody but its own server:
// the week picker redraws the table, the bars grow in (and stand still under reduced motion), nothing is requested
// from anywhere else, and nothing runs off the side from 320 to 1280 px.
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web"), source = readFileSync(join(web, "index_board.js"), "utf8");
const { renderIndexBoard, indexBoardHtml, boardOf, weeksOf, wilson, disputeUrl, agentBadgeSvg, badgeMessage, TOO_FEW, FEED_SCHEMA } = await import(pathToFileURL(join(web, "index_board.js")).href);
const committed = JSON.parse(readFileSync(join(here, "../../docs/agent_weekly.json"), "utf8"));
const feed = JSON.parse(readFileSync(join(here, "../../docs/index.json"), "utf8"));

let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };

// ---- the committed file: the page counts what the script counted ---------------------------------------------------------
const KEYS = ["agent", "weeks", "claimed_passing", "merged", "failed_at_merge", "share", "ci95", "rank", "status", "overlaps_above", "dispute"];
const slim = (rows) => rows.map((r) => Object.fromEntries(KEYS.map((k) => [k, r[k]])));
ok("the feed is the versioned one and lists every week of the series, newest first", feed.schema === FEED_SCHEMA && JSON.stringify(feed.weeks.map((w) => w.week)) === JSON.stringify(weeksOf(committed)) && weeksOf(committed)[0] === committed.latest_week);
const differs = feed.weeks.filter((w) => JSON.stringify(slim(boardOf(committed, w.week).rows)) !== JSON.stringify(slim(w.rows)) || boardOf(committed, w.week).read !== w.read).map((w) => w.week);
ok("for every week the page works out the rows docs/index.json holds: counts, shares, intervals, places, dispute links", differs.length === 0, differs);
const top = feed.weeks[0], real = indexBoardHtml(committed, undefined, feed);
ok("the committed file draws its newest week, one row an agent", real.includes(`Agent PR Index, week of ${committed.latest_week}`) && real.split("<tr data-agent=").length - 1 === Object.keys(committed.agents).length);
ok("a place is drawn for each agent the feed places and for no other", real.split('class="ib-place').length - 1 === top.rows.filter((r) => r.rank != null).length && real.split(`>${TOO_FEW}<`).length - 1 === top.rows.filter((r) => r.status === TOO_FEW).length);
ok("every rate of the committed file has its sample size beside it", top.rows.filter((r) => r.merged).every((r) => real.includes(`${r.failed_at_merge} of ${r.merged} merged`)) && top.rows.every((r) => r.merged == null || r.merged >= (r.rank != null ? feed.min_claims_to_rank : 0)));
ok("an agent too few to rank is still shown with its counts", top.rows.filter((r) => r.status === TOO_FEW).every((r) => (real.split("<tr").find((t) => t.includes(`data-agent="${r.agent}"`)) || "").includes(`${r.failed_at_merge} of ${r.merged} merged`)));
ok("in the committed sample verified is 0, and no row is disputed", real.includes("Verified: 0 this week.") && !real.includes("ib-disputed\"") && feed.disputes.length === 0);
ok("every week of the committed file draws", weeksOf(committed).every((w) => { const h = indexBoardHtml(committed, w, feed); return h.includes(`week of ${w}`) && !h.includes("NaN") && !h.includes("undefined"); }));
ok("the interval is Wilson's", JSON.stringify(wilson(18, 65)) === JSON.stringify([0.1829, 0.3958]) && wilson(0, 0) === null && JSON.stringify(wilson(0, 20)) === JSON.stringify([0, 0.1611]));

// ---- a made-up series: two weeks, a tie, an agent too few to rank, one whose merge state was not read, one disputed -----------
const rate = (k, n) => ({ k, n, share: n ? k / n : null, ci95: wilson(k, n) });
const row = (week, claimed, k, n, verified = 0) => ({ week, read: "2026-10-05", claimed_passing: claimed, ci_finished: n, merged_despite_failed_check: n == null ? null : rate(k, n), verified });
const made = { name: "Agent PR Index", read: "2026-10-05", latest_week: "2026-09-28", min_claims_to_rank: 30,
  agents: {
    "alpha": { weeks: [row("2026-09-21", 50, 9, 30), row("2026-09-28", 40, 9, 30, 1)] },          // 18 of 60: 30.0%
    "beta": { weeks: [row("2026-09-21", 70, 2, 40), row("2026-09-28", 10, 0, 5)] },               // 2 of 45: 4.4%
    "gamma<b>": { weeks: [row("2026-09-21", 44, 12, 40)] },                                        // 12 of 40: 30.0%, the same share as alpha
    "delta": { weeks: [row("2026-09-21", 29, 0, 29)] },                                            // one short of the bar
    "epsilon": { weeks: [{ ...row("2026-09-28", 12, null, null), ci_finished: 9 }] },              // merge state not read
  } };
const madeFeed = { schema: FEED_SCHEMA, weeks: [{ week: "2026-09-28", rows: [{ agent: "alpha", disputed: [{ issue: "https://github.com/drexthealpha/Knos/issues/7", opened: "2026-10-06" }] }, { agent: "beta", disputed: [{ issue: "javascript:alert(1)" }] }] }] };
const latest = indexBoardHtml(made, undefined, madeFeed), old = indexBoardHtml(made, "2026-09-21", madeFeed);
const tr = (html, agent) => html.split("<tr").find((t) => t.includes(`data-agent="${agent}"`)) || "";
const b = boardOf(made, "2026-09-28");
ok("the weeks are listed newest first", JSON.stringify(weeksOf(made)) === JSON.stringify(["2026-09-28", "2026-09-21"]));
ok("a board adds up every week through the one shown", tr(latest, "alpha").includes("18 of 60 merged") && tr(old, "alpha").includes("9 of 30 merged") && tr(latest, "beta").includes("2 of 45 merged"));
ok("placed agents come first, the smallest share first; equal shares share a place", b.rows.map((r) => `${r.agent}:${r.rank}`).join() === "beta:1,alpha:2,gamma<b>:2,delta:null,epsilon:null", b.rows.map((r) => `${r.agent}:${r.rank}`));
ok("29 merged claims is too few to rank, has no place and keeps its counts", tr(latest, "delta").includes(`>${TOO_FEW}</span>`) && tr(latest, "delta").includes('data-placed="false"') && tr(latest, "delta").includes("0 of 29 merged") && !tr(latest, "delta").includes("ib-place"));
ok("a merge state that was not read is not drawn as a rate", tr(latest, "epsilon").includes(">not read</span>") && !tr(latest, "epsilon").includes('class="ib-bar"') && !latest.includes("NaN"));
ok("the share, the count over its total and the interval stand together", tr(latest, "alpha").includes('<span class="ib-share k-num">30.0%</span> <span class="ib-count k-num">18 of 60 merged</span>') && tr(latest, "alpha").includes("19.9% to 42.5%"));
ok("the bar runs from 0 to the share and the whisker spans the interval", tr(latest, "alpha").includes('class="ib-fill" style="width:30.0%"') && tr(latest, "alpha").includes('class="ib-whisker" style="left:19.9%;width:22.6%"'));
ok("the bar says in words what it draws", latest.includes('aria-label="18 of 60 merged had a failed check: 30.0%, 95% interval 19.9% to 42.5%"'));
ok("a place whose interval reaches into the one above says so", b.rows[2].overlaps_above === true && tr(latest, "gamma&lt;b&gt;").includes(">overlaps<") && b.rows[0].overlaps_above === false && !tr(latest, "beta").includes(">overlaps<"));
ok("every row has a link that opens a filled-in dispute", (latest.match(/class="ib-dispute"/g) || []).length === 5 && disputeUrl("alpha", "2026-09-28") === "https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+alpha%2C+week+of+2026-09-28&agent=alpha&week=2026-09-28"
  && tr(latest, "alpha").includes(`href="${disputeUrl("alpha", "2026-09-28").replace(/&/g, "&amp;")}"`));
ok("a disputed row carries its mark and the issue's link; a link that is not https is not drawn", tr(latest, "alpha").includes('data-disputed="true"') && tr(latest, "alpha").includes('<a class="ib-disputed" href="https://github.com/drexthealpha/Knos/issues/7"') && latest.includes("Marks 1 disputed row with †.")
  && tr(latest, "beta").includes('data-disputed="false"') && !latest.includes("javascript:") && !old.includes("ib-disputed\""));
ok("verified counts only what Knos paid on a black-box check that week", latest.includes("Verified: 1 this week.") && old.includes("Verified: 0 this week."));
ok("an agent's name is text, never markup", latest.includes("gamma&lt;b&gt;") && !latest.includes("gamma<b>"));
ok("an agent with no week yet is shown with nothing counted", tr(old, "epsilon").includes("0 of 0 merged"));
const svg = agentBadgeSvg(b.rows[1], "2026-09-28");
ok("each row has a badge: an SVG with the count, its total and the week, grey for every agent", (latest.match(/<details class="k-more ib-badge">/g) || []).length === 5 && svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"') && svg.includes("alpha: 18 of 60 merged had a failed check, week of 2026-09-28")
  && svg.includes('fill="#57606a"') && !/#1a7f37|green|red/.test(svg) && svg.includes("not always a failed test or a false claim") && !/href|<image|<script|url\(/.test(svg) && badgeMessage(b.rows[3], "2026-09-28").includes("0 of 29"));
ok("it says what a place is not, and that no vendor pays", latest.includes("Treat a failed check as a record, not proof.") && latest.includes("Dispute any row; no vendor pays to change one."));
ok("the table sits in the site's table that scrolls inside itself", latest.includes('<div class="k-table ib-wrap table-wrap"><table id="ib-table"'));
const one = { ...made, agents: { alpha: { weeks: [made.agents.alpha.weeks[1]] } } };
ok("a week picker is there only when there is more than one week", latest.includes('id="ib-week"') && !indexBoardHtml(one).includes('id="ib-week"') && indexBoardHtml({ agents: {} }).includes("Holds no week yet."));
// the word budget: every statement on the board is 12 words at most
const statements = [...latest.matchAll(/<(?:li|p|span)[^>]*id="ib-(?:rate|bar|rank|not|pay|verified|sum|open)"[^>]*>(.*?)<\/(?:li|p|span)>/gs)].flatMap((m) => m[1].replace(/<[^>]+>/g, "").split(/(?<=\.)\s+/)).map((t) => t.trim()).filter(Boolean);
ok("every statement keeps to 12 words", statements.length === 9 && statements.every((t) => t.split(/\s+/).length <= 12), statements);
const heads = [...latest.matchAll(/<th scope="col">(.*?)<\/th>/g)].map((m) => m[1]);
ok("and so does every column head", heads.length === 5 && heads.every((t) => t.split(/\s+/).length <= 12), heads);
ok("the board names no company as best in words", !/\b(best|worst|winner|leads|beats)\b/i.test(latest.replace(/<style>.*?<\/style>/s, "")));

// nothing from anywhere else: no fetch, no import; the only addresses are links a reader may follow
ok("the module asks for nothing", !/fetch\(|XMLHttpRequest|import\s*\(|^import /m.test(source) && !/src=|url\(|<link|<script/.test(latest));
ok("every address on the board is a dispute link or an issue", [...latest.matchAll(/https?:\/\/[^"<\s]+/g)].map((m) => m[0]).every((u) => u.startsWith("https://github.com/drexthealpha/Knos/issues") || u === "http://www.w3.org/2000/svg"));
const fake = { innerHTML: "" };
ok("it draws into an element that cannot be searched (no browser) without failing, and still takes a week as its third argument", renderIndexBoard(fake, made).innerHTML === indexBoardHtml(made) && renderIndexBoard(fake, made, "2026-09-21").innerHTML === indexBoardHtml(made, "2026-09-21"));

// ---- in a browser, when there is one --------------------------------------------------------------------------------------
async function chromium() {
  let pw;
  try { pw = await import("playwright"); } catch {
    const paths = (process.env.NODE_PATH || "").split(/[:;]/).filter(Boolean);
    try { pw = createRequire(import.meta.url)(createRequire(import.meta.url).resolve("playwright", { paths })); } catch { return console.log("SKIP the browser part: the playwright package is not installed"); }
  }
  try { return await (pw.default || pw).chromium.launch(); } catch (e) { return console.log(`SKIP the browser part: no Chromium to start: ${String(e.message).split("\n")[0]}`); }
}
const browser = await chromium();
if (browser) {
  const page0 = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><body style="margin:16px"><div id="board"></div>
    <script type="module">import { renderIndexBoard } from "./index_board.js"; const get = async (u) => (await fetch(u)).json();
      renderIndexBoard(document.getElementById("board"), await get("./weekly.json"), { feed: await get("./feed.json") }); document.body.dataset.ready = "1";</script>`;
  const files = { "/": ["text/html", page0], "/index_board.js": ["text/javascript", source], "/weekly.json": ["application/json", JSON.stringify(made)], "/feed.json": ["application/json", JSON.stringify(madeFeed)] };
  const server = createServer((req, res) => { const f = files[new URL(req.url, "http://x").pathname]; if (!f) { res.writeHead(404); return res.end(); } res.writeHead(200, { "content-type": f[0] }); res.end(f[1]); });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`, asked = [];
  const open = async (opts) => {
    const ctx = await browser.newContext({ viewport: { width: 320, height: 700 }, ...opts });
    await ctx.route("**/*", (route) => { asked.push(route.request().url()); return route.request().url().startsWith(base) ? route.continue() : route.abort(); });
    const page = await ctx.newPage();
    await page.goto(base, { waitUntil: "load" });
    await page.waitForSelector("body[data-ready]");
    return page;
  };
  const scale = (page) => page.evaluate(() => new DOMMatrixReadOnly(getComputedStyle(document.querySelector(".ib-fill")).transform).a);
  const page = await open({ reducedMotion: "no-preference" });
  ok("browser: the newest week is drawn first", (await page.textContent("#ib-title")) === "Agent PR Index, week of 2026-09-28");
  ok("browser: the board is set to grow in, and its bars reach their full length", (await page.locator(".index-board.ib-anim").count()) === 1 && await page.waitForFunction(() => document.querySelector(".index-board.in") && new DOMMatrixReadOnly(getComputedStyle(document.querySelector(".ib-fill")).transform).a === 1, null, { timeout: 5000 }).then(() => true, () => false));
  const t0 = Date.now();
  await page.selectOption("#ib-week", "2026-09-21");
  await page.waitForFunction(() => document.querySelector("#ib-title").textContent.endsWith("2026-09-21"));
  const took = Date.now() - t0;
  ok("browser: picking a week redraws the table for it, within 300 ms", (await page.locator(".ib-place").count()) === 3 && (await page.inputValue("#ib-week")) === "2026-09-21" && took < 300, took);
  ok("browser: the first row is place 1", (await page.locator("#ib-table tbody tr").first().getAttribute("data-agent")) === "beta");
  await page.selectOption("#ib-week", "2026-09-28");
  ok("browser: and back again, with the disputed mark and the verified count", (await page.locator(".ib-disputed:visible").count()) === 1 && (await page.textContent("#ib-verified")).includes("Verified: 1 this week."));
  ok("browser: every row shows a dispute link and a sample size", (await page.locator("a.ib-dispute:visible").count()) === 5 && (await page.locator("#ib-table tbody tr[data-agent=alpha] .ib-count").textContent()) === "18 of 60 merged");
  await page.locator("tr[data-agent=alpha] details.ib-badge summary").click();
  const badge = await page.evaluate(() => { const s = document.querySelector("tr[data-agent=alpha] .ib-svg svg"); return [s.getBoundingClientRect().height, s.querySelector("title").textContent.length > 20]; });
  ok("browser: a row's badge opens and is drawn", badge[0] === 20 && badge[1], badge);
  await page.locator("tr[data-agent=alpha] .ib-copy").click();
  ok("browser: copying the badge answers at once", await page.waitForFunction(() => document.querySelector("tr[data-agent=alpha] .ib-copy, tr[data-agent=alpha] textarea") && !/^Copy SVG$/.test((document.querySelector("tr[data-agent=alpha] .ib-copy") || {}).textContent || ""), null, { timeout: 300 }).then(() => true, () => false));
  const boxed = await page.evaluate(() => { const w = document.querySelector(".k-table"); return [w.scrollWidth > w.clientWidth, getComputedStyle(w).overflowX]; });
  ok("browser: at 320px the table scrolls inside its own box", boxed[0] === true && boxed[1] === "auto", boxed);
  ok("browser: the picker has a label and the table a name", (await page.getByLabel("Week of", { exact: true }).count()) === 1 && (await page.getByRole("table", { name: "Agent PR Index, week of 2026-09-28" }).count()) === 1);
  const over = [];
  for (const w of [320, 480, 768, 1024, 1280]) { await page.setViewportSize({ width: w, height: 700 }); over.push(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)); }
  ok("browser: from 320 to 1280 px the page does not scroll sideways", over.every((x) => x <= 1), over);
  await page.waitForFunction(() => [...document.querySelectorAll(".ib-fill, .ib-whisker")].every((e) => new DOMMatrixReadOnly(getComputedStyle(e).transform).a === 1), null, { timeout: 5000 });   // the week was just picked: let the bars finish growing
  const bar = await page.evaluate(() => { const b = document.querySelector("tr[data-agent=alpha] .ib-bar"), f = b.querySelector(".ib-fill"), w = b.querySelector(".ib-whisker"); const B = b.getBoundingClientRect(), F = f.getBoundingClientRect(), W = w.getBoundingClientRect(); return [B.width, F.width / B.width, (W.left - B.left) / B.width, W.width / B.width]; });
  ok("browser: the bar is as long as the share and the whisker spans the interval", bar[0] >= 100 && Math.abs(bar[1] - 0.30) < 0.02 && Math.abs(bar[2] - 0.199) < 0.02 && Math.abs(bar[3] - 0.226) < 0.02, bar);
  const still = await open({ reducedMotion: "reduce" });
  ok("browser: with reduced motion the bars are simply there", (await still.locator(".index-board.ib-anim").count()) === 0 && (await scale(still)) === 1 && (await still.evaluate(() => getComputedStyle(document.querySelector(".ib-fill")).transitionDuration)) === "0s");
  ok("browser: nothing was asked of anyone but the page's own server", asked.length === 8 && asked.every((u) => u.startsWith(base)), asked);
  await browser.close(); server.close();
}
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
