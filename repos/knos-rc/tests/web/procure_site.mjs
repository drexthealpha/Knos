// node tests/web/procure_site.mjs <site dir> [screenshot dir]
// The console's procurement screens (web/buyer.js renderProcurement, web/console.js section 8, web/procure.js) in
// headless Chromium on a build of the site (scripts/build_site.sh). An offer is created from the rate card in three
// fields: the envelope shows before and after as the fields are typed, the file to commit opens as a new-file page
// on the forge already filled in, the comment that funds it is the one `/knos offer` reads, and the Budgets bar and
// the Approvals list change. An offer over the limit is refused with the amount it is over by. The Invoice screen
// answers the seven questions for one deliverable. A repository's own files are read through a mocked forge API.
// No statement is longer than twelve words, nothing says wallet, hash or token account, nothing scrolls sideways at
// 320 px, and the page asks nobody but this site (and the forge, once a repository is named).
// No `playwright` package or no browser: says so and exits 0 (a skip).
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { readFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname } from "node:path";
import { pathToFileURL } from "node:url";

const [root, shots] = process.argv.slice(2);
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/procure_site.mjs <site dir> [screenshot dir]"); process.exit(2); }
const skip = (why) => { console.log(`SKIP ${why}`); process.exit(0); };
const check = (name, cond, detail) => { if (!cond) { console.error("FAIL", name, detail === undefined ? "" : detail); process.exitCode = 1; } else console.log("ok  ", name); };
let pw;
try { pw = await import("playwright"); } catch {
  const paths = (process.env.NODE_PATH || "").split(":").filter(Boolean);
  try { const req = createRequire(import.meta.url); pw = req(req.resolve("playwright", { paths })); } catch { skip("the playwright package is not installed"); }
}
const { chromium } = pw.default || pw;
let browser;
try { browser = await chromium.launch(); } catch (e) { skip(`no Chromium to start: ${String(e.message).split("\n")[0]}`); }

const p = await import(pathToFileURL(join(root, "procure.js")));
const book = JSON.parse(readFileSync(join(root, "buyer_templates.json"), "utf8")), sample = book.procurement.sample, DIR = book.procurement.directory;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://localhost:${server.address().port}/`, U = 1_000_000;

// a second organisation's files, as the forge's API would hand them over: the sample's, with another envelope limit
const theirs = { [`${DIR}/rate-cards/${sample.rate_card.name}.yaml`]: p.dumpYaml(sample.rate_card), [`${DIR}/envelopes/ops.yaml`]: p.dumpYaml({ ...sample.envelope, name: "ops", limit: 900, committed: 0, spent: 100, held: 0 }),
  [`${DIR}/envelopes/broken.yaml`]: "name: {x}\n", [`${DIR}/policy.yaml`]: p.dumpYaml(sample.policy), [`${DIR}/approvals.jsonl`]: `${JSON.stringify(sample.approvals[0])}\n` };
const forge = (url) => {
  const path = decodeURIComponent(new URL(url).pathname);
  if (path === "/repos/octo/app") return { default_branch: "trunk", id: 1 };
  const inside = path.replace("/repos/octo/app/contents/", "");
  if (theirs[inside] !== undefined) return { content: Buffer.from(theirs[inside]).toString("base64"), encoding: "base64" };
  const listed = Object.keys(theirs).filter((f) => f.startsWith(`${inside}/`)).map((f) => ({ name: f.split("/").pop(), path: f }));
  return listed.length ? listed : null;
};

const asked = [], strangers = [];
async function open(width) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  await ctx.addInitScript((ms) => { Date.now = () => ms; }, Date.UTC(2026, 9, 6, 12) );
  await ctx.route("**/*", (route) => {
    const url = route.request().url();
    asked.push(url);
    if (url.startsWith(base)) return route.continue();
    if (url.startsWith("https://api.github.com/repos/octo/app")) { const got = forge(url); return route.fulfill(got ? { status: 200, contentType: "application/json", body: JSON.stringify(got) } : { status: 404, contentType: "application/json", body: "{}" }); }
    if (!url.startsWith("https://api.devnet.solana.com") && !url.startsWith("https://api.github.com")) strangers.push(url);
    return route.abort();
  });
  const page = await ctx.newPage(), errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}#buy`, { waitUntil: "load" });
  await page.waitForSelector("#proc-outcome option", { state: "attached" });
  return { ctx, page, errors };
}
const { page, errors } = await open(1280);
const text = (sel) => page.locator(sel).first().innerText();
const attr = (sel, name) => page.locator(sel).first().getAttribute(name);

