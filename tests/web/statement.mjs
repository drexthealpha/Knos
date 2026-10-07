// The statement of one invoice as the site makes it (web/finance_data.js), with no browser: node tests/web/statement.mjs
// Every file of tests/data/statement was written by the Python (tests/test_statement.py holds them equal to knos.statement
// and knos.exports). The site's functions must give the same bytes from the same statement and the same status file.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), data = join(here, "../data/statement");
const fd = await import(pathToFileURL(join(here, "../../web/finance_data.js")).href);
const read = (name) => readFileSync(join(data, name), "utf8"), json = (name) => JSON.parse(read(name));

let failed = 0;
const same = (what, got, want) => {
  const a = typeof got === "string" ? got : JSON.stringify(got), b = typeof want === "string" ? want : JSON.stringify(want), ok = a === b;
  if (!ok) { failed++; let i = 0; while (i < a.length && a[i] === b[i]) i++; console.log(`FAIL ${what}: differs at ${i}: got ${JSON.stringify(a.slice(Math.max(0, i - 40), i + 80))}, want ${JSON.stringify(b.slice(Math.max(0, i - 40), i + 80))}`); } else console.log(`ok   ${what}`);
};

const st = json("sept.json"), status = json("sept.status.json"), oct = json("october.json");
same("the canonical text is the file", fd.canonicalText(st), read("sept.json"));
same("the statement's own sha256", await fd.statementDigest(st), st.sha256);
same("an edited statement is not its sha256", (await fd.statementDigest({ ...st, invoice: "INV-other" })) === st.sha256, false);
same("the CSV with no status", await fd.statementCsv(st), read("sept.plain.csv"));
same("the CSV with approvals and payments", await fd.statementCsv(st, status), read("sept.csv"));
same("the next invoice's CSV, with the line billed before", await fd.statementCsv(oct), read("october.csv"));
for (const fmt of fd.STATEMENT_FORMATS) same(`the ${fmt} file`, await fd.statementExport(fmt, st, status, { account: "6100 Contract engineering" }), read(`sept.${fmt}.csv`));
same("four states on one invoice", fd.statementLines(st).map((r) => r.state), ["agreed", "disputed", "insufficient_evidence", "duplicate", "agreed"]);
same("the duplicate across two statements", [oct.lines[0].state, oct.lines[0].duplicate_of], ["duplicate", `statement ${st.sha256.slice(0, 12)} line 1`]);
same("who approved", Object.fromEntries(fd.statementAnswers(st, status)).Approved, "2 agreed lines, 160.00 USD by Dana Reyes (finance controller) on 2026-10-01, role as stated");
same("every line says its assurance level, computed", fd.statementLines(st, status).map((r) => r.assurance), ["reported", "reported", "reported", "not evaluated", "reported"]);
for (const n of [0, 1, 3]) same(`the goods-received note of line ${n + 1} is the Python's`, fd.canonicalText(fd.statementGrn(st, status, st.lines[n].invoice_line)), read(`sept.grn.${n + 1}.json`));
const noted = json("sept.grn.status.json");
same("a recorded note is shown as recorded, with its purchase order", fd.canonicalText(fd.statementGrn(st, noted, st.lines[4].invoice_line)), read("sept.grn.5.json"));
same("the CSV with a recorded note", await fd.statementCsv(st, noted), read("sept.grn.csv"));
same("the generic file carries PO, GRN and assurance", await fd.statementExport("generic", st, noted), read("sept.grn.generic.csv"));
let refused = ""; try { fd.statementLines(oct, status); } catch (e) { refused = e.message; }
same("another statement's status is refused", refused, "The status file is another statement's: it names another sha256.");
// the statement made in the page (web/statement_make.js: what the front door downloads) is knos.statement.from_shadow's
const mk = await import(pathToFileURL(join(here, "../../web/statement_make.js")).href);
same("made again in the page from its own evidence, the statement is the same bytes", fd.canonicalText(await mk.fromShadow(st.evidence.embedded, { invoice: st.invoice, supplier: st.supplier, buyer: st.buyer, currency: st.currency, date: st.date })), read("sept.json"));
same("an approval made in the page is knos.statement.approve's", fd.canonicalText(mk.approve(st, null, "Dana Reyes", "finance controller", "2026-10-01").events[0]), fd.canonicalText(status.events[0]));
same("an invoice line id is ids.py's", await mk.ids.invoiceLine("Acme Agents", "INV-2026-09", 1), st.lines[0].invoice_line);
same("every file is a file export until an import is verified", fd.LABEL, "file export, not an integration");
if (failed) { console.log(`${failed} failed`); process.exit(1); }
console.log("the statement in the page is the Python's, byte for byte");
