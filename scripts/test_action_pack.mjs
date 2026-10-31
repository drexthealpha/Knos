// J3 test_action_pack, live: an Open card offers 2 downloads a founder uses next week, a pre-order page text naming the
// launch city and target, and a calendar file with the first milestone deadline and the refund date; on 3 Open cards
// (read with the app's Qloo-off switch, the cache only) both files download and name that card's city and dates.
//
//   node scripts/test_action_pack.mjs [result file]
import { appendFileSync } from "node:fs";

const APP = "https://knos.onrender.com";
const OUT = process.argv[2] || "";
const IDEAS = ["a jazz bar with live music", "a probiotic kombucha brand", "a solar powered music festival", "a gene editing therapy", "a recycled ocean plastic swimwear brand"];
const lines = [], fails = [];
const log = (s) => { console.log(s); lines.push(s); if (OUT) appendFileSync(OUT, s + "\n"); };
const ok = (c, what) => { log(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails.push(what); return c; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const again = async (f) => { try { return await f(); } catch { await sleep(20000); return await f(); } };

let n = 0;
for (const idea of IDEAS) {
  if (n === 3) break;
  const c = await again(async () => (await fetch(APP + "/api/check?qloo=off", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ idea, picked: true, qloo: "off" }) })).json());
  const t = c.terms || {};
  if ((c.decision || {}).verdict !== "OPEN" || !t.city) { log(`note ${idea}: ${(c.decision || {}).verdict}, launch city ${t.city || "none"}: no Open card with a city, skipped`); continue; }
  n++;
  const kinds = ((c.story || {}).downloads || []).map((d) => d.kind);
  const pre = await again(async () => (await fetch(`${APP}/api/card/preorder?hash=${c.hash}`)).text());
  const ics = await again(async () => (await fetch(`${APP}/api/card/refund.ics?hash=${c.hash}`)).text());
  const day = (ics.match(/DTSTART;VALUE=DATE:(\d{8})/) || [])[1] || "";
  const iso = day ? `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}` : "";
  const preOk = pre.includes(t.city) && pre.includes(`${t.target} pre-orders`) && !!iso && pre.includes(iso);
  const icsOk = /BEGIN:VCALENDAR/.test(ics) && /First milestone deadline/.test(ics) && /Refund date/.test(ics) && ics.includes(t.city) && (ics.match(/BEGIN:VEVENT/g) || []).length === 2;
  ok(kinds.includes("preorder") && kinds.includes("refund.ics") && preOk && icsOk,
    `${idea}: Open in ${t.city}, target ${t.target}; offers ${kinds.join(", ")}; pre-order text names the city ${pre.includes(t.city)}, the target ${pre.includes(`${t.target} pre-orders`)}, the date ${iso}; calendar: first milestone deadline and refund date ${icsOk}, ${iso}`);
}
ok(n === 3, `Open cards with a launch city checked: ${n} of 3`);
log(fails.length ? `FAIL test_action_pack: ${fails.length} of ${lines.length} checks failed; first: ${fails[0].slice(0, 160)}`
  : `PASS test_action_pack: 3 of 3 Open cards offer both downloads, each naming its city, target and dates`);
process.exit(fails.length ? 1 : 0);
