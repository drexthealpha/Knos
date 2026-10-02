// node tests/web/site.mjs <site dir> [screenshot.png]
// The built site (scripts/build_site.sh) in headless Chromium: every view renders, there are no console errors, and
// each flow works against a mocked GitHub API and Solana RPC. Needs the `playwright` package (tests.yml installs it).
import pw from "playwright";
const { chromium } = pw;
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import * as knos from "../../sdk/settle/index.js";

const root = process.argv[2];
const stats = { updated: "2026-10-02 09:00 UTC", funded: 5, refunded: 1, vetoed: 0, recent: [{ repo: 9, issue: 3, author: 555, amount: 4875000, kind: "outside", seconds: 100, tx: "5".repeat(88) }],
  outside: { paid: 2, amount: 24375000, repositories: 2, funders: 2, authors: 2, median_seconds_fund_to_paid: 350 },
  own: { paid: 1 }, self_funded: { paid: 1 }, live: { open: 1, open_amount: 7000000, unclaimed_amount: 4875000 } };
const index = { date: "2026-10-02", n_prs: 5, agents: {}, prs: [
  { agent: "copilot", repo: "octo/widgets", number: 1, sha: "a".repeat(40), class: "passed", failed_checks: [], phrase: "all tests pass" },
  { agent: "copilot", repo: "octo/widgets", number: 2, sha: "b".repeat(40), class: "failed", failed_checks: ["build (3.12)"], phrase: "tests pass" },
  { agent: "devin", repo: "octo/widgets", number: 4, sha: "f".repeat(40), class: "other", failed_checks: [], phrase: "CI is green" },
  { agent: "codex", repo: "octo/widgets", number: 3, sha: "c".repeat(40), class: "failed", failed_checks: ["lint"], phrase: "<img src=x onerror=alert(1)> green" },
  { agent: "devin", repo: "acme/gadgets", number: 9, sha: "d".repeat(40), class: "other", failed_checks: [], phrase: "CI is green" }] };
let githubReads = 0;
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".yml": "text/plain" };
const server = createServer((req, res) => {
  if (req.url === "/stats.json") { res.writeHead(200, { "Content-Type": "application/json" }); return res.end(JSON.stringify(stats)); }
  if (req.url === "/index.json") { res.writeHead(200, { "Content-Type": "application/json" }); return res.end(JSON.stringify(index)); }
  const p = join(root, req.url.split("?")[0] === "/" ? "index.html" : req.url.split("?")[0]);
  if (!existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "Content-Type": types[extname(p)] || "text/plain" }); res.end(readFileSync(p));
}).listen(0);
const base = `http://127.0.0.1:${server.address().port}/`;
const ids = JSON.parse(readFileSync(join(root, "program_ids.json"), "utf8"));
const k = knos.client(ids);

// a job account for repo 5550001 issue 7, and a due account for user 4242
const job = new Uint8Array(256); const dv = new DataView(job.buffer);
job[0] = 1; job[2] = 1; dv.setBigUint64(8, 5550001n, true); dv.setBigUint64(16, 7n, true); dv.setBigUint64(24, 20000000n, true);
dv.setBigInt64(32, BigInt(Math.floor(Date.now() / 1000) + 14 * 86400), true);
job.set(new TextEncoder().encode("c".repeat(40)), 216);
const due = new Uint8Array(48); new DataView(due.buffer).setBigUint64(0, 19500000n, true); new DataView(due.buffer).setBigUint64(8, 4242n, true);
due.set(knos.unb58(await k.faucetMint()), 16);
const rep = new Uint8Array(32); new DataView(rep.buffer).setUint32(0, 3, true); new DataView(rep.buffer).setBigUint64(8, 58500000n, true); new DataView(rep.buffer).setUint32(16, 2, true);
const pdImmutable = new Uint8Array(60); pdImmutable[0] = 3;
const b64 = (u8) => Buffer.from(u8).toString("base64");
const repAddr = await k.rep(4242), pdOidc = await knos.programData(ids.knos_oidc), pdPay = await knos.programData(ids.knos_pay);
const jobAddr = await k.job(5550001, 7);

