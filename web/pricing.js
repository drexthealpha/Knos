// The Pricing view: the price book (index.html holds the words; the numbers in it come from price.js) and two
// calculators. Nothing here is sent anywhere.
import { priceConstants, quote, meterCost, unitsOf, bpsOf, show, plain, percent } from "./price.js";
import { programVersion } from "./version.js";

const count = (n) => n.toLocaleString("en-US");

// The two sentences the page says about the version of the program, from what it answered. `jobFee`: the first
// kind of job's least fee (what sdk/settle exports as FEE_MIN), which a 2.0 program takes out of the amount.
export function versionWords(version, jobFee, c, upgrade = "") {
  if (version === 1) return `the program is 2.1: a task funded as an order costs what the calculator below says, the funder paying the fee on top of the amount.`;
  if (version === 0) {
    return `the program on devnet is 2.0, so a task funded now is a job: its fee is ${percent(c.feeBps)} of the amount, at least ${show(jobFee)}, and it comes out of the amount, which the payee then gets less of. `
      + `The prices in this book are those of 2.1${upgrade ? `: ${upgrade}` : ", which is live only after the upgrade of the second deployment has executed (a banner above says when one is pending)"}.`;
  }
  return "the program's version could not be read just now. Reload the page to try again.";
}

export function initPricing(ctx) {
  const { $, esc, knos, RPC, ids } = ctx, c = priceConstants();
  $("price-settle").textContent = `the funder pays the amount plus ${percent(c.feeBps)}, at least ${plain(c.feeMin)}, at most ${plain(c.feeMax)} USDC; the payee receives the posted amount; ${percent(c.planBpsMin)} to 1.5% under a contract (a Plan)`;
  $("price-meter").textContent = `${plain(c.meterFee)} per billable evaluation, ${plain(c.meterPlanMin)} at volume`;
  $("price-meter-free").textContent = `${count(c.meterFree)} evaluations a month`;

  function drawSettle() {
    const out = $("calc-result"), amount = unitsOf($("calc-amount").value), rateText = $("calc-rate").value.trim(), bps = rateText ? bpsOf(rateText) : c.feeBps;
    const bad = (words) => { out.innerHTML = `<p class="status bad">${esc(words)}</p>`; };
    if (amount === null) return bad("Write the amount as a number like 20 or 7.5, with at most six decimals.");
    if (amount < c.minAmount) return bad(`A task takes at least ${show(c.minAmount)} test USDC.`);
    if (amount > c.maxAmount) return bad(`A task takes at most ${show(c.maxAmount)} test USDC until an outside review.`);
    if (bps === null || bps < c.planBpsMin || bps > c.feeBps) return bad(`A contract rate is a percentage from ${percent(c.planBpsMin)} to ${percent(c.feeBps)}.`);
    const q = quote(amount, c, bps), row = (key, name, value, note = "") => `<tr data-key="${key}"><th scope="row">${name}</th><td>${show(value)}</td><td class="fine">${note}</td></tr>`;
    out.innerHTML = `<div class="table-wrap"><table id="calc-table"><tbody>
      ${row("funder", "The funder pays", q.funderPays, "the amount and the fee on top of it")}
      ${row("payee", "The payee receives", q.payeeReceives, "the posted amount, in full")}
      ${row("fee", "The fee, in all", q.fee, `${percent(q.bps)} of the amount, but never under ${show(c.feeMin)} or over ${show(c.feeMax)}`)}
      ${row("tip", "of it, the relay's tip", q.tip, `${show(c.tipFirst)} when the paying transaction has to create the payee's token account`)}
      ${row("knos", "of it, Knos's fee", q.knos, `${show(q.knosFirst)} in that case`)}</tbody></table></div>
      <p class="fine">The fee is paid by the funder and stays in the order until it is paid; the relay's tip goes to whoever sent the paying transaction. All in test USDC on devnet.</p>`;
  }

  function drawMeter() {
    const out = $("meter-result"), text = $("meter-n").value.replace(/[,\s]/g, ""), n = /^\d{1,11}$/.test(text) ? Number(text) : null;
    if (n === null) { out.innerHTML = `<p class="status bad">Write a whole number of evaluations, like 25000.</p>`; return; }
    const list = meterCost(n, c), plan = meterCost(n, c, c.meterPlanMin), row = (key, name, value, note = "") => `<tr data-key="${key}"><th scope="row">${name}</th><td>${value}</td><td class="fine">${note}</td></tr>`;
    out.innerHTML = `<div class="table-wrap"><table id="meter-table"><tbody>
      ${row("free", "Free", count(list.free), `an owner's first ${count(c.meterFree)} a month`)}
      ${row("billable", "Billable", count(list.billable))}
      ${row("list", "Cost at the price", show(list.cost), `${show(c.meterFee)} each`)}
      ${row("plan", "Cost at the lowest Plan rate", show(plan.cost), `${show(c.meterPlanMin)} each, set by a contract`)}</tbody></table></div>
      <p class="fine">An evaluation is one work order, artifact, policy and milestone: a retry or a duplicate is free. A rejection counts. Test USDC on devnet.</p>`;
  }

  $("calc-form").addEventListener("input", drawSettle);
  $("meter-form").addEventListener("input", drawMeter);
  $("calc-form").addEventListener("submit", (ev) => ev.preventDefault());
  $("meter-form").addEventListener("submit", (ev) => ev.preventDefault());
  drawSettle(); drawMeter();

  let said = false;
  return async function showVersion(upgrade = "") {
    if (said) return;
    said = true;
    const el = $("price-version-now");
    try { el.textContent = versionWords(await programVersion(knos, RPC, (await ids()).knos_pay), knos.FEE_MIN, c, upgrade); }
    catch { el.textContent = versionWords(null, knos.FEE_MIN, c); }
  };
}
