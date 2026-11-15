// Which fee the program on devnet charges NOW, for every page that shows a fee before anything is funded.
//
// knos_pay has two fee rules (web/price.js): the 0.3.18 one (0.30%, at least 0.05) from knos_pay 2.2 on, and the
// 0.3.14 one (three tiers, at least 0.40) before. The public programs charge the 0.3.14 fee until the upgrade to 2.2
// executes, so a page asks before it shows a number:
//   1. the program itself (web/version.js: Version, simulated, nothing sent): 2 is knos_pay 2.2;
//   2. when devnet did not answer, upgrades.json, the file of this site written from the upgrade multisig's accounts:
//      2 once a proposal of knos_pay after the 2.1 one has executed. The file is as old as its `generated`.
// liveFee answers { version, source, c }: `source` is "chain", "feed" or null (nobody answered: `c` is then the 0.3.18
// rule with c.fee.live false, and the page says both rules). `c` is priceConstants of that version.
import * as settle from "./settle.js";
import { programVersion } from "./version.js";
import { priceConstants } from "./price.js";

export async function liveFee({ knos = settle, rpc = null, program = null, feed = "upgrades.json", fetcher = globalThis.fetch } = {}) {
  let version = null, source = null;
  if (rpc && program) {
    try { version = await programVersion(knos, rpc, program); } catch { version = null; }
    if (version !== null) source = "chain";
  }
  if (version === null && feed && fetcher) {
    try { const r = await fetcher(feed); version = knos.v2.feedFeeVersion(r.ok ? await r.json() : null); } catch { version = null; }
    if (version !== null) source = "feed";
  }
  return { version, source, c: priceConstants(knos, version) };
}