const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.route("https://api.github.com/**", (route) => {
  githubReads++;
  const u = new URL(route.request().url());
  const json = (o) => route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(o) });
  if (u.pathname === "/repos/octo/widgets") return json({ id: 5550001, default_branch: "main", full_name: "octo/widgets" });
  if (u.pathname === "/users/mona") return json({ id: 4242, login: "mona" });
  if (u.pathname === "/repos/octo/widgets/pulls/12") return json({ number: 12, body: "Fixes #7", html_url: "https://github.com/octo/widgets/pull/12", user: { login: "mona" },
    head: { sha: "e".repeat(40) }, base: { repo: { full_name: "octo/widgets", name: "widgets", owner: { login: "octo" }, default_branch: "main" } } });
  if (u.pathname.endsWith("/check-runs")) return json({ check_runs: [] });
  if (u.pathname.endsWith("/status")) return json({ sha: "e".repeat(40), statuses: [] });
  return route.fulfill({ status: 404, headers: { "access-control-allow-origin": "*" }, body: "{}" });
});
await page.route("https://api.devnet.solana.com/**", async (route) => {
  const { method, params } = JSON.parse(route.request().postData());
  const ok = (result) => route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, result }) });
  if (method === "getSlot") return ok(100);
  if (method === "getBlockTime") return ok(Math.floor(Date.now() / 1000));
  if (method === "getProgramAccounts") {
    const size = params[1].filters[0].dataSize;
    if (size === 256) return ok([{ pubkey: jobAddr, account: { data: [b64(job), "base64"] } }]);
    if (size === 48) return ok([{ pubkey: "11111111111111111111111111111111", account: { data: [b64(due), "base64"] } }]);
    return ok([]);
  }
  if (method === "getAccountInfo") {
    const a = params[0];
    if (a === repAddr) return ok({ value: { data: [b64(rep), "base64"] } });
    if (a === pdOidc || a === pdPay) return ok({ value: { data: [b64(pdImmutable), "base64"] } });
    return ok({ value: null });
  }
  return ok(null);
});

const check = (name, cond) => { if (!cond) { console.error("FAIL", name); process.exitCode = 1; } else console.log("ok  ", name); };
await page.goto(base);
check("front door renders", (await page.textContent("h1")).includes("GitHub's own signature"));
check("only the front view is shown", await page.isHidden("#view-bounty") && await page.isVisible("#view-check"));

// a repository's own record in the Agent PR Index: the same box, no request but index.json
for (const ask of ["octo/widgets", "OCTO/Widgets", "https://github.com/octo/widgets/", "github.com/octo/widgets.git", "https://github.com/octo/widgets/pulls?q=x"]) {
  githubReads = 0;
  await page.fill("#pr-url", ask);
  await page.click("#pr-check");
  await page.waitForSelector("#repo-record");
  const rec = await page.textContent("#repo-record");
  check(`repository record for ${ask}`, rec.includes("4 agent pull requests") && rec.includes("tests pass, 2 had a failing check") && rec.includes("octo/widgets"));
  check(`  ${ask}: no GitHub request, only index.json`, githubReads === 0);
}
await page.fill("#pr-url", "octo/widgets");
await page.click("#pr-check");
await page.waitForSelector("#repo-record");
const rec = await page.textContent("#repo-record");
check("record: per agent", rec.includes("copilot") && rec.includes("1 of 2") && rec.includes("codex") && rec.includes("1 of 1"));
check("record: each pull request links to GitHub", (await page.getAttribute('#repo-record a[href$="/pull/2"]', "href")) === "https://github.com/octo/widgets/pull/2" && rec.includes("build (3.12)"));
check("record: index text is escaped, not run", (await page.$("#repo-record img")) === null && rec.includes("<img src=x"));
await page.fill("#pr-url", "octo/unknown");
await page.click("#pr-check");
await page.waitForSelector("#repo-record");
const none = await page.textContent("#repo-record");
check("record: none says so and offers the single-PR check", none.includes("No agent pull requests") && none.includes("octo/unknown") && none.includes("pull request link"));
githubReads = 0;
await page.fill("#pr-url", "https://github.com/octo/widgets/pull/12");
await page.click("#pr-check");
await page.waitForSelector("#verdict");
check("a pull request link is still the single-PR check", githubReads > 0 && (await page.textContent("#verdict")).includes("No tests-pass claim") && (await page.$("#repo-record")) === null);
await page.fill("#pr-url", "not a thing");
await page.click("#pr-check");
await page.waitForSelector("#pr-result .status.bad");
check("anything else is refused in a sentence", (await page.textContent("#pr-result")).includes("owner/repo"));

index.prs = "not a list";                                           // an index that is not the shape it should be: a sentence, no error
await page.goto(base);
await page.fill("#pr-url", "octo/widgets");
await page.click("#pr-check");
await page.waitForSelector("#repo-record");
check("record: an index without a list of pull requests says none", (await page.textContent("#repo-record")).includes("No agent pull requests"));

