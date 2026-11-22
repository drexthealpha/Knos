// node tests/web/section12.mjs <site dir>
//
// Round 13 H3 g (v0328 research ROUND13-ITEMS.md): the implementation tests of section 12 of
// LAWS\MISSION\PACKAGE\Knos_Plain_Language_Product_Spec_2026-11-15.md, each on the tool screen (/t/limit-check/), the
// result screen (/r/<id>/) and the price screen (/Knos/pricing/, with the pay screen the tool shows once the free runs
// are used up), as built locally (tests/web/law_lib.mjs: the site build and the app, run here):
//   1 every control produces a visible result (a DOM change, focus, a file chooser or a new page within 3 s of the press)
//   2 text a person types is never run as markup (a table whose header is HTML, run, then its result page opened)
//   3 an error keeps what the person entered (a limit that is not a number, no answer from the server, a timeout,
//     a test payment that fails)
//   4 going back keeps the request (typed and not sent; sent; from the pay screen)
//   5 pressing "Pay with test money" twice records one test payment (and "Yes, record it" twice)
//   6 the layout holds at 320 px wide and at 200% zoom (a 1280 px window zoomed to 200%, and text at 200% at 320 px)
//   7 light and dark themes pass the contrast rule of LAWS\UX\U5.md R1: WCAG 2.2 1.4.3, 4.5:1 for text (3:1 for large
//     text), measured by axe-core's rule color-contrast, on each screen and on the result and pay states
import { setup, pressAll, words, ownForm, toPay, settled, isResult, OWN_TABLE } from "./law_lib.mjs";

const T_START = Date.now();
const env = await setup(process.argv[2]);
let fails = 0, passes = 0, skipped = 0;
const check = (name, ok, detail) => { if (ok) { passes++; console.log("ok  ", name, detail === undefined ? "" : "| " + detail); } else { fails++; console.error("FAIL", name, detail === undefined ? "" : "| " + detail); } };
const THREE = ["tool", "result", "price"];
const TABLE = "cycle,reading\n1,3.2\n2,3.1\n3,2.9\n4,2.7";
// ---- 1 every control produces a visible result ---------------------------------------------------------------------------
{
  const list = await pressAll(env, THREE, { w: 390, h: 844 });
  for (const s of THREE) {
    const mine = list.filter((x) => x.screen === s), pressed = mine.filter((x) => !x.skipped), none = pressed.filter((x) => !(x.ms < Infinity));
    check(`1 every control produces a visible result: ${s} screen`, pressed.length > 0 && none.length === 0, `${pressed.length} pressed, ${mine.length - pressed.length} links to other sites not pressed; no visible result: ${none.length ? none.map((x) => `${x.name} (${x.how})`).join("; ") : "none"}`);
  }
  // the pay screen's own controls
  const p = await env.open("tool"); await ownForm(p, "tool");
  const at = await toPay(p);
  const step = async (label) => { const before = await p.evaluate(() => document.body.innerHTML.length + "|" + (document.getElementById("pay") || {}).innerHTML); await p.click(`button:has-text('${label}')`, { timeout: 3000 }).catch(() => {}); await p.waitForTimeout(400); const after = await p.evaluate(() => document.body.innerHTML.length + "|" + (document.getElementById("pay") || {}).innerHTML); return before !== after; };
  const a = at ? await step("Cancel") : false;
  let b = false, c = false;
  if (at) { await p.click("#go"); await settled(p); b = await step("Pay with test money"); c = await step("Yes, record it"); }
  check("1 every control produces a visible result: the pay screen (Cancel, Pay with test money, Yes, record it)", at && a && b && c, at ? `Cancel ${a}, Pay with test money ${b}, Yes, record it ${c}` : "the pay screen did not appear after the free runs");
  await p.context().close();
}

