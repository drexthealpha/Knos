// The playground (web/playground.js): node tests/web/playground.mjs
// First with no browser: the two links, the rows and their states, the three outside counts, the word budget, from
// made-up data that is in this file only. Then, when the `playwright` package and a Chromium are there, in a page
// whose GitHub is mocked: the list is drawn and read again, nothing is asked of anyone but the page's own server and
// api.github.com (which the site already reads), and nothing runs off the side from 320 to 1280 px.
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), root = join(here, "../.."), web = join(root, "web"), source = readFileSync(join(web, "playground.js"), "utf8");
const lib = await import(pathToFileURL(join(web, "playground.js")).href);
const { renderPlayground, playgroundHtml, tasksOf, fundUrl, takeUrl, editUrl, REPO, TEMPLATE, TASK_FILE, FUND_LABEL, TAKE_LABEL, LABEL_KNOS_FAUCET } = lib;

let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const read = (rel) => readFileSync(join(root, rel), "utf8");

// ---- made-up data ----------------------------------------------------------------------------------------------------------
const issue = (number, title, login, extra = {}) => ({ number, title, state: "open", user: { login }, ...extra });
const issues = [issue(14, "Playground: reverse the words of a line", "stranger-a"), issue(12, "Playground: <img src=x onerror=alert(1)>", "stranger-b"),
  issue(13, "Reverse the words", "solver", { pull_request: {} }), issue(9, "Playground: reverse the words of a line", "stranger-c")];
const bounty = (repository, n, amount = 5_000_000) => ({ repository, issue: n, amount, decimals: 6, currency: "test USDC", mint_kind: "test" });
const bounties = { count: 3, bounties: [bounty(REPO, 12), bounty(REPO, 9), bounty("octo/widgets", 14)] };
const definitions = { funders: "accounts that are not Knos's and funded a job", repositories: "repositories that are not Knos's", payees: "accounts that are not Knos's and were paid",
  funders_in_knos_repositories_faucet: `${LABEL_KNOS_FAUCET}: an outside account's comment` };
const zeros = { measured: true, funders: 0, funders_in_outside_repositories: 0, funders_in_knos_repositories_faucet: 0, repositories: 0, payees: 0, summed: false, definitions };
const some = { ...zeros, funders: 3, funders_in_outside_repositories: 1, funders_in_knos_repositories_faucet: 2, repositories: 1, payees: 2 };

// ---- the two buttons -------------------------------------------------------------------------------------------------------
const rules = read("src/knos/playground.py"), small = read("scripts/small_repos.py");
ok("the playground is the repository the rules name", rules.includes(`REPO = "${REPO}"`) && small.includes(`"knos-playground": (`));
ok("Fund opens a new issue from the template the repository holds: one click, then Submit", fundUrl() === `https://github.com/${REPO}/issues/new?template=${TEMPLATE}` && small.includes(`".github/ISSUE_TEMPLATE/${TEMPLATE}": ISSUE_TEMPLATE`));
ok("the file a solver edits is the one the rules and the checks name", rules.includes(`TASK = "${TASK_FILE}"`) && editUrl() === `https://github.com/${REPO}/edit/main/${TASK_FILE}`);
ok("the two buttons say what the brief says", FUND_LABEL === "Fund a test task (one click, then Submit)" && TAKE_LABEL === "Take one");

// ---- the rows --------------------------------------------------------------------------------------------------------------
const tasks = tasksOf(issues, bounties);
ok("open issues are tasks, newest first; a pull request is not one", tasks.map((t) => t.number).join() === "14,12,9", tasks.map((t) => t.number));
ok("a task is funded only when devnet's list has it for THIS repository", tasks.map((t) => t.state).join() === "opened,funded,funded" && tasks[1].amount === "5" && tasks[1].currency === "test USDC", tasks);
ok("with no list from devnet nothing is called funded or unfunded", tasksOf(issues, null).every((t) => t.state === "unread"));
ok("Take one goes to the funded task that has waited longest, or to GitHub's list", takeUrl(tasks) === `https://github.com/${REPO}/issues/9` && takeUrl(tasksOf(issues, null)) === `https://github.com/${REPO}/issues` && takeUrl(null) === `https://github.com/${REPO}/issues`);
ok("what GitHub sends that is no list makes no row", tasksOf({ message: "rate limit" }, bounties).length === 0 && tasksOf([null, { number: "7" }, issue(3, "x", "y", { state: "closed" })], bounties).length === 0);

