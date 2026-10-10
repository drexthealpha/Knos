// The fee fold of the Fund page (#fund, "How it pays, the fee"): the rule the program on devnet charges, read from the
// program as Pricing reads it (web/fee_live.js: the program's version, else upgrades.json). Until one answers, the page's
// own words stand: knos_pay 2.2's rule, live at the public id since 9 October 2026 (the words of feeWords(2)).
// tests/test_fund_fee.py holds those words to web/price.js and knos.fees.
import { liveFee } from "./fee_live.js";
import { feeWords } from "./price.js";

/** Draws the rule of the build that is live into `el` (id "fund-fee"). ctx: { knos, RPC, ids, live } (`live`: a promise of
 *  liveFee's answer, for a test). Returns the version that answered, or null when nobody did and the words stand. */
export async function renderFundFee(el, ctx = {}) {
  if (!el) return null;
  let got = null;
  try {
    got = await (ctx.live || liveFee({ knos: ctx.knos, rpc: ctx.RPC ?? null, program: (await Promise.resolve(ctx.ids ? ctx.ids() : null).catch(() => null))?.knos_pay ?? null }));
  } catch { got = null; }
  if (!got || got.version === null || got.version === undefined) return null;
  el.textContent = feeWords(got.version, ctx.knos);
  el.dataset.fee = got.c.fee.release;
  el.dataset.source = got.source;
  return got.version;
}
