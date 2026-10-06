// The Pricing view. First the calculator (renderPricing): four inputs, and the year's invoice lines change as they
// move, with the greater of Meter and Verify visibly chosen. Under it the price book (index.html holds the words; the
// numbers in it come from price.js) and the two older calculators of the programs' own fees. Nothing here is sent
// anywhere. The arithmetic is yearEstimate in price.js, which is `estimate` in src/knos/billing.py: both are held
// to tests/data/billing_vectors.json.
import { priceConstants, priceBook, RULE, PAYS, DEVNET, PLANS, BILL, yearEstimate, usd, centsOf, effectiveFees, quote, feeParts, orderFee, meterCost, unitsOf, bpsOf, show, plain, percent } from "./price.js";
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

// ---- the calculator ---------------------------------------------------------------------------------------------------
export const BILLING_DOC = "https://github.com/drexthealpha/Knos/blob/main/docs/MARKET.md#3-the-price-book";
// where each slider stops: [least, most, step]
export const RANGES = Object.freeze({ evaluations: [0, 1_000_000, 5_000], accepted: [0, 50_000_000, 100_000], suppliers: [0, 50, 1] });
export const START = Object.freeze({ plan: "business", evaluations: 110_000, accepted: 10_000_000, suppliers: 5 });      // the worked example of docs/MARKET.md
const STYLE = `
.bill form { display: grid; gap: 12px 20px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 230px), 1fr)); margin: 0 0 16px; }
.bill .bill-in { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 8em); gap: 4px 10px; align-items: center; min-width: 0; }
.bill .bill-in label { grid-column: 1 / -1; margin: 0; }
.bill .bill-in input[type=range] { padding: 0; min-height: 44px; border: 0; background: none; accent-color: var(--accent); }
.bill .bill-in select { grid-column: 1 / -1; }
.bill table td { text-align: right; }
.bill table td.bill-say { text-align: left; color: var(--ink-2); }
.bill tr[data-line] th, .bill tr[data-line] td { transition: opacity var(--dur-2) var(--ease), color var(--dur-2) var(--ease), background-color var(--dur-2) var(--ease); }
.bill tr[data-charged="no"] th, .bill tr[data-charged="no"] td { opacity: .5; }
.bill tr[data-charged="no"] td.k-num { text-decoration: line-through; }
.bill tr[data-charged="yes"] th, .bill tr[data-charged="yes"] td { color: var(--ink); background: color-mix(in srgb, var(--accent) 9%, transparent); }
.bill tr[data-charged="yes"] td.bill-say { color: var(--accent); font-weight: 600; }
.bill tr[data-line="total"] th, .bill tr[data-line="total"] td { color: var(--ink); font-weight: 600; font-size: var(--s1, 1.1em); border-bottom: 0; }
.bill .bill-pays { font-weight: 600; color: var(--ink); margin: 14px 0 4px; }
.bill .status.bad { margin: 0 0 8px; }
@media (max-width: 520px) { .bill table th, .bill table td { padding-right: 8px; } .bill td.bill-say { font-size: var(--s-1); } }
@media (prefers-reduced-motion: reduce) { .bill tr[data-line] th, .bill tr[data-line] td { transition: none; } }`;

// The rows of a year's invoice, from an estimate: [key, name, amount, what is said beside it, charged: "yes" | "no" | ""].
export function billRows(e) {
  const other = e.chosen === "verify" ? "Meter" : "Verify", name = e.chosen === "verify" ? "Verify" : "Meter";
  return [
    ["control", "Control", usd(e.control), e.deliverable ? "a year" : "from; not deliverable yet", ""],
    ["meter", "Meter", usd(e.meter), e.chosen === "meter" ? "charged" : "not charged", e.chosen === "meter" ? "yes" : "no"],
    ["verify", "Verify", usd(e.verify), e.chosen === "verify" ? "charged" : "not charged", e.chosen === "verify" ? "yes" : "no"],
    ["usage", "The greater of the two", usd(e.usage), e.usage ? `${name}, never ${other} too` : "nothing to charge", ""],
    ["suppliers", "Supplier connections", usd(e.connections), `${e.extra} beyond five`, ""],
    ["total", "Total a year", usd(e.total), "USD, billed to the buyer", ""],
    ["settle", "Settle on devnet", "0.00", DEVNET, ""],
  ];
}