// ---- the page as a string --------------------------------------------------------------------------------------------------
const html = playgroundHtml({ tasks, outsiders: zeros });
ok("two buttons with their links", html.includes(`id="pg-fund" href="${fundUrl()}"`) && html.includes(`>${FUND_LABEL}</a>`) && html.includes(`id="pg-take" href="https://github.com/${REPO}/issues/9"`) && html.includes(`>${TAKE_LABEL}</a>`));
ok("each row has its state, and only a funded one offers the edit", (html.match(/data-state="funded"/g) || []).length === 2 && (html.match(new RegExp(`Edit ${TASK_FILE.replace(".", "\\.")}`, "g")) || []).length === 2 && html.includes("Funded: 5 test USDC") && html.includes("Waiting for devnet"));
ok("a title is text, never markup", html.includes("&lt;img src=x onerror=alert(1)&gt;") && !html.includes("<img"));
ok("zeros that were counted are shown as zeros", /id="pg-funders"[^>]*><strong class="k-num">0<\/strong> outside funders/.test(html) && /id="pg-repos"[^>]*><strong class="k-num">0<\/strong> outside repositories/.test(html) && /id="pg-payees"[^>]*><strong class="k-num">0<\/strong> outside payees/.test(html) && html.includes('data-measured="true"'));
const counted = playgroundHtml({ tasks, outsiders: some });
ok("the three are three numbers, each with its definition, and are told apart from the faucet's funders", />3<\/strong> outside funders/.test(counted) && />1<\/strong> outside repositories/.test(counted) && />2<\/strong> outside payees/.test(counted)
  && counted.includes(`title="${definitions.funders.replace(/'/g, "&#x27;")}"`) && new RegExp(`id="pg-faucet"[^>]*><strong class="k-num">2</strong> of those funders: ${LABEL_KNOS_FAUCET}\\.`).test(counted));
ok("no sum of the three is written anywhere", !/>6<|>5<\/strong>|total/i.test(counted.replace(/<style>[\s\S]*?<\/style>/, "")) && counted.includes("Add none of them together."));
ok("the label is the counting script's own", read("scripts/outsiders.py").includes(`LABEL_KNOS_FAUCET = "${LABEL_KNOS_FAUCET}"`));
for (const [name, o] of [["a build that read nothing", { ...zeros, measured: false }], ["a file that was not read", null], ["a file with no numbers", { measured: true }]]) {
  const h = playgroundHtml({ tasks, outsiders: o });
  ok(`${name} says the counts were not read, and shows no zero`, h.includes('data-measured="false"') && h.includes("Outside counts: not read in this build.") && !h.includes("pg-funders"));
}
ok("before GitHub answers it says it is reading; when GitHub does not, it says so and links the list", playgroundHtml({}).includes("Reading GitHub…") && playgroundHtml({ tasks: null }).includes("GitHub did not answer.") && playgroundHtml({ tasks: [] }).includes("No open task now."));

