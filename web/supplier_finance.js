// The supplier's finance lead: what is funded for this work, until when it can be accepted, what may be done about a
// refusal, and the day the money arrives. Read from the order's own account on devnet; nothing here needs a wallet.
//
//   readPasted(text)                  { order, tx } from what is pasted: Knos's funding comment, an explorer link, or the
//                                     order's address (a funding transaction, when one is named, is kept to link to)
//   financeOf(o, now[, given])        the four rows a finance lead reads, from knos.v2.readOrder's object `o` (null: no order
//                                     at that address) and `now` in seconds: { stage, rows: [{ id, title, value, detail, href }],
//                                     pay: { first, rest } }. given: { order, tx, cluster }
//   group(text)                       1500.00 as 1,500.00
//   SAMPLE                            a made-up order of 5,000.00 test USDC, for the sample button
//   renderSupplierFinance(el[, ctx])  the view in `el`. ctx, all optional: { knos } the client (web/settle.js is loaded when
//                                     left out), { rpc } the devnet URL, { ids } program_ids.json's object, { now } a Date.
//
// What each row rests on (sdk/settle/index.js readOrder; programs-v2/knos_pay): the amount is what the payees receive,
// escrowed at funding with the fee on top, so the supplier is never charged; `payUntil` is the last moment a passing run
// is paid, after which a refund returns the money to the funder; a holdback keeps holdbackBps of each payment for
// warrantyS seconds and then releases it unless the buyer reverts it inside that time with a signed failing run; an
// arbiter (arbiterId) or the neutral judge (F_NEUTRAL) hears an appeal (`/knos appeal <reason>`, src/knos/commands.py).
export const F_NEUTRAL = 4, MERGE = 0, TESTS = 1;
export const RPC = "https://api.devnet.solana.com";
const DAY = 86400;
export const group = (text) => String(text ?? "").replace(/^(-?)(\d{4,})/, (m, sign, whole) => sign + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ","));
const units = (n, decimals) => { const v = BigInt(n), base = 10n ** BigInt(decimals); return `${v / base}.${(v % base).toString().padStart(decimals, "0").slice(0, 2)}`; };
const when = (s) => new Date(s * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
const day = (s) => new Date(s * 1000).toISOString().slice(0, 10);
/** "9 days 4 hours" from a number of seconds (never below a minute). */
export function left(s) {
  if (s <= 0) return "closed";
  const d = Math.floor(s / DAY), h = Math.floor((s % DAY) / 3600), m = Math.max(1, Math.floor((s % 3600) / 60));
  const p = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  return d ? `${p(d, "day")} ${p(h, "hour")}` : h ? `${p(h, "hour")} ${p(m, "minute")}` : p(m, "minute");
}
const explorer = (kind, id, cluster = "devnet") => `https://explorer.solana.com/${kind}/${id}?cluster=${cluster}`;

const B58 = /[1-9A-HJ-NP-Za-km-z]+/g;
/** The order and its funding transaction in what was pasted. */
export function readPasted(text) {
  const words = String(text || "").match(B58) || [];
  const order = words.find((w) => w.length >= 32 && w.length <= 44) || "", tx = words.find((w) => w.length >= 64 && w.length <= 88) || "";
  return { order, tx };
}

/** The four rows: funded, acceptance window, appeal, payment date. */
export function financeOf(o, now, given = {}) {
  const cluster = given.cluster || "devnet", money = cluster === "devnet" ? "test USDC" : "USDC";
  if (!o) return { stage: "none", rows: [{ id: "funded", title: "Funded", value: "No order at this address", detail: "It was paid out, refunded, or never funded." }], pay: null };
  const dec = o.decimals ?? 6, amount = `${group(units(o.amount, dec))} ${money}`, keep = Math.round((o.holdbackBps || 0) / 100);
  const held = (BigInt(o.amount) * BigInt(o.holdbackBps || 0)) / 10000n, first = BigInt(o.amount) - held;
  const rows = [];
  rows.push({ id: "funded", title: "Funded", value: amount, detail: `Held for this work since funding. The funder paid the ${group(units(o.fee, dec))} fee on top.`,
    href: given.tx ? explorer("tx", given.tx, cluster) : given.order ? explorer("address", given.order, cluster) : "", link: given.tx ? "See the funding transaction" : given.order ? "See the order's account" : "" });
  const until = o.payUntil ?? o.deadline, open = o.state === "open";
  rows.push({ id: "window", title: "Acceptance window", value: open ? (now < until ? `${left(until - now)} left` : "Closed") : "Accepted",
    detail: open ? `${o.mode === TESTS ? "Passing checks pay without a merge" : "Merged passing work is paid"} until ${when(until)}. Then unpaid money returns to the funder.`
      : "The work was accepted; the window no longer applies.", countdown: open && now < until ? until : 0 });
  rows.push({ id: "appeal", title: "Appeal", value: o.arbiterId ? "An arbiter decides" : o.flags & F_NEUTRAL ? "A neutral judge decides" : "The checks run again",
    detail: `Refused? Comment /knos appeal with your reason, free.${o.arbiterId ? ` GitHub user id ${o.arbiterId} decides.` : o.flags & F_NEUTRAL ? " Another account runs the agreed checks again." : ""}` });
  let pay;
  if (open) {
    pay = { first: until, rest: keep ? until + (o.warrantyS || 0) : 0 };
    rows.push({ id: "payment", title: "Payment date", value: `The day the checks pass`, detail: keep
      ? `${group(units(first, dec))} ${money} at once; ${keep}% (${group(units(held, dec))}) ${Math.round((o.warrantyS || 0) / DAY)} days later. Latest: ${day(until + (o.warrantyS || 0))}.`
      : `All ${amount} at once. Latest: ${day(until)}.` });
  } else if (o.state === "warranty") {
    pay = { first: 0, rest: o.holdUntil };
    rows.push({ id: "payment", title: "Payment date", value: day(o.holdUntil), detail: `The rest arrives ${when(o.holdUntil)}, unless a failing run reverts it.` });
  } else if (o.state === "held") {
    pay = { first: 0, rest: o.holdUntil };
    rows.push({ id: "payment", title: "Payment date", value: "When the payee names an address", detail: `Accepted and held for the payee until ${when(o.holdUntil)}.` });
  } else rows.push({ id: "payment", title: "Payment date", value: "Unknown", detail: `The order reads as "${o.state}".` });
  return { stage: o.state, rows, pay };
}

// A made-up order: 5,000.00 test USDC, passing checks pay without a merge, 10% held 14 days, the neutral judge.
export const SAMPLE = { now: 1791446400, order: { state: "open", mode: TESTS, flags: F_NEUTRAL, decimals: 6, amount: 5_000_000_000, fee: 15_000_000, holdbackBps: 1000,
  warrantyS: 14 * DAY, arbiterId: 0, deadline: 1791446400 + 9 * DAY + 4 * 3600, payUntil: 1791446400 + 9 * DAY + 4 * 3600, holdUntil: 0, paid: 0 } };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STYLE = `.sf-rows{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:12px;margin:12px 0}
.sf-rows>div{border:1px solid var(--line);border-radius:var(--radius,12px);padding:12px 14px;background:var(--paper-2);min-width:0;overflow-wrap:anywhere}
.sf-rows .k-kicker{margin:0}.sf-rows .k-num{display:block;white-space:normal;overflow-wrap:anywhere;font-size:clamp(18px,4vw,24px);font-weight:700;line-height:1.2}.sf-rows p{margin:6px 0 0}
.sf-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.sf-row .k-btn{margin:0}.sf-row input{flex:1 1 220px;min-width:0;box-sizing:border-box}.sf-row+[data-sf=said]{margin-top:10px}
.sf-rows>div[data-row]{animation:sf-in var(--dur-2,240ms) var(--ease,ease)}@keyframes sf-in{from{opacity:0;translate:0 4px}}
@media (prefers-reduced-motion:reduce){.sf-rows>div[data-row]{animation:none}}`;

/** Draw the finance lead's view in `el`. */
export function renderSupplierFinance(el, ctx = {}) {
  const doc = el.ownerDocument, win = doc.defaultView;
  if (!doc.getElementById("sf-style")) { const s = doc.createElement("style"); s.id = "sf-style"; s.textContent = STYLE; doc.head.appendChild(s); }
  const h = el.closest(".supplier") ? "h3" : "h2";      // a section of the supplier page, or a page of its own (#payee)
  el.innerHTML = `<${h}>See when you are paid</${h}>
    <form class="sf-row" data-sf="in" novalidate><input type="text" id="sf-order" aria-label="The funding comment, or the order's address" placeholder="Paste the funding comment, or the order's address" spellcheck="false" autocomplete="off">
      <button type="submit" class="k-btn" data-sf="read">Read</button> <button type="button" class="k-btn quiet" data-sf="sample">Try the sample</button></form>
    <p data-sf="said" role="status" aria-live="polite"></p>
    <div class="sf-rows" data-sf="rows"></div>
    <p class="fine">Read from the order's account on devnet. Nothing to install or sign.</p>`;
  const $ = (n) => el.querySelector(`[data-sf="${n}"]`), said = (t) => { $("said").textContent = t; };
  let shown = null, timer = 0;
  const nowS = () => Math.floor((ctx.now ? ctx.now.getTime() : Date.now()) / 1000);
  const draw = (o, now, given, words) => {
    shown = { o, given };
    const got = financeOf(o, now, given);
    $("rows").innerHTML = got.rows.map((r) => `<div data-row="${r.id}"><p class="k-kicker">${esc(r.title)}</p><span class="k-num" data-sf-value>${esc(r.value)}</span>
      <p>${esc(r.detail)}</p>${r.href ? `<p><a href="${esc(r.href)}" target="_blank" rel="noopener">${esc(r.link)}</a></p>` : ""}</div>`).join("");
    said(words);
    win.clearInterval(timer);
    const end = got.rows.find((r) => r.countdown)?.countdown;
    // the countdown is a state that changes: it is redrawn once a minute while the view is on the page, and stops after
    if (end && !ctx.now) timer = win.setInterval(() => { if (!el.isConnected) return win.clearInterval(timer); const v = el.querySelector('[data-row="window"] [data-sf-value]'); if (v) v.textContent = `${left(end - nowS())} left`; }, 60_000);
    return got;
  };
  async function read(text) {
    const given = readPasted(text);
    if (!given.order) { said("Paste the funding comment, or the order's address."); return null; }
    said("Reading the order.");
    try {
      const knos = ctx.knos || (await import("./settle.js")), ids = ctx.ids || (await fetch(new URL("./program_ids.json", import.meta.url)).then((r) => r.json()));
      const info = await knos.accountInfo(ctx.rpc || RPC, given.order), o = info && info.owner === ids.knos_pay ? knos.v2.readOrder(info.data) : null;
      return draw(o, nowS(), given, o ? "Read from devnet. Test money." : "No order at that address.");
    } catch { said("Devnet could not be read. Try again."); return null; }
  }
  const sample = () => draw(SAMPLE.order, SAMPLE.now, {}, "Sample: a made-up order of test money.");
  $("in").addEventListener("submit", (ev) => { ev.preventDefault(); read(el.querySelector("#sf-order").value); });
  $("sample").addEventListener("click", sample);
  return { read, sample, shown: () => shown };
}
