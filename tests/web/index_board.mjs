// The Agent PR Index board (web/index_board.js): node tests/web/index_board.mjs
// First with no browser: the rows, the places, the sample sizes and the "verified" count, from the committed
// docs/agent_weekly.json and from a made-up series that has places (the made-up numbers are in this file only).
// Then, when the `playwright` package and a Chromium are there, in a page that may ask nobody but its own server:
// the week picker redraws the table, nothing is requested from anywhere else, and nothing runs off the side at 320px.
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web"), source = readFileSync(join(web, "index_board.js"), "utf8");
const { renderIndexBoard, indexBoardHtml, boardRows, weeksOf, TOO_FEW } = await import(pathToFileURL(join(web, "index_board.js")).href);
const committed = JSON.parse(readFileSync(join(here, "../../docs/agent_weekly.json"), "utf8"));

let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };

// a series with places: 2026-09-21 has three agents over the bar, 2026-09-28 has none
const rate = (k, n, lo, hi) => ({ k, n, share: n ? k / n : null, ci95: n ? [lo, hi] : null });
const row = (week, rank, sampled, claimed, done, failed_, merged, verified = 0) => ({ week, read: "2026-10-05", full_week: true, rank, sampled, claimed_passing: claimed, ci_finished: done,
  failed_a_check: { ...failed_, test_or_build: 0 }, merged_despite_failed_check: merged, verified });
const made = { name: "Agent PR Index", read: "2026-10-05", latest_week: "2026-09-28", min_claims_to_rank: 30, verified_against: "a list of 1 pull requests paid through Knos under terms with a black-box check",
  agents: {
    "copilot": { weeks: [row("2026-09-21", 2, 90, 60, 56, rate(14, 56, 0.1555, 0.3766), rate(5, 28, 0.079, 0.356)), row("2026-09-28", null, 9, 5, 3, rate(1, 3, 0.0615, 0.7923), rate(1, 3, 0.0615, 0.7923))] },
    "devin": { weeks: [row("2026-09-21", 1, 70, 40, 40, rate(4, 40, 0.0396, 0.2305), rate(0, 20, 0, 0.1611), 1), row("2026-09-28", null, 7, 4, 0, rate(0, 0), null)] },
    "codex<b>": { weeks: [row("2026-09-21", 2, 80, 44, 40, rate(10, 40, 0.1419, 0.4019), null)] },
    "claude-bot": { weeks: [row("2026-09-21", null, 40, 29, 29, rate(0, 29, 0, 0.1168), rate(0, 20, 0, 0.1611))] },
  } };

ok("the weeks are listed newest first", JSON.stringify(weeksOf(made)) === JSON.stringify(["2026-09-28", "2026-09-21"]), weeksOf(made));
ok("placed agents come first by place, the rest keep the file's order", boardRows(made, "2026-09-21").map((r) => r.agent).join() === "devin,copilot,codex<b>,claude-bot", boardRows(made, "2026-09-21").map((r) => r.agent));
const old = indexBoardHtml(made, "2026-09-21"), latest = indexBoardHtml(made);
ok("it is named and dated", old.includes("Agent PR Index, week of 2026-09-21") && latest.includes("Agent PR Index, week of 2026-09-28"));
ok("29 claims with no failure is too few to rank and has no place", /too few to rank<\/span><\/td><th scope="row">claude-bot/.test(old) && (old.match(/class="ib-place"/g) || []).length === 3);
ok("the newest week has no placed agent at all", !latest.includes('class="ib-place"') && latest.split(TOO_FEW).length - 1 >= 2);
ok("every share shows its count and its total", ["14 of 56", "4 of 40", "10 of 40", "0 of 29", "5 of 28", "0 of 20"].every((t) => old.includes(t)));
ok("the columns of sample sizes are there for every agent", (old.match(/class="ib-n"/g) || []).length === 4 * 3 && ["<td class=\"ib-n\">90</td>", "<td class=\"ib-n\">60</td>", "<td class=\"ib-n\">56</td>"].every((t) => old.includes(t)));
ok("an interval is drawn from its low end, as wide as it is, with the share marked", old.includes('style="left:15.6%;width:22.1%"') && old.includes('class="ib-point" style="left:25.0%"') && old.includes("15.6% to 37.7%"));
ok("the bar says in words what it draws", old.includes('aria-label="14 of 56 with finished CI failed a check: 25.0%, 95% interval 15.6% to 37.7%"'));
ok("a share that was not read says so, and 0 of 0 is not drawn as 0%", old.includes('<span class="ib-none">not read</span>') && latest.includes("0 of 0") && !latest.includes("NaN"));
ok("verified counts only what Knos paid on a black-box check", old.includes("<strong>1 verified</strong>") && old.includes("Verified: 1 this week.") && (old.match(/data-verified="0"/g) || []).length === 3);
ok("an agent's name is text, never markup", old.includes("codex&lt;b&gt;") && !old.includes("codex<b>"));
ok("an agent with no row for the week says so", latest.includes("no row for this week in the file"));
ok("it says what a place is not", old.includes("not proof that the claim was false") && old.includes("not a ranking of the agents"));

// the committed file: the sample of 2026-10-01, with the weeks a later capped scan read in place of the sample's. A place
// is drawn for each agent the file ranks and for no other, nothing is verified, and it says why.
const real = indexBoardHtml(committed);
const newest = Object.values(committed.agents).map((a) => a.weeks.find((w) => w.week === committed.latest_week)).filter(Boolean);
ok("the committed file draws its newest week", real.includes(`Agent PR Index, week of ${committed.latest_week}`) && weeksOf(committed)[0] === committed.latest_week);
ok("in the committed file a place is drawn for each ranked agent and for no other",
   real.split('class="ib-place"').length - 1 === newest.filter((w) => w.rank != null).length && real.split(`>${TOO_FEW}<`).length - 1 === newest.filter((w) => w.rank == null).length);
ok("in the committed sample verified is 0 and the page says what it would take", real.includes("Verified: 0 this week.") && real.includes("no list of Knos payments was joined") && real.includes("--paid") && !real.includes(" verified</strong>"));
ok("it says the sample is capped and where a hit's date was not kept", (newest.every((w) => w.full_week) || real.includes("a capped sample cut by week")) && (newest.every((w) => w.sampled != null) || real.includes("not kept")));
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
