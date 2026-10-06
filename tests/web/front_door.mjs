// The front door (web/front_door.js): your own invoice is the first thing the site checks.
//   node tests/web/front_door.mjs          the module's functions, with no browser
//   node tests/web/front_door.mjs page <site dir>     and the page in headless Chromium, on a build of the site
//                                                     (scripts/build_site.sh): the control alone, then the first screen
// With no browser: the four line states are src/knos/ids.py's, the invoice line's id is the Python's, the sample is
// examples/shadow/ word for word and falls into the four groups. With `page`: the first screen says 40 words at most
// and holds one control; the sample is answered with no request at all; a pasted invoice with a line billed twice has
// it flagged; a named repository asks nobody but api.github.com (answered here from tests/data/shadow_cases.json);
// nothing runs off the side at 320 px. No `playwright` package or no browser: says so and exits 0.
import { readFileSync, existsSync } from "node:fs";
import { join, dirname, extname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), root = join(here, "../../web");
const load = (f) => import(pathToFileURL(join(root, f)).href);
const { LINE_STATES, LINE_WORDS, COLUMNS, FEEDBACK, REPO_LINES, stateOf, answers, reading, repoInvoice, invoiceLineId } = await load("front_door.js");
const { SAMPLE_INVOICE, SAMPLE_BOOK } = await load("front_door_sample.js");
const { parse, gather, statement, recorded } = await load("shadow.js");
const { book } = JSON.parse(readFileSync(join(here, "../data/shadow_cases.json"), "utf8"));

let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const same = (what, got, want) => ok(what, JSON.stringify(got) === JSON.stringify(want), { got, want });
const words = (t) => t.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;

const ids = readFileSync(join(here, "../../src/knos/ids.py"), "utf8");
same("the four line states are ids.LINE_STATES, in its order", LINE_STATES, JSON.parse(`[${/^LINE_STATES = \(([^)]*)\)/m.exec(ids)[1]}]`));
same("and their words are ids.LINE_WORDS", LINE_WORDS, JSON.parse(/^LINE_WORDS = (\{[^}]*\})/m.exec(ids)[1]));
same("an invoice line's id is ids.invoice_line's", [await invoiceLineId("Acme Agents", "INV-1", 3), await invoiceLineId("", "sha256:ab", 1)], ["inv_9893a9c48ca5732c2ac3ee2c", "inv_f64f92df6563fb65917043e3"]);
same("the sample is examples/shadow/invoice.csv", SAMPLE_INVOICE, readFileSync(join(here, "../../examples/shadow/invoice.csv"), "utf8"));
same("with the answers of examples/shadow/recorded.json", SAMPLE_BOOK, JSON.parse(readFileSync(join(here, "../../examples/shadow/recorded.json"), "utf8")));
const invoice = parse(SAMPLE_INVOICE), st = statement(invoice, await gather(invoice, recorded(SAMPLE_BOOK)));
const WANT = ["agreed", "disputed", "disputed", "duplicate", "agreed", "duplicate", "insufficient_evidence"], COUNTS = { agreed: 2, disputed: 2, duplicate: 2, insufficient_evidence: 1 };
same("the sample's seven lines fall into the four groups", st.lines.map(stateOf), WANT);
// THE STATEMENT the front door makes (web/statement_make.js) is the one `knos statement make` writes from the same invoice
// and the same answers: tests/data/statement/front_door.* are the Python's (tests/test_site_front_door.py holds them to it)
const make = await load("statement_make.js"), finance = await load("finance_data.js"), fixture = (name) => readFileSync(join(here, "../data/statement", name), "utf8");
const made = await make.fromShadow({ invoice: SAMPLE_INVOICE, answers: SAMPLE_BOOK }, {});
same("the sample's statement is the Python's, byte for byte", finance.canonicalText(made), fixture("front_door.json"));
same("  its CSV too, before an approval and after one", [await finance.statementCsv(made), await finance.statementCsv(made, make.approve(made, null, "you", "approver", "2026-10-06"))], [fixture("front_door.plain.csv"), fixture("front_door.csv")]);
same("  every line has its deliverable and invoice line ids, an evaluation where one ran, and one of the four states", [made.lines.every((l) => /^dlv_[0-9a-f]{24}$/.test(l.deliverable) && /^inv_[0-9a-f]{24}$/.test(l.invoice_line) && l.evaluations.every((e) => /^evl_[0-9a-f]{24}$/.test(e))),
  made.lines.filter((l) => l.evaluations.length).length, made.lines.map((l) => l.state)], [true, 4, WANT]);
