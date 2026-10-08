// The Pricing view. First the calculator (renderPricing): plan, evaluations a month, accepted value a month, the share
// of it released on chain and record lookups; the year's invoice lines change as they move, and the Acceptance line
// shows the month's value moving through its two marginal rates (the rate never goes below 0.20%). Under it the price book (index.html holds the
// words; the numbers in it come from price.js) and the calculators of what the program takes at release. Nothing here
// is sent anywhere. The arithmetic is yearEstimate in price.js, which is `estimate` in src/knos/billing.py: both are
// held to tests/data/billing_vectors.json.
import { priceConstants, priceBook, feeParts, RULE, PAYS, CONNECT, DEVNET, PLANS, BILL, yearEstimate, usd, centsOf, effectiveFees, quote, orderFee, meterCost, unitsOf, bpsOf, show, plain, rateOf, feeWords, feeRate, feeNext, enforcedNow, FEE_VERSION } from "./price.js";
import { liveFee } from "./fee_live.js";
import { programVersion } from "./version.js";

const count = (n) => n.toLocaleString("en-US");
export const WORKED = [100, 5_000, 100_000];      // whole units

// The sentence the page says about the version of the program, from what it answered.
export function versionWords(version, jobFee, c, upgrade = "") {
  if (version >= FEE_VERSION) return `the program is 2.2 or later: at release it takes what the calculator below says, the funder paying the fee on top of the amount.`;
  // 2.1 is live and charges the fee of its own build: the calculators below show that fee (drawLive), and the next one in a line
  if (version >= 1) return `the program on devnet is 2.1. ${feeWords(version)} The calculator below shows the fee it charges today.`;
  if (version === 0) {
    return `the program on devnet is 2.0, older than this price book: a task funded now pays the fee that program holds, out of the amount. `
      + `The prices in this book are those of the next program${upgrade ? `: ${upgrade}` : ", which is live only after the upgrade of the second deployment has executed (a banner above says when one is pending)"}.`;
  }
  return "the program's version could not be read just now. Reload the page to try again.";
}

// The fee of six release sizes, and the sentence that goes with it: index.html holds the table (id "fee-effective")
// and the sentence, and this writes both again from the constants in use.
function drawEffective($, esc, c) {
  const rows = effectiveFees(c), body = $("fee-effective")?.querySelector("tbody"), small = $("fee-small");
  if (body) body.innerHTML = rows.map((r) => `<tr data-amount="${r.amount}"><th scope="row">${count(r.amount)}</th><td>${plain(r.fee)}</td><td>${esc(r.share)}</td></tr>`).join("");
  if (small) small.textContent = `${count(rows[0].amount)} test USDC pays the floor, ${plain(rows[0].fee)}: ${rows[0].share} of it. `
    + "On devnet the fee is test money: 0 revenue.";
}

// ---- which fee the program charges today -------------------------------------------------------------------------------
// Two rows of facts: the rule of the build that is LIVE (web/fee_live.js asks the program, then upgrades.json), and,
// only when that is not this tree's rule, one row "After the next upgrade". Until somebody has answered the row says
// so; when nobody does, it says the rule of the next build and the one charged until then.
export function drawLive(dl, live, esc = (t) => String(t)) {
  if (!dl) return;
  const c = live ? live.c : null, next = c ? feeNext(c) : null;
  dl.hidden = false; dl.dataset.fee = c ? c.fee.release : ""; dl.dataset.live = c && c.fee.live ? "1" : "0"; dl.dataset.source = (live && live.source) || "";
  dl.innerHTML = !c ? `<dt>Fee on devnet today</dt><dd>reading…</dd>`
    : `<dt data-row="now">${c.fee.live ? "Fee on devnet today" : "Fee from the next build"}</dt><dd data-row="now">${esc(feeRate(c))}</dd>${
      next ? `<dt data-row="next">${esc(next.label)}</dt><dd data-row="next">${esc(next.rate)}</dd>` : ""}`;
}

