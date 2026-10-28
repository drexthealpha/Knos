// test_idea_page, live: /demo/ says above step 1 what Qloo sets; works the pre-order target through for the J3
// crossing's idea (idea, city, mean affinity, population, each linked) and gets the T its log recorded; shows the same
// idea without Qloo; says what this does not establish; gives 3 sourced numbers, each with a link that answers 200.
// Every element at 390 and 1280 px.
//   node scripts/test_idea_page.mjs <commit sha under test>
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";

const SHA = process.argv[2];
const WORLD = process.env.KNOS_WORLD || `${process.env.KNOS_PRIVATE_DIR || "."}/v0328/world`;
const OUT = `${WORLD}/test_idea_page.txt`;
const DEMO = "https://drexthealpha.github.io/Knos/try/";
const SENTENCE = "Qloo sets where a product launches and how many pre-orders prove demand, before any money is held.";
const lines = []; let fails = 0;
const ok = (c, what) => { lines.push(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails++; };

const dep = JSON.parse(execFileSync("gh", ["api", "repos/drexthealpha/Knos/deployments?environment=github-pages&per_page=1"], { encoding: "utf8" }))[0];
ok(dep && dep.sha === SHA, `Pages deployed at ${dep && dep.sha.slice(0, 7)} (commit under test ${SHA.slice(0, 7)})`);
const log = JSON.parse(readFileSync(`${WORLD}/crossing-J3.json`, "utf8")).terms;     // the J3 log: city, affinity, population, T

const browser = await chromium.launch();
let got = null;
try {
  for (const [w, h] of [[390, 844], [1280, 800]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    await page.goto(DEMO + "?t=" + Date.now(), { waitUntil: "load" });
    got = await page.evaluate(() => {
      const vis = (sel) => { const e = document.querySelector(sel); if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.right <= innerWidth + 1; };
      const lede = document.querySelector("#demo-qloo"), first = document.querySelector("#step-demand");
      return { lede: lede?.textContent.trim(), before: !!(lede && first && lede.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING),
        parts: ["#demo-qloo", "#demo-target", "#demo-without", "#demo-limits", "#demo-numbers"].map(vis),
        facts: [...document.querySelectorAll("#demo-target dt")].map((d) => [d.textContent.trim(), d.nextElementSibling?.textContent.trim(), !!d.nextElementSibling?.querySelector("a[href]")]),
        affinity: Number(document.querySelector("#demo-affinity")?.textContent), pop: Number((document.querySelector("#demo-pop")?.textContent || "").replace(/,/g, "")),
        t: Number(document.querySelector("#demo-t")?.textContent), without: document.querySelector("#demo-without")?.textContent || "",
        limits: document.querySelector("#demo-limits")?.textContent || "",
        nums: [...document.querySelectorAll("#demo-numbers li")].map((li) => ({ text: li.textContent.trim(), href: li.querySelector("a[href]")?.href || "" })),
        scroll: document.documentElement.scrollWidth <= innerWidth };
    });
    ok(got.lede === SENTENCE && got.before, `${w}px: the sentence above step 1`);
    ok(got.parts.every(Boolean) && got.scroll, `${w}px: sentence, worked target, without Qloo, limits and numbers all shown ${JSON.stringify(got.parts)}`);
    await page.screenshot({ path: `${WORLD}/test_idea_page_${w}.png`, fullPage: true });
    await page.close();
  }
} finally {
  await browser.close();
}
const names = got.facts.map((f) => f[0]);
ok(["Idea", "City", "Mean affinity", "Population"].every((n) => names.includes(n)) && got.facts.every((f) => f[2]), `inputs labelled and linked: ${names.join(", ")}`);
const t = Math.max(10, Math.round(got.pop / 100000 * got.affinity));
ok(got.affinity === log.affinity && got.pop === log.population && t === log.target && got.t === log.target,
  `the formula: max(10, round(${got.pop} / 100,000 x ${got.affinity})) = ${t}; the page says ${got.t}; the J3 log recorded ${log.target}`);
ok(/no launch city and no pre-order target, so pre-orders cannot open/.test(got.without), "the same idea without Qloo: no city, no target, pre-orders closed");
ok(/aggregate affinities/.test(got.limits) && /never a person's behaviour/.test(got.limits) && /What this does not establish/.test(got.limits), "What this does not establish: aggregate affinities, never a person's behaviour");
let good = 0;
for (const n of got.nums) {
  const r = await fetch(n.href, { redirect: "follow", headers: { "User-Agent": "Mozilla/5.0 (link check)" } }).catch(() => ({ status: 0 }));
  good += r.status === 200 && /\d/.test(n.text);
  lines.push(`${r.status === 200 ? "ok  " : "FAIL"} ${r.status} ${n.text.slice(0, 60)} (${n.href.slice(0, 60)})`);
}
ok(got.nums.length === 3 && good === 3, `3 sourced numbers, ${good} with a link that answers 200`);
lines.push(fails ? `FAIL test_idea_page: ${fails} check(s) failed` :
  `PASS test_idea_page: every element at 390 and 1280, T = ${t} as the J3 log recorded, 3 of 3 numbers linked`);
console.log(lines.join("\n"));
writeFileSync(OUT, lines.join("\n") + "\n");
process.exit(fails ? 1 : 0);