// protect
await page.fill("#protect-repo", "octo/widgets");
await page.click("#protect-go");
const href = await page.getAttribute("#protect-open", "href");
check("protect link prefills the workflow at the site's commit", href.startsWith("https://github.com/octo/widgets/new/main?filename=.github/workflows/knos.yml") && decodeURIComponent(href).includes("prove.yml@" + "c".repeat(40)) && decodeURIComponent(href).includes("checks: read"));

const chk = decodeURIComponent(await page.getAttribute("#protect-check", "href"));
check("the check alone, with no money, is one file too", chk.startsWith("https://github.com/octo/widgets/new/main?filename=.github/workflows/knos-check.yml") && chk.includes("check.yml@" + "c".repeat(40)) && !chk.includes("id-token"));

// fund: a new issue
await page.goto(base + "#bounty");
check("bounty view", await page.isVisible("#view-bounty") && await page.isHidden("#view-check"));
await page.fill("#ni-repo", "octo/widgets"); await page.fill("#ni-title", "slugify keeps punctuation"); await page.fill("#ni-amount", "12.5");
await page.click("#ni-go");
const issueUrl = decodeURIComponent(await page.getAttribute("#ni-open", "href"));
check("new issue link carries the command on its last line", issueUrl.startsWith("https://github.com/octo/widgets/issues/new?title=slugify keeps punctuation") && issueUrl.endsWith("/knos bounty 12.5"));

// escrow status
await page.fill("#st-issue", "octo/widgets#7");
await page.click("#st-go");
await page.waitForSelector("#st-result dl");
const st = await page.textContent("#st-result");
check("escrow status read from the chain", st.includes("20.00 USDC") && st.includes("open") && st.includes("merges the pull request") && st.includes(jobAddr) && st.includes("0.50"));

// what is waiting
await page.goto(base + "#claim");
await page.fill("#due-login", "mona");
await page.click("#due-go");
await page.waitForSelector("#due-result .verdict");
const dueText = await page.textContent("#due-result");
check("due read from the chain", dueText.includes("19.50 test USDC is waiting for mona") && dueText.includes("Paid for 3") && dueText.includes("58.50"));
await page.fill("#claim-repo", "mona/dotfiles");
await page.click("#claim-go");
await page.waitForSelector("#claim-add");
const add = decodeURIComponent(await page.getAttribute("#claim-add", "href"));
check("claim workflow prefilled", add.startsWith("https://github.com/mona/dotfiles/new/main?filename=.github/workflows/knos-claim.yml") && add.includes("audience=knos:claim:$ADDRESS") && add.includes("workflow_dispatch"));
check("claim: one command first", (await page.textContent("#view-claim")).includes("knos claim YOUR_SOLANA_ADDRESS"));
check("claim run link", (await page.getAttribute("#claim-run", "href")) === "https://github.com/mona/dotfiles/actions/workflows/knos-claim.yml");

// deep links
await page.goto(base + "#bounty=" + encodeURIComponent("octo/widgets#7"));
await page.waitForSelector("#st-result dl");
check("deep link to an escrow", (await page.inputValue("#st-issue")) === "octo/widgets#7");

// numbers
await page.goto(base + "#network");
await page.waitForSelector("#network-stats .stat");
const net = await page.textContent("#view-network");
check("numbers: outside kept apart from own", net.includes("Outside use") && net.includes("24.38") && net.includes("paid, Knos's own accounts") && net.includes("6 min"));
check("numbers: each payment links its transaction", (await page.getAttribute("#network-recent a", "href")) === `https://explorer.solana.com/tx/${"5".repeat(88)}?cluster=devnet`);
await page.waitForSelector("#network-programs dl");
check("numbers: immutability checked live", (await page.textContent("#network-programs")).split("no upgrade authority").length === 3);

// build
await page.goto(base + "#build");
check("build view", (await page.textContent("#view-build")).includes("knos_oidc_interface::{Token"));

// narrow screen: nothing overflows
await page.setViewportSize({ width: 360, height: 700 });
await page.goto(base + "#bounty");
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
check("no horizontal scroll at 360px", overflow <= 1);
if (process.argv[3]) await page.screenshot({ path: process.argv[3], fullPage: true });
check("no console errors", errors.length === 0);
if (errors.length) console.error(errors);
await browser.close(); server.close();