// ---- the calculator ---------------------------------------------------------------------------------------------------
export const BILLING_DOC = "https://github.com/drexthealpha/Knos/blob/main/docs/MARKET.md#3-the-price-book";
// where each slider stops: [least, most, step]
export const RANGES = Object.freeze({ evaluations: [0, 2_000_000, 10_000], accepted: [0, 30_000_000, 50_000], onchain: [0, 100, 5], lookups: [0, 5_000, 10] });
// the worked customer of docs/MARKET.md: Business, 110,000 evaluations a month, 10 million accepted a year
export const START = Object.freeze({ plan: "business", evaluations: "110,000", accepted: "833,333.33", onchain: "0", lookups: "0" });
const STYLE = `
.bill form { display: grid; gap: 12px 20px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 230px), 1fr)); margin: 0 0 16px; }
.bill .bill-in { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 8em); gap: 4px 10px; align-items: center; min-width: 0; }
.bill .bill-in label { grid-column: 1 / -1; margin: 0; }
.bill .bill-in input[type=range] { padding: 0; min-height: 44px; border: 0; background: none; accent-color: var(--accent); }
.bill .bill-in select { grid-column: 1 / -1; }
.bill table td { text-align: right; }
.bill table td.bill-say { text-align: left; color: var(--ink-2); }
.bill tr[data-line] th, .bill tr[data-line] td { transition: opacity var(--dur-2) var(--ease), color var(--dur-2) var(--ease); }
.bill tr[data-off="yes"] th, .bill tr[data-off="yes"] td { opacity: .5; }
.bill tr[data-line="total"] th, .bill tr[data-line="total"] td { color: var(--ink); font-weight: 600; font-size: var(--s1, 1.1em); border-bottom: 0; }
.bill .bill-tiers { display: grid; gap: 6px; margin: 4px 0 14px; }
.bill .bill-tier { display: grid; grid-template-columns: minmax(0, 9.5em) minmax(24px, 1fr) auto; gap: 10px; align-items: center; min-width: 0; }
.bill .bill-tier .bill-bar { display: block; height: 10px; padding: 0; margin: 0; border-radius: 5px; background: var(--paper-2); box-shadow: inset 0 0 0 1px var(--line); overflow: hidden; }
.bill .bill-tier .bill-bar i { display: block; height: 100%; width: 0; background: var(--accent); transition: width var(--dur-2) var(--ease); }
.bill .bill-tier .k-num { text-align: right; }
.bill .bill-tier[data-on="no"] { opacity: .5; }
.bill .bill-live { margin: 0 0 16px; padding: 10px 14px; border-radius: var(--radius); background: var(--paper-2); box-shadow: inset 0 0 0 1px var(--line); }
.bill .bill-live dd[data-row="next"] { color: var(--ink-2); }
.bill .bill-pays { font-weight: 600; color: var(--ink); margin: 14px 0 4px; }
.bill .status.bad { margin: 0 0 8px; }
@media (max-width: 520px) { .bill table th, .bill table td { padding-right: 8px; } .bill td.bill-say { font-size: var(--s-1); } .bill .bill-tier { grid-template-columns: minmax(0, 5.5em) minmax(24px, 1fr) auto; gap: 8px; font-size: var(--s-1); } }
/* a phone: the price book's cells are stacked (app.css), so each says which column it is; small type keeps a long line of the book in view */
@media (max-width: 560px) {
  #price-book td, #price-book td:nth-child(2) { font-size: var(--s-1); line-height: 1.35; }
  #price-book td::before { color: var(--fg); font-weight: 600; }
  #price-book td:nth-child(2)::before { content: "Unit: "; }
  #price-book td:nth-child(3)::before { content: "Price: "; }
  #price-book td:nth-child(4)::before { content: "Who pays: "; }
  #price-book td:nth-child(5)::before { content: "Enforced: "; }
}
@media (prefers-reduced-motion: reduce) { .bill tr[data-line] th, .bill tr[data-line] td, .bill .bill-tier .bill-bar i { transition: none; } }`;

