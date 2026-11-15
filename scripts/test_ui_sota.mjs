// Knos's interface, live, in headless Chromium:
//
//   node scripts/test_ui_sota.mjs design    test_one_design_system: one logo, type, colour, spacing and bar everywhere
//   node scripts/test_ui_sota.mjs layout    test_layout_audit: no word broken mid-word, no floating button over the page,
//                                           no sideways scroll, at 320, 375, 768 and 1280 on every public page
//   node scripts/test_ui_sota.mjs legibility  test_legibility: body text >= 16 px, <= 75 characters a line, line height
//                                           >= 1.5, paragraphs <= 60 words, <= 120 words of prose above the fold, <= 3 secondary
//                                           text lines a screen, one title and meta pattern (contrast: axe, quality.yml)
//
// The pages are scripts/public_pages.json (the product pages on GitHub Pages); SITE_URL and APP_URL point the site and
// the app (whose brand files the design check compares) elsewhere (a local build).
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { chromium } from "playwright";

const SITE = process.env.SITE_URL || "https://drexthealpha.github.io/Knos/", APP = (process.env.APP_URL || "https://knos.onrender.com/app/").replace(/\/?$/, "/");
const PAGES = JSON.parse(readFileSync(new URL("./public_pages.json", import.meta.url), "utf8")).pages
  .map((u) => u.replace("https://drexthealpha.github.io/Knos/", SITE).replace("https://knos.onrender.com/app/", APP));
const what = process.argv[2];
let fails = 0;
const ok = (c, msg, extra) => { console.log((c ? "ok   " : "FAIL ") + msg + (extra === undefined ? "" : " " + JSON.stringify(extra))); if (!c) fails += 1; };
const browser = await chromium.launch();
// the wake page forwards to the app once it answers: measured as itself, the app's address is not asked
const open = async (url, w, h, scheme = "light") => {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: scheme });
  const page = await ctx.newPage();
  if (/wanted\.html/.test(url)) await page.route(/onrender\.com/, (r) => r.abort());
  await page.goto(url, { waitUntil: "load", timeout: 120000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1200);
  return { ctx, page };
};
const sha = (b) => createHash("sha256").update(b).digest("hex").slice(0, 16);