// The calculator, in `el`. `ctx.esc` escapes text (the app's); without one the few words here are escaped the same way.
export function renderPricing(el, ctx = {}) {
  if (!el) return null;
  const doc = el.ownerDocument, c = priceConstants(), esc = ctx.esc || ((t) => String(t).replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`));
  if (!doc.getElementById("bill-style")) { const st = doc.createElement("style"); st.id = "bill-style"; st.textContent = STYLE; doc.head.appendChild(st); }
  const slider = (key, label) => { const [min, max, step] = RANGES[key]; return `<div class="bill-in"><label for="bill-${key}">${label}</label>
      <input type="range" id="bill-${key}-range" min="${min}" max="${max}" step="${step}" value="${START[key]}" aria-label="${label}, slider">
      <input id="bill-${key}" inputmode="numeric" autocomplete="off" value="${count(START[key])}"></div>`; };
  el.classList.add("bill");
  el.innerHTML = `<p class="k-kicker">Price a year before work starts</p>
    <form id="bill-form">
      <div class="bill-in"><label for="bill-plan">Plan</label><select id="bill-plan">${PLANS.map(([key, name]) => `<option value="${key}"${key === START.plan ? " selected" : ""}>${name}${BILL.control[key] ? `, ${key === "enterprise" ? "from " : ""}${count(BILL.control[key])} a year` : ""}</option>`).join("")}</select></div>
      ${slider("evaluations", "Evaluations a month")}${slider("accepted", "Accepted value a year, USD")}${slider("suppliers", "Suppliers")}
    </form>
    <div id="bill-said" role="status" aria-live="polite"></div>
    <div class="k-table"><table id="bill-table"><tbody></tbody></table></div>
    <p class="bill-pays" id="bill-pays">${esc(PAYS)}</p>
    <p class="fine" id="bill-benefit"></p>
    <p class="fine"><a href="${BILLING_DOC}">Read the billing rule</a></p>`;
  const $ = (id) => el.querySelector(`#${id}`), body = $("bill-table").querySelector("tbody");
  body.innerHTML = billRows(yearEstimate({}, c)).map(([key, name]) => `<tr data-line="${key}"><th scope="row">${esc(name)}</th><td class="k-num"></td><td class="bill-say"></td></tr>`).join("");

  function read() {
    const whole = (id, most) => { const t = $(id).value.replace(/[,\s]/g, ""); return /^\d{1,12}$/.test(t) && Number(t) <= most ? Number(t) : null; };
    const evaluations = whole("bill-evaluations", 99_999_999_999), suppliers = whole("bill-suppliers", 100_000), acceptedCents = centsOf($("bill-accepted").value);
    if (evaluations === null) return "Write evaluations as a whole number.";
    if (acceptedCents === null) return "Write accepted value as dollars, like 10,000,000.";
    if (suppliers === null) return "Write suppliers as a whole number.";
    return { plan: $("bill-plan").value, evaluations, acceptedCents, suppliers };
  }
  function draw() {
    const input = read();
    if (typeof input === "string") { $("bill-said").innerHTML = `<p class="status bad">${esc(input)}</p>`; return null; }
    $("bill-said").textContent = "";
    const e = yearEstimate(input, c);
    for (const [key, , amount, say, charged] of billRows(e)) {
      const tr = body.querySelector(`[data-line="${key}"]`);
      tr.children[1].textContent = key === "settle" ? "" : amount; tr.children[2].textContent = say;
      if (charged) tr.dataset.charged = charged; else delete tr.dataset.charged;
    }
    body.dataset.chosen = e.chosen;
    $("bill-benefit").textContent = `Demand a benefit of ${BILL.benefitRule} to 1: ${usd(e.benefit)} a year.`;
    return e;
  }
  // a slider and its box hold one number: moving either writes the other
  for (const key of Object.keys(RANGES)) {
    const range = $(`bill-${key}-range`), box = $(`bill-${key}`);
    range.addEventListener("input", () => { box.value = count(Number(range.value)); draw(); });
    box.addEventListener("input", () => { const n = Number(box.value.replace(/[,\s]/g, "")); if (Number.isFinite(n)) range.value = String(n); draw(); });
  }
  $("bill-plan").addEventListener("change", draw);
  $("bill-form").addEventListener("submit", (ev) => ev.preventDefault());
  draw();
  return { draw };
}

export function initPricing(ctx) {
  const { $, esc, knos, RPC, ids } = ctx, c = priceConstants();
  // the calculator leads the view: in the place index.html gives it (id "bill"), or else above the first card
  let bill = $("bill");
  const view = $("view-pricing");
  if (!bill && view) { bill = document.createElement("div"); bill.id = "bill"; bill.className = "k-card"; view.insertBefore(bill, view.querySelector(".card, .k-card")); }
  renderPricing(bill, ctx);
  // the price book: its seven rows are written here from price.js, in the book's own words (docs/MARKET.md, "The price book"),
  // and the rule it is published with, where the page has a place for it (id "price-rule")
  const set = (id, words) => { const el = $(id); if (el) el.textContent = words; };
  const book = $("price-book")?.querySelector("tbody");
  if (book) book.innerHTML = priceBook(c).map(([line, unit, price]) => `<tr><th scope="row">${esc(line)}</th><td>${esc(unit)}</td><td>${esc(price)}</td></tr>`).join("");
  set("price-rule", RULE);
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
      <p class="fine">The funder pays the fee on top. The relay's tip goes to whoever sends. Test USDC on devnet.</p>`;
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
