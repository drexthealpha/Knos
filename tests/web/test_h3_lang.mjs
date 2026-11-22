// node tests/web/test_h3_lang.mjs <site dir>
// Round 13, H3 a, b and f, in headless Chromium at 360 by 800 (and 320 by 712), on the four screens: the front door,
// the tool page /t/<id>/, the result page /r/<id>/ and the pricing page (tests/web/test_h3_common.mjs serves them).
// The automatic checks of U7 (v0328 research LAWS/UX/U7.md) that these screens can run, as each "Automatic check:"
// line describes them:
//   R1  every screen in Arabic, Persian, Urdu and Hebrew: html dir="rtl" and its lang; no sideways scroll at 320 and 360 px; no element crosses
//       the screen's edge
//   R2  every input and textarea has dir="auto"
//   R5  the front door with every string padded by IBM's allowance (x3 up to 10 characters, down to x1.3) at 320 px: no
//       button, label or heading cut or wider than its box
//   R7  every message with a count holds exactly the CLDR forms of its language (Intl.PluralRules); the server's own
//       plural rules, counts and sums of money equal the browser's Intl
//   R13 the limit box reads 1.4 typed in Arabic-Indic, Persian, Devanagari or Bengali digits, or with a decimal comma
//   R15 no date written as numbers and slashes on any screen
//   R17 locale ar-EG with nothing stored: lang ar; a stored choice of fr beats ar-EG; locale xx: English; no request to
//       a place or address lookup; the server's pages send Vary: Accept-Language
//   R18 the language control is on the first screen, at least 44 by 44 px, with a word; each language is written in
//       itself (Intl.DisplayNames) with its lang, the current one first
//   R19 no string of a non-English screen equals its English source (the words each file lists as the same excepted)
// and H3: the "How it works" fold opens with the five labelled lines in the screen's language, says the page is machine
// translated in that language, and the result's fold has Listen, which reads the result sentence in the screen's
// language through the browser's speech (a stand-in records it); the question box's Speak fills the box from the
// browser's speech recognition (a stand-in), and is not shown where the browser has none.
import { execFileSync } from "node:child_process";
import { chromiumOrSkip } from "./overflow.mjs";
import { serveScreens, LANGS, RTL, ROOT } from "./test_h3_common.mjs";

let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail).slice(0, 600)); } };
const browser = await chromiumOrSkip();
const S = await serveScreens(process.argv[2]);
const SCREENS = Object.entries(S.screens);
const FIVE = ["q.get", "q.next", "q.pay", "q.why", "q.who"];

// ---- R7 and R13/R14: the files' plural forms, and the server's rules against the browser's Intl --------------------------
for (const lang of LANGS) {
  const cats = new Intl.PluralRules(lang).resolvedOptions().pluralCategories.slice().sort().join(",");
  const bad = Object.entries(S.file(lang).strings).filter(([, v]) => typeof v === "object" && Object.keys(v).sort().join(",") !== cats).map(([k]) => k);
  check(`R7 ${lang}: every message with a count has the CLDR forms ${cats}`, bad.length === 0, bad);
}
{
  const env = { ...process.env, PYTHONPATH: [`${ROOT}/apps/wanted`, `${ROOT}/src`].join(process.platform === "win32" ? ";" : ":"), PYTHONIOENCODING: "utf-8" };
  const ns = [...Array(125).keys(), 1000, 1001, 100000, 1000000, 2000000, 1234567];
  const py = JSON.parse(execFileSync(process.env.PYTHON || "python3", ["-c", `import json,sys
from knos_wanted import tool_page as p
ns = json.loads(sys.argv[1])
print(json.dumps({l: {"plural": [p.plural(l, n) for n in ns], "nf": [p.nf(l, n) for n in ns], "money": [p.money(l, x) for x in (1, 20, 330, 763, 1000)]} for l in p.LANGS}))`, JSON.stringify(ns)], { env, encoding: "utf8" }));
  for (const lang of LANGS) {
    const pr = new Intl.PluralRules(lang), nf = new Intl.NumberFormat(lang), mf = new Intl.NumberFormat(lang, { style: "currency", currency: "USD", currencyDisplay: "narrowSymbol", minimumFractionDigits: 0, maximumFractionDigits: 0 });
    check(`R7 ${lang}: the server's plural rules equal Intl.PluralRules for ${ns.length} counts`, ns.every((n, i) => pr.select(n) === py[lang].plural[i]), ns.filter((n, i) => pr.select(n) !== py[lang].plural[i]).slice(0, 5));
    check(`R13 ${lang}: the server writes counts as Intl.NumberFormat does`, ns.every((n, i) => nf.format(n) === py[lang].nf[i]), ns.map((n, i) => [nf.format(n), py[lang].nf[i]]).filter(([a, b]) => a !== b).slice(0, 3));
    check(`R14 ${lang}: the server writes US dollars as Intl.NumberFormat does`, [1, 20, 330, 763, 1000].every((x, i) => mf.format(x) === py[lang].money[i]), [mf.format(1), py[lang].money[0]]);
  }
}