// ---- 2 text a person types is never run as markup ----------------------------------------------------------------------
{
  // a column named with markup and a cell of markup that is not a number (that row is skipped): the run must give a result
  const HEAD = "<img src=x onerror=window.__xss=1>", CELL = "<b id=xssb>b</b>";
  for (const s of ["tool", "result"]) {
    const p = await env.open(s); await ownForm(p, s);
    const before = new URL(p.url()).pathname;
    await p.fill("#list", `cycle,${HEAD}\n1,3\n2,${CELL}\n3,1`); await p.waitForTimeout(100);
    await p.evaluate(() => { const sel = document.getElementById("col"); if (sel.options.length) sel.value = sel.options[sel.options.length - 1].value; });
    await p.fill("#limit", "2"); await p.click("#go"); await settled(p); await p.waitForTimeout(300);
    const here = await p.evaluate(() => ({ ran: window.__xss || 0, el: document.querySelectorAll("#xssb, img[src='x']").length, out: (document.getElementById("out") || {}).innerText || "", col: (document.getElementById("col") || {}).value }));
    const now = new URL(p.url()).pathname, link = now.startsWith("/r/") && now !== before ? p.url() : null;
    let there = { ran: 0, el: 0, shown: false };
    if (link) { await p.goto(link); await p.waitForTimeout(500); there = await p.evaluate((h) => ({ ran: window.__xss || 0, el: document.querySelectorAll("#xssb, img[src='x']").length, shown: (document.getElementById("list").value + ((document.querySelector("#k-input pre") || {}).textContent || "")).includes(h) }), HEAD); }
    await p.context().close();
    const result = /^(Failed at row |Passed: all )/.test(here.out.trim());
    check(`2 typed text is never run as markup: ${s} screen`, result && here.ran === 0 && here.el === 0 && !!link && there.ran === 0 && there.el === 0 && there.shown, `the run: ${result ? "a result" : "no result"} ("${here.out.slice(0, 70).replace(/\n/g, " ")}"); on the screen: ran ${here.ran}, elements made ${here.el}; its own result page ${link ? `ran ${there.ran}, elements made ${there.el}, the markup shown as text ${there.shown}` : "not reached"}`);
  }
  // the price screen's one place to type is the tool's box (every screen has its main input: UX/U4.md lines 87 and 98);
  // markup typed there and sent on to the front door's tool runs nowhere and stays text in the box
  const p = await env.open("price"); const inputs = await p.evaluate(() => document.querySelectorAll("input:not([type=hidden]), textarea, [contenteditable]").length);
  await p.fill("#list", `cycle,${HEAD}\n1,3`); await Promise.all([p.waitForNavigation({ waitUntil: "load" }).catch(() => {}), p.click("#try")]); await p.waitForTimeout(300);
  const door = await p.evaluate((h) => ({ ran: window.__xss || 0, el: document.querySelectorAll("img[src='x']").length, kept: (document.getElementById("list") || {}).value === `cycle,${h}\n1,3` }), HEAD); await p.context().close();
  check("2 typed text is never run as markup: price screen", inputs === 1 && door.ran === 0 && door.el === 0 && door.kept, `${inputs} place to type on the price screen (the tool's box); sent on to the front door: run ${door.ran}, markup elements ${door.el}, kept as text ${door.kept}`);
}

