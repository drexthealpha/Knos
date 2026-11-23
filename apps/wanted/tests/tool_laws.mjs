// node apps/wanted/tests/tool_laws.mjs
//
// The tool and result pages of the app (/t/limit-check/, /r/<id>/), run locally (tests/web/law_app.py), in Chromium at
// 360 x 800, for the laws of v0328 research IQ/PLAN.md that live on these pages:
//   L03 a failed press keeps what was typed, says what failed and where to fix it, offers Try again; HTML typed is text;
//       going back after a result restores the request
//   L07 the history stays in the browser (one key, read in try/catch), reopens on the next visit, no history request;
//       with storage blocked the page still works
//   L08 the microphone sits inside the box (the first screen keeps 3 controls); spoken words land in the box as text and
//       nothing is sent before the press; the verdict has a Listen control that calls speechSynthesis
//   L12 the pay box names the amount, the currency, who receives it, when, the undo rule, and a control that closes it
//   L17 delete from the server, and Guest reset empties every knos key
//   L18 offline: the notice names the kept copy and its time; a check pressed offline is sent once on reconnect
//   L21 every press shows a visible change: p75 printed, warn above 100 ms, fail above 200 ms
//   L23 after a result: the time question once, the streak (day 7 a milestone), a missed day's repair and bonus, and
//       no notification permission asked
// No `playwright` package (NODE_PATH) or no browser (KNOS_CHROME): prints SKIP and exits 0.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const skip = (why) => { console.log("SKIP " + why); process.exit(0); };
let pw;
try { pw = await import("playwright"); } catch {
  const paths = (process.env.NODE_PATH || "").split(delimiter).filter(Boolean);
  try { pw = createRequire(import.meta.url)(createRequire(import.meta.url).resolve("playwright", { paths })); } catch { skip("the playwright package is not installed"); }
}
const { chromium } = pw.default || pw;
let browser;
try { browser = await chromium.launch(process.env.KNOS_CHROME ? { executablePath: process.env.KNOS_CHROME } : {}); } catch (e) { skip("no Chromium: " + String(e.message).split("\n")[0]); }

