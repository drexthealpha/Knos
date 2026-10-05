// The Agent PR Index board (web/index_board.js): node tests/web/index_board.mjs
// First with no browser: the headline rate, the places, the sample sizes, the `capped` mark and the 12-word budget, from the committed
// docs/agent_weekly.json and from a made-up series that has places (the made-up numbers are in this file only).
// Then, when the `playwright` package and a Chromium are there, in a page that may ask nobody but its own server:
// the week picker redraws the table, nothing is requested from anywhere else, and nothing runs off the side at 320px.
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web"), source = readFileSync(join(web, "index_board.js"), "utf8");
const { renderIndexBoard, indexBoardHtml, boardRows, weeksOf, sampleOf, TOO_FEW, NO_RATE } = await import(pathToFileURL(join(web, "index_board.js")).href);
const committed = JSON.parse(readFileSync(join(here, "../../docs/agent_weekly.json"), "utf8"));

let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };

// a series with places: 2026-09-21 has three agents over the bar, 2026-09-28 has none
const rate = (k, n, lo, hi) => ({ k, n, share: n ? k / n : null, ci95: n ? [lo, hi] : null });
const strata = (drawn, planned, reported) => Object.fromEntries(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => [d, { reported: reported == null ? null : reported + i, planned, drawn: Math.min(planned, drawn), claimed: 0, checks_read: 0 }]));
const row = (week, rank, sampled, claimed, head, failed_, merged, capped = false, verified = 0) => ({ week, read: "2026-10-05", full_week: false, design: "stratified-seeded-v1", capped,
  strata: strata(capped ? 20 : 30, 30, 1000), rank, ranked_by: "verified_acceptance_rate", sampled, claimed_passing: claimed, ci_finished: failed_.n, verified_acceptance_rate: head,
  failed_a_check: { ...failed_, test_or_build: 0 }, merged_despite_failed_check: merged, verified });
const made = { name: "Agent PR Index", read: "2026-10-05", latest_week: "2026-09-28", min_claims_to_rank: 30, verified_against: "a list of 1 pull requests paid through Knos under terms with a black-box check",
  agents: {
    "copilot": { weeks: [row("2026-09-21", 2, 90, 60, rate(42, 60, 0.5748, 0.8009), rate(14, 56, 0.1555, 0.3766), rate(5, 28, 0.079, 0.356)), row("2026-09-28", null, 9, 5, rate(2, 5, 0.1176, 0.7693), rate(1, 3, 0.0615, 0.7923), rate(1, 3, 0.0615, 0.7923), true)] },
    "devin": { weeks: [row("2026-09-21", 1, 70, 40, rate(36, 40, 0.7695, 0.9604), rate(4, 40, 0.0396, 0.2305), rate(0, 20, 0, 0.1611), false, 1), row("2026-09-28", null, 7, 4, rate(0, 0), rate(0, 0), null, true)] },
    "codex<b>": { weeks: [row("2026-09-21", 2, 80, 44, rate(28, 40, 0.5456, 0.8193), rate(10, 40, 0.1419, 0.4019), null, true)] },
    "claude-bot": { weeks: [row("2026-09-21", null, 40, 29, rate(29, 29, 0.8832, 1), rate(0, 29, 0, 0.1168), rate(0, 20, 0, 0.1611))] },
    // a row from before the rate was recorded: it keeps the place it was published with (by another count), and is not placed here
    "old-row": { weeks: [{ week: "2026-09-21", read: "2026-10-01", full_week: false, design: "newest-first-capped-v0", capped: true, strata: null, rank: 1, ranked_by: "failed_a_check", sampled: 140, claimed_passing: 120, ci_finished: 109,
      verified_acceptance_rate: null, failed_a_check: { ...rate(70, 109, 0.5488, 0.7259), test_or_build: 5 }, merged_despite_failed_check: rate(2, 37, 0.015, 0.177), verified: 0 }] },
  } };

ok("the weeks are listed newest first", JSON.stringify(weeksOf(made)) === JSON.stringify(["2026-09-28", "2026-09-21"]), weeksOf(made));
ok("placed agents come first by place, the rest keep the file's order", boardRows(made, "2026-09-21").map((r) => r.agent).join() === "devin,copilot,codex<b>,claude-bot,old-row", boardRows(made, "2026-09-21").map((r) => r.agent));
const old = indexBoardHtml(made, "2026-09-21"), latest = indexBoardHtml(made);
const tr = (html, agent) => html.split("<tr").find((t) => t.includes(`data-agent="${agent}"`)) || "";
ok("it is named and dated", old.includes("Agent PR Index, week of 2026-09-21") && latest.includes("Agent PR Index, week of 2026-09-28"));
ok("the headline of a row is its verified acceptance rate: the share, the count over its total, the interval", tr(old, "copilot").includes('<td class="ib-head"><span class="ib-share k-num">70.0%</span> <span class="ib-count k-num">42 of 60</span>') && tr(old, "copilot").includes("57.5% to 80.1%")
  && old.indexOf("Verified acceptance rate</th>") < old.indexOf("Sampled</th>") && old.indexOf("Verified acceptance rate</th>") < old.indexOf("Failed a check anyway</th>"));
