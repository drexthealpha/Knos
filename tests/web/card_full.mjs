// The demand check's card in full (web/brand/hero.js), in headless Chromium, on 3 SYNTHETIC reports shaped as
// apps/wanted check.py writes them: the room against the leader, the taste persona, the brand ladder
// and the recommendations are drawn from the report (no new call), each value names the Qloo call it came from, and the
// calls panel lists every call with its endpoint, key parameters, milliseconds and the part of the card it fed.
//   node tests/web/card_full.mjs
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromiumOrSkip } from "./overflow.mjs";

const here = dirname(fileURLToPath(import.meta.url)), web = join(here, "../../web");
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };

const call = (n, what, params) => ({ n, call: "GET /v2/insights", what, params, ms: 100 + n, cached: false });
function report(i) {
  const calls = [call(1, "search", { query: `idea ${i}`, take: 5 }), call(2, "who", { "filter.type": "urn:demographics" }),
    call(3, "launch cities", { "filter.type": "urn:entity:destination", take: 8 }), call(4, "taste persona", { "filter.type": "urn:tag", take: 8 }),
    call(5, "brand ladder", { "filter.type": "urn:entity:brand", take: 6 }), call(6, "recommendations", { "filter.type": "urn:entity:brand", take: 10 }),
    { n: 7, call: "GET /v2/analysis/compare", what: "versus", params: { "a.signal.interests.entities": "e1", "b.signal.interests.entities": "e0" }, ms: 90 }];
  return { hash: `${String(i).repeat(8)}`.padEnd(64, "0"), idea: `synthetic herbal drink ${i}`, label: "LIVE Qloo data (synthetic test)", stage: "full",
    decision: { verdict: "OPEN", reasons: ["synthetic"] }, who: { top_age: "25_to_29", top_gender: "female", src: 2 },
    matches: [{ id: "e0", name: `Leader ${i}` }, { id: "e1", name: `Match ${i}` }], leader: { id: "e0", name: `Leader ${i}` },
    cities: [{ name: `City ${i}`, lat: 40.7, lon: -74, src: 3, because: ["e1"] }],
    persona: [{ name: `Herbal Fans ${i}`, src: 4 }, { name: "Beet Salad", src: 4 }],
    ladder: [{ name: `Brand X${i}`, affinity: 0.91, src: 5 }, { name: `Brand Y${i}`, affinity: 0.82, src: 5 }],
    recommended: { items: [{ name: `Herbal Co ${i}` }, { name: "BforBank" }], src: 6 },
    versus: { leader: `Leader ${i}`, overlap: 0.4, whitespace: [`Room ${i}`, `Room ${i}b`], src: 7 },
    trend: { entity: `Leader ${i}`, direction: "flat", data_through: "2026-05-07", src: 1 }, calls };
}

