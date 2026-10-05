// node tests/web/motion.mjs <site dir>
// The budget of the first screen and of what moves, held on a build of web/ in headless Chromium:
//   words     the first screen says 40 words at most, at a laptop's width and a phone's, with every page of the bar offered
//   weight    app.css under 60 KB; motion.js and brand/mark3d.js under 12 KB together; no request leaves the site
//   stillness with `prefers-reduced-motion: reduce` nothing runs (document.getAnimations() is empty) after load, after a
//             change of page and after the pointer has crossed the mark and a card; the mark is drawn all the same
//   movement  without it: a section enters once, a card leans and comes back, a token travels and lands, the mark
//             flies, a change of page is a view transition; and afterwards nothing is left running (nothing loops)
//   place     mounting the mark moves nothing
//   access    the focus is drawn on every link, button and field; the text is 4.5:1 or more against what it is on, light and dark
//   width     no sideways scroll from 320 to 1280
// No `playwright` package or no browser: says so and exits 0 (tests/test_site_overflow.py reports that as a skip).
import { createServer } from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { join, extname } from "node:path";
import { chromiumOrSkip, measure, TYPES } from "./overflow.mjs";

const root = process.argv[2];
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/motion.mjs <site dir>"); process.exit(2); }
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };

// ---- weight -------------------------------------------------------------------------------------------------------------
const size = (f) => statSync(join(root, f)).size;
check("weight: app.css is under 60 KB", size("app.css") < 60_000, size("app.css"));
check("weight: motion.js and brand/mark3d.js are under 12 KB together", size("motion.js") + size("brand/mark3d.js") < 12_000, size("motion.js") + size("brand/mark3d.js"));
check("weight: neither draws on a canvas or asks for a file", !/canvas|WebGL|fetch\(|import\(|https?:/i.test(readFileSync(join(root, "motion.js"), "utf8").replace(/^\/\/.*$/gm, "") + readFileSync(join(root, "brand/mark3d.js"), "utf8").replace(/^\/\/.*$/gm, "")));

const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;
const strangers = [];
const world = async (o = {}) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: "dark", ...o });
  // GitHub and devnet are what the page reads when a reader asks it something; they are refused here, and counted apart
  await ctx.route("**/*", (route) => { const u = route.request().url(); if (u.startsWith(base)) return route.continue(); if (!/^https:\/\/(api\.github\.com|api\.devnet\.solana\.com)\//.test(u)) strangers.push(u); return route.abort(); });
  return ctx;
};
const open = async (ctx, hash = "") => { const page = await ctx.newPage(); await page.goto(base + hash, { waitUntil: "load" }); await page.evaluate(() => document.fonts.ready); await page.waitForSelector("#mark3d .face", { state: "attached" }); return page; };
const settle = (page, ms = 700) => page.waitForTimeout(ms);                      // longer than --dur-3, the longest thing that moves
const running = (page) => page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running" || a.playState === "pending").map((a) => a.animationName || a.transitionProperty || "script"));

// ---- words ---------------------------------------------------------------------------------------------------------------
// What a reader sees before scrolling: every word drawn inside the window, the bar's included. The demo's own words
// are its module's (web/demo.js) and are not this shell's to count.
const firstScreen = (page) => page.evaluate(() => {
  const words = [], walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const el = n.parentElement;
    if (!n.textContent.trim() || el.closest("#demo, script, style, noscript") || !el.checkVisibility({ visibilityProperty: true, opacityProperty: true })) continue;
    const range = document.createRange(); range.selectNodeContents(n);
    const r = range.getBoundingClientRect(), box = el.getBoundingClientRect();
    if (r.width <= 1 || box.width <= 1 || r.bottom <= 0 || r.top >= innerHeight) continue;       // a name kept for a screen reader is one pixel wide
    words.push(...(n.textContent.match(/[A-Za-z0-9][\w'’%.,-]*/g) || []));
  }
  return words;
});
for (const [width, height] of [[1280, 800], [390, 844], [1440, 900]]) {
  const ctx = await world({ viewport: { width, height } });
  const page = await open(ctx);
  // every page the bar can offer is offered: the mounts other modules fill are filled, as they are on the site
  await page.evaluate(() => { for (const id of ["shadow", "buy", "demo"]) { const m = document.getElementById(id); if (!m.childElementCount) m.innerHTML = "<p>Filled by its module</p>"; } });
  await page.waitForFunction(() => !document.querySelector('nav a[data-mount="shadow"]').hidden);
  await settle(page);
  const words = await firstScreen(page);
  check(`words: the first screen says 40 words at most at ${width} by ${height}`, words.length <= 40 && words.length >= 20, [words.length, words.join(" ")]);
  if (width === 1280) {
    const bar = await page.$$eval("#nav > a", (l) => l.filter((a) => a.offsetParent !== null).map((a) => a.textContent));
    check("words: the bar shows five links and More", bar.join() === "Demo,Check an invoice,Console,Pricing,Docs" && await page.isVisible("#more-button") && (await page.$$eval("#more-list a", (l) => l.filter((a) => a.offsetParent !== null).length)) === 0, bar);
    const hero = await page.evaluate(() => ({ h1: document.querySelector("h1").textContent.trim(), fact: document.getElementById("hero-fact").textContent.trim().split(/\s+/).length,
      order: [...document.querySelectorAll(".hero h1, .hero #hero-fact, .hero .actions, .hero #mark3d, #demo")].map((e) => e.id || e.className || e.tagName),
      demoTop: document.getElementById("demo").getBoundingClientRect().top, fold: innerHeight }));
    check("words: the sentence, the figure in 12 words or fewer, two buttons, the mark, then the demo at the fold", hero.h1 === "The neutral meter for AI agent work: neither side keeps the count." && hero.fact <= 12
      && hero.order.join() === "check,hero-fact,actions,mark3d,demo" && Math.abs(hero.demoTop - hero.fold) <= 1, hero);
    const folded = await page.$$eval("details.k-more", (l) => [l.length, l.filter((d) => d.open).length]);
    check("words: the longer explanations are folded, one press away", folded[0] > 10 && folded[1] === 0, folded);
  }
  await ctx.close();
}

// ---- stillness: a reader who asked for no movement ------------------------------------------------------------------------
{
  const ctx = await world({ reducedMotion: "reduce" });
  const page = await open(ctx);
  await settle(page, 300);
  check("stillness: after load nothing runs", (await running(page)).length === 0 && (await page.evaluate(() => document.getAnimations().length)) === 0, await running(page));
  const mark = await page.$eval("#mark3d", (e) => ({ layers: e.querySelectorAll("i").length, face: getComputedStyle(e.querySelector(".face")).backgroundImage.startsWith("radial-gradient"), w: e.getBoundingClientRect().width }));
  check("  the mark is drawn, with its edge, and stands still", mark.layers >= 10 && mark.face && mark.w > 200, mark);
  await page.mouse.move(900, 300); await page.mouse.move(1000, 400);
  check("  the pointer over it turns nothing", (await page.$eval("#mark3d", (e) => e.getAttribute("style"))) === null && (await page.evaluate(() => document.getAnimations().length)) === 0);
  check("  nothing is held back to be revealed", await page.evaluate(() => !document.documentElement.classList.contains("k-motion") && [...document.querySelectorAll("main .card")].every((c) => getComputedStyle(c).opacity === "1")));
  await page.evaluate(() => { window.transitions = 0; if (document.startViewTransition) { const real = document.startViewTransition.bind(document); document.startViewTransition = (f) => { window.transitions++; return real(f); }; } });
  await page.click('#nav a[href="#pricing"]');
  await page.waitForFunction(() => location.hash === "#pricing" && !document.getElementById("view-pricing").hidden);
  check("  a change of page changes at once", await page.isVisible("#view-pricing") && await page.isHidden("#view-check") && (await page.evaluate(() => window.transitions + document.getAnimations().length)) === 0);
  const still = await page.evaluate(async () => {
    const m = await import("./motion.js"), a = document.querySelector("#view-pricing h2"), b = document.querySelector("#view-pricing table"), token = document.createElement("i");
    const before = document.body.childElementCount;
    await m.travel(token, a, b, 480); await m.raven(a, b);
    return { reduced: m.prefersReduced(), added: document.body.childElementCount - before, running: document.getAnimations().length };
  });
  check("  a token and the mark do not travel: the caller's promise is kept at once", still.reduced && still.added === 0 && still.running === 0, still);
  await ctx.close();
}

// ---- movement, and that it ends --------------------------------------------------------------------------------------------
{
  const ctx = await world();
  const page = await open(ctx);
  const before = await page.evaluate(() => { const r = (s) => { const b = document.querySelector(s).getBoundingClientRect(); return [b.left, b.top, b.width, b.height].map(Math.round).join(); };
    const at = () => [r("#mark3d"), r("h1"), r(".hero .actions"), r("#check-a-pull-request"), document.documentElement.scrollHeight].join(" ");
    const mounted = at(), mark = document.getElementById("mark3d"), body = mark.firstElementChild;
    mark.replaceChildren(); const empty = at(); mark.append(body); return { mounted, empty }; });
  check("place: mounting the mark moves nothing", before.mounted === before.empty, before);
  await settle(page);
  check("movement: the page says it moves, and after the mark has settled nothing is left running", await page.evaluate(() => document.documentElement.classList.contains("k-motion")) && (await running(page)).length === 0, await running(page));
  await page.mouse.move(700, 300); await page.mouse.move(980, 380, { steps: 4 });
  const turned = await page.$eval("#mark3d", (e) => [e.style.getPropertyValue("--turn-y"), e.style.getPropertyValue("--light-x")]);
  await page.mouse.move(640, 790); await page.mouse.move(640, 2);
  check("  the mark turns with the pointer, and settles when it leaves", /deg$/.test(turned[0]) && /%$/.test(turned[1]) && (await page.$eval("#mark3d", (e) => e.style.getPropertyValue("--turn-y"))) === "", turned);
  // a section enters once
  const card = await page.evaluate(() => { const c = document.querySelector("#view-check .how > li"); return { reveal: c.classList.contains("k-reveal"), in: c.classList.contains("in"), opacity: getComputedStyle(c).opacity }; });
  await page.$eval("#view-check .how", (e) => e.scrollIntoView({ block: "center", behavior: "instant" }));
  await page.waitForFunction(() => document.querySelector("#view-check .how > li").classList.contains("in"));
  await settle(page);
  check("  a section below the fold waits, enters when it is scrolled to, and stays", card.reveal && !card.in && card.opacity === "0" && (await page.$eval("#view-check .how > li", (c) => getComputedStyle(c).opacity)) === "1", card);
  // a card leans to the pointer and comes back
  await page.evaluate(() => { const c = document.createElement("div"); c.className = "k-card"; c.id = "lean"; c.dataset.tilt = ""; c.textContent = "A card"; document.querySelector("#view-check .how").before(c); c.scrollIntoView({ block: "center", behavior: "instant" }); });
  await page.waitForFunction(() => document.getElementById("lean").classList.contains("in"));
  const box = await page.$eval("#lean", (e) => { const r = e.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; });
  await page.mouse.move(box.x + box.w * 0.9, box.y + box.h * 0.2);
  const lean = await page.$eval("#lean", (e) => [parseFloat(e.style.getPropertyValue("--tilt-y")), parseFloat(e.style.getPropertyValue("--tilt-x")), e.style.getPropertyValue("--light-x")]);
  await page.mouse.move(box.x + box.w / 2, box.y - 40);
  check("  a card with data-tilt leans a few degrees to the pointer, with a light on it, and comes back", lean[0] > 1 && lean[0] <= 4 && lean[1] > 0 && lean[1] <= 4 && /%$/.test(lean[2]) && (await page.$eval("#lean", (e) => e.style.getPropertyValue("--tilt-y"))) === "", lean);
  // a token travels; the mark flies
  const trip = await page.evaluate(async () => {
    const m = await import("./motion.js"), a = document.querySelector("#lean"), b = document.querySelector("#view-check .how > li:last-child"), token = document.createElement("i");
    Object.assign(token.style, { width: "10px", height: "10px", display: "block" });
    const going = m.travel(token, a, b, 240);
    const mid = { fixed: getComputedStyle(token).position, on: token.isConnected, running: token.getAnimations().length };
    await going;
    const flying = m.raven(a, b), bird = document.querySelector(".k-raven");
    const flight = { bird: !!bird, mask: bird ? getComputedStyle(bird).maskImage || getComputedStyle(bird).webkitMaskImage : "" };
    await flying;
    return { mid, gone: !token.isConnected, flight, birdGone: !document.querySelector(".k-raven") };
  });
  check("  travel() carries a token from one element to another and takes it away; raven() flies the mark", trip.mid.fixed === "fixed" && trip.mid.on && trip.mid.running === 2 && trip.gone && trip.flight.bird && /brand\/mark\.svg/.test(trip.flight.mask) && trip.birdGone, trip);
  // a change of page morphs
  await page.evaluate(() => { scrollTo(0, 0); window.transitions = 0; const real = document.startViewTransition.bind(document); document.startViewTransition = (f) => { window.transitions++; return real(f); }; });
  await page.click('#nav a[href="#pricing"]');
  await page.waitForSelector("#view-pricing", { state: "visible" });
  check("  a link to another page is a view transition, and the page asked for is shown", (await page.evaluate(() => window.transitions)) === 1 && await page.isHidden("#view-check") && (await page.evaluate(() => location.hash)) === "#pricing");
  // a second change of page, by a link inside a fold: the fold is opened first, so the press lands at once
  await page.$eval('#view-pricing a[href="#pilot"]', (a) => { a.closest("details").open = true; });
  await page.click('#view-pricing a[href="#pilot"]');
  await settle(page, 1200);
  check("  and when everything has landed nothing is left running: nothing loops", (await running(page)).length === 0, await running(page));
  await ctx.close();
}

// ---- access: the focus, and the contrast of the text ------------------------------------------------------------------------
const lum = (c) => { const [r, g, b] = c.match(/[\d.]+/g).slice(0, 3).map((v) => { const s = Number(v) / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
for (const scheme of ["dark", "light"]) {
  const ctx = await world({ colorScheme: scheme, reducedMotion: "reduce" });
  const page = await open(ctx);
  const seen = await page.evaluate(() => {
    const probe = (cls, parent) => { const p = document.createElement("p"); p.className = cls; p.textContent = "text"; parent.append(p); const s = getComputedStyle(p).color; p.remove(); return s; };
    const card = document.querySelector("#pr-form"), a = document.createElement("a"); a.href = "#x"; card.append(a);
    const out = { paper: getComputedStyle(document.body).backgroundColor, card: getComputedStyle(card).backgroundColor, ink: getComputedStyle(document.body).color, quiet: probe("fine", card), lede: probe("lede", document.querySelector("main")),
      link: getComputedStyle(a).color, fact: getComputedStyle(document.getElementById("hero-fact")).color, button: getComputedStyle(document.getElementById("go-demo")).color, buttonOn: getComputedStyle(document.getElementById("go-demo")).backgroundColor,
      nav: getComputedStyle(document.querySelector("#nav a")).color };
    a.remove(); return out;
  });
  const pairs = { "text on the paper": [seen.ink, seen.paper], "text on a card": [seen.ink, seen.card], "quiet text on the paper": [seen.lede, seen.paper], "quiet text on a card": [seen.quiet, seen.card], "the figure's line": [seen.fact, seen.paper],
    "a link on the paper": [seen.link, seen.paper], "a link on a card": [seen.link, seen.card], "a button's word": [seen.button, seen.buttonOn], "the bar's links": [seen.nav, seen.paper] };
  const low = Object.entries(pairs).map(([name, [a, b]]) => [name, Math.round(ratio(a, b) * 100) / 100]).filter(([, r]) => r < 4.5);
  check(`access, ${scheme}: text is 4.5:1 or more against what it is on`, low.length === 0 && ratio(seen.ink, seen.paper) >= 7 && seen.paper !== seen.ink, [low, seen]);
  // the focus: every link, button and field of a page, reached as a keyboard reaches it
  for (const hash of scheme === "dark" ? ["", "#fund", "#claim", "#pricing", "#records"] : [""]) {
    await page.goto(base + hash); await page.waitForSelector("#mark3d .face", { state: "attached" });
    await page.keyboard.press("Tab");
    const unseen = await page.evaluate(() => {
      for (const d of document.querySelectorAll("details")) d.open = true;
      document.getElementById("more-button").click();
      const bad = []; let n = 0;
      for (const el of document.querySelectorAll("a[href], button, input, select, textarea, summary, [tabindex]")) {
        if (el.disabled || !el.checkVisibility() || el.offsetParent === null) continue;
        el.focus({ preventScroll: true }); n++;
        const s = getComputedStyle(el), ring = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2;
        if (document.activeElement !== el || !el.matches(":focus-visible") || !ring) bad.push(`${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""} ${el.textContent.trim().slice(0, 20)}`);
      }
      return { n, bad: bad.slice(0, 6) };
    });
    check(`access, ${scheme} ${hash || "(first screen)"}: the focus is drawn on each of ${unseen.n} links, buttons and fields`, unseen.n > 10 && unseen.bad.length === 0, unseen.bad);
  }
  await ctx.close();
}

// ---- width ------------------------------------------------------------------------------------------------------------------
{
  const ctx = await world();
  const page = await open(ctx);
  for (const width of [320, 360, 390, 768, 1024, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("about:blank"); await page.goto(base); await page.waitForSelector("#mark3d .face", { state: "attached" }); await settle(page, 600);
    if (width <= 860) await page.click("#menu");
    await page.click("#more-button");
    const { over, culprits } = await measure(page);
    const list = await page.$eval("#more-list", (e) => { const r = e.getBoundingClientRect(); return r.left >= 0 && r.right <= document.documentElement.clientWidth + 1 && r.width > 100; });
    check(`width: no sideways scroll at ${width}px, with the mark turned and More open inside the window`, over <= 1 && list, [over, culprits]);
  }
  await ctx.close();
}
check("weight: no request left the site for anyone but GitHub and devnet, which were refused", strangers.length === 0, strangers);

await browser.close(); server.close();
console.log(fails ? `${fails} checks failed` : "motion: every check held");
process.exit(fails ? 1 : 0);