// ---- 3 an error keeps what the person entered ---------------------------------------------------------------------------
{
  for (const s of ["tool", "result"]) {
    const out = []; let ok = true;
    for (const [name, prep] of [["a limit that is not a number", (c) => { c.law.fail = null; }], ["no answer from the server", (c) => { c.law.fail = "down"; }], ["a timeout", (c) => { c.law.fail = "408"; }]]) {
      const p = await env.open(s); await ownForm(p, s);
      await p.fill("#list", TABLE); await p.waitForTimeout(50); await p.selectOption("#col", "reading").catch(() => {}); const lim = name.startsWith("a limit") ? "two" : "2"; await p.fill("#limit", lim);
      prep(p.context()); await p.click("#go"); await settled(p); await p.waitForTimeout(300);
      const r = await p.evaluate(() => ({ box: document.getElementById("list").value, limit: document.getElementById("limit").value, col: (document.getElementById("col") || {}).value, msg: ((document.querySelector("[role=alert]") || {}).textContent || "").trim() }));
      await p.context().close();
      const kept = r.box === TABLE && r.limit === lim && r.col === "reading" && !!r.msg; ok = ok && kept; out.push(`${name}: table ${r.box === TABLE ? "kept" : "lost"}, limit ${r.limit === lim ? "kept" : "lost"}, column ${r.col === "reading" ? "kept" : r.col}, message ${r.msg ? `${words(r.msg)} words` : "none"}`);
    }
    check(`3 an error keeps what the person entered: ${s} screen`, ok, out.join("; "));
  }
  const p = await env.open("tool"); await ownForm(p, "tool"); const at = await toPay(p);
  let r = null;
  if (at) { p.context().law.payFail = true; await p.click("button:has-text('Pay with test money')"); await p.click("button:has-text('Yes, record it')"); await p.waitForTimeout(800);
    r = await p.evaluate(() => ({ still: !document.getElementById("pay").hidden, msg: ((document.querySelector("#pay [role=alert]") || {}).textContent || "").trim(), retry: [...document.querySelectorAll("#pay button")].some((b) => /try again/i.test(b.textContent)) })); }
  await p.context().close();
  check("3 an error keeps what the person entered: price (pay) screen, a test payment that fails", !!r && r.still && !!r.msg && r.retry, r ? `pay screen kept ${r.still}, message "${r.msg.slice(0, 60)}", Try again ${r.retry}` : "the pay screen did not appear");
}

// ---- 4 going back keeps the request -------------------------------------------------------------------------------------
{
  for (const s of ["tool", "result"]) {
    const out = []; let ok = true;
    for (const sent of [false, true]) {
      const p = await env.open(s); await ownForm(p, s);
      await p.fill("#list", TABLE); await p.waitForTimeout(50); await p.selectOption("#col", "reading").catch(() => {}); await p.selectOption("#rule", "below"); await p.fill("#limit", "3.5");
      if (sent) { await p.click("#go"); await settled(p); await p.waitForTimeout(200); }
      await p.goto(env.URLS.price); await p.goBack({ waitUntil: "load" }); await p.waitForTimeout(500);
      const r = await p.evaluate(() => ({ box: document.getElementById("list").value, limit: document.getElementById("limit").value, rule: document.getElementById("rule").value, col: (document.getElementById("col") || {}).value || document.getElementById("colname").textContent }));
      await p.context().close();
      const kept = r.box.replace(/\r\n/g, "\n").trim() === TABLE && r.limit === "3.5" && r.rule === "below" && r.col === "reading"; ok = ok && kept;
      out.push(`${sent ? "sent" : "typed, not sent"}: table ${r.box.trim() === TABLE ? "kept" : "lost"}, rule ${r.rule}, limit "${r.limit}", column ${r.col}`);
    }
    check(`4 going back keeps the request: ${s} screen`, ok, out.join("; "));
  }
  const p = await env.open("tool"); await ownForm(p, "tool"); const at = await toPay(p); let r = null;
  if (at) { const box = await p.inputValue("#list"); await p.goto(env.URLS.price); await p.goBack({ waitUntil: "load" }); await p.waitForTimeout(500); r = await p.evaluate((box) => ({ box: document.getElementById("list").value === box, pay: !document.getElementById("pay").hidden }), box); }
  await p.context().close();
  check("4 going back keeps the request: price (pay) screen", !!r && r.box, r ? `the file from before the pay screen ${r.box ? "kept" : "lost"}; pay screen shown again ${r.pay}` : "the pay screen did not appear");
}