same("seven columns, one per question an approver asks", COLUMNS.map((c) => c[1]), ["Authorized", "Delivered", "Passed", "Billed before", "Approved by", "Owed", "Evidence"]);
const said = st.lines.map((r) => answers(r));
ok("each answer is a few words", said.every((a) => COLUMNS.every(([k]) => a[k].text && words(a[k].text) <= 6)), said.flatMap((a) => COLUMNS.map(([k]) => a[k].text)).filter((t) => words(t) > 6));
same("a line billed twice says where, and is owed nothing", [said[5].billed_before.text, said[5].owed.text, said[0].billed_before.text, said[0].owed.text], ["yes, line 1", "nothing: billed twice", "no", "400.00"]);
same("what the box holds: a repository's name, or an invoice", [reading(" acme/app ").repo, reading("https://github.com/acme/app").repo.repo, reading("acme/app#1").invoice.lines.length, reading("acme/app#1\nacme/app#2").invoice.lines.length],
  [{ owner: "acme", repo: "app", branch: "main" }, "app", 1, 2]);
const listing = [1, 2, 3, 5, 9, 12, 13, 14].map((n) => book[`repos/acme/app/pulls/${n}`]);
const listed = await repoInvoice({ owner: "acme", repo: "app" }, async () => listing);
same(`a repository is read as its merged pull requests, ${REPO_LINES} at most, none asked for twice`, [listed.invoice.lines.map((l) => l.pr), listed.known.size], [[1, 2, 5, 9, 12, 13, 14].map((n) => `acme/app#${n}`), 7]);
const fb = new URL(FEEDBACK);
same("the feedback link: a new issue on drexthealpha/Knos, labelled, three questions, nothing else", [fb.origin + fb.pathname, fb.searchParams.get("labels"), fb.searchParams.get("body").split("\n").filter(Boolean)],
  ["https://github.com/drexthealpha/Knos/issues/new", "shadow-feedback", ["1. What was wrong in the result?", "2. Would you use this on a real invoice?", "3. What would you pay for it?"]]);

