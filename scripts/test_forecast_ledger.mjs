// test_forecast_ledger, live: the front door's /forecasts/ lists every recorded idea that has a recorded model answer with
// three forecasts (Knos with Qloo, the model alone, a placebo) and the date made; the plan's sha256 on the page is the
// sha256 of docs/reference/forecast_plan.md at the commit under test, and the plan was committed before the page.
//   node scripts/test_forecast_ledger.mjs <commit sha under test>
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const [SHA] = process.argv.slice(2);
const ROOT = fileURLToPath(new URL("..", import.meta.url));
const OUT = `${process.env.KNOS_WORLD || `${process.env.KNOS_PRIVATE_DIR || "."}/v0328/world`}/test_forecast_ledger.txt`;
const SITE = process.env.KNOS_SITE || "https://drexthealpha.github.io/Knos/";
const IDEAS = 7;
const lines = []; let fails = 0;
const ok = (c, what) => { lines.push(`${c ? "ok  " : "FAIL"} ${what}`); if (!c) fails++; };
const git = (...a) => execFileSync("git", ["-C", ROOT, ...a], { encoding: "utf8", maxBuffer: 1 << 26 });

const dep = JSON.parse(execFileSync("gh", ["api", "repos/drexthealpha/Knos/deployments?environment=github-pages&per_page=1"], { encoding: "utf8" }))[0];
ok(dep && dep.sha === SHA, `Pages deployed at ${dep && dep.sha.slice(0, 7)} (commit under test ${SHA.slice(0, 7)})`);
const html = await (await fetch(`${SITE}forecasts/?t=${Date.now()}`)).text();
const strip = (s) => s.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&#x27;|&#39;/g, "'").trim();
const rows = [...html.matchAll(/<tr data-idea="[^"]*">([\s\S]*?)<\/tr>/g)].map((m) => [...m[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((c) => strip(c[1])));
const full = rows.filter((r) => r.length === 5 && r.slice(1, 4).every((c) => c && !/^none/.test(c)) && /^\d{4}-\d{2}-\d{2}$/.test(r[4]));
for (const r of rows) lines.push(`     ${r[0].slice(0, 40).padEnd(40)} Knos ${r[1]} | model ${r[2]} | placebo ${r[3]} | ${r[4]}`);
ok(rows.length === IDEAS && full.length === IDEAS, `/forecasts/: ${rows.length} ideas listed, ${full.length} with all 3 forecasts and the date made (in the served HTML)`);
// the plan's sha256: the page's against the file at the commit under test; the plan's first commit before the page's
const shown = (html.match(/data-plan-sha>([0-9a-f]{64})</) || [])[1];
const plan = createHash("sha256").update(execFileSync("git", ["-C", ROOT, "show", `${SHA}:docs/reference/forecast_plan.md`])).digest("hex");
ok(shown === plan, `plan sha256: page ${String(shown).slice(0, 16)}, committed file ${plan.slice(0, 16)}`);
const first = (path) => git("log", "--format=%H %ct", "--diff-filter=A", SHA, "--", path).trim().split("\n").at(-1).split(" ");
const [pc, pt] = first("docs/reference/forecast_plan.md"), [wc, wt] = first("web/forecasts/index.html");
ok(pc && wc && pc !== wc && Number(pt) <= Number(wt) && git("merge-base", "--is-ancestor", pc, wc).length === 0,
  `the plan (${pc.slice(0, 7)}) was committed before the page (${wc.slice(0, 7)})`);
// what the plan fixes, from the Census page it names
const p = git("show", `${SHA}:docs/reference/forecast_plan.md`);
ok(/County Business Patterns/.test(p) && /CBP 2024 is therefore the outcome year/.test(p) && /hit at 5/i.test(p) && /random\.Random\(4\)/.test(p),
  "the plan names the outcome (CBP 2024), the metric (hit at 5) and the placebo (random.Random(4))");
ok(false, "BLOCKED: the grading date: the Census CBP page (revised 16 Sep 2026) says \"We do not have a planned release date for our 2024 data at this time\"");
lines.push(fails ? `FAIL test_forecast_ledger: ${fails} check(s) failed` : `PASS test_forecast_ledger: ${full.length} ideas with 3 forecasts each; plan sha256 ${plan.slice(0, 12)} matches`);
console.log(lines.join("\n"));
appendFileSync(OUT, lines.join("\n") + "\n");
process.exit(fails ? 1 : 0);