const TIER_NAMES = BILL.acceptBps.map((bps, n) => `${rateOf(bps)} ${n === 0 ? "to" : "above"} ${(BILL.acceptAbove[n] || BILL.acceptAbove[1]) / 1e6}M`);
// The rows of a year's invoice, from an estimate: [key, name, amount, what is said beside it, off: "yes" when nothing is charged on it].
export function billRows(e) {
  return [
    ["control", "Control", usd(e.control), e.deliverable ? "a year" : "from; not deliverable yet", ""],
    ["meter", "Meter", usd(e.meter), `${count(e.billable)} billable a month`, e.meter ? "" : "yes"],
    ["acceptance", "Acceptance", usd(e.acceptance), "on value reconciled off chain", e.acceptance ? "" : "yes"],
    ["onchain", "Paid on chain", usd(e.paidOnChain), "at release; never charged again", e.paidOnChain ? "" : "yes"],
    ["rebate", "Volume rebate", `${e.rebate ? "-" : ""}${usd(e.rebate)}`, e.volume ? "by contract, on chain value" : "needs a contract", e.rebate ? "" : "yes"],
    ["records", "Record lookups", usd(e.records), `${(BILL.recordCents / 100).toFixed(2)} a lookup`, e.records ? "" : "yes"],
    ["total", "Total a year", usd(e.total), "USD, billed to the buyer", ""],
    ["devnet", "Fees on devnet", "0.00", DEVNET, ""],
  ];
}