// ---- every screen in every language --------------------------------------------------------------------------------
async function open(lang, url, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: opts.width || 360, height: opts.height || 800 }, locale: lang, hasTouch: true });
  await S.route(ctx);
  const hosts = new Set();
  ctx.on("request", (r) => hosts.add(new URL(r.url()).hostname));
  if (opts.init) await ctx.addInitScript(opts.init);
  const page = await ctx.newPage();
  const resp = await page.goto(url, { waitUntil: "load" });
  await page.waitForFunction((l) => document.documentElement.lang === l, opts.expect || lang, { timeout: 8000 }).catch(() => {});
  return { ctx, page, resp, hosts };
}
const pressRun = async (page) => { await page.click("#try, #go"); await page.waitForFunction(() => !!document.querySelector("#about") && document.querySelector("#about").textContent.trim() && (!document.getElementById("result") || !document.getElementById("result").hidden), null, { timeout: 10000 }); };

for (const lang of LANGS) {
  const file = S.file(lang), same = new Set(file._meta.same || []);
  const english = new Map(Object.entries(S.en).filter(([k, v]) => typeof v === "string" && v.length > 3 && !same.has(k) && !/[{<]/.test(v)).map(([k, v]) => [v, k]));
  for (const [screen, url] of SCREENS) {
    const at = `${lang} ${screen}:`;
    const { ctx, page, resp, hosts } = await open(lang, url);
    if (screen === "door") { await page.evaluate(() => { document.getElementById("how").open = true; }); await pressRun(page); }
    const m = await page.evaluate(() => {
      const de = document.documentElement, H = innerHeight;
      const texts = [], walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) { const p = n.parentElement; if (!p || /^(SCRIPT|STYLE|TEXTAREA|OPTION)$/.test(p.tagName) || p.closest("#col, .klang-list, svg, #original, [lang=en]")) continue; const t = n.nodeValue.trim(); if (t) texts.push(t); }
      for (const e of document.querySelectorAll("[placeholder], [aria-label], [title]")) for (const a of ["placeholder", "aria-label", "title"]) if (e.getAttribute(a) && !e.closest(".klang-list, svg")) texts.push(e.getAttribute(a));
      texts.push(document.title.replace(/ \| Knos$/, ""));
      const sw = document.querySelector("[data-language-switcher]"), sb = sw && sw.querySelector("summary").getBoundingClientRect();
      const inputs = [...document.querySelectorAll("input:not([type=file]), textarea")].filter((e) => e.getAttribute("dir") !== "auto" && e.getAttribute("dir") !== "ltr").map((e) => e.id);
      const dt = [...document.querySelectorAll("details .five dt")].map((x) => x.textContent.trim());
      const mt = [...document.querySelectorAll("details p")].map((p) => p.textContent.trim());
      return { lang: de.lang, dir: de.dir, texts, inputs, dt, mt, switcher: sw ? { top: sb.top, bottom: sb.bottom, w: sb.width, h: sb.height, text: sw.querySelector("summary").textContent.trim() } : null,
        wide: de.scrollWidth - innerWidth, slashDate: /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/.test(document.body.innerText) };
    });
    check(`${at} html lang is ${lang}${RTL.includes(lang) ? ', dir="rtl"' : ""} (R1, R17)`, m.lang === lang && m.dir === (RTL.includes(lang) ? "rtl" : "ltr"), [m.lang, m.dir]);
    if (screen === "tool" || screen === "result") check(`${at} the server answers in that language with Vary: Accept-Language (R17)`, /Accept-Language/i.test(resp.headers()["vary"] || ""), resp.headers());
    check(`${at} the language control is on the first screen, 44 by 44 px or more, with a word (R18)`, m.switcher && m.switcher.bottom <= 800 && m.switcher.w >= 44 && m.switcher.h >= 44 && m.switcher.text === file._meta.name, m.switcher);
    check(`${at} every input and box keeps the direction of what is typed (R2)`, m.inputs.length === 0, m.inputs);
    check(`${at} no sideways scroll at 360 px`, m.wide <= 0, m.wide);
    check(`${at} no date as numbers and slashes (R15)`, !m.slashDate);
    if (lang !== "en") {
      const left = m.texts.filter((t) => english.has(t));
      check(`${at} no English string left on the screen (R19)`, left.length === 0, left);
      check(`${at} the fold says the page is machine translated, in ${lang}`, m.mt.includes(file.strings["fold.mt"]), m.mt.slice(-3));
    }
    check(`${at} the fold opens with the five labelled lines in order (H3 f)`, JSON.stringify(m.dt) === JSON.stringify(FIVE.map((k) => file.strings[k])), m.dt);
    check(`${at} no request to a place or address lookup (R17)`, [...hosts].every((h) => h === "127.0.0.1" || h === "knos.onrender.com"), [...hosts]);
    // R18: the list, each language written in itself and marked with its lang, the current one first
    await page.click("[data-language-switcher] summary");
    const opts = await page.evaluate(() => [...document.querySelectorAll("[data-language-switcher] .klang-list a")].map((a) => ({ text: a.textContent.trim(), lang: a.getAttribute("lang"), h: a.getBoundingClientRect().height })));
    check(`${at} each language in the list is written in itself, the current one first, 44 px tall (R18)`, opts.length === LANGS.length && opts[0].lang === lang && opts.every((o) => o.text === new Intl.DisplayNames([o.lang], { type: "language" }).of(o.lang) && o.h >= 44), opts.map((o) => o.text));
    await ctx.close();
  }
}

