// L32 (IQ PLAN.md): the money lines of the status page, held to three rules (MISSION S18): a missing input is "not
// known", never 0; refundable money held in open jobs is held money, never revenue; a transfer between Knos's own
// accounts is counted once and is never revenue. The status page draws these rows from the jobs contract's get_totals
// (read by the browser from NEAR testnet); tests/test_honest_money.py holds the rules.
//
//   moneyRows(totals)            [[label, value or null]] from get_totals of one token (base units of 6 decimals)
//   cell(value)                  the shown text: a number with two decimals, or "not known"
//   transfersOnce(list, own)     {revenue, internal}: test dollars into Knos's fee account from outside its own accounts,
//                                and between its own accounts, each transaction counted once
(function (root) {
  const units = (x) => (x === null || x === undefined || x === "" || !Number.isFinite(+x)) ? null : +x / 1e6;
  function moneyRows(t) {
    const g = t || {};
    return [["Held in open jobs, refundable", units(g.open)], ["Paid out for passed work", units(g.paid)], ["Refunded", units(g.refunded)],
      // Knos's fee is not split out by get_totals: not known, rather than a figure made from the held money
      ["Knos's revenue", units(g.fee)]];
  }
  const cell = (v) => v === null || v === undefined || !Number.isFinite(+v) ? "not known" : (+v).toFixed(2);
  function transfersOnce(list, own) {
    const mine = new Set(own || []), seen = new Set();
    let revenue = 0, internal = 0;
    for (const x of list || []) {
      if (!x || seen.has(x.tx)) continue;
      seen.add(x.tx);
      const amount = units(x.amount);
      if (amount === null) continue;
      if (mine.has(x.from)) internal += amount; else revenue += amount;
    }
    return { revenue: Math.round(revenue * 1e6) / 1e6, internal: Math.round(internal * 1e6) / 1e6 };
  }
  const api = { moneyRows, cell, transfersOnce };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.KnosMoney = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