// ---- the sample, before anything is typed ----------------------------------------------------------------------------------------------
check("the page says whose files it shows", (await attr("#proc-source [data-source]", "data-source")) === "sample");
check("three fields are asked for, and the button waits", (await page.locator("#proc-offer-form > .row select, #proc-offer-form > .row input, #proc-offer-form > input").count()) === 3 && await page.locator("#proc-create").isDisabled());
check("the rate card's outcomes are the choices", (await page.locator("#proc-outcome option").allInnerTexts()).join("|") === "bug-fix: 50.00 per accepted pull request|feature: 80.00 per accepted pull request");
await page.click("#proc-tab-budgets");
check("Budgets: the envelope as the file has it", Number(await attr("#proc-budgets .k-env", "data-left")) === 2800 * U && (await text("#proc-budgets [data-fact=left]")) === "2,800.00");
const widths = () => page.locator("#proc-budgets .k-bar span").evaluateAll((els) => els.map((s) => Math.round(s.getBoundingClientRect().width)));
const before = await widths();
check("the bar is filled in proportion: spent, held, committed, nothing drafted", before[0] > before[1] && before[2] > before[0] && before[3] === 0, before);

// ---- an offer in three fields: the envelope before and after, then the file and the comment -------------------------------------------------
await page.click("#proc-tab-offers");
await page.selectOption("#proc-outcome", "maintenance-2026q4/feature");
await page.fill("#proc-supplier", "hubot");
const t0 = Date.now();
await page.fill("#proc-cap", "400");
await page.waitForSelector("#proc-fit [data-fit='1']");
check("the envelope answers within 300 ms of the last field", Date.now() - t0 < 300, Date.now() - t0);
// the fee is the live build's (web/fee_live.js): devnet is not asked here, and the site's upgrades.json says proposal 8 executed,
// so knos_pay 2.2: 0.30%, at least 0.05. Three months of 400.00 are 1,200.00 and 3.60 of fees.
check("before: 2,800.00 left; after: 1,596.40 left", (await page.locator("#proc-fit [data-fact=left]").allInnerTexts()).join("|") === "2,800.00|1,596.40");
check("it says so in one sentence", (await text("#proc-fit [data-fit-said]")) === "Fits: 1,203.60 is committed, and 1,596.40 stays in envelope eng-2026q4.");
check("periods, suppliers and fees are named", (await text("#proc-fit [data-offer-sum]")) === "3 months, 1 supplier; fees 3.60 on top.", await text("#proc-fit [data-offer-sum]"));
await page.click("#proc-create");
await page.waitForSelector("#proc-file");
const file = await text("#proc-file"), made = p.readYaml(file);
check("the file is a sound standing offer", p.offerProblems(made, sample.rate_card).length === 0 && made.name === "feature-hubot" && made.cap === 400 && made.suppliers.join() === "hubot" && made.envelope === "eng-2026q4" && made.starts === "2026-10-06", file);
const link = new URL(await attr("#proc-file-open", "href"));
check("it opens as a new file on the forge, already filled in", link.origin + link.pathname === "https://github.com/drexthealpha/knos-playground/new/main" && link.searchParams.get("filename") === `${DIR}/offers/feature-hubot.yaml` && link.searchParams.get("value") === `${file}\n`.replace(/\n+$/, "\n"),
  link.href);
check("the comment that funds it on devnet", (await text("[data-offer-comment]")) === "/knos offer @hubot rate 80 budget 400 checks: unit days 30", await text("[data-offer-comment]"));
check("the approval it needs is said", (await text("[data-offer-need]")) === "Waits for 2 approvers: 1,200.00 needs 2 approvers.");
check("the offer is listed", (await page.locator("#proc-offer-list tr[data-offer]").count()) === 2 && /Waits for 2 approvers/.test(await text("#proc-offer-list tr[data-offer=feature-hubot]")));
await page.click("#proc-tab-budgets");
check("Budgets: the envelope changed", Number(await attr("#proc-budgets .k-env", "data-left")) === 1_596_400_000 && Number(await attr("#proc-budgets .k-env", "data-committed")) === 2_403_600_000 && (await text("#proc-budgets [data-fact=left]")) === "1,596.40"
  && (await text("#proc-budgets [data-fact=committed]")) === "2,403.60");
await page.waitForFunction(() => document.querySelector("#proc-budgets .k-bar [data-part=draft]").getBoundingClientRect().width > 0);
const after = await widths();
check("the bar grew by what was drafted, and the rest stayed", after[3] > 0 && after[0] === before[0] && after[2] === before[2], after);
if (shots) { mkdirSync(shots, { recursive: true }); await page.locator("#buy-part-budgets").screenshot({ path: join(shots, "procure-budgets.png") }); }