// The calculator, in `el`. `ctx.esc` escapes text (the app's); without one the few words here are escaped the same way.
export function renderPricing(el, ctx = {}) {
  if (!el) return null;
  const doc = el.ownerDocument, esc = ctx.esc || ((t) => String(t).replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`));
  if (!doc.getElementById("bill-style")) { const st = doc.createElement("style"); st.id = "bill-style"; st.textContent = STYLE; doc.head.appendChild(st); }
  const slider = (key, label) => { const [min, max, step] = RANGES[key]; return `<div class="bill-in"><label for="bill-${key}">${label}</label>
      <input type="range" id="bill-${key}-range" min="${min}" max="${max}" step="${step}" value="${Math.round(Number(START[key].replace(/,/g, "")))}" aria-label="${label}, slider">
      <input id="bill-${key}" inputmode="decimal" autocomplete="off" value="${START[key]}"></div>`; };
  el.classList.add("bill");
  el.innerHTML = `<p class="k-kicker">Price a year before work starts</p>
    <form id="bill-form">
      <div class="bill-in"><label for="bill-plan">Plan</label><select id="bill-plan">${PLANS.map(([key, name]) => `<option value="${key}"${key === START.plan ? " selected" : ""}>${name}${BILL.control[key] ? `, ${key === "enterprise" ? "from " : ""}${count(BILL.control[key])} a year` : ""}</option>`).join("")}</select></div>
      ${slider("evaluations", "Evaluations a month")}${slider("accepted", "Accepted value a month, USD")}${slider("onchain", "Share released on chain, percent")}${slider("lookups", "Record lookups a month")}
    </form>
    <div id="bill-said" role="status" aria-live="polite"></div>
    <div class="k-table"><table id="bill-table"><tbody></tbody></table></div>
    <dl class="facts bill-live" id="bill-live" data-keep hidden></dl>
    <p class="k-kicker">A month's accepted value, rate by rate</p>
    <div class="bill-tiers" id="bill-tiers" data-not-prose>${TIER_NAMES.map((name, n) => `<div class="bill-tier" data-tier="${n}"><span>${name}</span><span class="bill-bar"><i></i></span><span class="k-num"></span></div>`).join("")}</div>
    <p class="bill-pays" id="bill-pays">${esc(PAYS)}</p>
    <p class="bill-pays" id="bill-connect">${esc(CONNECT)}</p>
    <p class="fine" id="bill-benefit"></p>
    <p class="fine"><a href="${BILLING_DOC}">Read the billing rule</a></p>`;
  const $ = (id) => el.querySelector(`#${id}`), body = $("bill-table").querySelector("tbody");
  body.innerHTML = billRows(yearEstimate({})).map(([key, name]) => `<tr data-line="${key}"><th scope="row">${esc(name)}</th><td class="k-num"></td><td class="bill-say"></td></tr>`).join("");

  function read() {
    const whole = (id, most) => { const t = $(id).value.replace(/[,\s]/g, ""); return /^\d{1,12}$/.test(t) && Number(t) <= most ? Number(t) : null; };
    const evaluations = whole("bill-evaluations", 99_999_999_999), lookups = whole("bill-lookups", 99_999_999), onChainPercent = whole("bill-onchain", 100), monthCents = centsOf($("bill-accepted").value);
    if (evaluations === null) return "Write evaluations as a whole number.";
    if (monthCents === null) return "Write accepted value as dollars, like 833,333.33.";
    if (onChainPercent === null) return "Write the share as a whole percentage, 0 to 100.";
    if (lookups === null) return "Write lookups as a whole number.";
    return { plan: $("bill-plan").value, evaluations, acceptedCents: monthCents * 12, onChainPercent, lookups };
  }
  function draw() {
    const input = read();
    if (typeof input === "string") { $("bill-said").innerHTML = `<p class="status bad">${esc(input)}</p>`; return null; }
    $("bill-said").textContent = "";
    const e = yearEstimate(input);
    for (const [key, , amount, say, off] of billRows(e)) {
      const tr = body.querySelector(`[data-line="${key}"]`);
      tr.children[1].textContent = key === "devnet" ? "" : amount; tr.children[2].textContent = say;
      if (off) tr.dataset.off = off; else delete tr.dataset.off;
    }
    // the tiers move: each bar is the share of the month's value that pays that rate
    const month = e.tiers.reduce((sum, t) => sum + t.of, 0);
    e.tiers.forEach((t, n) => {
      const row = $("bill-tiers").children[n];
      row.dataset.on = t.of ? "yes" : "no"; row.dataset.of = usd(t.of);
      row.querySelector("i").style.width = `${month ? ((t.of / month) * 100).toFixed(2) : 0}%`;
      row.querySelector(".k-num").textContent = usd(t.of);
    });
    $("bill-tiers").dataset.volume = e.volume ? "yes" : "no";
    $("bill-benefit").textContent = `Demand a benefit of ${BILL.benefitRule} to 1: ${usd(e.benefit)} a year.`;
    return e;
  }
  // a slider and its box hold one number: moving either writes the other
  for (const key of Object.keys(RANGES)) {
    const range = $(`bill-${key}-range`), box = $(`bill-${key}`);
    range.addEventListener("input", () => { box.value = count(Number(range.value)); draw(); });
    box.addEventListener("input", () => { const n = Number(box.value.replace(/[,\s]/g, "")); if (Number.isFinite(n)) range.value = String(Math.round(n)); draw(); });
  }
  $("bill-plan").addEventListener("change", draw);
  $("bill-form").addEventListener("submit", (ev) => ev.preventDefault());
  draw();
  // the fee the program charges today, under the invoice: ctx.live is what web/fee_live.js answered (or will)
  if (ctx.live) { drawLive($("bill-live"), null, esc); Promise.resolve(ctx.live).then((live) => drawLive($("bill-live"), live, esc)).catch(() => { $("bill-live").hidden = true; }); }
  return { draw };
}

export function initPricing(ctx) {
  const { $, esc, knos, RPC, ids } = ctx;
  // every fee on this page is the fee of the build that is LIVE: this tree's rule until the program (or upgrades.json)
  // has answered, then drawn again by the rule it named, with one line for the next upgrade when the two differ
  let c = priceConstants();
  const live = ctx.live || Promise.resolve().then(async () => liveFee({ knos, rpc: RPC, program: (await Promise.resolve(ids()).catch(() => null))?.knos_pay ?? null }));
  // the calculator leads the view: in the place index.html gives it (id "bill"), or else above the first card
  let bill = $("bill");
  const view = $("view-pricing");
  if (!bill && view) { bill = document.createElement("div"); bill.id = "bill"; bill.className = "k-card"; view.insertBefore(bill, view.querySelector(".card, .k-card")); }
  renderPricing(bill, { ...ctx, live });
  // the price book: its rows are written here from price.js, in the book's own words (docs/MARKET.md, "The price book"),
  // as many columns as the page's table has, and the rule it is published with (id "price-rule")
  const set = (id, words) => { const el = $(id); if (el) el.textContent = words; };
  const table = $("price-book"), book = table?.querySelector("tbody"), columns = table?.querySelectorAll("thead th").length || 3;
  if (book) book.innerHTML = priceBook().map((row) => `<tr><th scope="row">${esc(row[0])}</th>${row.slice(1, columns).map((cell) => `<td>${esc(cell).replace(/`([^`]+)`/g, "<code>$1</code>")}</td>`).join("")}</tr>`).join("");
  set("price-rule", RULE);
  // the book's on-chain cell follows the build that is LIVE: "today" and "after the next upgrade" while knos_pay 2.1
  // runs, the book's one rule once Version is 2 (price.js, enforcedNow). Until somebody has answered it says so.
  const enforced = columns >= 5 ? book?.querySelector("tr:nth-child(3) td:last-child") : null;
  function drawEnforced(answered) {
    if (!enforced) return;
    enforced.dataset.fee = answered ? c.fee.release : ""; enforced.dataset.live = answered && c.fee.live ? "1" : "0";
    enforced.textContent = enforcedNow(answered ? c : null);
  }
  drawEnforced(false);
  // three releases worked: one step each under one rate, the steps of each tier under the 0.3.14 rule
  const how = (whole) => (c.tiered ? feeParts(whole * 1e6, c.feeBps, c).filter((part) => part.of).map((part) => `${rateOf(part.bps)} of ${count(part.of / 1e6)}`).join(" + ") : `${rateOf(c.feeBps)} of ${count(whole)}`);
  function drawRule() {
    set("price-bounds", `${plain(c.minAmount)} to ${count(c.maxAmount / 1e6)}`);
    drawEffective($, esc, c);
    const worked = $("fee-worked")?.querySelector("tbody");
    if (worked) worked.innerHTML = WORKED.map((whole) => `<tr data-amount="${whole}"><th scope="row">${count(whole)}</th><td>${how(whole)}</td><td>${plain(orderFee(whole * 1e6, c.feeBps, c))}</td></tr>`).join("");
    for (const id of ["calc-settle", "arithmetic"]) if ($(id)) $(id).dataset.fee = c.fee.release;
    set("fee-how", `${c.tiered ? "Each part of the amount pays its tier's rate" : "One rate applies to the whole amount"}, and the fee is never under the floor. The funder pays the fee on top; the payee receives the amount in full.`);
    set("price-honest-now", c.tiered ? `Until knos_pay 2.2 is live the program charges the ${c.fee.release} fee: ${feeRate(c)}. From 2.2: ` : "");
  }
  drawRule();

  // how the fee was reached: the rate, or the floor when the floor is the fee
  function feeNote(amount, q) {
    const byRate = c.tiered ? feeParts(amount, q.bps, c).reduce((sum, part) => sum + part.fee, 0) : Math.floor((amount * q.bps) / 10_000);
    if (c.tiered && byRate >= c.feeMin) return `${feeParts(amount, q.bps, c).filter((part) => part.of).map((part) => `${rateOf(part.bps)} of ${show(part.of)}`).join(" + ")}; never under ${show(c.feeMin)}`;
    return byRate < c.feeMin ? `the floor: ${rateOf(q.bps)} of ${show(amount)} would be ${show(byRate)}, and the fee is never under ${show(c.feeMin)}`
      : `${rateOf(q.bps)} of ${show(amount)}; never under ${show(c.feeMin)}, and there is no cap`;
  }

  function drawSettle() {
    const out = $("calc-result"), amount = unitsOf($("calc-amount").value), rateText = $("calc-rate").value.trim(), bps = rateText ? bpsOf(rateText) : c.feeBps;
    const bad = (words) => { out.innerHTML = `<p class="status bad">${esc(words)}</p>`; };
    if (amount === null) return bad("Write the amount as a number like 20 or 7.5, with at most six decimals.");
    if (amount < c.minAmount) return bad(`A task takes at least ${show(c.minAmount)} test USDC.`);
    if (amount > c.maxAmount) return bad(`A task takes at most ${show(c.maxAmount)} test USDC on devnet.`);
    if (bps === null || bps < c.planBpsMin || bps > c.feeBps) return bad(`A contract rate is a percentage from ${rateOf(c.planBpsMin)} to ${rateOf(c.feeBps)}.`);
    const q = quote(amount, c, bps), row = (key, name, value, note = "") => `<tr data-key="${key}"><th scope="row">${name}</th><td>${show(value)}</td><td class="fine">${note}</td></tr>`;
    out.innerHTML = `<div class="table-wrap"><table id="calc-table"><tbody>
      ${row("funder", "The funder pays", q.funderPays, "the amount and the fee on top of it")}
      ${row("payee", "The payee receives", q.payeeReceives, "the posted amount, in full")}
      ${row("fee", "The fee, in all", q.fee, feeNote(amount, q))}
      ${row("tip", "of it, the relay's tip", q.tip, "never more than the fee")}
      ${row("knos", "of it, Knos's fee", q.knos, `${show(q.knosFirst)} on a payee's first payment`)}</tbody></table></div>
      ${next(amount, bps)}
      <p class="fine">The funder pays the fee on top. The payee pays nothing. Test USDC on devnet.</p>`;
  }
  // one line when the fee shown is not this tree's: what the same order pays after (or until) the next upgrade
  function next(amount, bps) {
    const n = feeNext(c, amount);
    if (!n) return "";
    const other = priceConstants(undefined, n.release === "0.3.18" ? FEE_VERSION : FEE_VERSION - 1), their = orderFee(amount, Math.min(bps, other.feeBps), other);
    return `<p id="calc-next" data-fee="${esc(n.release)}">${esc(n.label)}: <span class="k-num">${show(their)}</span> on this order.</p>`;
  }

  function drawMeter() {
    const out = $("meter-result"), text = $("meter-n").value.replace(/[,\s]/g, ""), n = /^\d{1,11}$/.test(text) ? Number(text) : null;
    if (n === null) { out.innerHTML = `<p class="status bad">Write a whole number of evaluations, like 250000.</p>`; return; }
    const m = meterCost(n), row = (key, name, value, note = "") => `<tr data-key="${key}"><th scope="row">${name}</th><td>${value}</td><td class="fine">${note}</td></tr>`;
    out.innerHTML = `<div class="table-wrap"><table id="meter-table"><tbody>
      ${row("free", "Free", count(m.free), `an organisation's first ${count(BILL.meterFree)} a month`)}
      ${row("billable", "Billable", count(m.billable))}
      ${row("list", "Cost at the price", usd(m.cost), `${BILL.meterPerThousandCents / 100_000} USD each`)}</tbody></table></div>
      <p class="fine">A retry or a duplicate is free. A rejection counts. Charged from prepaid credits.</p>`;
  }

  if ($("calc-form")) { $("calc-form").addEventListener("input", drawSettle); $("calc-form").addEventListener("submit", (ev) => ev.preventDefault()); drawSettle(); }
  live.then((answer) => { c = answer.c; drawRule(); drawEnforced(true); if ($("calc-form")) drawSettle(); }).catch(() => { drawEnforced(true); });
  if ($("meter-form")) { $("meter-form").addEventListener("input", drawMeter); $("meter-form").addEventListener("submit", (ev) => ev.preventDefault()); drawMeter(); }

  let said = false;
  return async function showVersion(upgrade = "") {
    if (said) return;
    said = true;
    const el = $("price-version-now");
    try { el.textContent = versionWords(await programVersion(knos, RPC, (await ids()).knos_pay), knos.FEE_MIN, c, upgrade); }
    catch { el.textContent = versionWords(null, knos.FEE_MIN, c); }
  };
}
