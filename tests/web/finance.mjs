// The finance view's data as the site makes it (web/finance_data.js), with no browser: node tests/web/finance.mjs
// Every file of tests/data/finance was written by the Python (tests/test_exports.py holds them equal to knos.audit and
// knos.exports). The site's functions must give the same bytes from the same statement and the same refs file.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), data = join(here, "../data/finance");
const fd = await import(pathToFileURL(join(here, "../../web/finance_data.js")).href);
const read = (name) => readFileSync(join(data, name), "utf8"), json = (name) => JSON.parse(read(name));

let failed = 0;
const same = (what, got, want) => {
  const a = typeof got === "string" ? got : fd.canonical(got), b = typeof want === "string" ? want : fd.canonical(want), ok = a === b;      // objects: whatever the order of their keys
  if (!ok) { failed++; let i = 0; while (i < a.length && a[i] === b[i]) i++; console.log(`FAIL ${what}: differs at ${i}: got ${JSON.stringify(a.slice(Math.max(0, i - 40), i + 80))}, want ${JSON.stringify(b.slice(Math.max(0, i - 40), i + 80))}`); } else console.log(`ok   ${what}`);
};

const doc = json("statement_mix.json"), { scope, head } = doc, options = json("options.json"), extras = json("extras.json");
const lines = doc.rows.map(({ seq, prev, ...r }) => r);           // what audit/<owner id>.json holds: the lines, unnumbered
const refs = fd.readRefs(read("refs.csv"));

// the statement, version 2: the chain, the head and both files
const made = await fd.chained(lines, scope);
same("the head is the Python's", made.head, head);
same("every row and its hash", made.rows, doc.rows);
same("the columns of version 2", fd.columnsOf(scope), doc.columns);
same("the statement as CSV", fd.auditWrite(scope, made.rows, made.head, "csv"), read("statement_mix.csv"));
same("the statement as JSON", fd.auditWrite(scope, made.rows, made.head, "json"), read("statement_mix.json"));
same("auditExport is both steps", (await fd.auditExport(scope, lines, "csv")).text, read("statement_mix.csv"));
same("the rows verify", await fd.verifyRows(scope, doc.rows, head), []);
const edited = doc.rows.map((r, n) => (n === 1 ? { ...r, paid_units: r.paid_units + 1 } : r));
same("an edited row is found", (await fd.verifyRows(scope, edited, head)).some((s) => s.startsWith("Row 3 does not follow")), true);
same("the totals", fd.totals(doc.rows), doc.totals);

// a statement of version 1 keeps its columns, its bytes and its head
const old = json("audit_v1.json"), oldLines = old.rows.map(({ seq, prev, ...r }) => r);
same("version 1: the head", (await fd.chained(oldLines, old.scope)).head, old.head);
same("version 1: the CSV", (await fd.auditExport(old.scope, oldLines, "csv")).text, read("audit_v1.csv"));
same("version 1: the JSON", (await fd.auditExport(old.scope, oldLines, "json")).text, read("audit_v1.json"));
let refused = ""; try { fd.columnsOf({ version: 3 }); } catch (e) { refused = e.message; }
same("a version this page does not know is refused", refused.includes("version 3"), true);

// the four linked objects
same("the refs file", refs["OrdB:FB:12"], { order: "OrdB:FB:12", ref: "PO-4412 line 1", paid_outside: "2026-09-28 bank ref 77120", dispute: "" });
same("the records, with the refs and a receipt", `${fd.canonical(fd.recordsOf(doc.rows, refs, extras.receipts))}\n`, read("records_mix.json"));
same("the records from the statement alone", `${fd.canonical(fd.recordsOf(doc.rows))}\n`, read("records_mix_chain_only.json"));
const recs = fd.recordsOf(doc.rows, refs);
same("every record has the four objects", recs.every((r) => fd.OBJECTS.every((k) => r[k])), true);
same("every settlement status is a named one", recs.every((r) => fd.SETTLEMENTS.includes(r.settlement.status)), true);
same("the states of the mix", [...new Set(recs.map((r) => r.settlement.status))].sort(), ["held", "paid on devnet (test money)", "paid outside Knos", "payable", "refunded", "reverted"]);
const approval = { multisig: "M", vault: "V", threshold: 2, members: ["a", "b", "c"], time_lock: 0, proposal: 4, approved: ["a", "b"] };
const viaVault = fd.record(doc.rows.filter((r) => r.order === "OrdA"), null, null, approval).authorisation.approved_by;
same("a Squads approval is the two-person approval", [viaVault.two_person, viaVault.said],
  [true, "A Squads vault funded this: 2 of its 3 members had to approve, and 2 did. This is the two-person approval Knos has today. It is the multisig's own rule, not a workflow inside Knos."]);

// the files a finance system imports
for (const fmt of Object.keys(fd.FORMATS)) same(`${fmt}: the file`, await fd.exportAs(fmt, scope, doc.rows, head, refs, options), read(`${fmt}.csv`));
const back = fd.statementOf(read("generic.csv"));
same("the generic file gives the statement back", back.text, read("statement_mix.csv"));
same("and the same head", [back.head, await fd.verifyRows(back.scope, back.rows, back.head)], [head, []]);
same("decimal and day", [fd.decimal(19500000), fd.decimal(404999), fd.decimal(7), fd.day("2026-09-03", "M/D/YYYY"), fd.day("2026-12-25", "DD.MM.YYYY")],
  ["19.50", "0.404999", "0.000007", "9/3/2026", "25.12.2026"]);
same("canonical JSON is the Python's", fd.canonical({ b: [1, "é", null, true], a: "x\"y\n" }), '{"a":"x\\"y\\n","b":[1,"\\u00e9",null,true]}');

console.log(failed ? `${failed} failed` : "all the same");
process.exit(failed ? 1 : 0);