const browser = await chromiumOrSkip();
{
  try {
    const page = await browser.newPage();
    const asked = [];
    await page.route("http://stub.test/**", async (route) => {
      const u = new URL(route.request().url());
      if (u.pathname === "/hero.js") return route.fulfill({ contentType: "text/javascript", body: readFileSync(join(web, "brand/hero.js"), "utf8") });
      if (u.pathname === "/api/check") {
        const body = JSON.parse(route.request().postData() || "{}");
        asked.push(body.idea);
        const i = Number(String(body.idea).split(" ").pop());
        return route.fulfill({ contentType: "application/json", body: JSON.stringify(report(i)) });
      }
      return route.fulfill({ contentType: "application/json", body: "{}" });
    });
    const hero = readFileSync(join(web, "brand/hero.html"), "utf8").replace(/\{API\}/g, "http://stub.test").replace(/\{APP\}/g, "http://stub.test/");
    await page.setContent(`<!doctype html><body>${hero}<script src="http://stub.test/hero.js"></script></body>`);
    for (const i of [1, 2, 3]) {
      await page.fill("#k-q", `synthetic herbal drink ${i}`);
      await page.click("#k-go");
      await page.waitForFunction((i) => document.querySelector("#k-card .k-card .k-kick")?.textContent.includes(`synthetic herbal drink ${i}`), i, { timeout: 15000 });
      const got = await page.evaluate(() => {
        const card = document.querySelector("#k-card .k-card");
        const parts = Object.fromEntries(["because", "whitespace", "persona", "ladder", "recommendations"].map((p) => {
          const s = card.querySelector(`[data-part="${p}"]`);
          return [p, s ? [...s.querySelectorAll("li")].map((li) => [[...li.childNodes].filter((n) => !n.classList?.contains("k-schip")).map((n) => n.textContent).join("").trim(), li.dataset.call,
            li.querySelector("a.k-val")?.getAttribute("href").endsWith(`#call-${li.dataset.call}`)]) : null];
        }));
        const panel = card.querySelector('[data-part="calls"]');
        const rows = panel ? [...panel.querySelectorAll("li")].map((li) => li.textContent.replace(/\s+/g, " ").trim()) : [];
        return { parts, rows, summary: panel?.querySelector("summary")?.firstChild?.textContent.trim(), trend: card.querySelector('[data-part="trend"]')?.textContent.trim(),
          city: card.querySelector(".k-cities li [data-because]")?.textContent.trim() };
      });
      const want = { because: null, whitespace: [[`Room ${i}`, "7", true], [`Room ${i}b`, "7", true]],
        persona: [[`Herbal Fans ${i}`, "4", true]], ladder: [[`Brand X${i} 0.91`, "5", true], [`Brand Y${i} 0.82`, "5", true]],
        recommendations: [[`Herbal Co ${i}`, "6", true]] };
      for (const [p, rows] of Object.entries(want))
        ok(`report ${i}: "${p}" renders each value, linked to the call it came from in the trace`, JSON.stringify(got.parts[p]) === JSON.stringify(rows), got.parts[p]);
      const fed = { 3: ["launch cities", "because"], 4: ["taste persona"], 5: ["brand ladder"], 6: ["next to it"], 7: ["room against the leader"], 2: ["who wants it"] };
      ok(`report ${i}: the calls panel lists 7 calls, each live or recorded`, got.summary === "Qloo calls (7)" && got.rows.length === 7 && got.rows.every((r) => / \u00b7 (live|recorded( \d{4}-\d\d-\d\d)?)( \u00b7 |$)/.test(r)), got.summary);
      // the card lists launch cities only from the launch terms (apps/wanted metros.launch_terms); this report has none
      ok(`report ${i}: the trend line, and no launch-city list without launch terms`, got.trend === `Trend of Leader ${i}: flat, data through 2026-05-07 source` && got.city === undefined, [got.trend, got.city]);
      await page.click("#k-card [data-without]");
      const off = await page.evaluate(() => ({ v: document.querySelector("#k-card [data-without-qloo]")?.dataset.verdict, cities: document.querySelectorAll("#k-card .k-cities li").length,
        said: document.querySelector("#k-card [data-without-qloo] .k-why")?.textContent }));
      ok(`report ${i}: Without Qloo: no verdict, no launch city, no target, pre-orders closed`, off.v === "CANNOT_DECIDE" && off.cities === 0 && /no launch city and no pre-order target/.test(off.said || ""), off);
      await page.click("#k-card [data-without]");
      ok(`report ${i}: switched back, the card is whole again`, await page.evaluate(() => !!document.querySelector('#k-card [data-part="persona"]')));
      for (const [n, names] of Object.entries(fed)) {
        const row = got.rows.find((r) => r.startsWith(`#${n} `)) || "";
        const ms = n === "7" ? "90 ms" : `${100 + Number(n)} ms`, key = n === "7" ? "" : "filter.type=";
        ok(`report ${i}: call #${n} shows its endpoint, key parameters, milliseconds and the parts it fed`,
          /GET \/v2\//.test(row) && row.includes(key) && row.includes(ms) && names.every((x) => row.includes(x)), row);
      }
    }
    ok("the card asked the app for nothing but the 3 checks (no new Qloo call)", asked.length === 3, asked);
  } finally {
    await browser.close();
  }
}
console.log(failed ? `card_full: ${failed} check(s) failed` : "card_full: all checks passed");
process.exit(failed ? 1 : 0);
