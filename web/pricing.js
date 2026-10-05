// The Pricing view: the price book (index.html holds the words; the numbers in it come from price.js) and two
// calculators. Nothing here is sent anywhere.
import { priceConstants, priceBook, effectiveFees, quote, feeParts, orderFee, meterCost, unitsOf, bpsOf, show, plain, percent } from "./price.js";
import { programVersion } from "./version.js";

const count = (n) => n.toLocaleString("en-US");
export const WORKED = [100, 5_000, 50_000];      // whole units: one amount in each tier

// The two sentences the page says about the version of the program, from what it answered. `jobFee`: the first
// kind of job's least fee (what sdk/settle exports as FEE_MIN), which a 2.0 program takes out of the amount.
export function versionWords(version, jobFee, c, upgrade = "") {
  if (version >= 1) return `the program is 2.1: a task funded as an order costs what the calculator below says, the funder paying the fee on top of the amount.`;
  if (version === 0) {
    return `the program on devnet is 2.0, so a task funded now is a job: its fee is ${percent(c.feeBps)} of the amount, at least ${show(jobFee)}, and it comes out of the amount, which the payee then gets less of. `
      + `The prices in this book are those of 2.1${upgrade ? `: ${upgrade}` : ", which is live only after the upgrade of the second deployment has executed (a banner above says when one is pending)"}.`;
  }
  return "the program's version could not be read just now. Reload the page to try again.";
}

// The effective fee of five order sizes, and the warning that goes with it: index.html holds the table (id
// "fee-effective") and the sentence in the price book's own numbers, and this writes both again from the constants in use.
function drawEffective($, esc, c) {
  const rows = effectiveFees(c), body = $("fee-effective")?.querySelector("tbody"), small = $("fee-small");
  if (body) body.innerHTML = rows.map((r) => `<tr data-amount="${r.amount}"><th scope="row">${count(r.amount)}</th><td>${plain(r.fee)}</td><td>${esc(r.share)}</td></tr>`).join("");
  if (small) small.textContent = `Knos is not cheaper on a small order: ${count(rows[0].amount)} test USDC pays the minimum, ${plain(rows[0].fee)}, which is ${rows[0].share} of it. `
    + "The calculator above shows this share for any amount before you fund. On devnet the fee is test money: no real revenue.";
}

export function initPricing(ctx) {
  const { $, esc, knos, RPC, ids } = ctx, c = priceConstants();
  // the price book: its six rows are written here from price.js, in the book's own words (docs/MARKET.md, "The price book")
  const set = (id, words) => { const el = $(id); if (el) el.textContent = words; };
  const book = $("price-book")?.querySelector("tbody");
  if (book) book.innerHTML = priceBook(c).map(([line, unit, price]) => `<tr><th scope="row">${esc(line)}</th><td>${esc(unit)}</td><td>${esc(price)}</td></tr>`).join("");
  set("price-bounds", `${plain(c.minAmount)} to ${count(c.maxAmount / 1e6)}`);
  drawEffective($, esc, c);
  // three amounts worked through the tiers, one in each: "2.5% of 1,000 + 1% of 4,000 = 25 + 40"
  const worked = $("fee-worked")?.querySelector("tbody");
  if (worked) worked.innerHTML = WORKED.map((whole) => {
    const parts = feeParts(whole * 1e6, c.feeBps, c).filter((p) => p.of > 0), fee = orderFee(whole * 1e6, c.feeBps, c);
    const how = parts.map((p) => `${percent(p.bps)} of ${count(p.of / 1e6)}`).join(" + ") + (parts.length > 1 ? ` = ${parts.map((p) => plain(p.fee)).join(" + ")}` : "");
    return `<tr data-amount="${whole}"><th scope="row">${count(whole)}</th><td>${esc(how)}</td><td>${plain(fee)}</td></tr>`;
  }).join("");

  // how the fee was reached: each tier that the amount touches, or the floor when the floor is the fee
  function feeNote(amount, q, c) {
    const parts = feeParts(amount, q.bps, c).filter((p) => p.of > 0).map((p) => `${percent(p.bps)} of ${show(p.of)}`).join(", plus ");
    const sum = feeParts(amount, q.bps, c).reduce((n, p) => n + p.fee, 0), rate = ((q.fee / amount) * 100).toFixed(2);
    return sum < c.feeMin ? `the minimum: ${parts} would be ${show(sum)}, and the fee is never under ${show(c.feeMin)}` : `${parts}; ${rate}% of the amount in all; never under ${show(c.feeMin)}, and there is no maximum`;
  }

  function drawSettle() {
    const out = $("calc-result"), amount = unitsOf($("calc-amount").value), rateText = $("calc-rate").value.trim(), bps = rateText ? bpsOf(rateText) : c.feeBps;
    const bad = (words) => { out.innerHTML = `<p class="status bad">${esc(words)}</p>`; };
    if (amount === null) return bad("Write the amount as a number like 20 or 7.5, with at most six decimals.");
    if (amount < c.minAmount) return bad(`A task takes at least ${show(c.minAmount)} test USDC.`);
    if (amount > c.maxAmount) return bad(`A task takes at most ${show(c.maxAmount)} test USDC on devnet.`);
    if (bps === null || bps < c.planBpsMin || bps > c.feeBps) return bad(`A contract rate is a percentage from ${percent(c.planBpsMin)} to ${percent(c.feeBps)}. It replaces the rate of the first ${count(c.tier1 / 1e6)} only.`);
    const q = quote(amount, c, bps), row = (key, name, value, note = "") => `<tr data-key="${key}"><th scope="row">${name}</th><td>${show(value)}</td><td class="fine">${note}</td></tr>`;
    out.innerHTML = `<div class="table-wrap"><table id="calc-table"><tbody>
      ${row("funder", "The funder pays", q.funderPays, "the amount and the fee on top of it")}
      ${row("payee", "The payee receives", q.payeeReceives, "the posted amount, in full")}
      ${row("fee", "The fee, in all", q.fee, feeNote(amount, q, c))}
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