// ---- the page ------------------------------------------------------------------------------------------------------------
async function page() {
  const { createServer } = await import("node:http");
  const { chromiumOrSkip, measure, TYPES } = await import("./overflow.mjs");
  const browser = await chromiumOrSkip();
  const HOLDER = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Front door</title>
    <link rel="stylesheet" href="app.css"></head><body><main><form id="front-door"></form></main>
    <script type="module">import { renderFrontDoor } from "./front_door.js"; window.door = renderFrontDoor(document.getElementById("front-door"), { now: new Date("2026-10-06T12:00:00Z") }); window.drawn = true;</script></body></html>`;
  const built = process.argv[3];
  if (!built || !existsSync(join(built, "index.html"))) { console.error("usage: node tests/web/front_door.mjs page <site dir>"); process.exit(2); }
  const server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url, "http://x").pathname), from = built, file = join(from, path === "/" ? "index.html" : path);
    if (path === "/door.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(HOLDER); }
    if (!file.startsWith(from) || !existsSync(file) || !extname(file)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }); res.end(readFileSync(file));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}/`;

  async function visit(path, width, o = {}) {
    const ctx = await browser.newContext({ viewport: { width, height: o.height || 800 }, acceptDownloads: true, reducedMotion: o.motion ? "no-preference" : "reduce" }), sent = [], strangers = [], errors = [];
    const cors = { "access-control-allow-origin": "*", "access-control-expose-headers": "x-ratelimit-remaining, x-ratelimit-limit, x-ratelimit-reset, retry-after" };
    await ctx.route("**/*", (route) => {            // registered first, so asked last: nothing but this site and GitHub's API
      const u = new URL(route.request().url());
      if (u.origin === new URL(base).origin || u.protocol === "blob:") return route.continue();
      strangers.push(u.href); return route.abort();
    });
    await ctx.route("https://api.github.com/**", (route) => {
      const q = route.request(), u = new URL(q.url()), at = (u.pathname + u.search).slice(1), head = { ...cors, "x-ratelimit-remaining": "50", "x-ratelimit-limit": "60", "x-ratelimit-reset": "2000000000" };
      if (o.offline) { strangers.push(u.href); return route.abort(); }
      sent.push({ method: q.method(), path: at, body: q.postData(), headers: q.headers() });
      if (at === "rate_limit") return route.fulfill({ status: 200, contentType: "application/json", headers: head, body: JSON.stringify({ resources: { core: { limit: 60, remaining: 50, reset: 2000000000 } } }) });
      if (at.startsWith("repos/acme/app/pulls?")) return route.fulfill({ status: 200, contentType: "application/json", headers: head, body: JSON.stringify(listing) });
      const got = Object.prototype.hasOwnProperty.call(book, at) ? book[at] : { __unread: "not found or private" };
      if (got.__unread) return route.fulfill({ status: 404, contentType: "application/json", headers: head, body: "{}" });
      return route.fulfill({ status: 200, contentType: "application/json", headers: head, body: JSON.stringify(got) });
    });
    const p = await ctx.newPage();
    p.on("pageerror", (e) => errors.push(String(e)));
    p.on("console", (m) => { if (m.type() === "error" && !/^https:\/\/api\.github\.com\//.test(m.location().url || "") && !/ERR_FAILED|Failed to load resource/.test(m.text())) errors.push(m.text()); });
    await p.goto(base + path);
    if (path === "door.html") await p.waitForFunction(() => window.drawn === true); else await p.waitForSelector("#front-door textarea");
    return { ctx, p, sent, strangers, errors };
  }
  const groups = (p) => p.$$eval("#front-result .fd-group", (l) => Object.fromEntries(l.map((g) => [g.dataset.group, [Number(g.querySelector("[data-count]").textContent), [...g.querySelectorAll(".fd-line")].map((li) => Number(li.dataset.line))]])));
  const statements = (p) => p.evaluate(() => [...document.querySelectorAll("#front-door button, #front-door a, #front-result p, #front-result h3, #front-result button, #front-result a, #front-result dt, #front-result dd, #front-result .fd-counts span")]
    .filter((e) => e.offsetParent !== null).flatMap((e) => e.innerText.split(/(?<=[.!?])\s+|\n+/)).map((t) => t.trim()).filter(Boolean));
  const wordy = (list) => list.filter((t) => words(t) > 12);
  const done = (p) => p.waitForSelector("#front-result[data-done]");

  // 1. the first screen of the site itself: 40 words at most, one control, the round below it
  for (const [width, height] of [[1280, 800], [390, 844], [320, 640]]) {
    const { ctx, p, strangers } = await visit("", width, { height });
    await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(700);
    const first = await p.evaluate(() => {
      const out = [], walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        const el = n.parentElement;
        if (!n.textContent.trim() || el.closest("#demo, script, style, noscript") || !el.checkVisibility({ visibilityProperty: true, opacityProperty: true })) continue;
        const range = document.createRange(); range.selectNodeContents(n);
        const r = range.getBoundingClientRect(), box = el.getBoundingClientRect();
        if (r.width <= 1 || box.width <= 1 || r.bottom <= 0 || r.top >= innerHeight) continue;
        out.push(...(n.textContent.match(/[A-Za-z0-9][\w'’%.,-]*/g) || []));
      }
      return out;
    });
    ok(`${width}px: the first screen says 40 words at most`, first.length <= 40 && first.length >= 15, [first.length, first.join(" ")]);
    const hero = await p.evaluate(() => ({ h1: document.querySelector("h1").textContent.trim(), fact: document.getElementById("hero-fact").textContent.trim(),
      controls: [...document.querySelectorAll(".hero input, .hero textarea, .hero select, .hero button, .hero-words a:not(.k-num)")].map((e) => e.dataset.fd || e.id),
      below: document.getElementById("demo").previousElementSibling.classList.contains("hero"), boxTop: document.querySelector("#front-door [data-fd=run]").getBoundingClientRect().bottom, fold: innerHeight }));
    ok(`${width}px: the sentence, then the number`, hero.h1 === "The neutral meter for AI agent work: neither side keeps the count." && hero.fact === "241 merged agent “tests pass” pull requests: 30 had a failed check." && words(hero.fact) <= 12, hero);
    ok(`${width}px: one control (a box, its button, a sample), above the fold, and the round below`, hero.controls.join() === "fd-in,run,sample" && hero.below && hero.boxTop <= hero.fold, hero);
    ok(`${width}px: the first screen does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    // the upgrades that are waiting, in one line on the first screen, from upgrades.json (a file of the site): inside the 40
    // words counted above, in the hero's top margin above the sentence, and opened it says each proposal in the file's words
    const feed = JSON.parse(readFileSync(join(built, "upgrades.json"), "utf8")), pending = feed.entries.filter((e) => e.status === "pending");
    const up = await p.evaluate(() => { const d = document.getElementById("hero-upgrades"), r = d.getBoundingClientRect(), w = document.querySelector(".hero-words").getBoundingClientRect();
      const h = document.getElementById("hero-upgrades-line");
      return { shown: !d.hidden && r.height > 0, words: h.textContent, badge: getComputedStyle(h, "::before").content, label: h.getAttribute("aria-label"), bottom: r.bottom, wordsTop: w.top, fold: innerHeight,
        inHero: d.parentElement.classList.contains("hero"), place: getComputedStyle(d).position }; });
    const n = pending.length, due = Math.min(...pending.map((e) => e.earliest_execution)), now = await p.evaluate(() => Date.now() / 1000), over = pending.every((e) => e.squads_status === "Approved") && now >= due;
    const want = { words: over ? "Upgrades approved" : "Upgrades pending", badge: `"${n}"`, label: `${n} program upgrade${n === 1 ? "" : "s"} ${over ? "approved, delay over" : "pending"}` };
    ok(`${width}px: the upgrade line is on the first screen: "${want.label}" (the count a badge, two words), from upgrades.json, above the sentence and out of the flow`,
      n ? up.shown && up.words === want.words && up.badge === want.badge && up.label === want.label && up.bottom <= up.wordsTop + 1 && up.bottom <= up.fold && up.inHero && up.place === "absolute" && first.join(" ").includes(want.words) : !up.shown, [up, want]);
    if (n) {
      await p.click("#hero-upgrades > summary");
      const told = await p.$$eval("#hero-upgrades-body p.upgrade", (l) => l.map((x) => [x.dataset.program, x.dataset.index, x.textContent]));
      same(`${width}px: opened, it says each pending proposal in the file's own sentence, newest first, and when the file was written`, [told, (await p.textContent("#upgrade-source")).includes(feed.generated.slice(0, 10))],
        [pending.map((e) => [e.program, String(e.index), e.words]), true]);
      ok(`${width}px:   opened, nothing runs off the side`, (await measure(p)).over <= 0, await measure(p));
      await p.click("#hero-upgrades > summary");
    }
    ok(`${width}px: the first screen asks nobody at all: not GitHub, not devnet`, strangers.length === 0, strangers);
    // THE GLOW belongs to the sentence and the mark: before an answer it fills the hero; once the sample's lines are drawn
    // under them it ends above the first of them, at every width (it used to run down through the list at 1280)
    const glow = () => p.evaluate(() => {
      const hero = document.querySelector(".hero"), s = getComputedStyle(hero, "::before"), probe = document.createElement("div");
      for (const k of ["position", "top", "right", "bottom", "left", "gridRowStart", "gridRowEnd", "gridColumnStart", "gridColumnEnd"]) probe.style[k] = s[k];
      hero.append(probe); const g = probe.getBoundingClientRect(); probe.remove();
      const res = document.getElementById("front-result"), h = hero.getBoundingClientRect(), w = document.querySelector(".hero-words").getBoundingClientRect();
      return { top: Math.round(g.top), bottom: Math.round(g.bottom), heroBottom: Math.round(h.bottom), wordsTop: Math.round(w.top), wordsBottom: Math.round(w.bottom), resultTop: res.hidden ? null : Math.round(res.getBoundingClientRect().top), content: s.content };
    });
    const g0 = await glow();
    ok(`${width}px: before an answer, the glow is behind the whole hero`, g0.content !== "none" && g0.resultTop === null && g0.top <= g0.wordsTop && Math.abs(g0.bottom - g0.heroBottom) <= 1, g0);
    if (width !== 320) {
      await p.click('[data-fd="sample"]'); await done(p);
      const g1 = await glow();
      ok(`${width}px: with the sample's lines drawn, the glow stays behind the sentence and ends above the lines`, g1.resultTop !== null && g1.top <= g1.wordsTop && g1.bottom >= g1.wordsBottom - 1 && g1.bottom <= g1.resultTop + 1 && g1.heroBottom > g1.bottom + 200, g1);
    }
    if (width === 320) {      // the sample on the site itself, with GitHub out of reach
      await p.click('[data-fd="sample"]'); await done(p);
      const g1 = await glow();
      ok("320px: with the sample's lines drawn, the glow ends above the lines", g1.resultTop !== null && g1.top <= g1.wordsTop && g1.bottom <= g1.resultTop + 1, g1);
      ok("320px, on the site: the sample's result does not scroll sideways", (await measure(p)).over <= 0, await measure(p));
      ok("320px, on the site: the result is in the first screen's own block, above the round", await p.$eval("#front-result", (e) => e.parentElement.classList.contains("hero") && !e.hidden));
      await p.click('[data-fd="approve"]'); await p.click('[data-fd="statement"]');
      await p.waitForSelector("#aps-statement", { state: "visible" });
      same("320px, on the site: Open the statement shows the same statement on the Statement page, with the approval", await p.$eval("#aps-statement", (e) => [e.dataset.sha256, e.dataset.whole, document.body.dataset.page]).then(async (l) => [...l,
        (await p.textContent("#aps-answers")).includes("2 agreed lines, 650.00 by you (approver) on"), await p.$$eval("#aps-lines .k-state", (x) => x.map((e) => e.dataset.state))]), [made.sha256, "1", "invoice-statement", true, WANT]);
      ok("320px, on the site: the statement does not scroll sideways", (await measure(p)).over <= 0, await measure(p));
    }
    await ctx.close();
  }
  const figures = JSON.parse(readFileSync(join(here, "../../docs/backtest.json"), "utf8")).sample.merged.overall;
  same("the number is docs/backtest.json's", [figures.any_check_failed.prs, figures.prs], [30, 241]);

  // 2. the sample, with no network at all (GitHub refused), with and without motion
  for (const motion of [false, true]) {
    const tag = motion ? "sample, moving" : "sample", { ctx, p, strangers, errors } = await visit("door.html", motion ? 390 : 320, { offline: true, motion });
    const t0 = Date.now();
    await p.click('[data-fd="sample"]');
    const pending = await p.textContent('#front-result [data-fd="said"]'), took = Date.now() - t0;
    ok(`${tag}: a pending state is drawn at once`, /^(Checking 7 lines\.|Checked 7 lines\. 5 exceptions\.)$/.test(pending) && took < 300, [pending, took]);
    await done(p);
    const g = await groups(p);
    same(`${tag}: four groups with the expected counts`, Object.fromEntries(Object.entries(g).map(([k, v]) => [k, v[0]])), COUNTS);
    same(`${tag}: every line is in its group`, Object.fromEntries(Object.entries(g).map(([k, v]) => [k, v[1]])), { agreed: [1, 5], disputed: [2, 3], duplicate: [4, 6], insufficient_evidence: [7] });
    same(`${tag}: the neutral count beside the supplier's`, await p.$$eval("#front-result .fd-counts > div", (l) => l.map((d) => d.innerText.split("\n").map((t) => t.trim()).filter(Boolean))),
      [["Supplier's count", "7", "lines, 2900.00 billed"], ["Neutral count", "2", "lines, 650.00 agreed"]]);
    same(`${tag}: each line answers the seven questions`, await p.$$eval("#front-result .fd-line", (l) => [...new Set(l.map((li) => [...li.querySelectorAll("dt")].map((d) => d.textContent).join()))]), [COLUMNS.map((c) => c[1]).join()]);
    same(`${tag}: it is marked as made up, and nothing is left pending`, [await p.textContent('[data-fd="mark"]'), await p.$$eval('[data-fd="pending"] li', (l) => l.length), await p.textContent('[data-fd="said"]')],
      ["Sample: a made-up invoice from a made-up supplier.", 0, "Checked 7 lines. 5 exceptions."]);
    ok(`${tag}: every statement is twelve words at most`, wordy(await statements(p)).length === 0, wordy(await statements(p)));
    ok(`${tag}: the result does not scroll sideways`, (await measure(p)).over <= 0, await measure(p));
    if (!motion) {
      same("sample: one link installs, one optional link asks what it missed", await p.$$eval('#front-result [data-fd="after"] a', (l) => l.map((a) => [a.textContent, a.getAttribute("href")])), [["Open the statement", "#invoice-statement"], ["Install the meter", "#install"], ["Tell us what it missed", FEEDBACK]]);
      ok("sample: the feedback link carries nothing of the invoice", !/example|storefront|400|2900|Agents/i.test(decodeURIComponent(FEEDBACK)));
      const [d0] = await Promise.all([p.waitForEvent("download"), p.click('[data-fd="csv"]')]);
      same("sample: before anyone approves, the CSV says nobody has", readFileSync(await d0.path(), "utf8"), fixture("front_door.plain.csv"));
      await p.click('[data-fd="approve"]');
      same("sample: approving marks the agreed lines and says what is left", [await p.textContent('[data-fd="approved"]'), await p.$$eval(".fd-line[data-approved]", (l) => l.map((li) => `${li.dataset.line} ${li.querySelector('[data-col="approved_by"]').textContent}`)),
        await p.$$eval('.fd-line:not([data-approved]) [data-col="approved_by"]', (l) => [...new Set(l.map((d) => d.textContent))])], ["Approved 2 lines. 5 exceptions left.", ["1 you, 2026-10-06", "5 you, 2026-10-06"], ["nobody yet"]]);
      const [d] = await Promise.all([p.waitForEvent("download"), p.click('[data-fd="csv"]')]), csv = readFileSync(await d.path(), "utf8");
      same("sample: Download CSV gives the statement `knos statement make` writes, with the approval: the same bytes", [d.suggestedFilename(), csv], ["statement-sha256-fb61f3411e72ffea.csv", fixture("front_door.csv")]);
      same("sample: its columns are the statement's, and every line is in one of the four states", [csv.split("\n")[10], [...new Set(csv.split("\n").slice(11, 18).map((r) => r.split(",")[3]))].sort()],
        ["line,reference,supplier,state,amount,why,deliverable,evaluations,invoice_line,settlement,payment,evidence,evidence_sha256,duplicate_of", ["agreed", "disputed", "duplicate", "insufficient evidence"]]);
      await p.waitForSelector(".k-toast");
      same("sample: a toast says what was downloaded", await p.textContent(".k-toast"), "Downloaded statement-sha256-fb61f3411e72ffea.csv");
      ok("sample: every statement is still twelve words at most", wordy(await statements(p)).length === 0, wordy(await statements(p)));
    }
    ok(`${tag}: nobody is asked, GitHub included`, strangers.length === 0, strangers);
    ok(`${tag}: no error on the page`, errors.length === 0, errors);
    await ctx.close();
  }

  // 3. a pasted invoice with one pull request billed twice
  {
    const { ctx, p, sent, strangers, errors } = await visit("door.html", 320);
    ok("pasted: nothing is asked before anyone asks", sent.length === 0, sent);
    await p.fill("#fd-in", "https://github.com/acme/app/pull/1,100.00,Acme Agents\nhttps://github.com/acme/app/pull/2,100.00,Acme Agents\nacme/app#1,100.00,Acme Agents\n");
    await p.click('[data-fd="run"]'); await done(p);
    const g = await groups(p);
    same("pasted: the line billed twice is flagged as a duplicate", [g.duplicate, await p.$eval('.fd-line[data-line="3"] [data-col="billed_before"]', (d) => d.textContent), await p.$eval('.fd-line[data-line="3"] .fd-why', (d) => d.textContent)],
      [[1, [3]], "yes, line 1", "Same pull request as line 1."]);
    same("pasted: the other lines are judged as shadow mode judges them", [g.agreed[1], g.disputed[1], g.insufficient_evidence[1]], [[1], [2], []]);
    const install = await p.getAttribute('[data-fd="install"]', "href");
    ok("pasted: Install the meter opens GitHub's new-file page for that repository, the workflow filled in, no login in it", install.startsWith("https://github.com/acme/app/new/main?filename=.github%2Fworkflows%2Fknos.yml&value=%23%20.github%2Fworkflows%2Fknos.yml") && !/token|secret=/i.test(install.split("&value=")[0]), install.slice(0, 120));
    ok("pasted: only GETs with no body and no login reach GitHub", sent.length > 2 && sent.every((s) => s.method === "GET" && !s.body && !s.headers.authorization && !s.headers.cookie), sent);
    ok("pasted: nothing of the invoice but the pull requests' names is sent", !sent.some((s) => /Acme(%20| )Agents|100\.00/i.test(s.path)) && sent.filter((s) => s.path === "repos/acme/app/pulls/1").length === 1);
    ok("pasted: nobody but this page and api.github.com is asked", strangers.length === 0, strangers);
    ok("pasted: every statement is twelve words at most", wordy(await statements(p)).length === 0, wordy(await statements(p)));
    ok("pasted: the result does not scroll sideways at 320 px", (await measure(p)).over <= 0, await measure(p));
    await p.fill("#fd-in", "this is not an invoice"); await p.click('[data-fd="run"]'); await done(p);
    same("pasted: words that name no pull request are said to be that", [await p.textContent('[data-fd="said"]'), await p.textContent(".fd-line .fd-why"), (await groups(p)).insufficient_evidence], ["Checked 1 line. 1 exception.", "No pull request named.", [1, [1]]]);
    ok("pasted: no error on the page", errors.length === 0, errors);
    await ctx.close();
  }

  // 4. a public repository, named: its merged pull requests, and no host but api.github.com
  {
    const { ctx, p, sent, strangers, errors } = await visit("door.html", 320);
    await p.fill("#fd-in", "acme/app"); await p.press("#fd-in", "Enter"); await done(p);
    const g = await groups(p), total = Object.values(g).reduce((a, v) => a + v[0], 0);
    same("repository: seven merged pull requests, each in a group", [total, await p.textContent('[data-fd="theirs"]'), await p.textContent('[data-fd="theirs-name"]'), Number(await p.textContent('[data-fd="ours"]'))], [7, "7", "Merged there", g.agreed[0]]);
    ok("repository: no pull request is asked for again after the listing", sent.filter((s) => /^repos\/acme\/app\/pulls\/\d+$/.test(s.path)).length === 0 && sent.filter((s) => s.path.startsWith("repos/acme/app/pulls?")).length === 1, sent.map((s) => s.path));
    ok("repository: no request to anyone but api.github.com, GET only, no login", strangers.length === 0 && sent.every((s) => s.method === "GET" && !s.body && !s.headers.authorization), strangers);
    ok("repository: Install the meter is for that repository", (await p.getAttribute('[data-fd="install"]', "href")).startsWith("https://github.com/acme/app/new/main?filename="));
    ok("repository: every statement is twelve words at most", wordy(await statements(p)).length === 0, wordy(await statements(p)));
    ok("repository: the result does not scroll sideways at 320 px", (await measure(p)).over <= 0, await measure(p));
    await p.fill("#fd-in", "acme/nothing-here"); await p.press("#fd-in", "Enter");
    await p.waitForFunction(() => /private/.test(document.querySelector('[data-fd="said"]').textContent));
    same("repository: one that is private or not there is said to be that", await p.textContent('[data-fd="said"]'), "Not read: that repository is private, or not there.");
    ok("repository: no error on the page", errors.length === 0, errors);
    await ctx.close();
  }
  await browser.close(); server.close();
}

if (process.argv[2] === "page") await page();
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