// ---- 5 "Pay with test money" twice records one test payment --------------------------------------------------------------
{
  const p = await env.open("tool"); await ownForm(p, "tool"); const at = await toPay(p);
  const posts = []; p.on("request", (q) => { if (q.method() === "POST" && new URL(q.url()).pathname === "/api/pay") posts.push(q.postData()); });
  let left = null, said = null;
  if (at) {
    await p.evaluate(() => { const b = [...document.querySelectorAll("#pay button")].find((x) => x.textContent.trim() === "Pay with test money"); b.click(); b.click(); });
    await p.waitForTimeout(200);
    await p.evaluate(() => { const b = [...document.querySelectorAll("#pay button")].find((x) => x.textContent.trim() === "Yes, record it"); if (b) { b.click(); b.click(); } });
    await p.waitForFunction(() => document.getElementById("pay").hidden, null, { timeout: 10000 }).catch(() => {});
    said = await p.evaluate(() => (document.getElementById("out") || {}).innerText || "");
    await p.fill("#list", TABLE + "\n9,2.5"); await p.selectOption("#col", "reading").catch(() => {}); await p.fill("#limit", "2"); await p.click("#go"); await settled(p);
    left = await p.evaluate(() => { const m = (document.getElementById("out").innerText.match(/(\d+) runs? left/) || [])[1]; return m ? Number(m) : null; });
  }
  await p.context().close();
  const presses = new Set(posts.map((b) => { try { return JSON.parse(b).press; } catch { return b; } }));
  check("5 pressing \"Pay with test money\" twice (and \"Yes, record it\" twice) records one test payment", at && left === 19 && presses.size === 1,
    at ? `pay requests ${posts.length} with ${presses.size} press id(s); after it "${(said || "").trim().slice(0, 30)}", and after one more run ${left} runs left (one payment of 20 leaves 19)` : "the pay screen did not appear");
  // the same press sent twice to the server: recorded once
  const b = "law" + Date.now().toString(16).padEnd(21, "0").slice(0, 21);
  const send = () => fetch(env.ORIGIN + "/api/pay", { method: "POST", headers: { "content-type": "application/json", "x-knos-test": "1" }, body: JSON.stringify({ browser: b, press: "press-law-000001", test: true }) }).then((r) => r.json());
  const x = await send(), y = await send();
  const run = await env.runApi({ table: TABLE, column: "reading", rule: "above", limit: 2, mode: "own", browser: b });
  check("5 the same test payment sent twice to the server is recorded once", x.runs_left === y.runs_left && run.status === 200, `answers ${JSON.stringify(x)} and ${JSON.stringify(y)}; the next run: ${run.status} ${run.body.runs_left ?? JSON.stringify(run.body).slice(0, 80)} runs left`);
  const p2 = await env.open("price"); const pay = await p2.evaluate(() => [...document.querySelectorAll("button")].filter((b) => /pay/i.test(b.textContent)).length); await p2.context().close();
  check("5 the price screen has no pay control of its own (the pay screen above is where a test payment is made)", pay === 0, `${pay} pay buttons on /pricing/`);
}