// ---- the word budget: every statement is 12 words or fewer, and none claims a user ----------------------------------------------
const statements = (h) => h.replace(/<style>[\s\S]*?<\/style>/g, "").replace(/<(th|td|a|button|p|span)[^>]*>/g, "\n").replace(/<[^>]+>/g, " ").replace(/&[a-z#0-9]+;/g, "x").split(/\n|(?<=[.…!?])\s+(?=[A-Z])/).map((s) => s.trim()).filter(Boolean);
const long = [playgroundHtml({ tasks: tasksOf([issues[0], issues[3]], bounties), outsiders: some }), playgroundHtml({}), playgroundHtml({ tasks: null }), playgroundHtml({ tasks: [], outsiders: null })]
  .flatMap(statements).filter((s) => s.split(/\s+/).length > 12);
ok("no statement on it is longer than 12 words", long.length === 0, long);
// the first screen's 40 words (tests/web/words.mjs, which counts no figure, table, button or control) hold with every
// count read, as the Pages build writes them: the staging build of 7 Oct said 41 there
const prose = (h) => h.replace(/<style>[\s\S]*?<\/style>/g, "").replace(/<(table|button|strong)[\s\S]*?<\/\1>/g, " ").replace(/<a class="k-btn[\s\S]*?<\/a>/g, " ").replace(/<[^>]+>/g, " ")
  .split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
const firstScreen = prose(playgroundHtml({ tasks, outsiders: some }));
ok("the first screen says 40 words at most with every count read", firstScreen <= 40, firstScreen);
ok("it claims nobody has used it", !/\b(users?|customers?|people have|already funded|join)\b/i.test(html.replace(/<style>[\s\S]*?<\/style>/, "")));
ok("the module asks only GitHub's API and its own site", [...source.matchAll(/https?:\/\/[a-z0-9.-]+/gi)].map((m) => m[0]).every((u) => ["https://github.com", "https://api.github.com"].includes(u)) && !/XMLHttpRequest|import\s*\(|^import /m.test(source));

// ---- drawn with no browser: the reads, a failure of each, and a slow read that a newer one overtakes ---------------------------
{
  const el = { innerHTML: "" }, asked = [];
  const view = renderPlayground(el, { gh: (p) => { asked.push(p); return Promise.resolve(issues); }, file: (p) => { asked.push(p); return p === "bounties.json" ? Promise.resolve(bounties) : Promise.resolve(zeros); }, every: 0 });
  ok("it says it is reading at once", el.innerHTML.includes("Reading GitHub…"));
  await view.first;
  ok("then it has read one list from GitHub and two files of the site", asked.join() === `repos/${REPO}/issues?state=open&per_page=50,bounties.json,outsiders.json` && el.innerHTML === playgroundHtml({ tasks, outsiders: zeros }), asked);
  const down = { innerHTML: "" };
  await renderPlayground(down, { gh: () => Promise.reject(new Error("403")), file: () => { throw new Error("404"); }, every: 0 }).first;
  ok("GitHub down and no files: it says so, with both buttons still there", down.innerHTML.includes("GitHub did not answer.") && down.innerHTML.includes(`href="${fundUrl()}"`) && down.innerHTML.includes("Outside counts: not read in this build."));
  const part = { innerHTML: "" };
  await renderPlayground(part, { gh: () => Promise.resolve(issues), file: (p) => (p === "bounties.json" ? Promise.reject(new Error("404")) : Promise.resolve(zeros)), every: 0 }).first;
  ok("without devnet's list every task says devnet was not read", (part.innerHTML.match(/Devnet not read/g) || []).length === 3 && !part.innerHTML.includes("Funded:"));
  const race = { innerHTML: "" }, gates = [];
  const slow = renderPlayground(race, { gh: () => new Promise((r) => gates.push(r)), file: () => Promise.resolve(zeros), every: 0 });
  const second = slow.refresh();
  for (let i = 0; i < 5 && gates.length < 2; i++) await Promise.resolve();      // both reads have asked
  gates[1]([issues[0]]); await second;
  gates[0](issues); await slow.first;
  ok("an older read that answers late does not replace a newer one", (race.innerHTML.match(/data-issue=/g) || []).length === 1);
  slow.stop();
}

// ---- in a browser, when there is one -------------------------------------------------------------------------------------------
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
  const page0 = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="./app.css"><body style="margin:16px"><div id="playground"></div>
    <script type="module">import { renderPlayground } from "./playground.js"; window.view = renderPlayground(document.getElementById("playground"), { every: 0 }); await window.view.first; document.body.dataset.ready = "1";</script>`;
  const files = { "/": ["text/html", page0], "/playground.js": ["text/javascript", source], "/app.css": ["text/css", read("web/app.css")],
    "/bounties.json": ["application/json", JSON.stringify(bounties)], "/outsiders.json": ["application/json", JSON.stringify(zeros)] };
  const server = createServer((req, res) => { const f = files[new URL(req.url, "http://x").pathname]; if (!f) { res.writeHead(404); return res.end(); } res.writeHead(200, { "content-type": f[0] }); res.end(f[1]); });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`, asked = [], api = `https://api.github.com/repos/${REPO}/issues?state=open&per_page=50`;
  let listed = issues;
  const ctx = await browser.newContext({ viewport: { width: 320, height: 700 } });
  await ctx.route("**/*", (route) => {
    const url = route.request().url();
    asked.push(url);
    if (url.startsWith(base)) return route.continue();
    if (url === api) return route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(listed) });
    return route.abort();
  });
  const page = await ctx.newPage();
  await page.goto(base, { waitUntil: "load" });
  await page.waitForSelector("body[data-ready]");
  ok("browser: the two buttons are links to GitHub", (await page.getAttribute("#pg-fund", "href")) === fundUrl() && (await page.textContent("#pg-fund")) === FUND_LABEL && (await page.textContent("#pg-take")) === TAKE_LABEL && (await page.getAttribute("#pg-take", "href")) === `https://github.com/${REPO}/issues/9`);
  ok("browser: the open tasks are listed with their state", (await page.locator("#pg-tasks tbody tr").count()) === 3 && (await page.locator('#pg-tasks tr[data-state="funded"]').count()) === 2 && (await page.textContent('#pg-tasks tr[data-issue="14"] .k-step')) === "Waiting for devnet");
  ok("browser: the three outside counts are zeros, shown as zeros", (await page.textContent("#pg-funders")) === "0 outside funders" && (await page.textContent("#pg-repos")) === "0 outside repositories" && (await page.textContent("#pg-payees")) === "0 outside payees");
  ok("browser: a title with markup in it made no element", (await page.locator("#playground img").count()) === 0);
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 700 });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    ok(`browser: at ${width}px the page does not scroll sideways`, over <= 1, over);
  }
  listed = [issue(15, "Playground: reverse the words of a line", "stranger-d"), ...issues];
  files["/bounties.json"][1] = JSON.stringify({ bounties: [...bounties.bounties, bounty(REPO, 15)] });
  files["/outsiders.json"][1] = JSON.stringify(some);
  await page.click("#pg-again");
  await page.waitForSelector('#pg-tasks tr[data-issue="15"]');
  ok("browser: Read again reads again: the new task and the new counts are drawn", (await page.locator("#pg-tasks tbody tr").count()) === 4 && (await page.textContent("#pg-funders")) === "3 outside funders" && (await page.textContent("#pg-faucet")).trim() === `2 of those funders: ${LABEL_KNOS_FAUCET}.`);
  const others = asked.filter((u) => !u.startsWith(base) && u !== api);
  ok("browser: nothing was asked of anyone but the page's own server and GitHub's API", others.length === 0 && asked.filter((u) => u === api).length === 2, others);
  await browser.close(); server.close();
}
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