// ---- R1 at 320 px in English and the right-to-left languages (Arabic, Persian, Urdu, Hebrew): nothing crosses the edge ---------------------------------------------------
for (const lang of ["en", ...RTL]) for (const [screen, url] of SCREENS) {
  const { ctx, page } = await open(lang, url, { width: 320, height: 712 });
  if (screen === "door") await pressRun(page);
  const out = await page.evaluate(() => ({ wide: document.documentElement.scrollWidth - innerWidth,
    cross: [...document.querySelectorAll("main *, header *")].filter((e) => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width && s.display !== "none" && s.position !== "absolute" && !e.closest("details:not([open]) > :not(summary), .sr, textarea, svg") && (r.left < -1 || r.right > innerWidth + 1); }).map((e) => e.tagName + "#" + e.id).slice(0, 5) }));
  check(`R1 ${lang} ${screen} at 320 px: no sideways scroll and nothing crosses the edge`, out.wide <= 0 && out.cross.length === 0, out);
  await ctx.close();
}

// ---- R5: the front door with every string padded by IBM's allowance, at 320 px ---------------------------------------
{
  const pad = (s) => { const n = s.length, f = n <= 10 ? 3 : n <= 20 ? 2 : n <= 30 ? 1.8 : n <= 50 ? 1.6 : n <= 70 ? 1.4 : 1.3, extra = Math.ceil(n * (f - 1));
    return s + " " + "Ẽxtrãwörd ".repeat(Math.ceil(extra / 10)).slice(0, Math.max(0, extra - 1)); };
  const padded = { _meta: { lang: "es", name: "español", dir: "ltr" }, strings: Object.fromEntries(Object.entries(S.en).map(([k, v]) => [k, typeof v === "string" ? (/[{<]/.test(v) ? v : pad(v)) : Object.fromEntries(["one", "many", "other"].map((c) => [c, v.other || v.one]))])) };
  const ctx = await browser.newContext({ viewport: { width: 320, height: 712 }, locale: "es" });
  await S.route(ctx);
  await ctx.route(/\/i18n\/es\.json$/, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(padded) }));
  const page = await ctx.newPage();
  await page.goto(S.screens.door, { waitUntil: "load" });
  await page.waitForFunction(() => document.documentElement.lang === "es", null, { timeout: 8000 }).catch(() => {});
  const cut = await page.evaluate(() => ({ wide: document.documentElement.scrollWidth - innerWidth,
    cut: [...document.querySelectorAll("button, label, h1, h2, summary, a")].filter((e) => e.offsetParent && !e.closest(".sr") && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== "visible").map((e) => e.tagName + " " + e.textContent.trim().slice(0, 20)).slice(0, 5),
    over: [...document.querySelectorAll("button, label, h1, h2")].filter((e) => { const r = e.getBoundingClientRect(); return e.offsetParent && (r.right > innerWidth + 1 || r.left < -1); }).map((e) => e.id || e.tagName).slice(0, 5) }));
  check("R5: the front door with every string padded by IBM's allowance fits at 320 px", cut.wide <= 0 && cut.cut.length === 0 && cut.over.length === 0, cut);
  await ctx.close();
}