// ---- 6 the layout holds at 320 px and at 200% zoom ---------------------------------------------------------------------
{
  const LAYOUT = () => { const W = innerWidth; const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden"; };
    const out = [...document.querySelectorAll("body *")].filter((e) => vis(e) && getComputedStyle(e).position !== "fixed" && (e.getBoundingClientRect().right > W + 1 || e.getBoundingClientRect().left < -1)).map((e) => e.tagName.toLowerCase() + (e.id ? "#" + e.id : ""));
    const clip = [...document.querySelectorAll("body *")].filter((e) => { if (!vis(e) || e.tagName === "TEXTAREA" || !e.textContent.trim()) return false; const cs = getComputedStyle(e); return ((cs.overflowX === "hidden" || cs.overflowX === "clip") && e.scrollWidth > e.clientWidth + 1) || ((cs.overflowY === "hidden" || cs.overflowY === "clip") && e.scrollHeight > e.clientHeight + 1); }).map((e) => e.tagName.toLowerCase() + (e.id ? "#" + e.id : ""));
    return { scroll: document.documentElement.scrollWidth, W, out: out.slice(0, 4), clip: clip.slice(0, 4) }; };
  const modes = [["320 px", { w: 320, h: 712 }], ["200% zoom of a 1280 px window", { w: 640, h: 400, dsf: 2 }], ["text at 200% at 320 px", { w: 320, h: 712, fontScale: 2 }]];
  for (const s of THREE) {
    const out = []; let ok = true;
    for (const [name, o] of modes) {
      const p = await env.open(s, o);
      if (s !== "price") { await p.click("#go").catch(() => {}); await isResult(p); }
      const r = await p.evaluate(LAYOUT); await p.context().close();
      const fine = r.scroll <= r.W && r.out.length === 0 && r.clip.length === 0; ok = ok && fine;
      out.push(`${name}: width ${r.scroll}/${r.W}${r.out.length ? `, past the edge ${r.out.join(",")}` : ""}${r.clip.length ? `, clipped ${r.clip.join(",")}` : ""}`);
    }
    check(`6 the layout holds at 320 px and at 200% zoom: ${s} screen${s === "price" ? "" : " (with a result)"}`, ok, out.join("; "));
  }
  const out = []; let ok = true;
  for (const [name, o] of modes) { const p = await env.open("tool", o); await ownForm(p, "tool"); const at = await toPay(p); const r = at ? await p.evaluate(LAYOUT) : null; await p.context().close(); const fine = !!r && r.scroll <= r.W && r.out.length === 0 && r.clip.length === 0; ok = ok && fine; out.push(`${name}: ${r ? `width ${r.scroll}/${r.W}${r.out.length ? `, past the edge ${r.out.join(",")}` : ""}${r.clip.length ? `, clipped ${r.clip.join(",")}` : ""}` : "pay screen not reached"}`); }
  check("6 the layout holds at 320 px and at 200% zoom: the pay screen", ok, out.join("; "));
}

// ---- 7 light and dark pass the contrast rule of LAWS\UX (U5 R1: WCAG 1.4.3, 4.5:1; axe color-contrast) -----------------
// axe-core missing: on a laptop (CI unset) the check is skipped and says so; in CI (the workflow installs axe-core@4.10.2
// on its npm line) a missing axe-core fails, as any other check does.
if (!env.hasAxe && !process.env.CI) { skipped++; console.log("SKIPPED 7 contrast in light and dark | not checked: axe-core missing (npm install axe-core@4.10.2)"); }
else if (!env.hasAxe) check("7 contrast (U5 R1, 4.5:1) in light and dark", false, "axe-core missing in CI (the workflow's npm line installs axe-core@4.10.2)");
else {
  const rule = { runOnly: { type: "rule", values: ["color-contrast"] } };
  const text = (r) => r.error ? r.error : r.violations.length ? r.violations.map((v) => `${v.id} x${v.n} (${v.at}; ${v.why})`).join("; ") : "0 violations";
  for (const s of THREE) for (const scheme of ["light", "dark"]) {
    const p = await env.open(s, { scheme }); const a = await env.axe(p, rule);
    let b = { violations: [] };
    if (s !== "price") { await p.click("#go").catch(() => {}); await isResult(p); b = await env.axe(p, rule); }
    await p.context().close();
    check(`7 contrast (U5 R1, 4.5:1) in ${scheme}: ${s} screen${s === "price" ? "" : " and its result"}`, !a.error && !b.error && a.violations.length === 0 && b.violations.length === 0, `as loaded: ${text(a)}${s === "price" ? "" : `; with a result: ${text(b)}`}`);
  }
  for (const scheme of ["light", "dark"]) {
    const p = await env.open("tool", { scheme }); await ownForm(p, "tool"); const at = await toPay(p); const a = at ? await env.axe(p, rule) : { error: "the pay screen did not appear" }; await p.context().close();
    check(`7 contrast (U5 R1, 4.5:1) in ${scheme}: the pay screen`, !a.error && a.violations.length === 0, text(a));
  }
}

await env.close();
const took = `elapsed ${Math.round((Date.now() - T_START) / 1000)} s (set-up included)`;
console.log(`section 12: ${fails ? `${fails} failed, ${passes} passed` : `all passed (${passes})`}${skipped ? `, ${skipped} not checked` : ""}; ${took}`);
process.exit(fails ? 1 : 0);
