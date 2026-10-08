// node tests/web/added.mjs <site dir>
// A page added by name (web/views.js ADDED; how: the head of web/mounts.js), held on a build of web/ in headless Chromium.
// The build keeps only the lines of ADDED whose module and data it has, so this script serves that build with the
// repository's whole list and STAND-INS for whatever the build lacks (a module that draws one heading, an
// enforce.json and a judges.json of the documented shapes): what is held is the mount itself, and the two views this
// release adds (web/enforce_view.js, web/judges.js) on data of the shape their sources promise.
//   list      the build's views.js names no page whose module or data is not in the build
//   menu      each page has one link: in the bar where its line says so, under "More" otherwise; no link without it
//   mount     the press shows the page's section at once with grey bars, then the module's drawing; the title is the
//             page's own; the hash opens it directly; a page opened twice is drawn once
//   matrix    #enforcement: one row a route, one column a restriction, every cell one of the four classes; a cell
//             pressed with the keyboard says what holds it and names its bypass test; a class filters
//   judges    #judges: the rows of judges.json, one link each, and what is not real yet
//   width     none of the three scrolls sideways at 320, 390, 768 and 1280
// No browser: a failure in CI, a skip elsewhere (tests/web/overflow.mjs, `owed`).
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromiumOrSkip, measure, TYPES, addedPages, menuOf } from "./overflow.mjs";

const root = process.argv[2], web = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "web");
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/added.mjs <site dir>"); process.exit(2); }
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };

const whole = readFileSync(join(web, "views.js"), "utf8");
const LIST = [...whole.matchAll(/^\s+([\w-]+): \{ file: "\.\/([\w.-]+)", draw: "(\w+)", nav: "([^"]+)"(, bar: true)?(?:, json: "([\w.-]+)")? \},$/gm)].map((m) => ({ name: m[1], file: m[2], draw: m[3], nav: m[4], bar: !!m[5], json: m[6] }));
check("list: every line of ADDED is one line of the documented shape", LIST.length >= 3 && LIST.length === (whole.match(/^\s+[\w-]+: \{ file: /gm) || []).length, LIST.map((a) => a.name));
const built = addedPages(root);
check("list: the build names no page whose module or data it lacks", built.every((n) => { const a = LIST.find((x) => x.name === n); return a && existsSync(join(root, a.file)) && (!a.json || existsSync(join(root, a.json))); })
  && LIST.every((a) => built.includes(a.name) === (existsSync(join(root, a.file)) && (!a.json || existsSync(join(root, a.json))))), built);

const ENFORCE = { routes: [{ id: "comment", name: "Funding by comment" }, { id: "wallet", name: "Wallet funding" }, "netted_release"],
  restrictions: [{ id: "who", name: "Who may fund" }, { id: "limit", name: "Per-order limit" }, "deadline"],
  cells: { comment: { who: { class: "workflow", by: "fund.yml job fund: approvals.gate", test: "tests/test_enforcement.py::test_comment_who" }, limit: { class: "advisory", by: "procurement/limits.json", test: "tests/test_enforcement.py::test_comment_limit" }, deadline: { class: "program", by: "knos_pay FundOrder: deadline <= MAX_WORK", test: "tests/test_enforcement.py::test_deadline" } },
    wallet: { who: { class: "outside", by: "a wallet is its owner's", test: "" }, limit: { class: "outside", by: "a wallet is its owner's", test: "" }, deadline: { class: "program", by: "knos_pay FundOrder", test: "tests/test_enforcement.py::test_deadline" } },
    netted_release: { who: { class: "workflow", by: "release job", test: "t::a" } } } };
const JUDGES = { source: "docs/JUDGES.md", columns: ["Judged", "What exists", "Evidence"], not_real: ["Outside funders: 0.", "Interviews: 0."],
  rows: ["How well it works", "Potential impact", "Novelty", "User experience", "Open source", "Business plan"].map((thing, i) => ({ thing, sentence: `Sentence ${i + 1}.`, link: i ? `https://github.com/drexthealpha/Knos/blob/main/docs/E${i}.md` : "https://explorer.solana.com/tx/abc?cluster=devnet", label: `evidence ${i + 1}` })) };
const standIn = (a) => `export const ${a.draw} = (el, ctx) => { window.__drawn = (window.__drawn || 0) + 1; el.innerHTML = '<h2>${a.nav} stands in here</h2><p class="lede">A stand-in page.</p><div class="card"><button type="button">One control</button></div>'; };\n`;
const over = { "/views.js": [whole, ".js"] };
for (const a of LIST) {
  if (!existsSync(join(root, a.file))) over[`/${a.file}`] = [standIn(a), ".js"];
  if (a.json && !existsSync(join(root, a.json))) over[`/${a.json}`] = [JSON.stringify(a.json === "enforce.json" ? ENFORCE : JUDGES), ".json"];
}
const real = (a) => !(`/${a.file}` in over), realData = (a) => !a.json || !(`/${a.json}` in over);

const browser = await chromiumOrSkip();
// While `held` is a promise, a page's module (a file of ADDED, the build's own or a stand-in) is answered only once it
// settles: the test opens the gate when it has looked at the page, so "before its module has arrived" does not depend on
// how fast a runner is. (A fixed 400 ms held only the stand-ins, and a loaded runner could take longer to look.)
let held = null;
const server = createServer((req, res) => {
  const url = decodeURIComponent(new URL(req.url, "http://x").pathname), path = join(root, url.replace(/\/$/, "/index.html"));
  const send = (type, body) => { res.writeHead(200, { "content-type": TYPES[type] || "application/octet-stream" }); res.end(body); };
  const answer = () => {
    if (url in over) return send(over[url][1], over[url][0]);
    if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
    return send(extname(path), readFileSync(path));
  };
  if (held && LIST.some((a) => url === `/${a.file}`)) return void held.then(answer);
  return answer();
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" });
await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : route.abort()));
const page = await ctx.newPage(), errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const ready = (n) => page.waitForFunction((name) => document.documentElement.dataset.ready === name, n);

await page.goto(base, { waitUntil: "load" }); await page.waitForSelector("#theme:not([hidden])");
// What the menu must be for the whole list (the same rule as web/front.js fitBar, written again in overflow.mjs menuOf):
// read from a folder that holds the whole views.js.
const MENU = menuOf(web), barWords = (l) => l.join(" ").split(" ").filter(Boolean).length;
const menu = () => page.evaluate(() => { const nav = document.getElementById("nav"), vis = (e) => !e.hidden && e.checkVisibility();
  const tops = [...nav.querySelectorAll(":scope > a, :scope > .more")].filter(vis).map((e) => e.offsetTop), tools = document.querySelector(".tools").getBoundingClientRect(), more = document.getElementById("more").getBoundingClientRect();
  return { bar: [...nav.querySelectorAll(":scope > a")].filter(vis).map((e) => e.textContent), under: [...document.querySelectorAll("#more-list > a")].filter((e) => !e.hidden).map((e) => e.textContent),
    one: Math.max(...tops) - Math.min(...tops) < 8 && more.right <= tools.left, sections: [...document.querySelectorAll("main > section.mount")].map((x) => x.id), links: [...nav.querySelectorAll("a[data-mount]")].map((a) => a.dataset.mount) }; });
const at1280 = await menu();
check("menu: each page has one link with its words and a section of its own", LIST.every((a) => at1280.links.filter((n) => n === a.name).length === 1 && at1280.sections.includes(a.name) && [...at1280.bar, ...at1280.under].includes(a.nav)), at1280);
check("menu: the bar is six words on one line: a page added to it stands before Pricing, and Docs, Leaderboard and Check make room, first under More", at1280.bar.join() === MENU.bar.join() && barWords(at1280.bar) <= 6 && at1280.one
  && at1280.under.slice(0, MENU.first.length).join() === MENU.first.join() && LIST.filter((a) => a.bar).every((a) => at1280.bar.includes(a.nav)), [at1280.bar, at1280.under.slice(0, 4)]);
check("menu: a page not of the bar is the last under More, and no link of the menu is lost", at1280.under.slice(-MENU.last.length).join() === MENU.last.join() && ["Check", "Demo", "Console", "Leaderboard", "Pricing", "Docs"].every((w) => [...at1280.bar, ...at1280.under].includes(w)), at1280.under);
{
  const tried = [];
  for (const width of [1100, 1000, 940, 900, 870]) { await page.setViewportSize({ width, height: 800 }); await page.waitForTimeout(60); tried.push([width, await menu()]); }
  check("menu: from 870 to 1100 the bar is still one line of six words at most, and no link is lost", tried.every(([, m]) => m.one && barWords(m.bar) <= 6 && LIST.every((a) => [...m.bar, ...m.under].includes(a.nav))), tried.map(([w, m]) => [w, m.one, m.bar]));
  await page.setViewportSize({ width: 390, height: 800 }); await page.waitForTimeout(60);
  await page.click("#menu");
  const phone = await page.evaluate(() => [...document.querySelectorAll("#nav > a")].filter((e) => !e.hidden && e.checkVisibility()).map((e) => e.textContent));
  check("menu: on a phone nothing has moved: the menu lists the bar's own six and the pages added to it, in place", phone.join() === ["Check", "Demo", "Console", "Leaderboard", ...LIST.filter((a) => a.bar).map((a) => a.nav), "Pricing", "Docs"].join(), phone);
  await page.click("#menu");
  await page.setViewportSize({ width: 1280, height: 800 }); await page.waitForTimeout(60);
  const back = await menu();
  check("menu: and back at 1280 the bar is as it was", back.bar.join() === at1280.bar.join() && back.under.join() === at1280.under.join() && back.one, back.bar);
}

// the press shows the section at once, with grey bars until the module (held back here until the page is looked at) has drawn
const one = LIST[0];
let release; held = new Promise((r) => { release = r; });
await page.click(`#nav a[data-mount="${one.name}"]`);
const pending = await page.evaluate((n) => { const el = document.getElementById(n); return { shown: el.checkVisibility(), bars: !!el.querySelector(".k-skeleton"), busy: el.getAttribute("aria-busy"), hash: location.hash, first: document.body.dataset.page === n }; }, one.name);
check("mount: the press shows the page's section at once, with grey bars, before its module has arrived", pending.shown && pending.bars && pending.busy === "true" && pending.hash === `#${one.name}` && pending.first, pending);
held = null; release();
await ready(one.name);
const drawn = await page.evaluate((n) => { const el = document.getElementById(n); return { title: el.querySelector("h2")?.textContent, bars: !!el.querySelector(".k-skeleton"), busy: el.hasAttribute("aria-busy"), current: document.querySelector(`#nav a[data-mount="${n}"]`).getAttribute("aria-current") }; }, one.name);
check("mount: then the module's own drawing, the bars gone and the link marked as the page shown", !!drawn.title && !drawn.bars && !drawn.busy && drawn.current === "page", drawn);
if (!real(one)) {
  await page.evaluate(() => { location.hash = "#pricing"; }); await ready("pricing");
  await page.evaluate((n) => { location.hash = `#${n}`; }, one.name); await ready(one.name);
  check("mount: a page opened twice is drawn once", (await page.evaluate(() => window.__drawn)) === 1);
}

const enforcement = LIST.find((a) => a.name === "enforcement"), judges = LIST.find((a) => a.name === "judges");
if (enforcement) {
  await page.goto(`${base}#enforcement`, { waitUntil: "load" }); await ready("enforcement");
  const data = realData(enforcement) ? JSON.parse(readFileSync(join(root, "enforce.json"), "utf8")) : ENFORCE;
  const n = (v) => (Array.isArray(v) ? v.length : Object.keys(v).length), cells = Object.values(data.cells).flatMap((r) => Object.values(r));
  const got = await page.evaluate(() => { const el = document.getElementById("enforcement"); return { title: el.querySelector("h2").textContent, rows: el.querySelectorAll("tbody tr").length, cols: el.querySelectorAll("thead th").length - 1,
    cells: [...el.querySelectorAll(".ke-cell")].map((c) => c.dataset.class), keys: [...el.querySelectorAll("[data-only]")].map((k) => k.textContent.replace(/\s+/g, " ").trim()), heads: [...el.querySelectorAll("tbody th")].map((t) => t.textContent) }; });
  check("matrix: the hash opens it: one row a route, one column a restriction, a cell for every cell of the file", got.rows === n(data.routes) && got.cols === n(data.restrictions) && got.cells.length === cells.length && got.title === "Who enforces each rule", got);
  check("matrix: every cell is one of the four classes, and the four keys count them", got.cells.every((c) => ["program", "workflow", "advisory", "outside"].includes(c))
    && got.keys.join("|") === ["program", "workflow", "advisory", "outside"].map((k) => `${k} ${cells.filter((c) => c.class === k).length}`).join("|"), got.keys);
  await page.focus("#enforcement .ke-cell"); await page.keyboard.press("Enter");
  const said = await page.evaluate(() => { const el = document.getElementById("enforcement"); return { text: el.querySelector(".ke-said").textContent.replace(/\s+/g, " ").trim(), pressed: el.querySelectorAll('.ke-cell[aria-pressed="true"]').length, live: el.querySelector(".ke-said").getAttribute("aria-live") }; });
  const firstRoute = Array.isArray(data.routes) ? data.routes[0] : Object.keys(data.routes)[0], rid = typeof firstRoute === "object" ? firstRoute.id : firstRoute;
  // the first cell drawn is the first route's first restriction, in the file's lists' order (an object's keys may be sorted, as `--json` sorts them)
  const firstRule = Array.isArray(data.restrictions) ? data.restrictions[0] : Object.keys(data.restrictions)[0], cid = typeof firstRule === "object" ? firstRule.id : firstRule, c0 = data.cells[rid][cid] || Object.values(data.cells[rid])[0];
  check("matrix: a cell pressed with the keyboard says what holds it and names its bypass test, in a line read out", said.pressed === 1 && said.live === "polite" && (!c0.by || said.text.includes(c0.by)) && (!c0.test || said.text.includes(`Bypass test: ${c0.test}`)), [said, c0]);
  await page.click('#enforcement [data-only="program"]');
  await page.click("#enforcement .ke-cell");          // a cell pressed while a class is shown leaves the class shown
  const only = await page.evaluate(() => { const el = document.querySelector("#enforcement .ke"); return { only: el.dataset.show, on: [...el.querySelectorAll(".ke-cell[data-on]")].map((c) => c.dataset.class), pressed: el.querySelector('[data-only="program"]').getAttribute("aria-pressed") }; });
  check("matrix: a class pressed marks its cells and no others; pressed again, none", only.only === "program" && only.pressed === "true" && only.on.length === cells.filter((c) => c.class === "program").length && only.on.every((c) => c === "program")
    && await page.evaluate(() => { document.querySelector('#enforcement [data-only="program"]').click(); const el = document.querySelector("#enforcement .ke"); return el.dataset.show === undefined && !el.querySelector(".ke-cell[data-on]"); }), only);
}
if (judges) {
  await page.goto(`${base}#judges`, { waitUntil: "load" }); await ready("judges");
  const data = realData(judges) ? JSON.parse(readFileSync(join(root, "judges.json"), "utf8")) : JUDGES;
  const got = await page.evaluate(() => { const el = document.getElementById("judges"); return { title: el.querySelector("h2").textContent, rows: [...el.querySelectorAll("table")[0].querySelectorAll("tbody tr")].map((r) => [r.cells[0].textContent, r.cells[1].textContent.trim(), r.querySelector("a")?.getAttribute("href") || "", r.querySelectorAll("a").length]),
    zeros: [...el.querySelectorAll("#judges-zeros + .k-table td")].map((t) => t.textContent), doc: el.querySelector("#judges-doc")?.getAttribute("href") }; });
  check("judges: the hash opens it: the file's rows, word for word, one link each", got.rows.length === data.rows.length && data.rows.every((r, i) => got.rows[i][0] === r.thing && got.rows[i][1] === r.sentence && got.rows[i][2] === (r.link || "") && got.rows[i][3] === (r.link ? 1 : 0)), got.rows);
  check("judges: then what is not real yet, as the file lists it, and the document itself", got.zeros.join("|") === (data.not_real || []).join("|") && got.doc === "https://github.com/drexthealpha/Knos/blob/main/docs/JUDGES.md" && got.title === "For judges: one page", got);
}
// ON A PHONE (390 x 640): the matrix scrolls sideways under a sticky first column. A cell reached with Tab is wholly in
// the visible part, clear of that column and of the edge, row after row; the answer, drawn under the table, is in view
// once a cell is pressed. For judges draws a row as a block: the sentence has the table's width, not a third of it.
if (enforcement) {
  await page.setViewportSize({ width: 390, height: 640 });
  await page.goto(`${base}#enforcement`, { waitUntil: "load" }); await ready("enforcement");
  await page.focus("#enforcement .ke-cell");
  const hidden = [];
  for (let i = 0; i < 14; i++) {
    const g = await page.evaluate(() => { const a = document.activeElement, w = a.closest(".k-table"), r = a.getBoundingClientRect(), wr = w.getBoundingClientRect(), lead = w.querySelector("tbody th").getBoundingClientRect().right;
      return { cell: a.getAttribute("aria-label"), inside: r.left >= lead - 0.5 && r.right <= wr.left + w.clientLeft + w.clientWidth + 0.5 }; });
    if (!g.inside) hidden.push(g.cell);
    if (i < 13) await page.keyboard.press("Tab");
  }
  check("phone: every cell reached with Tab is wholly in view, clear of the sticky column and the edge", hidden.length === 0, hidden);
  await page.keyboard.press("Enter");
  const seen = await page.evaluate(() => { const s = document.querySelector("#enforcement .ke-said"), r = s.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, height: innerHeight, text: s.textContent.trim().slice(0, 60),
    breaks: [...s.querySelectorAll(".mono")].map((m) => getComputedStyle(m).wordBreak) }; });
  check("phone: the answer under the table is in view once a cell is pressed, its lines broken between words", seen.top >= 0 && seen.bottom <= seen.height + 1 && !seen.text.startsWith("No cell pressed") && seen.breaks.every((b) => b !== "break-all"), seen);
}
if (judges) {
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`${base}#judges`, { waitUntil: "load" }); await ready("judges");
    const g = await page.evaluate(() => { const t = document.querySelector("#judges table"), c = t.querySelector("tbody td"); return { cell: c.getBoundingClientRect().width, table: t.getBoundingClientRect().width, head: t.tHead.getBoundingClientRect().height }; });
    check(`judges at ${width}: ${width < 560 ? "each row a block, the sentence as wide as the table" : "three columns under their heads"}`, width < 560 ? g.cell >= g.table * 0.9 && g.head <= 1 : g.cell < g.table * 0.7 && g.head > 10, g);
  }
}
for (const width of [320, 390, 768, 1280]) {
  await page.setViewportSize({ width, height: 800 });
  const wide = [];
  for (const a of LIST) { await page.goto(`${base}#${a.name}`, { waitUntil: "load" }); await ready(a.name); const m = await measure(page); if (m.over > 1) wide.push([a.name, m]); }
  check(`width: none of the added pages scrolls sideways at ${width}`, wide.length === 0, wide);
}
check("no page error", errors.length === 0, errors);
await browser.close(); server.close();
console.log(fails ? `${fails} checks failed` : "added: every check held");
process.exit(fails ? 1 : 0);
