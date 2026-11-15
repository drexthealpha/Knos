// node tests/web/receipt_parts.mjs [web dir]
// web/verifier.js reads a receipt in five parts (`receiptParts`), with no browser: every receipt of tests/data/receipt_parts.json
// must read to what knos.receipt.parts says of it, word for word (the receipt's digest apart, which the page does not compute).
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = process.argv[2] || join(here, "..", "..", "web");
const lib = await import(pathToFileURL(join(root, "verifier.js")).href);
const { cases } = JSON.parse(readFileSync(join(here, "..", "data", "receipt_parts.json"), "utf8"));
const sort = (v) => (Array.isArray(v) ? v.map(sort) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sort(v[k])])) : v);
let bad = 0;
for (const c of cases) {
  const { ok, ...got } = lib.receiptParts(c.receipt);
  const same = ok && JSON.stringify(sort({ ...got, receipt: c.parts.receipt })) === JSON.stringify(sort(c.parts));
  if (!same) { bad++; console.error("FAIL", c.name, ok ? got.parts.filter((p, n) => JSON.stringify(sort(p)) !== JSON.stringify(sort(c.parts.parts[n]))).map((p) => p.id).join(", ") : got.error); }
  const html = lib.partsHtml({ ok, ...got });
  if (lib.FIVE.some((id) => !html.includes(`data-part="${id}"`)) || html.includes(`data-parts="weak"`) !== c.parts.weak) { bad++; console.error("FAIL", c.name, "the five rows"); }
}
for (const [doc, want] of [[{ type: "x" }, "another file"], [{ type: "knos.acceptance-receipt", version: 2 }, "version 2"], [{ type: "knos.acceptance-receipt", version: 5 }, "a part is missing"], [null, "another file"]]) {
  const got = lib.receiptParts(doc);
  if (got.ok || !got.error.includes(want) || got.error.split(/\s+/).length > 12) { bad++; console.error("FAIL", "refused in a few words", got.error); }
}
console.log(`${cases.length} cases, ${bad} differ`);
process.exit(bad ? 1 : 0);