ok("its interval is drawn from its low end, as wide as it is, with the share marked", tr(old, "copilot").includes('style="left:57.5%;width:22.6%"') && tr(old, "copilot").includes('class="ib-point" style="left:70.0%"'));
ok("the bar says in words what it draws", old.includes('aria-label="42 of 60 claims with checks read passed every check: 70.0%, 95% interval 57.5% to 80.1%"'));
ok("29 claims that all passed is too few to rank and has no place", tr(old, "claude-bot").includes(`>${TOO_FEW}</span>`) && tr(old, "claude-bot").includes('data-placed="false"') && !tr(old, "claude-bot").includes("ib-place") && (old.match(/class="ib-place/g) || []).length === 3);
ok("a row whose rate the file does not hold is not placed by another count", tr(old, "old-row").includes(`>${NO_RATE}</span>`) && tr(old, "old-row").includes('<td class="ib-head"><span class="ib-none">not recorded</span>') && !tr(old, "old-row").includes("ib-place"));
ok("the newest week has no placed agent at all", !latest.includes('class="ib-place') && latest.split(TOO_FEW).length - 1 >= 2);
ok("every share shows its count and its total", ["42 of 60", "36 of 40", "14 of 56", "4 of 40", "10 of 40", "0 of 29", "5 of 28", "0 of 20"].every((t) => old.includes(t)));
ok("the sample sizes are there for every agent", (old.match(/class="ib-n k-num"/g) || []).length === 5 * 2 && ['<td class="ib-n k-num">90</td>', '<td class="ib-n k-num">60</td>'].every((t) => old.includes(t)));
ok("every row says whether its sample was capped, and how much of the plan was drawn", (old.match(/class="ib-sample"/g) || []).length === 5 && tr(old, "copilot").includes('data-capped="false">not capped<') && tr(old, "copilot").includes("drew 210 of 210") && tr(old, "copilot").includes("7,021 reported")
  && tr(old, "codex&lt;b&gt;").includes('data-capped="true">capped<') && tr(old, "codex&lt;b&gt;").includes("drew 140 of 210") && tr(old, "old-row").includes('data-capped="true">capped<') && tr(old, "old-row").includes("newest-first-capped-v0"));
ok("the week says it too, above the table, and a week with one capped row is capped", old.split("<table")[0].includes('data-capped="true">capped<') && latest.split("<table")[0].includes('data-capped="true">capped<') && old.includes('id="ib-design">stratified-seeded-v1, newest-first-capped-v0<'));
const bare = JSON.parse(JSON.stringify(made)); for (const a of Object.values(bare.agents)) for (const w of a.weeks) { delete w.capped; delete w.strata; delete w.design; }
ok("a file that does not say is never shown as not capped", !indexBoardHtml(bare, "2026-09-21").includes("not capped") && indexBoardHtml(bare, "2026-09-21").includes("design not recorded") && sampleOf({}).capped === true && sampleOf({ capped: false }).capped === false);
ok("a share that was not read says so, and 0 of 0 is not drawn as 0%", old.includes('<span class="ib-none">not read</span>') && latest.includes("0 of 0") && !latest.includes("NaN"));
ok("verified counts only what Knos paid on a black-box check", old.includes("Verified: 1 this week.") && latest.includes("Verified: 0 this week."));
ok("an agent's name is text, never markup", old.includes("codex&lt;b&gt;") && !old.includes("codex<b>"));
ok("an agent with no row for the week says so", latest.includes("no row this week"));
ok("it says what a place is not", old.includes("Treat a failed check as a record, not proof."));
ok("the table sits in the site's table that scrolls inside itself", old.includes('<div class="k-table ib-wrap table-wrap"><table id="ib-table"'));
// the word budget: every statement on the board is 12 words at most
const statements = [...old.matchAll(/<(?:li|p)[^>]*id="ib-(?:rate|bar|rank|not|verified)"[^>]*>(.*?)<\/(?:li|p)>/gs)].flatMap((m) => m[1].replace(/<[^>]+>/g, "").split(/(?<=\.)\s+/)).map((t) => t.trim()).filter(Boolean);
ok("every statement keeps to 12 words", statements.length === 6 && statements.every((t) => t.split(/\s+/).length <= 12), statements);
const heads = [...old.matchAll(/<th scope="col">(.*?)<\/th>/g)].map((m) => m[1]);
ok("and so does every column head", heads.length === 8 && heads.every((t) => t.split(/\s+/).length <= 12), heads);

// the committed file: the sample of 2026-10-01, with the weeks a later capped scan read in place of the sample's. A place
// is drawn for each agent the file ranks by the headline and for no other, every row carries its mark, and nothing is verified.
const real = indexBoardHtml(committed);
const newest = Object.values(committed.agents).map((a) => a.weeks.find((w) => w.week === committed.latest_week)).filter(Boolean);
const ranked = (w) => w.rank != null && w.verified_acceptance_rate != null && w.ranked_by === "verified_acceptance_rate";
ok("the committed file draws its newest week", real.includes(`Agent PR Index, week of ${committed.latest_week}`) && weeksOf(committed)[0] === committed.latest_week);
ok("in the committed file a place is drawn for each agent ranked by the headline and for no other",
   real.split('class="ib-place').length - 1 === newest.filter(ranked).length && real.split(`>${TOO_FEW}<`).length - 1 === newest.filter((w) => !ranked(w) && w.verified_acceptance_rate != null).length
   && real.split(`>${NO_RATE}<`).length - 1 === newest.filter((w) => w.verified_acceptance_rate == null).length);
ok("in the committed sample verified is 0", real.includes("Verified: 0 this week."));
ok("every row of the committed file says whether it is capped, and none is called complete without the file saying so", real.split('class="ib-capped"').length - 1 === newest.length + 1
   && newest.every((w) => typeof w.capped === "boolean" && typeof w.design === "string") && (newest.some((w) => w.capped) === real.split("<table")[0].includes('data-capped="true"')));
ok("it says where a hit's date was not kept", newest.every((w) => w.sampled != null) || real.includes("not kept"));
ok("every week of the committed file draws", weeksOf(committed).every((w) => { const h = indexBoardHtml(committed, w); return h.includes(`week of ${w}`) && !h.includes("NaN") && !h.includes("undefined"); }));
const five = Object.keys(committed.agents);
ok("every agent of the file has a row", five.every((a) => real.includes(`<th scope="row">${a}</th>`)), five);

// nothing from anywhere else: no address, no fetch, no import in the module
ok("the module names no address and asks for nothing", !/https?:|fetch\(|XMLHttpRequest|import\s*\(|^import /m.test(source) && !/https?:\/\/|src=|url\(/.test(old));
const fake = { innerHTML: "" };
ok("it draws into an element that cannot be searched (no browser) without failing", renderIndexBoard(fake, made).innerHTML === latest);

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
    <script type="module">import { renderIndexBoard } from "./index_board.js"; renderIndexBoard(document.getElementById("board"), await (await fetch("./weekly.json")).json()); document.body.dataset.ready = "1";</script>`;
  const files = { "/": ["text/html", page0], "/index_board.js": ["text/javascript", source], "/weekly.json": ["application/json", JSON.stringify(made)] };
  const server = createServer((req, res) => { const f = files[new URL(req.url, "http://x").pathname]; if (!f) { res.writeHead(404); return res.end(); } res.writeHead(200, { "content-type": f[0] }); res.end(f[1]); });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`, asked = [];
  const ctx = await browser.newContext({ viewport: { width: 320, height: 700 } });
  await ctx.route("**/*", (route) => { asked.push(route.request().url()); return route.request().url().startsWith(base) ? route.continue() : route.abort(); });
  const page = await ctx.newPage();
  await page.goto(base, { waitUntil: "load" });
  await page.waitForSelector("body[data-ready]");
  ok("browser: the newest week is drawn first", (await page.textContent("#ib-title")) === "Agent PR Index, week of 2026-09-28");
  await page.selectOption("#ib-week", "2026-09-21");
  ok("browser: picking a week redraws the table for it", (await page.textContent("#ib-title")) === "Agent PR Index, week of 2026-09-21" && (await page.locator(".ib-place").count()) === 3 && (await page.inputValue("#ib-week")) === "2026-09-21");
  ok("browser: the first row is place 1", (await page.locator("#ib-table tbody tr").first().getAttribute("data-agent")) === "devin");
  await page.selectOption("#ib-week", "2026-09-28");
  ok("browser: and back again", (await page.locator(".ib-place").count()) === 0 && (await page.textContent("#ib-verified")).includes("Verified: 0 this week."));
  ok("browser: the capped mark and the sample sizes can be seen, in every row and above the table", (await page.locator("#ib-table tbody .ib-capped").count()) === 2 && (await page.locator(".ib-capped:visible").count()) === 3
    && (await page.locator("#ib-read .ib-capped").isVisible()) && (await page.locator("#ib-table tbody tr[data-agent=copilot] .ib-sample").textContent()).includes("drew 140 of 210"));
  const boxed = await page.evaluate(() => { const w = document.querySelector(".k-table"); return [w.scrollWidth > w.clientWidth, getComputedStyle(w).overflowX]; });
  ok("browser: at 320px the table scrolls inside its own box", boxed[0] === true && boxed[1] === "auto", boxed);
  ok("browser: the picker has a label and the table a name", (await page.getByLabel("Week of", { exact: true }).count()) === 1 && (await page.getByRole("table", { name: "Agent PR Index, week of 2026-09-28" }).count()) === 1);
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  ok("browser: at 320px the page does not scroll sideways (the table scrolls in its own box)", over <= 1, over);
  const bar = await page.evaluate(() => { const b = document.querySelector(".ib-bar"), r = b.querySelector(".ib-range"); return [b.getBoundingClientRect().width, r.getBoundingClientRect().width]; });
  ok("browser: an interval bar has a width", bar[0] >= 90 && bar[1] > 0, bar);
  ok("browser: nothing was asked of anyone but the page's own server", asked.length === 3 && asked.every((u) => u.startsWith(base)), asked);
  await browser.close(); server.close();
}
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