// ---- over the limit: refused, with the amount it is over by --------------------------------------------------------------------------------
await page.click("#proc-tab-offers");
await page.fill("#proc-supplier", "octocat");
await page.selectOption("#proc-outcome", "maintenance-2026q4/feature");
await page.fill("#proc-cap", "1000");
await page.waitForSelector("#proc-fit [data-fit='0']");
check("an offer over the limit is refused with the amount over", (await text("#proc-fit [data-fit-said]")) === "Refused: this is 1,412.60 over envelope eng-2026q4. 1,596.40 of 5,000.00 is left." && await page.locator("#proc-create").isDisabled(), await text("#proc-fit [data-fit-said]"));
check("a refusal leaves the after-view as it was", (await page.locator("#proc-fit [data-fact=left]").allInnerTexts()).join("|") === "1,596.40|1,596.40");
await page.fill("#proc-cap", "40");
check("a cap under one outcome's price is said plainly", (await text("#proc-fit [data-offer-bad]")) === "The cap of 40.00 is less than one feature at 80.00.");
await page.fill("#proc-cap", "");

// ---- approvals: what waits for whom, and who approved with which authority ----------------------------------------------------------------
await page.click("#proc-tab-approvals");
const first = "#proc-approvals [data-request='offer:bug-fix-octocat']";
check("Approvals: the open offer waits for one more approver, named", (await text(`${first} [data-request-said]`)) === "Waits for 1 approver: 1,200.00 needs 2 approvers." && /Waits for 1 of approver: @sam-acme\./.test(await text(`${first} [data-waiting]`)));
check("who approved, with the authority shown", /@mei-acme approved on 2026-10-02\./.test(await text(`${first} [data-approved]`)) && (await text(`${first} [data-authority]`)) === "Authority: approver from 2026-01-01 to 2026-12-31, up to 25,000.00.");
check("the drafted offer waits for two", /@mei-acme or @sam-acme/.test(await text("#proc-approvals [data-request='offer:feature-hubot'] [data-waiting]")));
check("the line an approver posts", (await page.locator(`${first} [data-approve-line]`).textContent()) === "/knos approve offer:bug-fix-octocat");

// ---- the invoice approver's screen: seven questions, one deliverable ----------------------------------------------------------------------
await page.click("#proc-tab-invoice");
const qs = await page.locator("#proc-invoice dt[data-q]").allInnerTexts(), as = await page.locator("#proc-invoice dd[data-a] > strong").allInnerTexts();
check("the seven questions, in order", qs.join("|") === "What did we authorize?|What did the supplier deliver?|Which requirements passed?|Has this deliverable already been billed?|Who approved it, and did they have authority?|What is disputed, credited, or still owed?|Can I explain this decision next quarter?", qs);
check("each is answered for the one deliverable", as.join("|") === ["One bug-fix at 50.00, up to 400.00 a month.", "@octocat delivered pull request #31. Verdict: accepted.", "3 of 3 passed.", "No. One invoice line names it.",
  "Waits for 1 approver: 1,200.00 needs 2 approvers.", "Nothing is disputed. 0.00 credited, 0.00 owed.", "Yes. Five files in your repository rebuild it."].join("|"), as);
check("the exception is counted first", (await text("#proc-invoice [data-seven-open]")) === "1 of 7 answers needs a person." && (await attr("#proc-invoice dd[data-a='5']", "data-ok")) === "0");
if (shots) await page.locator("#buy-part-invoice").screenshot({ path: join(shots, "procure-invoice.png") });

// ---- funding one task shows the envelope too (the task is funded under Offers) --------------------------------------------------------------
await page.click("#proc-tab-offers");
await page.fill("#buy-amount", "50");
// the verdict is one line in the step; the envelope before and after is behind the fold "Budget, envelope, earlier bills"
await page.waitForSelector("#buy-fit [data-fit='1']");
check("the step says in one line whether the order fits its envelope", (await text("#buy-fit")) === (await page.locator("#buy-envelope [data-fit-said]").textContent()) && /^Fits: /.test(await text("#buy-fit")), await text("#buy-fit"));
await page.click("#buy-controls > summary");
await page.waitForSelector("#buy-envelope [data-fit='1']");
check("funding a task shows the envelope before and after, fee included", (await page.locator("#buy-envelope [data-fact=left]").allInnerTexts()).join("|") === "1,596.40|1,546.25", await page.locator("#buy-envelope [data-fact=left]").allInnerTexts());
await page.fill("#buy-amount", "2000");
await page.waitForSelector("#buy-envelope [data-fit='0']");
check("and refuses over the limit with the amount over", (await text("#buy-envelope [data-fit-said]")) === "Refused: this is 409.60 over envelope eng-2026q4. 1,596.40 of 5,000.00 is left.", await text("#buy-envelope [data-fit-said]"));