// ---- R17: the stored choice beats the browser, an unknown language is English -----------------------------------------
for (const [screen, url] of SCREENS) {
  const stored = await open("ar-EG", url, { init: () => { try { localStorage.setItem("knos.lang", "fr"); } catch { /* none */ } }, expect: "fr" });
  await stored.page.waitForFunction(() => document.documentElement.lang === "fr", null, { timeout: 8000 }).catch(() => {});
  check(`R17 ${screen}: a stored choice of fr beats a browser in ar-EG`, await stored.page.evaluate(() => document.documentElement.lang) === "fr");
  await stored.ctx.close();
  const plain = await open("ar-EG", url);
  check(`R17 ${screen}: a browser in ar-EG with nothing stored gets Arabic`, await plain.page.evaluate(() => document.documentElement.lang) === "ar");
  await plain.ctx.close();
  const tw = await open("zh-TW", url, { expect: "zh-Hant" });   // L09: Chinese of Taiwan reads Traditional characters
  check(`R17 ${screen}: a browser in zh-TW gets Traditional Chinese (zh-Hant)`, await tw.page.evaluate(() => document.documentElement.lang) === "zh-Hant");
  await tw.ctx.close();
  const none = await open("xx", url, { expect: "en" });
  check(`R17 ${screen}: a language Knos does not ship gets English`, await none.page.evaluate(() => document.documentElement.lang) === "en");
  await none.ctx.close();
}

// ---- R13: the limit box reads every digit set ----------------------------------------------------------------------
{
  const { ctx, page } = await open("ar", S.screens.door);
  const got = await page.evaluate(() => ["١٫٤", "۱.۴", "१.४", "১.৪", "1,4", " 1.4 "].map((s) => KI.num(s)));
  check("R13: the limit box reads 1.4 in Arabic-Indic, Persian, Devanagari and Bengali digits and with a decimal comma", got.every((x) => x === "1.4"), got);
  await ctx.close();
}