const app = spawn(process.env.PYTHON || "python3", [join(ROOT, "tests", "web", "law_app.py")], { cwd: ROOT, stdio: ["pipe", "pipe", "pipe"] });
const port = await new Promise((ok, no) => { let buf = ""; app.stdout.on("data", (d) => { buf += d; const m = /port (\d+)/.exec(buf); if (m) ok(m[1]); }); app.on("exit", () => no(new Error("the app stopped"))); setTimeout(() => no(new Error("the app did not start")), 60000); });
const BASE = `http://127.0.0.1:${port}`, TOOL = `${BASE}/t/limit-check/?test=1`;
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "ok   " : "FAIL ") + name + (detail ? " | " + detail : "")); if (!ok) fails++; };
const page = async (opts = {}) => { const ctx = await browser.newContext({ viewport: { width: 360, height: 800 }, serviceWorkers: "block", ...opts }); const p = await ctx.newPage(); p.errors = []; p.on("pageerror", (e) => p.errors.push(String(e))); return p; };
const verdict = (p) => p.waitForSelector("#out [data-verdict]", { timeout: 15000 });
const OWN = "cycle,capacity_ah\n1,5\n2,6\n3,7";
const typeOwn = async (p, table = OWN, limit = "4") => {
  await p.click("#k-sample", { trial: true }).catch(() => {});
  await p.evaluate(([t, l]) => { const b = document.getElementById("list"); b.value = t; b.dispatchEvent(new Event("input")); document.getElementById("limit").value = l; }, [table, limit]);
};
try {
  // ---- L03 ------------------------------------------------------------------------------------------------------------
  for (const how of ["500", "timeout"]) {
    const p = await page();
    await p.goto(TOOL);
    await p.route("**/api/run", (r) => how === "500" ? r.fulfill({ status: 500, body: "{}", contentType: "application/json" }) : r.abort("timedout"));
    await typeOwn(p, "<b>x</b>,capacity_ah\n1,5");
    const first = await p.evaluate(() => new Promise((done) => { const o = document.getElementById("out"), t0 = performance.now();
      const mo = new MutationObserver(() => { mo.disconnect(); requestAnimationFrame(() => done(Math.round(performance.now() - t0))); });
      mo.observe(o, { subtree: true, childList: true, attributes: true, characterData: true }); document.getElementById("go").click(); setTimeout(() => done(9999), 3000); }));
    await p.waitForSelector("[data-where]", { timeout: 10000 });
    const r = await p.evaluate(() => ({ box: document.getElementById("list").value, where: !!document.querySelector("[data-where]"), retry: !!document.querySelector("[data-retry]"), b: document.querySelectorAll("#out b, main b").length }));
    check(`L03 ${how}: the typed text stays, what failed and where to fix it, Try again, HTML shown as text`, r.box.startsWith("<b>x</b>") && r.where && r.retry && r.b === 0, `visible change ${first} ms; box kept ${r.box.startsWith("<b>x</b>")}; retry ${r.retry}`);
    check(`L03 ${how}: a visible change within 200 ms of the press`, first <= 200, `${first} ms`);
    await p.context().close();
  }
  {
    const p = await page();
    await p.goto(TOOL); await typeOwn(p); await p.click("#go"); await verdict(p);
    await p.goto(`${BASE}/api/tools`); await p.goBack();
    await p.waitForTimeout(500);
    const box = await p.evaluate(() => document.getElementById("list").value + "|" + ((document.querySelector("#k-input pre") || {}).textContent || ""));
    check("L03 going back after a result restores the request", box.includes("1,5"), box.replace(/\n/g, " ").slice(0, 60));
    await p.context().close();
  }
  // ---- L07 and L17 ----------------------------------------------------------------------------------------------------
  {
    const p = await page(); const reqs = [];
    p.on("request", (r) => reqs.push(r.url()));
    await p.goto(TOOL); await typeOwn(p); await p.click("#go"); await verdict(p);
    const kept = await p.evaluate(() => { try { return JSON.parse(localStorage.getItem("knos.history") || "[]"); } catch (e) { return []; } });
    await p.goto(TOOL);
    await p.waitForSelector("[data-history] li a", { timeout: 5000 }).catch(() => {});
    const listed = await p.evaluate(() => [...document.querySelectorAll("[data-history] li a")].map((a) => a.getAttribute("href")));
    check("L07 the run is kept in this browser under one key and listed on the next visit", kept.length === 1 && kept[0].verdict && listed.length === 1 && listed[0] === kept[0].link, `${kept.length} kept; ${listed.length} listed`);
    check("L07 no history request reaches the server", !reqs.some((u) => /history/i.test(u)), `${reqs.length} requests`);
    await p.goto(kept[0].link + "?test=1");
    // the result's other actions sit in the fold How it works (U2 R4, U6 R44): open it first
    await p.waitForSelector("#k-extras [data-delete]", { state: "attached", timeout: 5000 });
    await p.click("details:has(#k-extras) > summary");
    await p.waitForSelector("[data-delete]", { timeout: 5000 });
    await p.click("[data-delete]");
    await p.waitForSelector("[data-deleted]", { timeout: 5000 });
    const gone = await p.request.get(kept[0].link);
    check("L17 Delete from the server removes the result (its page is then 404)", gone.status() === 404, `status ${gone.status()}`);
    await p.goto(TOOL); await p.click("[data-guest-reset]");
    const left = await p.evaluate(() => Object.keys(localStorage).filter((k) => /^knos/.test(k)).concat(Object.keys(sessionStorage).filter((k) => /^knos/.test(k))));
    check("L17 Guest reset empties every knos key", left.length === 0, left.join(", ") || "none left");
    await p.context().close();
  }
  {
    const p = await page();
    await p.addInitScript(() => { for (const s of ["localStorage", "sessionStorage"]) Object.defineProperty(window, s, { get() { throw new Error("blocked"); } }); });
    await p.goto(TOOL); await p.click("#go"); await verdict(p);
    check("L07 with storage blocked the page still works", p.errors.length === 0, p.errors.join("; ").slice(0, 120) || "no page errors");
    await p.context().close();
  }
  // ---- L08 ------------------------------------------------------------------------------------------------------------
  {
    const p = await page(); const runs = [];
    p.on("request", (r) => { if (r.url().endsWith("/api/run")) runs.push(1); });
    await p.addInitScript(() => {
      window.__spoke = 0;
      window.SpeechRecognition = class { start() { setTimeout(() => { this.onresult && this.onresult({ results: [[{ transcript: "check the sample" }]] }); this.onend && this.onend(); }, 50); } stop() {} };
      window.speechSynthesis.speak = () => { window.__spoke++; };
    });
    await p.goto(TOOL);
    const n = await p.evaluate(() => [...document.querySelectorAll("a[href], button, input:not([type=hidden]), textarea, select, summary")].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.top < 800 && r.bottom > 0; }).length);
    check("L08 the first screen still holds at most 3 controls", n <= 3, `${n} controls`);
    await p.focus("#list"); await p.click("#k-mic"); await p.waitForTimeout(300);
    const r = await p.evaluate(() => ({ box: document.getElementById("list").value, inBox: !!document.querySelector(".boxwrap #k-mic") }));
    check("L08 spoken words land in the box as editable text, nothing sent before the press", r.box.includes("check the sample") && r.inBox && runs.length === 0, `box "${r.box}"; requests ${runs.length}`);
    await p.goto(TOOL); await p.click("#go"); await verdict(p);
    await p.click("details:has(#k-extras) > summary"); await p.click("[data-listen]"); const spoke = await p.evaluate(() => window.__spoke);
    check("L08 the verdict has a Listen control that calls speechSynthesis", spoke === 1, `speak called ${spoke}`);
    await p.context().close();
  }
  // ---- L12 ------------------------------------------------------------------------------------------------------------
  {
    const p = await page();
    await p.goto(TOOL);
    for (let i = 0; i < 6; i++) { await typeOwn(p, OWN + "\n" + (4 + i) + ",9"); await p.click("#go"); await p.waitForFunction(() => !document.getElementById("pay").hidden || !!document.querySelector("#out [data-verdict]"), null, { timeout: 15000 }); if (await p.evaluate(() => !document.getElementById("pay").hidden)) break; await p.waitForTimeout(100); }
    const box = await p.evaluate(() => { const t = document.querySelector("#pay [data-terms]"); return { terms: t ? t.textContent : "", cancel: !!document.querySelector("#pay [data-cancel]") }; });
    check("L12 the pay box names amount, currency, receiver, timing, undo rule and a close control", /\$1/.test(box.terms) && /US dollars/.test(box.terms) && /Knos/.test(box.terms) && /as soon as you press Yes/.test(box.terms) && /Undo/.test(box.terms) && box.cancel, box.terms.slice(0, 80));
    await p.context().close();
  }
  // ---- L18 ------------------------------------------------------------------------------------------------------------
  {
    const p = await page(); const runs = [];
    p.on("request", (r) => { if (r.url().endsWith("/api/run")) runs.push(1); });
    await p.goto(TOOL);
    await p.context().setOffline(true);
    await p.waitForTimeout(200);
    const notice = await p.evaluate(() => { const o = document.getElementById("k-offline"); return o && !o.hidden ? o.textContent : ""; });
    await typeOwn(p); await p.click("#go");
    const waiting = await p.evaluate(() => !!document.querySelector("[data-pending]"));
    await p.context().setOffline(false);
    await verdict(p).catch(() => {});
    await p.waitForTimeout(500);
    check("L18 offline: the notice names the kept copy and its time", /kept at/.test(notice), notice);
    check("L18 a check pressed offline waits, then is sent once on reconnect", waiting && runs.length === 1, `waiting ${waiting}; requests after reconnect ${runs.length}`);
    await p.context().close();
  }
  // ---- L23 ------------------------------------------------------------------------------------------------------------
  {
    const p = await page(); let asked = 0, bonus = 0;
    await p.exposeFunction("__asked", () => { asked++; });
    await p.addInitScript(() => { if (window.Notification) window.Notification.requestPermission = () => { window.__asked(); return Promise.resolve("denied"); }; });
    p.on("request", (r) => { if (r.url().endsWith("/api/bonus")) bonus++; });
    await p.goto(TOOL); await typeOwn(p); await p.click("#go"); await verdict(p);
    const a = await p.evaluate(() => ({ q: !!document.querySelector("[data-remind]"), s: (document.querySelector("[data-streak]") || {}).dataset?.streak }));
    const day = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };
    await p.evaluate((y) => localStorage.setItem("knos.streak", JSON.stringify({ last: y, n: 6 })), day(1));
    await typeOwn(p); await p.click("#go"); await p.waitForFunction(() => (document.querySelector("[data-streak]") || {}).dataset?.streak === "7", null, { timeout: 15000 }).catch(() => {});
    const b = await p.evaluate(() => ({ s: (document.querySelector("[data-streak]") || {}).dataset?.streak, week: document.body.textContent.includes("Day 7"), q: !!document.querySelector("[data-remind]") }));
    await p.evaluate((y) => localStorage.setItem("knos.streak", JSON.stringify({ last: y, n: 4 })), day(3));
    await typeOwn(p); await p.click("#go"); await p.waitForSelector("[data-missed]", { timeout: 15000 }).catch(() => {});
    const missed = await p.evaluate(() => !!document.querySelector("[data-missed]") && !!document.querySelector("[data-repair]"));
    if (missed) { await p.click("[data-repair]"); await p.waitForTimeout(800); }
    const after = await p.evaluate(() => (document.querySelector("[data-streak]") || {}).dataset?.streak);
    check("L23 after a result: the time question and a streak of 1", a.q && a.s === "1", JSON.stringify(a));
    check("L23 the next day's run makes day 7, a milestone", b.s === "7" && b.week, JSON.stringify(b));
    check("L23 a missed day offers a repair and a return bonus", missed && bonus === 1 && after === "5", `repair ${missed}; bonus requests ${bonus}; streak after ${after}`);
    check("L23 no notification permission is asked", asked === 0, `${asked}`);
    await p.context().close();
  }
  // ---- L21 ------------------------------------------------------------------------------------------------------------
  {
    const times = [];
    for (const target of ["tool", "result"]) {
      const p = await page();
      await p.goto(TOOL);
      if (target === "result") { await p.click("#go"); await verdict(p); }
      const ids = await p.evaluate(() => [...document.querySelectorAll("button")].filter((b) => b.getBoundingClientRect().height > 0 && !b.disabled).map((b, i) => { b.dataset.pressId = String(i); return String(i); }));
      for (const id of ids) {
        const ms = await p.evaluate((id) => new Promise((done) => {
          const b = document.querySelector(`[data-press-id="${id}"]`); if (!b) return done(null);
          let t0 = 0; const mo = new MutationObserver(() => { mo.disconnect(); requestAnimationFrame(() => done(performance.now() - t0)); });
          mo.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
          setTimeout(() => { mo.disconnect(); done(null); }, 1500);
          t0 = performance.now(); b.click();
        }), id).catch(() => null);
        if (ms != null) times.push(ms);
      }
      await p.context().close();
    }
    times.sort((x, y) => x - y);
    const p75 = times.length ? times[Math.max(0, Math.ceil(0.75 * times.length) - 1)] : null;
    console.log(`L21 presses timed ${times.length}; p75 ${p75 == null ? "none" : p75.toFixed(1)} ms (target 64, warn 100)${p75 > 100 ? " WARN" : ""}`);
    check("L21 press to next paint: p75 at most 200 ms", p75 != null && p75 <= 200, `${p75 == null ? "none" : p75.toFixed(1)} ms over ${times.length} presses`);
  }
} finally {
  await browser.close();
  app.stdin.end(); app.kill();
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