// ---- words: twelve at most a statement; no key, address or digest ----------------------------------------------------------------------------
const said = await page.evaluate(() => {
  const out = [];
  // the four screens: the offers in #proc, the envelopes, the approvals and the deliverable each in its part of the console
  for (const panel of document.querySelectorAll("#proc, #proc-budgets, #proc-approvals, #proc-invoice, #buy-envelope")) for (const el of panel.querySelectorAll("p, li, dd, dt, summary, th, label, h3, h4, option, button")) {
    if (el.closest("pre") || el.querySelector("p, li, dd, dt, pre, table, details")) continue;
    out.push(el.textContent.replace(/\s+/g, " ").trim());
  }
  return out.concat([...document.querySelectorAll("#proc-invoice dd[data-a] > strong")].map((el) => el.textContent.trim()));
});
const sentences = said.flatMap((s) => s.split(/(?<=[.?!])\s+(?=[A-Z@])/)).filter(Boolean), long = sentences.filter((s) => s.split(/\s+/).length > 12);
check(`no statement is longer than twelve words (${sentences.length} read)`, sentences.length > 40 && long.length === 0, long);
const whole = await page.evaluate(() => [...document.querySelectorAll("#proc, #proc-budgets, #proc-approvals, #proc-invoice, #buy-envelope")].map((el) => el.textContent).join(" "));
check("the four screens are the console's four parts: the offers under Offers, the envelopes under Budgets, the approvals under Approvals, the deliverable under Invoice",
  await page.evaluate(() => [["buy-part-offers", "proc"], ["buy-part-budgets", "proc-budgets"], ["buy-part-approvals", "proc-approvals"], ["buy-part-invoice", "proc-invoice"]].every(([part, id]) => document.getElementById(part).contains(document.getElementById(id)))));
check("nothing says wallet, hash or token account", !/wallet|hash|token account|pubkey|sha256/i.test(whole), (whole.match(/.{30}(wallet|hash|token account|pubkey|sha256).{30}/i) || [])[0]);
check("the screens asked the forge for nothing", !asked.some((u) => u.includes("/contents/")) && strangers.length === 0, strangers);
check("no script error", errors.length === 0, errors);

// ---- a repository's own files, through the forge ---------------------------------------------------------------------------------------------
await page.fill("#proc-repo", "octo/app");
await page.click("#proc-repo-form button");
await page.waitForSelector("#proc-source [data-source='octo/app']");
check("the files are read from the named repository", (await text("#proc-source [data-source]")) === "Read from octo/app, branch trunk.");
check("a file that is not sound is named with its line", (await page.locator("#proc-source .status.bad").allInnerTexts()).some((s) => s.startsWith(`${DIR}/envelopes/broken.yaml: Line 1:`)), await page.locator("#proc-source .status.bad").allInnerTexts());
await page.click("#proc-tab-budgets");
check("their envelope, not the sample's", (await attr("#proc-budgets .k-env", "data-envelope")) === "ops" && (await text("#proc-budgets [data-fact=left]")) === "800.00");
await page.click("#proc-tab-offers");
await page.fill("#proc-supplier", "hubot"); await page.fill("#proc-cap", "200");
await page.waitForSelector("#proc-fit [data-fit='1']");
await page.click("#proc-create");
check("the new file opens in their repository, on its own branch", (await attr("#proc-file-open", "href")).startsWith("https://github.com/octo/app/new/trunk?filename="));

// ---- a phone ---------------------------------------------------------------------------------------------------------------------------
for (const width of [320, 390]) {
  const small = await open(width);
  await small.page.fill("#proc-supplier", "hubot"); await small.page.fill("#proc-cap", "400");
  await small.page.waitForSelector("#proc-fit [data-fit='1']");
  await small.page.click("#proc-create");
  for (const tab of ["offers", "budgets", "approvals", "invoice"]) {
    await small.page.click(`#proc-tab-${tab}`);
    const wide = await small.page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check(`${width} px, ${tab}: nothing scrolls sideways`, wide <= 0, wide);
  }
  if (shots && width === 390) await small.page.locator("#buy-part-invoice").screenshot({ path: join(shots, "procure-phone.png") });
  await small.ctx.close();
}
await browser.close(); server.close();
console.log(process.exitCode ? "FAILED" : "all passed");