// ---- H3 b: Listen in the result's fold, Speak on the question box ----------------------------------------------------
const SPEECH = () => {
  window.__said = [];
  class U { constructor(text) { this.text = text; this.lang = ""; } }
  window.SpeechSynthesisUtterance = U;
  Object.defineProperty(window, "speechSynthesis", { configurable: true, value: { speaking: false, cancel() { this.speaking = false; }, speak(u) { this.speaking = true; window.__said.push({ text: u.text, lang: u.lang }); } } });
  class R { start() { setTimeout(() => { this.onresult && this.onresult({ results: [[{ transcript: "Does HyperLogLog count visitors?" }]] }); this.onend && this.onend(); }, 50); } stop() { this.onend && this.onend(); } }
  window.SpeechRecognition = R; window.webkitSpeechRecognition = R;
};
const NO_SPEECH = () => { delete window.SpeechRecognition; delete window.webkitSpeechRecognition; delete window.speechSynthesis; delete window.SpeechSynthesisUtterance;
  Object.defineProperty(window, "webkitSpeechRecognition", { value: undefined }); Object.defineProperty(window, "SpeechRecognition", { value: undefined }); };
for (const lang of ["en", "ar", "hi", "zh-Hans"]) for (const screen of ["door", "result"]) {
  const { ctx, page } = await open(lang, S.screens[screen], { init: SPEECH });
  if (screen === "door") await pressRun(page);
  await page.evaluate(() => { document.querySelector("#how, main > details").open = true; });
  const t0 = await page.evaluate(() => new Promise((done) => { const b = document.getElementById("listen"), t = performance.now();
    const mo = new MutationObserver(() => { mo.disconnect(); done(performance.now() - t); }); mo.observe(b, { childList: true, characterData: true, subtree: true }); b.click(); setTimeout(() => done(9999), 1000); }));
  const said = await page.evaluate(() => ({ said: window.__said, about: document.getElementById("about").textContent.trim() }));
  const want = lang === "zh-Hans" ? "zh-CN" : lang;
  check(`H3 b ${lang} ${screen}: Listen reads the result sentence in the screen's language, a first change within 200 ms`, said.said.length === 1 && said.said[0].lang === want && said.said[0].text === said.about && t0 <= 200, [said, Math.round(t0)]);
  await ctx.close();
}
for (const lang of ["en", "fr"]) {
  const { ctx, page } = await open(lang, S.screens.door, { init: SPEECH });
  await page.focus("#list");   // L01: the one box; its microphone shows once the box has the focus (L08)
  const vis = await page.evaluate(() => !document.getElementById("speak").hidden);
  // every label the button shows from the press on, recorded as it changes: the stand-in's recognition ends 50 ms after it
  // starts, sooner than a read made after page.click returns (88 to 137 ms measured), so a single read could miss it
  await page.evaluate(() => { const b = document.getElementById("speak"); window.__labels = []; new MutationObserver(() => window.__labels.push(b.textContent)).observe(b, { childList: true, characterData: true, subtree: true }); });
  await page.click("#speak");
  await page.waitForFunction(() => document.getElementById("list").value !== "", null, { timeout: 3000 }).catch(() => {});
  await page.waitForFunction((idle) => document.getElementById("speak").textContent === idle, S.file(lang).strings["ask.speak"], { timeout: 3000 }).catch(() => {});
  const { filled, labels } = await page.evaluate(() => ({ filled: document.getElementById("list").value, labels: window.__labels }));
  check(`H3 b ${lang}: Speak shows in the one box, says it is listening once pressed, fills the box from the browser's speech recognition, then reads Speak again`,
    vis && filled === "Does HyperLogLog count visitors?" && labels[0] === S.file(lang).strings["ask.listening"] && labels[labels.length - 1] === S.file(lang).strings["ask.speak"], { vis, labels, filled });
  await ctx.close();
}
{
  const { ctx, page } = await open("en", S.screens.door, { init: NO_SPEECH });
  await pressRun(page);
  const hidden = await page.evaluate(() => ({ speak: document.getElementById("speak").hidden, listen: document.getElementById("listen").hidden }));
  check("H3 b: with no speech in the browser, Speak and Listen are not shown, and the tool still answers by taps alone (R28)", hidden.speak && hidden.listen, hidden);
  await ctx.close();
}

await browser.close(); S.close();
console.log(fails ? `${fails} failed` : "all passed");
process.exit(fails ? 1 : 0);
