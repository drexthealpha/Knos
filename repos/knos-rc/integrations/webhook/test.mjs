// node --experimental-strip-types integrations/webhook/test.mjs
// knos-verify.ts against fixtures.json: every case answers as knos_verify.py does (tests/test_integrations.py).
import { readFileSync } from "node:fs";
import { verify } from "./knos-verify.ts";

const fx = JSON.parse(readFileSync(new URL("./fixtures.json", import.meta.url), "utf8"));
let failed = 0;
for (const c of fx.cases) {
  const got = await verify(c.evidence, c.jwks ?? fx.jwks, c.expect ?? {});
  const same = got.ok === c.ok && got.refused === c.refused && got.why === c.why && JSON.stringify(got.checked) === JSON.stringify(c.checked);
  if (!same) {
    failed += 1;
    console.error(`not ok: ${c.name}\n  want ${JSON.stringify([c.ok, c.refused, c.why, c.checked])}\n  got  ${JSON.stringify([got.ok, got.refused, got.why, got.checked])}`);
  }
}
const flat = (v) => Array.isArray(v) ? v.map(flat)
  : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, flat(v[k])])) : v;
const good = await verify(fx.cases[0].evidence, fx.jwks);
if (JSON.stringify(flat(good.facts)) !== JSON.stringify(flat(fx.facts))) {
  failed += 1;
  console.error(`not ok: facts\n  want ${JSON.stringify(fx.facts)}\n  got  ${JSON.stringify(good.facts)}`);
}
console.log(JSON.stringify({ cases: fx.cases.length, failed }));
process.exit(failed ? 1 : 0);
