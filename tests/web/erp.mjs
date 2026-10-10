// The statement page's accounting-system files as the site makes them (web/erp.js), with no browser: node tests/web/erp.mjs
// Every file of tests/data/erp was written by the Python (tests/test_erp.py holds them equal to knos.erp). The site's
// functions must give the same bytes from the same statement, status, options and day.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), data = join(here, "../data/erp");
const erp = await import(pathToFileURL(join(here, "../../web/erp.js")).href);
const read = (name) => readFileSync(join(data, name), "utf8");
const st = JSON.parse(readFileSync(join(here, "../data/statement/sept.json"), "utf8")), status = JSON.parse(read("sept.refused.status.json"));
const { today, options } = JSON.parse(read("inputs.json"));

let failed = 0;
const same = (what, got, want) => {
  const ok = got === want;
  if (!ok) { failed++; let i = 0; while (i < got.length && got[i] === want[i]) i++; console.log(`FAIL ${what}: differs at ${i}: got ${JSON.stringify(got.slice(Math.max(0, i - 40), i + 80))}, want ${JSON.stringify(want.slice(Math.max(0, i - 40), i + 80))}`); } else console.log(`ok   ${what}`);
};
for (const to of Object.keys(erp.TARGETS)) {
  const got = await erp.erpWrite(to, st, status, options, today);
  same(`${to}: the payable file`, got.payable, read(`sept.${to}.csv`));
  same(`${to}: the held sheet`, got.held, read(`sept.${to}.held.csv`));
}
let refused = ""; try { await erp.erpWrite("sage", st); } catch (e) { refused = e.message; }
same("another system is refused", refused, '--to is xero, quickbooks, netsuite, csv; "sage" is none of them.');
process.exit(failed ? 1 : 0);
