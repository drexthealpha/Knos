// test_ai_readable, live: the front door reads with no JavaScript. Each of the 8 public pages and the 6 result pages
// carries its main text in the served HTML and exactly one H1; the 8 pages head their sections as questions with text
// right under each; every JSON-LD block parses and uses only schema.org types and properties (checked against the
// schema.org vocabulary file); the front door's Offer is the pricing page's own line; the sitemap lists every page with a
// date; llms.txt opens with the one line and links the evidence; the Pages run of this commit sent IndexNow its pages
// and IndexNow answered 200 or 202.
//   node scripts/test_ai_readable.mjs <commit sha under test>
import { execFileSync } from "node:child_process";
import { appendFileSync } from "node:fs";

const [SHA] = process.argv.slice(2);
const OUT = `${process.env.KNOS_WORLD || `${process.env.KNOS_PRIVATE_DIR || "."}/v0328/world`}/test_ai_readable.txt`;
const SITE = process.env.KNOS_SITE || "https://drexthealpha.github.io/Knos/";
const ONE = "Knos carries research across the valley of death: see who wants it and where, then get paid only on proof.";
const PAGES = ["", "proof/", "forecasts/", "status/", "demo/", "how-we-test.html", "pricing.html", "docs/"];
const lines = []; let fails = 0;
const ok = (c, what) => { lines.push(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails++; };
const get = async (u) => { const r = await fetch(u + (u.includes("?") ? "&" : "?") + "t=" + Date.now()); return [r.status, await r.text()]; };
const text = (h) => h.replace(/<(script|style|template)\b[\s\S]*?<\/\1>/g, " ").replace(/<[^>]+>/g, " ").replace(/&[a-z#0-9]+;/g, " ").replace(/\s+/g, " ").trim();
const gh = (...a) => execFileSync("gh", a, { encoding: "utf8", maxBuffer: 1 << 26 });

const dep = JSON.parse(gh("api", "repos/drexthealpha/Knos/deployments?environment=github-pages&per_page=1"))[0];
ok(dep && dep.sha === SHA, `Pages deployed at ${dep && dep.sha.slice(0, 7)} (commit under test ${SHA.slice(0, 7)})`);
// the schema.org vocabulary: every type and property name it defines
const vocab = JSON.parse((await get("https://schema.org/version/latest/schemaorg-current-https.jsonld"))[1]);
const terms = new Set((vocab["@graph"] || []).map((x) => String(x["@id"] || "").replace(/^schema:/, "")));
ok(terms.size > 2000, `schema.org vocabulary read: ${terms.size} terms`);
const lds = [];
const checkLd = (where, node) => {
  const bad = [];
  const walk = (o) => { if (Array.isArray(o)) return o.forEach(walk); if (!o || typeof o !== "object") return;
    for (const [k, v] of Object.entries(o)) { if (k === "@type") { for (const t of [].concat(v)) if (!terms.has(t)) bad.push(`type ${t}`); }
      else if (!k.startsWith("@") && !terms.has(k)) bad.push(`property ${k}`); walk(v); } };
  walk(node);
  return bad;
};
// 1. the 8 pages and the 6 result pages, as served
const results = JSON.parse((await get(`${SITE}results/index.json`))[1]).results || [];
let readable = 0, oneH1 = 0, asked = 0, sections = 0;
for (const path of [...PAGES, ...results.map((r) => r.path)]) {
  const [code, h] = await get(SITE + path);
  const body = h.slice(h.indexOf("<body"));
  const words = text(body).split(" ").length, h1 = (body.match(/<h1\b/g) || []).length;
  readable += code === 200 && words >= 60; oneH1 += h1 === 1;
  ok(code === 200 && words >= 60 && h1 === 1, `/${path}: ${code}, ${words} words in the served HTML, ${h1} H1`);
  for (const m of h.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)) {
    let doc = null;
    try { doc = JSON.parse(m[1]); } catch { doc = null; }
    const bad = doc ? checkLd(path, doc) : ["not JSON"];
    lds.push({ path, doc, bad });
  }
  if (PAGES.includes(path)) {
    // each section: a question, and text under it before the next heading
    const clean = body.replace(/<(script|style|template)\b[\s\S]*?<\/\1>/g, " ");
    const heads = [...clean.matchAll(/<h2\b[^>]*>([\s\S]*?)<\/h2>([\s\S]*?)(?=<h2\b|<\/main>|$)/g)].map((x) => [text(x[1]), text(x[2]).split(/(?<=[.?!])\s/)[0] || ""]);
    const q = heads.filter(([t, first]) => /\?$/.test(t) && first.length >= 8);
    sections += heads.length; asked += q.length;
    ok(heads.length > 0 && q.length === heads.length, `/${path}: ${q.length} of ${heads.length} sections headed as a question with text under it${q.length < heads.length ? ` (${heads.filter((x) => !q.includes(x)).map((x) => x[0]).slice(0, 3).join(" | ")})` : ""}`);
  }
}
// 2. JSON-LD: every block a schema.org document; the front door's application, its Offer and the Organization; breadcrumbs inside
const badLd = lds.filter((x) => !x.doc || x.bad.length);
ok(lds.length >= PAGES.length + results.length - 1 && badLd.length === 0, `JSON-LD: ${lds.length} blocks parsed, ${badLd.length} with a term schema.org does not define${badLd.length ? ` (${badLd[0].path}: ${badLd[0].bad.slice(0, 3).join(", ")})` : ""}`);
const front = (lds.find((x) => x.path === "" && x.doc && x.doc["@graph"]) || {}).doc || {};
const app = (front["@graph"] || []).find((x) => x["@type"] === "SoftwareApplication") || {}, org = (front["@graph"] || []).find((x) => x["@type"] === "Organization") || {};
ok(app.description === ONE && org.name === "Knos" && (org.sameAs || []).includes("https://github.com/drexthealpha/Knos"), "the front door: SoftwareApplication with the one line, Organization with the repository");
const [, pricing] = await get(`${SITE}pricing.html`);
const firstLine = text((pricing.match(/<h1[^>]*>[\s\S]*?<\/h1>\s*<p[^>]*>([\s\S]*?)<\/p>/) || [])[1] || "");
const offer = app.offers || {};
ok(offer["@type"] === "Offer" && offer.price === "0" && offer.description === firstLine && firstLine.length > 10, `the Offer is the pricing page's line: "${offer.description}"`);
const crumbs = lds.filter((x) => x.path !== "" && x.doc && x.doc["@type"] === "BreadcrumbList").map((x) => x.path);
ok(PAGES.slice(1).every((p) => crumbs.includes(p)) && results.every((r) => crumbs.includes(r.path)), `BreadcrumbList on ${crumbs.length} inner pages`);
// 3. the sitemap, as served: every page, each with a date
const [, map] = await get(`${SITE}sitemap.xml`);
const urls = [...map.matchAll(/<url><loc>([^<]+)<\/loc><lastmod>([^<]+)<\/lastmod><\/url>/g)].map((m) => [m[1], m[2]]);
const want = [...PAGES, ...results.map((r) => r.path)].map((p) => SITE + p);
ok(want.every((u) => urls.some(([l]) => l === u)) && urls.every(([, d]) => /^\d{4}-\d{2}-\d{2}$/.test(d)), `sitemap.xml: ${urls.length} pages, every one listed with its date (${new Set(urls.map(([, d]) => d)).size} different dates)`);
// 4. llms.txt
const [, llms] = await get(`${SITE}llms.txt`);
const links = ["proof/", "forecasts/", "status/"].map((p) => SITE + p).concat(["https://knos.onrender.com/mcp"], results.map((r) => SITE + r.path));
ok(llms.split("\n")[2] === `> ${ONE}` && links.every((l) => llms.includes(`(${l})`)) && !/hackathon|judge|CHAMPION|escrow/i.test(llms), `llms.txt: opens with the one line, links ${links.filter((l) => llms.includes(`(${l})`)).length} of ${links.length} evidence pages`);
// 5. IndexNow: the key file served, and the push-triggered Pages run of this commit
const [kc, key] = await get(`${SITE}indexnow.txt`);
ok(kc === 200 && /^[0-9a-f]{32}$/.test(key.trim()), `the IndexNow key file is served: ${kc}`);
const run = JSON.parse(gh("run", "list", "--workflow", "network.yml", "--commit", SHA, "--event", "push", "--json", "databaseId,conclusion", "--limit", "1"))[0];
let said = "";
if (run) { try { said = (gh("run", "view", String(run.databaseId), "--log").split("\n").find((l) => /indexnow: \d{3} for/.test(l)) || "").replace(/^.*indexnow: /, "indexnow: "); } catch { said = ""; } }
ok(/^indexnow: (200|202) for \d+ pages/.test(said), `the Pages run ${run ? run.databaseId : "(none)"} sent IndexNow: "${said.slice(0, 140)}"`);
lines.push(fails ? `FAIL test_ai_readable: ${fails} check(s) failed`
  : `PASS test_ai_readable: ${readable} pages readable with no JavaScript, ${oneH1} with one H1; ${asked} of ${sections} sections asked as questions; ${lds.length} JSON-LD blocks valid; the Offer matches pricing; ${urls.length} pages in the sitemap; IndexNow ${said.slice(10, 13)}`);
console.log(lines.join("\n"));
appendFileSync(OUT, lines.join("\n") + "\n");
process.exit(fails ? 1 : 0);