async function design() {
  const files = {};
  for (const f of ["brand/tokens.css", "brand/wordmark.svg", "brand/mark.svg", "fonts/geist.woff2", "fonts/bricolage-grotesque.woff2"]) {
    const a = await fetch(SITE + f).then((r) => r.arrayBuffer()), b = await fetch(APP + "static/" + f).then((r) => r.arrayBuffer());
    files[f] = [sha(Buffer.from(a)), sha(Buffer.from(b))];
    ok(files[f][0] === files[f][1] && a.byteLength > 0, `${f}: the front door and the app serve the same bytes`, files[f]);
  }
  const seen = {};
  for (const scheme of ["light", "dark"]) {
    for (const url of PAGES) {
      const { ctx, page } = await open(url, 1280, 800, scheme);
      const got = await page.evaluate(() => {
        const css = getComputedStyle(document.documentElement), v = (n) => css.getPropertyValue(n).trim();
        const bar = document.getElementById("k-bar"), mark = bar?.querySelector(".wordmark");
        const first = (f) => f.split(",")[0].replace(/["']/g, "").trim();
        const links = [...document.styleSheets].map((s) => s.href || "").filter(Boolean);
        return {
          tokens: ["--paper", "--paper-2", "--ink", "--ink-2", "--line", "--accent", "--ok", "--bad", "--head", "--text", "--code", "--s0", "--s1", "--s2", "--sp-2", "--sp-4", "--sp-5", "--radius"].map((n) => `${n}:${v(n)}`).join(";"),
          body: first(getComputedStyle(document.body).fontFamily), bg: getComputedStyle(document.body).backgroundColor,
          heading: first(getComputedStyle(document.querySelector("h1, h2") || document.body).fontFamily),
          logo: mark ? getComputedStyle(mark).maskImage || getComputedStyle(mark).webkitMaskImage : "",
          square: document.querySelectorAll(".mark").length,
          nav: bar ? [...bar.querySelectorAll("nav a, nav button, .tools a, .tools button")].map((a) => a.textContent.trim()).join("|") : "",
          barStyle: bar ? ["height", "backgroundColor", "fontFamily", "borderBottomColor"].map((k) => getComputedStyle(bar)[k]).join(";") : "",
          tokensFirst: links.length > 0 && /brand\/tokens\.css$/.test(links[0]),
        };
      });
      got.logo = /wordmark\.svg/.test(got.logo) ? "wordmark.svg" : got.logo;
      ok(got.square === 0 && got.logo === "wordmark.svg", `${scheme} ${url}: the logo is the raven wordmark, no green square`, { logo: got.logo, square: got.square });
      ok(got.tokensFirst, `${scheme} ${url}: the token file is the first stylesheet`);
      for (const k of ["tokens", "body", "bg", "heading", "nav", "barStyle"]) (seen[`${scheme}:${k}`] ||= new Map()).set(url, got[k]);
      await ctx.close();
    }
  }
  let diffs = 0;
  for (const [k, m] of Object.entries(seen)) {
    const values = [...new Set(m.values())];
    diffs += values.length - 1;
    ok(values.length === 1, `${k}: one value on ${m.size} pages`, values.length === 1 ? values[0].slice(0, 120)
      : values.map((x) => [x, [...m.entries()].filter(([, y]) => y === x).map(([u]) => u)]));
  }
  console.log(`differences: ${diffs}`);
}

async function layout() {
  let words = 0, floats = 0, sideways = 0;
  for (const url of PAGES) {
    for (const w of [320, 375, 768, 1280]) {
      const { ctx, page } = await open(url, w, 800);
      await page.evaluate(() => document.querySelectorAll("details").forEach((d) => { d.open = true; }));
      await page.waitForTimeout(200);
      const r = await page.evaluate(() => {
        const out = { broken: [], floating: [], sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth };
        // a word of letters (a name, a field, a verdict) laid on two lines is broken mid-word; codes, hashes and addresses may wrap
        const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let n; (n = walk.nextNode());) {
          const el = n.parentElement;
          if (!el || el.closest("code, pre, kbd, .mono, script, style, svg, [hidden], [aria-hidden='true']") || !el.offsetParent) continue;
          for (const m of n.data.matchAll(/\S+/g)) {
            // a whole token that is a word: letters, a capital only first, punctuation after (an address or a hash is not)
            const w = m[0].match(/^[("'“]?([A-Za-z][a-z]{2,})[)"'”,.;:!?]*$/);
            if (!w) continue;
            const range = document.createRange(); range.setStart(n, m.index); range.setEnd(n, m.index + m[0].length);
            const tops = new Set([...range.getClientRects()].filter((x) => x.width > 0).map((x) => Math.round(x.top)));
            if (tops.size > 1) out.broken.push(w[1]);
          }
        }
        // anything a reader presses that stays fixed over the page while it scrolls
        for (const el of document.querySelectorAll("body *")) {
          const s = getComputedStyle(el);
          if (s.position !== "fixed" && s.position !== "sticky" || el.closest("#k-bar")) continue;      // the bar is the page's header
          const b = el.getBoundingClientRect();
          if (s.display === "none" || s.visibility === "hidden" || b.width < 2 || b.height < 2 || b.bottom <= 0 || b.top >= innerHeight) continue;
          if (el.matches("a, button, [role=button]") || el.querySelector("a, button, [role=button]")) out.floating.push(String(el.id || el.className || el.tagName).slice(0, 40));
        }
        return out;
      });
      words += r.broken.length; floats += r.floating.length; sideways += r.sideways > 0 ? 1 : 0;
      ok(!r.broken.length && !r.floating.length && r.sideways <= 0, `${w}px ${url}`, r.broken.length || r.floating.length || r.sideways > 0 ? { broken: r.broken.slice(0, 6), floating: r.floating.slice(0, 4), sideways: r.sideways } : undefined);
      await ctx.close();
    }
  }
  console.log(`mid-word breaks: ${words}, floating buttons: ${floats}, pages that scroll sideways: ${sideways}`);
}

async function legibility() {
  const titles = [];
  for (const url of PAGES) {
    for (const [w, h] of [[375, 812], [1280, 800]]) {
      const { ctx, page } = await open(url, w, h);
      const r = await page.evaluate(() => {
        const out = { small: [], wide: [], tight: [], long: [], fold: 0, secondary: 0, seen2: [], title: document.title, meta: document.querySelector('meta[name="description"]')?.content || "" };
        const muted = getComputedStyle(document.documentElement).getPropertyValue("--ink-2").trim();
        // what a reader sees: a closed fold's text is not shown (checkVisibility reads content-visibility too)
        const shown = (el) => (el.checkVisibility ? el.checkVisibility({ contentVisibilityAuto: true, visibilityProperty: true, opacityProperty: true })
          : el.offsetParent !== null) && !el.closest("details:not([open]) > :not(summary)");
        const skip = "code, pre, kbd, .mono, button, input, textarea, select, label, summary, nav, header, footer, table, svg, .k-vectors, .k-chip, .k-try, [data-not-prose]";
        const toRGB = (c) => { const x = document.createElement("i"); x.style.color = c; document.body.append(x); const v = getComputedStyle(x).color; x.remove(); return v; };
        const mutedRGB = muted ? toRGB(muted) : "";
        for (const el of document.querySelectorAll("main p, main li, main dd")) {
          if (!shown(el) || el.closest(skip) || !el.textContent.trim()) continue;
          const cs = getComputedStyle(el), fs = parseFloat(cs.fontSize), lh = cs.lineHeight === "normal" ? fs * 1.2 : parseFloat(cs.lineHeight);
          const secondary = fs < 16 || cs.color === mutedRGB;
          const text = el.textContent.replace(/\s+/g, " ").trim(), words = text.split(" ").length, rect = el.getBoundingClientRect();
          const lines = Math.max(1, Math.round(rect.height / lh));
          if (!secondary && fs < 16) out.small.push(text.slice(0, 40));
          if (lines > 1 && text.length / lines > 75) out.wide.push([Math.round(text.length / lines), text.slice(0, 40)]);
          if (!secondary && lh / fs < 1.5 - 1e-6) out.tight.push([+(lh / fs).toFixed(2), text.slice(0, 40)]);
          if (el.tagName === "P" && words > 60) out.long.push([words, text.slice(0, 40)]);
          if (secondary && rect.top < innerHeight && rect.bottom > 0) { out.secondary += lines; out.seen2.push(text.slice(0, 30)); }
        }
        const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let n; (n = walk.nextNode());) {
          const el = n.parentElement;
          // the words a reader reads: data a reader scans (a grid, a chart, cards, the measured numbers: data-not-prose) apart
          if (!el || !n.data.trim() || el.closest("script, style, [hidden], [aria-hidden='true'], [data-not-prose]") || !shown(el)) continue;
          const range = document.createRange(); range.selectNodeContents(n);
          const b = range.getBoundingClientRect();
          if (b.width > 0 && b.top < innerHeight && b.bottom > 0) out.fold += n.data.trim().split(/\s+/).length;
        }
        return out;
      });
      titles.push([url, r.title, r.meta.length]);
      const bad = r.small.length || r.wide.length || r.tight.length || r.long.length || r.fold > 120 || r.secondary > 3;
      ok(!bad, `${w}px ${url}: ${r.fold} words above the fold, ${r.secondary} secondary lines`,
        bad ? { small: r.small.slice(0, 2), wide: r.wide.slice(0, 2), tight: r.tight.slice(0, 2), long: r.long.slice(0, 2), secondary: r.secondary > 3 ? r.seen2.slice(0, 8) : [] } : undefined);
      await ctx.close();
    }
  }
  const pattern = titles.filter(([, t, m]) => !/^Knos[: ]/.test(t) || m < 50 || m > 160);
  ok(!pattern.length, `titles and meta: one pattern ("Knos: page", a 50-160 character description) on ${titles.length / 2} pages`, pattern.length ? [...new Set(pattern.map((x) => `${x[1]} (${x[2]})`))] : undefined);
}

const TESTS = { design, layout, legibility };
if (!TESTS[what]) { console.error("usage: node scripts/test_ui_sota.mjs design|layout|legibility"); process.exit(2); }
await TESTS[what]();
await browser.close();
const NAME = { design: "test_one_design_system", layout: "test_layout_audit", legibility: "test_legibility" }[what];
console.log(fails ? `FAIL ${NAME} (${fails})` : `PASS ${NAME}`);
process.exit(fails ? 1 : 0);
