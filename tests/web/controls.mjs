// A Balance's limits as the site decides them (web/controls_data.js), with no browser: node tests/web/controls.mjs
// Every case of tests/data/controls_cases.json was answered by the Python (`knos budget check`: controls.decide; the
// file is checked against it by tests/test_controls.py). The site's function must give the same answer, word for word.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), dir = mkdtempSync(join(tmpdir(), "controls-"));
// price.js imports ./settle.js, which only the built site has: an empty one makes every constant "recorded"
writeFileSync(join(dir, "settle.js"), "export {};\n");
for (const f of ["price.js", "controls_data.js"]) writeFileSync(join(dir, f), readFileSync(join(here, "../../web", f), "utf8"));
const { explainFunding, feeTable, money, percent, decodeBalance, decodeBalx, decodePlan, base58, RULES } = await import(pathToFileURL(join(dir, "controls_data.js")).href);
const { cases, feeTable: table } = JSON.parse(readFileSync(join(here, "../data/controls_cases.json"), "utf8"));

let failed = 0;
const same = (what, got, want) => { const ok = JSON.stringify(got) === JSON.stringify(want); if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}${ok ? "" : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`); };
const sorted = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));

for (const c of cases) same(c.name, sorted(explainFunding(c.in)), sorted(c.out));
same("every rule is in the cases", [...new Set(cases.map((c) => c.out.rule))].sort(), Object.keys(RULES).sort());
same("the effective-fee table is the Python's", feeTable().map(sorted), table.map(sorted));
same("the table as the price book prints it", feeTable().map((r) => `${money(r.amount)} -> ${money(r.fee)} (${r.effectivePct}%)`),
  ["5.00 -> 0.40 (8.00%)", "20.00 -> 0.50 (2.50%)", "1,000.00 -> 25.00 (2.50%)", "5,000.00 -> 65.00 (1.30%)", "50,000.00 -> 515.00 (1.03%)"]);
same("money and percent", [money(1), money(1_234_567_890_120), percent(1, 0)], ["0.000001", "1,234,567.89012", "0.00"]);
same("only the named facts are needed: no plan, no clock, no side account",
  explainFunding({ balance: { ownerId: 7, spenders: [], capPerJob: 0 }, repoId: 1, amount: 20_000_000, byId: 7 }).sentence,
  "Fine: 20.00 and a fee of 0.50 (2.50%) leave the Balance: 20.50.");

// the accounts' bytes: a Balance, its side account and a Plan, laid out as programs-v2/knos_pay/src/state.rs has them
const u64 = (d, o, v) => new DataView(d.buffer).setBigUint64(o, BigInt(v), true);
const bal = new Uint8Array(160); bal[0] = 1; bal[3] = 1; u64(bal, 8, 424242); bal.fill(1, 16, 48); u64(bal, 80, 50_000_000); u64(bal, 96, 555000); u64(bal, 112, 777000); u64(bal, 128, 9);
same("a Balance's bytes", decodeBalance(bal), { faucet: false, hasX: true, ownerId: 424242, authority: base58(new Uint8Array(32).fill(1)), mint: "11111111111111111111111111111111",
  capPerJob: 50_000_000, spenders: [555000, 777000], spent: 9 });
same("base58 of 32 ones is the address a wallet shows", base58(new Uint8Array(32).fill(1)), "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi");
const x = new Uint8Array(152); x[0] = 1; u64(x, 8, 60_000_000); u64(x, 16, 500_000_000); u64(x, 24, 987654321); u64(x, 40, 5); x.fill(99, 88, 128); u64(x, 128, 20717); u64(x, 136, 3); u64(x, 144, 4);
same("a side account's bytes", decodeBalx(x), { dayLimit: 60_000_000, totalLimit: 500_000_000, repos: [987654321, 5], wfSha: "c".repeat(40), day: 20717, daySpent: 3, totalSpent: 4 });
const p = new Uint8Array(24); p[0] = 1; new DataView(p.buffer).setUint16(2, 100, true); u64(p, 8, 424242); u64(p, 16, 1_790_000_000);
same("a Plan's bytes", decodePlan(p), { feeBps: 100, ownerId: 424242, expires: 1_790_000_000 });
same("bytes that are not the account are null", [decodeBalance(new Uint8Array(160)), decodeBalx(bal), decodePlan(null)], [null, null, null]);
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
