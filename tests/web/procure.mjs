// Procurement files and approvals as the site judges them (web/procure.js), with no browser: node tests/web/procure.mjs
// Every case of tests/data/procure_cases.json was answered by the Python (src/knos/controls.py and
// src/knos/approvals.py; tests/test_procurement.py holds the file to them). The site's functions must give the same
// answer, word for word.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), dir = mkdtempSync(join(tmpdir(), "procure-"));
writeFileSync(join(dir, "settle.js"), "export {};\n");        // price.js imports ./settle.js, which only the built site has
for (const f of ["price.js", "procure.js"]) writeFileSync(join(dir, f), readFileSync(join(here, "../../web", f), "utf8"));
const p = await import(pathToFileURL(join(dir, "procure.js")).href);
const { cases } = JSON.parse(readFileSync(join(here, "../data/procure_cases.json"), "utf8"));

let failed = 0;
const sorted = (v) => (Array.isArray(v) ? v.map(sorted) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v);
const same = (what, got, want) => { const ok = JSON.stringify(sorted(got)) === JSON.stringify(sorted(want)); if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`); };
const run = { readYaml: (t) => { try { return p.readYaml(t); } catch (e) { if (e instanceof p.Unread) return { unread: e.message }; throw e; } } };

for (const c of cases) same(c.name, (run[c.fn] || p[c.fn])(...c.args), c.out);
same("every function of the file has a case", [...new Set(cases.map((c) => c.fn))].sort(),
  ["cardProblems", "chain", "check", "commitment", "dayOf", "dumpYaml", "envelopeProblems", "envelopeState", "fit", "offerComment", "offerProblems", "policyProblems", "readComment", "readYaml", "unitsOf"]);
const first = cases.find((c) => c.fn === "dumpYaml");
same("a file the page writes reads back", p.readYaml(p.dumpYaml(first.args[0])), first.args[0]);
same("an approvals log", p.readLog('{"type":"knos.approval","id":"apr_1"}\nnot json\n{"type":"other"}\n').map((e) => e.id), ["apr_1"]);
same("the line an approver posts", [p.commentLine("offer:x"), p.commentLine("offer:x", "finance"), p.readComment(p.commentLine("offer:x", "finance"))],
  ["/knos approve offer:x", "/knos approve offer:x as finance", ["offer:x", "finance"]]);
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
