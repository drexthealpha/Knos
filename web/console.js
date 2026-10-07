// Console: what the person who authorises a payment has to see before funding and has to defend after. web/buyer.js
// draws the Buy page and calls these; nothing here touches the page. Each function takes what was read (a Balance and
// its side account from devnet, the organisation's order statement from this site, an order's log lines) and returns
// words: the fee as an amount and as a share of the order, whether a funding would pass the organisation's budget and
// which rule decides, the earlier orders and payments for the same issue, the orders that wait for a person, and the
// five parts of a receipt. Money is test USDC, in millionths, as the programs hold it.
//
// The budget's rules are the program's own, in its order (programs-v2/knos_pay/src/order.rs fund_order_balance and
// fund.rs may_spend, spend_x): who may spend, the cap per order (on the amount), the allowed repositories, the daily
// and the total limit (on the amount and its fee), then what the Balance holds. web/controls_data.js decides it with
// `explainFunding`, the decision of `knos budget check`; `explainLocal` below reads the same rules for what that file
// is not handed (what the Balance holds now), and its answer stands when the two disagree toward refusing.
import { quote, show, percent, feeNote } from "./price.js";
import * as rules from "./controls_data.js";
import * as proc from "./procure.js";

export const SMALL = 20_000_000;          // under this the page warns: the minimum fee is a large share of a small order

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const code = (s) => esc(s).replace(/`([^`]*)`/g, "<code>$1</code>");
const when = (t) => `${new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC`;
const short = (a) => `${String(a).slice(0, 6)}…`;
/** A fee as a share of the amount, to two decimals: 400000 of 5000000 -> "8.00%". */
export const share = (fee, amount) => `${((fee * 100) / amount).toFixed(2)}%`;

/** web/controls_data.js: `explainFunding` and `feeTable`, the same decisions and the same table as the Python's. */
export const controls = rules;

// ---- 1. the fee, before funding --------------------------------------------------------------------------------------------------------
/** What an order of `units` costs its funder: { fee, pays, pct, words, warning, note }. `c`: priceConstants of the live build (web/fee_live.js). `warning` is "" from 20 test USDC up. */
export function feeView(units, c) {
  const q = quote(units, c), pct = share(q.fee, units), least = quote(c.minAmount, c);
  const binds = Math.ceil((c.feeMin * 10_000) / c.feeBps);        // below this the minimum is the fee
  const words = `You pay ${show(q.funderPays)} test USDC: ${show(q.amount)} for whoever does the work, and a fee of ${show(q.fee)} on top, which is ${pct} of the amount. The person paid receives the whole ${show(q.amount)}.`;
  const warning = units >= SMALL ? "" : `A small order pays a high fee. The fee is never less than ${show(c.feeMin)} test USDC, so under ${show(binds)} it is more than ${percent(c.feeBps)}: an order of ${show(c.minAmount)} costs ${share(least.fee, c.minAmount)}. `
    + `This order's fee is ${pct}. Small purchases are cheaper pooled into one order with milestones, or bought at a standing rate.`;
  // which rule the number is (the fee follows the build that is live), and what an older order keeps
  return { fee: q.fee, pays: q.funderPays, pct, words, warning, note: feeNote(units, c) };
}

// ---- 2. is this allowed: the organisation's budget ---------------------------------------------------------------------------------------
const u64 = (n) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(n), true); return b; };

/** Every Balance the GitHub owner `ownerId` has on devnet: [{ address, balance, balx, holds }], from one getProgramAccounts
 *  (the owner's id is at byte 8 of a Balance) and one read of each Balance's token account and side account. */
export async function readBudgets(knos, rpc, ids, ownerId) {
  const k = knos.v2.client(ids), found = await knos.programAccounts(rpc, ids.knos_pay, knos.v2.BALANCE_LEN, 8, u64(ownerId));
  const out = [];
  for (const f of found) {
    const balance = knos.v2.readBalance(f.data);
    if (!balance || balance.ownerId !== ownerId) continue;
    const [tok, side] = await knos.accounts(rpc, [await k.baltok(f.address), await k.balxPda(f.address)]);
    out.push({ address: f.address, balance, balx: side ? knos.v2.readBalx(side.data) : null, holds: tok ? knos.readTokenAccount(tok.data).amount : 0 });
  }
  return out.sort((a, b) => Number(a.balance.faucet) - Number(b.balance.faucet) || (a.address < b.address ? -1 : 1));
}

/** What is left of a Balance's limits at `now`: { cap, dayLeft, totalLeft } in units; null where there is no limit. */
export function remaining(balance, balx, now) {
  const today = balx && balx.day === Math.floor(now / 86_400) ? balx.daySpent : 0;
  return { cap: balance.capPerJob || null, dayLimit: balx?.dayLimit || null, totalLimit: balx?.totalLimit || null,
    dayLeft: balx?.dayLimit ? Math.max(0, balx.dayLimit - today) : null, totalLeft: balx?.totalLimit ? Math.max(0, balx.totalLimit - balx.totalSpent) : null };
}

/** The rules by the names web/controls_data.js gives them (its RULES), in the words the page shows. */
export const RULE_WORDS = { owner: "the repository's owner", spender: "who may spend", cap: "the cap per order", repository: "the allowed repositories", workflows: "the pinned workflows",
  day: "today's limit", total: "the total limit", funds: "what the Balance holds", amount: "the amount an order can take", faucet: "the devnet faucet", ok: "none: every limit lets it through" };
const asPct = (p) => (typeof p === "number" ? `${p.toFixed(2)}%` : p ? `${String(p).replace(/%$/, "")}%` : "");

/** Whether funding `amount` from this Balance would pass, and the rule that decides: { ok, rule, sentence, fee, effectivePct }.
 *  `byId`: the GitHub id of whoever posts the comment (0: not known, so that rule is not judged). `holds`: the Balance's money. */
export function explainLocal({ balance, balx, repoId, amount, byId = 0, holds = null, now = Math.floor(Date.now() / 1000) }, c) {
  const q = quote(amount, c), total = q.funderPays, left = remaining(balance, balx, now), m = (u) => `${show(u)} test USDC`;
  const out = (ok, rule, sentence) => ({ ok, rule, sentence, fee: q.fee, effectivePct: share(q.fee, amount) });
  if (balance.faucet) return out(amount <= 100_000_000, "faucet", amount <= 100_000_000 ? "Passes: this is the devnet faucet's Balance, test money any commenter can use, at most 100.00 per comment."
    : `Would be refused by the devnet faucet: it gives at most 100.00 test USDC per comment, and this order is ${show(amount)}.`);
  if (byId && byId !== balance.ownerId && !balance.spenders.includes(byId))
    return out(false, "spender", `Would be refused by who may spend: GitHub id ${byId} is not the owner (id ${balance.ownerId}) and is not one of the spenders the Balance's wallet listed.`);
  if (left.cap && amount > left.cap) return out(false, "cap", `Would be refused by the cap per order: the cap is ${m(left.cap)}, and this order is ${show(amount)}.`);
  if (balx?.repos.length && !balx.repos.includes(repoId)) return out(false, "repository", `Would be refused by the allowed repositories: repository ${repoId} is not one of the ${balx.repos.length} this Balance may fund.`);
  if (left.dayLeft !== null && total > left.dayLeft) return out(false, "day", `Would be refused by today's limit: ${m(left.dayLeft)} of ${show(left.dayLimit)} is left today, and this order takes ${show(total)} with its fee.`);
  if (left.totalLeft !== null && total > left.totalLeft) return out(false, "total", `Would be refused by the total limit: ${m(left.totalLeft)} of ${show(left.totalLimit)} is left in all, and this order takes ${show(total)} with its fee.`);
  if (holds !== null && total > holds) return out(false, "funds", `Would be refused by what the Balance holds: it holds ${m(holds)}, and this order takes ${show(total)} with its fee.`);
  const decides = left.dayLeft !== null || left.totalLeft !== null || left.cap ? "the limits below" : "what the Balance holds (it has no cap and no limit)";
  return out(true, "ok", `Passes: ${show(total)} test USDC with its fee is inside ${decides}${byId ? "" : ", for a comment by the owner or a listed spender"}.`);
}

/** One Balance as the page shows it: the verdict, then the budget as facts. `why`: explainFunding's or explainLocal's answer. */
export function budgetHtml(b, why, now, explorer) {
  const left = remaining(b.balance, b.balx, now), m = (u) => `${esc(show(u))} test USDC`, x = b.balx;
  const pct = asPct(why.effectivePct), rule = RULE_WORDS[why.rule] || String(why.rule);
  const who = b.balance.faucet ? "any commenter (the devnet faucet)" : `the owner (GitHub id ${b.balance.ownerId})${b.balance.spenders.length ? ` and GitHub id${b.balance.spenders.length > 1 ? "s" : ""} ${b.balance.spenders.join(", ")}` : "; no other spender is listed"}`;
  return `<div class="receipt" data-ok="${why.ok ? 1 : 0}" data-rule="${esc(why.rule)}"><strong class="status ${why.ok ? "ok" : "bad"}">${esc(why.sentence)}</strong></div>
    <dl class="facts"><dt>Balance</dt><dd><a class="mono" href="${esc(explorer("address", b.address))}" target="_blank" rel="noopener">${esc(short(b.address))}</a> holds ${m(b.holds)}</dd>
      <dt>Rule that decides</dt><dd data-part="rule">${esc(rule)}</dd>
      <dt>Cap per order</dt><dd data-part="cap">${left.cap ? m(left.cap) : "none"}</dd>
      <dt>Left today</dt><dd data-part="day">${left.dayLeft === null ? "no daily limit" : `${m(left.dayLeft)} of ${esc(show(left.dayLimit))}`}</dd>
      <dt>Left in all</dt><dd data-part="total">${left.totalLeft === null ? "no total limit" : `${m(left.totalLeft)} of ${esc(show(left.totalLimit))}`}</dd>
      <dt>Allowed repositories</dt><dd data-part="repos">${x?.repos.length ? `only GitHub repository id${x.repos.length > 1 ? "s" : ""} ${esc(x.repos.join(", "))}` : "any repository of the owner"}</dd>
      <dt>Who may spend</dt><dd data-part="who">${esc(who)}</dd>
      <dt>Fee on this order</dt><dd data-part="fee">${esc(typeof why.fee === "number" ? show(why.fee) : why.fee)} test USDC${pct ? `, ${esc(pct)} of the amount` : ""}</dd></dl>`;
}

// ---- 3. was this billed before ------------------------------------------------------------------------------------------------------------
const WORDS = { paid: "paid", released: "holdback released", kill: "kill fee paid", refunded: "refunded", reverted: "reverted", open: "funded, not paid yet", held: "accepted, held for a wallet" };
/** Every line of an organisation's statement file (audit/<id>.json), each once, oldest first. A line of an order still
 *  open is repeated in every month it stays open: the latest stands, and it goes once the order is paid or sent back. */
export function linesOf(file) {
  const seen = new Map();
  for (const month of Object.keys(file?.months || {}).sort()) for (const r of file.months[month].lines || []) seen.set(`${r.order}:${r.kind}:${r.transaction}`, r);
  const all = [...seen.values()].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  // "open" and "held" say what an order was at a month's end: once a later line of the order exists, that line says it
  return all.filter((r, n) => !(r.kind === "open" || r.kind === "held") || !all.slice(n + 1).some((x) => x.order === r.order));
}

/** The earlier orders and payments for one repository and issue: { rows, paid, privates }. A row: { date, order, kind,
 *  words, milestone, pullRequest, amount, transaction, funded }. The deliverable is the order and its milestone: the
 *  milestone of a standing order is the pull request, any other order has one, 0 (src/knos/audit.py, billing_key). */
export function earlierOf(lines, repoId, issue) {
  const rows = lines.filter((r) => Number(r.repository_id) === repoId && Number(r.issue) === issue).map((r) => {
    const milestone = r.billing_key ? Number(String(r.billing_key).split(":")[2] || 0) : Number(r.standing) ? Number(r.pull_request || 0) : 0;
    const amount = Number(r.paid_units) || Number(r.refunded_units) + Number(r.reverted_units) || Number(r.price_units);
    return { date: r.date, order: r.order, kind: r.kind, words: WORDS[r.kind] || r.kind, milestone, pullRequest: Number(r.pull_request) || 0, amount, currency: r.currency, transaction: r.transaction, funded: r.funded_transaction };
  });
  return { rows, paid: rows.filter((r) => r.kind === "paid").length, privates: new Set(lines.filter((r) => Number(r.private)).map((r) => r.order)).size };
}

/** The answer in words, and the rows: `live` are orders found on devnet for the issue that the statement does not list. */
export function earlierHtml(found, live, name, explorer) {
  const tx = (t, label) => (/^[1-9A-HJ-NP-Za-km-z]{60,90}$/.test(t || "") ? `${label} <a href="${esc(explorer("tx", t))}" target="_blank" rel="noopener">${esc(t.slice(0, 8))}…</a>` : "");
  const order = (a) => `<a class="mono" href="${esc(explorer("address", a))}" target="_blank" rel="noopener">${esc(short(a))}</a>`;
  const listed = new Set(found.rows.map((r) => r.order)), extra = live.filter((o) => !listed.has(o.address)), n = new Set([...listed, ...extra.map((o) => o.address)]).size;
  const verdict = found.paid ? `Yes. ${esc(name)} was billed before: ${found.paid} payment${found.paid > 1 ? "s" : ""} on ${n} order${n > 1 ? "s" : ""}. Funding again buys the same issue a second time.`
    : n ? `Not paid yet, but ${n} order${n > 1 ? "s" : ""} for ${esc(name)} exist${n > 1 ? "" : "s"} already. Funding again makes another order for the same work.`
      : `No. No earlier order or payment for ${esc(name)} is in the organisation's statement on this site or among its open orders on devnet.`;
  const rows = [...found.rows.map((r) => `<li data-kind="${esc(r.kind)}">${esc(r.date)}: <strong>${esc(r.words)}</strong>, ${esc(show(r.amount))} ${esc(r.currency)}${r.pullRequest ? `, pull request #${esc(r.pullRequest)}` : ""}. Deliverable: order ${order(r.order)}, milestone ${esc(r.milestone)}.
      ${[tx(r.transaction, r.kind === "open" ? "Funded in" : "Transaction"), r.transaction === r.funded ? "" : tx(r.funded, "funded in")].filter(Boolean).join("; ")}</li>`),
  ...extra.map((o) => `<li data-kind="live">On devnet now: <strong>${esc(o.state === "open" ? "funded, not paid yet" : o.state)}</strong>, ${esc(show(o.amount))} test USDC, ${esc(show(o.paid))} paid so far. Deliverable: order ${order(o.address)}, milestone 0. ${tx(o.fundedTx, "Funded in")}</li>`)];
  return `<div class="receipt" data-billed="${found.paid ? 1 : 0}" data-orders="${n}"><strong class="status ${found.paid || n ? "bad" : "ok"}">${verdict}</strong></div>
    ${rows.length ? `<ul class="plain" id="buy-before-rows">${rows.join("")}</ul>` : ""}
    <p class="fine" data-fold="Why two orders can buy one thing">The program pays one order's milestone once, whatever is sent to it. What it cannot know is that two orders buy the same thing: that is what this list is for.${found.privates ? ` ${found.privates} private order${found.privates > 1 ? "s" : ""} of the organisation name no repository in public and cannot be matched here.` : ""}</p>`;
}

// ---- 4. private and limited cases -----------------------------------------------------------------------------------------------------------
/** The panel for work in a private repository. `why`: "template" (the terms are private-attested), "github" (GitHub says
 *  the repository is private) or "hidden" (GitHub shows no public repository of that name). */
export function privateHtml(why) {
  const lead = { template: "These terms are for a private repository.", github: "GitHub says this repository is private.",
    hidden: "GitHub shows no public repository at that address. If it is private, this applies to it." }[why];
  return `<h4>Private work: what the supplier can and cannot do alone</h4>
    <p><strong>${esc(lead)}</strong> Read this before you fund, and show it to the supplier.</p>
    <dl class="parts"><dt>The supplier cannot settle alone</dt><dd>On a public repository a supplier can have the work judged and be paid without you. On a private one they cannot: only a run of your own workflow, in a repository you control, can say the work was accepted. If that run never happens, the supplier waits and the money goes back to you at the deadline.</dd>
      <dt>The evidence is where you control access</dt><dd>The run's log and the pull request stay in your private repository. The chain holds a hash and the payment, not the evidence. If you remove the supplier's access, they can no longer read what the acceptance was based on.</dd>
      <dt>Name an arbiter at funding, if that matters</dt><dd>An order can name one GitHub account as arbiter when it is funded, and only then: add <code>arbiter @their-account</code> to the funding comment. That account can rule on the order if the two of you disagree. It is one account, and it can rule wrongly or not at all. Agree on it with the supplier before the work starts; it cannot be added later.</dd>
      <dt>What Knos does not give here</dt><dd>A neutral evaluator with its own access to a private repository, or a copy of the evidence kept for the supplier. Neither exists today.</dd></dl>`;
}

// ---- 5. exceptions: the orders that need a person ------------------------------------------------------------------------------------------
/** The orders that wait for somebody. `lines`: linesOf a statement file (already narrowed to one repository, if one was
 *  asked for); `live`: Map of order address -> knos.v2.readOrder of its account now (null: the account is closed; no
 *  entry: devnet was not asked); `now`: the chain's time; `refused`: how many tokens the relay refused at a merge, when
 *  the site's file of the repository says (null: it does not). Rows: { kind, order, where, what, action, who, tx }. */
export function exceptionsOf({ lines, live = new Map(), now, refused = null, repo = "" }) {
  const groups = new Map();
  for (const r of lines) (groups.get(r.order) || groups.set(r.order, []).get(r.order)).push(r);
  const rows = [];
  for (const [order, g] of groups) {
    const o = live.get(order), known = live.has(order), last = g[g.length - 1], has = (kind) => g.find((r) => r.kind === kind);
    const where = Number(last.private) ? "a private order" : `repository ${last.repository_id}, issue #${last.issue}`;
    const add = (kind, what, action, who, tx = last.transaction) => rows.push({ kind, order, where, what, action, who, tx });
    const held = has("held"), paidHeld = g.find((r) => r.kind === "paid" && Number(r.held_units) > 0), ruled = g.find((r) => /arbiter ruling/.test(r.exception || ""));
    if (o?.state === "held" || (held && !has("paid") && !(known && !o)))
      add("held", `Accepted, but not paid: the payee (GitHub id ${held?.supplier_ids || o?.payeeId}) has bound no wallet. ${show(Number(held?.held_units ?? o.amount - o.paid))} test USDC waits${o?.holdUntil ? ` until ${when(o.holdUntil)}` : ""}.`,
        "Bind a wallet on the Get paid page. Then anyone can settle the order.", "the payee", held?.transaction);
    else if (o?.state === "warranty" || (paidHeld && !has("released") && !has("reverted") && !(known && !o))) {
      const over = o?.holdUntil && o.holdUntil <= now, share_ = show(Number(o ? o.amount - o.paid : paidHeld.held_units));
      add("review", `Paid, with ${share_} test USDC held back in the review window${o?.holdUntil ? `, which ${over ? "ended" : "ends"} ${when(o.holdUntil)}` : ""}.`,
        over ? "Release the held share to the supplier." : "If the accepted change is reverted before the window ends, run the revert so the held share comes back. Otherwise do nothing.",
        over ? "anyone" : "a signed run of the order's repository, or of its judge", paidHeld?.transaction);
    }
    const reverted = has("reverted");
    if (reverted) add("reverted", `Reverted inside the warranty: ${show(Number(reverted.reverted_units))} test USDC went back to the funder.`,
      "Decide with the supplier whether the work is redone. A new order is needed to pay for it again.", "the buyer and the supplier", reverted.transaction);
    if (ruled) add("challenged", "Challenged, and decided by the arbiter the order named at funding.", "Nothing on chain: the ruling stands for this order. File it with the contract.", "the buyer", ruled.transaction);
    if (o?.state === "open") {
      const left = show(o.amount - o.paid), due = o.grace && Number.isFinite(o.payUntil) ? o.payUntil : o.deadline;      // the refund opens after the grace, when the order has one
      if (o.cancelAt) add("cancelled", `Cancelled by its funder: it ends ${when(o.cancelAt)}, and ${left} test USDC goes back then.`, o.cancelAt <= now ? "Send the refund." : "Wait for the notice to end, then send the refund.", "anyone");
      else if (o.deadline <= now && due > now) add("grace", `Past its deadline (${when(o.deadline)}), inside its 2 hours' grace: a signed acceptance can still pay until ${when(due)}.`, "Wait for the grace to end, then send the refund.", "anyone");
      else if (due <= now) add("refundable", `Past its deadline (${when(o.deadline)})${o.grace ? ` and its grace (${when(due)})` : ""} and unpaid: ${left} test USDC can go back to the funder.`, "Send the refund. The money can only go back to where it came from.", "anyone");
      else if (o.reservedBy && o.reservedUntil <= now) add("stale", `Reserved by GitHub id ${o.reservedBy}, and the reservation ran out ${when(o.reservedUntil)} with nothing delivered.`,
        `Ask them, or let someone else take it: the order is open to any supplier again until ${when(o.deadline)}.`, "the buyer");
    }
  }
  if (refused) rows.push({ kind: "refused", order: "", where: repo || "this repository", what: `${refused} token${refused > 1 ? "s were" : " was"} refused by the relay at a merge: a payment or a proof that the program or the relay would not accept. This site keeps the count; the reason is in the relay's answer on each pull request.`,
    action: "Read the relay's answer on the pull request, fix what it names, and run the workflow again.", who: "the supplier", tx: "" });
  return rows;
}

const KIND = { grace: "Past deadline, in grace", held: "Held for a wallet", review: "In a review window", reverted: "Reverted", challenged: "Challenged", cancelled: "Cancelled", refundable: "Past deadline, refundable", stale: "Reserved and stale", refused: "Refused tokens" };
export function exceptionsHtml(rows, explorer, scope) {
  if (!rows.length) return `<p class="status ok" id="buy-exc-none">Nothing waits for a person: no order of ${esc(scope)} is held, in a review window, reverted, past its deadline or stale.</p>`;
  const tx = (t) => (/^[1-9A-HJ-NP-Za-km-z]{60,90}$/.test(t || "") ? ` <a href="${esc(explorer("tx", t))}" target="_blank" rel="noopener">${esc(t.slice(0, 8))}…</a>` : "");
  return `<p><strong id="buy-exc-count">${rows.length} thing${rows.length > 1 ? "s" : ""} need${rows.length > 1 ? "" : "s"} a person.</strong></p>
    <div id="buy-exc-rows">${rows.map((r) => `<div class="receipt exception" data-kind="${esc(r.kind)}"><span class="pill">${esc(KIND[r.kind])}</span>
      <span>${esc(r.where)}${r.order ? `, order <a class="mono" href="${esc(explorer("address", r.order))}" target="_blank" rel="noopener">${esc(short(r.order))}</a>` : ""}</span>
      <dl class="parts">
      <dt>What happened</dt><dd data-part="what">${esc(r.what)}${tx(r.tx)}</dd>
      <dt>What resolves it</dt><dd data-part="action">${esc(r.action)}</dd>
      <dt>Who can do it</dt><dd data-part="who">${esc(r.who)}</dd></dl></div>`).join("")}</div>`;
}

// ---- 6. the result: five parts, and who answers -------------------------------------------------------------------------------------------
export const PARTS = ["What the issuer authenticated", "What the evaluator observed", "Which policy produced the verdict", "Who authorised the money, and under which limit", "What trust remains"];
export const ANSWERS = "Today the founder alone. There is no support contract, no on-call team and no service-level agreement, and nobody else to call. "
  + "The money does not wait on that person: a refund after the deadline, the release of a holdback and the settling of a held payment can each be sent by anyone.";
const JUDGES = { 0: "the order's own repository", 1: "a neutral run, started by hand by the owner of the repository it ran in", 2: "the judge repository the order named",
  3: "the arbiter the order named", 9: "no token: a payment the program had already accepted" };

/** The five parts of an accepted order's receipt, one line each, from its account (`o`, null when closed) and its log
 *  lines (`events`, each with `tx`): [[heading, html]]. `tx(sig)` makes a transaction's link; `trusted`: the template's list. */
export function receiptParts(o, events, tx, trusted = null) {
  const first = (name) => events.find((e) => e.event === name), accepted = first("paid") || first("held"), funded = first("funded");
  const settled = [...events].reverse().find((e) => e.event === "settled"), by = Number(funded?.by ?? o?.funderId ?? 0);
  const source = funded?.source || o?.source || "", fromBalance = o ? o.fromBalance : by > 0;
  const authorised = !funded && !o ? "The funding is not in the part of the log this page read."
    : fromBalance ? `GitHub id ${esc(by)} funded it by comment, from the organisation's Balance <span class="mono">${esc(short(source))}</span>. The program checked that Balance's cap per order, daily limit, total limit, repositories and spenders in the funding itself${funded ? `, ${tx(funded.tx)}` : ""}: a funding outside them does not exist.`
      : `The wallet <span class="mono">${esc(short(source))}</span> signed the funding itself${funded ? `, in ${tx(funded.tx)}` : ""}. No organisation's budget was involved: the limit was what that wallet held.`;
  return [
    [PARTS[0], `GitHub signed a token for one run of the pinned workflow${o ? ` at commit <code>${esc(o.wfSha.slice(0, 7))}</code>` : ""}. The verifier program checked that signature on chain before the money moved, in ${tx(accepted.tx)}.`],
    [PARTS[1], `Verdict: accepted${Number(accepted.pr) ? `, for pull request #${esc(accepted.pr)}` : ""}. Judged by ${esc(JUDGES[settled?.judge] || "the order's judge")}. The run's own log stays on GitHub; the chain holds the verdict.`],
    [PARTS[2], `The terms fixed at funding${o ? `, hash <span class="mono">${esc(o.terms)}</span>` : funded ? `, in ${tx(funded.tx)}` : ""}. Nobody could change them after.`],
    [PARTS[3], authorised],
    [PARTS[4], trusted?.length ? `<ul>${trusted.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : "GitHub's signing key, the pinned workflow's code, and Knos's upgrade multisig."],
  ];
}

// ---- 7. one order as four linked objects: what a finance reader sees on one screen ----------------------------------------------------------
// `rec` is one record of web/finance_data.js recordsOf (audit.record in the Python): authorisation, acceptance,
// commercial record, settlement status. Each is a card of at most six labelled values; the chip is the settlement
// status in the five words every document uses; under Acceptance stands what is still trusted. Nothing here is
// worked out again: every value is the record's own.
export const OBJECT_NAMES = { authorisation: "Authorisation", acceptance: "Acceptance", commercial: "Commercial record", settlement: "Settlement status" };
/** finance_data.js SETTLEMENTS -> the settlement words: paid outside Knos, payable, held, refunded, devnet demonstration.
 *  A payment on devnet is test money, so it is a demonstration, never "paid"; a revert sends money back, as a refund does. */
export const CHIP = { "paid on devnet (test money)": "devnet demonstration", held: "held", refunded: "refunded", reverted: "refunded", payable: "payable", "paid outside Knos": "paid outside Knos" };
export const chipOf = (rec) => CHIP[rec?.settlement?.status] || "held";
const cut = (v, n = 10) => { const t = String(v ?? ""); return t.length > n + 6 ? `${t.slice(0, n)}…${t.slice(-4)}` : t; };
const units = (u, cur) => (cur === "test USDC" ? `${show(Number(u))} test USDC` : `${u} units of ${cur}`);

/** [[label, html]] of each object, six at most: { authorisation, acceptance, commercial, settlement }. `explorer(kind, id)` makes a link. */
export function objectValues(rec, explorer) {
  const a = rec.authorisation, c = rec.acceptance, m = rec.commercial, s = rec.settlement, cur = m.currency;
  const tx = (e) => `<a href="${esc(explorer("tx", e.transaction))}" target="_blank" rel="noopener">${esc(e.what)}</a>`;
  const none = `<span class="fine">none</span>`;
  return {
    authorisation: [
      ["Buyer", `GitHub id ${esc(a.buyer.owner_id)}${a.buyer.login ? ` (${esc(a.buyer.login)})` : ""}`],
      ["Supplier", a.supplier.length ? a.supplier.map((x) => `GitHub id ${esc(x.github_id)}`).join(", ") : `<span class="fine">nobody yet</span>`],
      ["Scope", a.scope.private ? "a private order" : `repository ${esc(a.scope.repository_id)}, issue #${esc(a.scope.issue)}`],
      ["Budget", `${esc(a.budget.kind)}${a.budget.address ? ` <span class="mono" title="${esc(a.budget.address)}">${esc(cut(a.budget.address, 6))}</span>` : ""}`],
      ["Approved by", `${esc(a.approved_by.funder)} (${esc(a.approved_by.role)})`],
      ["Second approver", a.approved_by.two_person ? `${esc(a.approved_by.multisig.threshold)} of ${esc(a.approved_by.multisig.members.length)}, a multisig` : "none"],
    ],
    acceptance: [
      ["Verdict", esc(c.verdict || (c.accepted ? "accepted" : "none yet"))],
      ["Artifact", c.artifact ? `<span class="mono" title="${esc(c.artifact)}">${esc(cut(c.artifact, 14))}</span>` : none],
      ["Policy", c.policy.terms_hash ? `<span class="mono" title="${esc(c.policy.terms_hash)}">${esc(cut(c.policy.terms_hash))}</span>` : none],
      ["Policy version", esc(c.policy.version || "not recorded")],
      ["Evaluator", c.evaluators.length ? esc(c.evaluators.map((e) => e.kind).join(", ")) : `<span class="fine">none yet</span>`],
      ["Evidence", c.evidence.length ? c.evidence.map(tx).join(" · ") : none],
    ],
    commercial: [
      ["Billable deliverable", `<span class="mono" title="${esc(m.deliverable)}">${esc(cut(m.deliverable))}</span>`],
      ["Amount", esc(units(m.amount_units, cur))],
      ["Fee", esc(units(m.fee_units, cur))],
      ["Invoice line", m.invoice_ref ? esc(m.invoice_ref) : `<span class="fine">none given</span>`],
      ["Dispute", m.dispute ? esc(m.dispute) : none],
      ["Credit", m.correction ? `${esc(m.correction.kind)} of ${esc(units(m.correction.units, cur))}` : none],
    ],
    settlement: [
      ["Paid", esc(units(s.paid_units, cur))],
      ["Held", esc(units(s.held_units, cur))],
      ["Sent back", esc(units(s.refunded_units + s.reverted_units, cur))],
      ...(s.held_until ? [["Held until", esc(s.held_until)]] : []),
      ...(s.paid_outside ? [["Paid outside Knos", esc(s.paid_outside)]] : []),
    ],
  };
}

/** What a reader still has to trust for this acceptance, in sentences: the record's own words about its evaluators. */
export function trustedOf(rec) {
  const c = rec.acceptance, own = c.evaluators.some((e) => e.independent_of_buyer === false);
  return [c.independence || "Nothing has judged this order yet.", ...(own ? ["The evaluator ran in the buyer's own repository."] : []), "GitHub's signing key, and the workflow the order pinned."];
}

/** The four cards of one record, side by side where there is room. */
export function objectsHtml(rec, explorer) {
  const v = objectValues(rec, explorer), chip = chipOf(rec);
  const card = (key, more = "") => `<section class="k-card" data-tilt data-object="${key}">
      <p class="k-kicker">${esc(OBJECT_NAMES[key])}${key === "settlement" ? ` <span class="pill" data-chip="${esc(chip)}">${esc(chip)}</span>` : ""}</p>
      <dl class="facts">${v[key].map(([k, html]) => `<dt>${esc(k)}</dt><dd>${html}</dd>`).join("")}</dl>${more}</section>`;
  return `<div class="k-objects k-stage" data-deliverable="${esc(rec.id)}" data-chip="${esc(chip)}">
    ${card("authorisation")}
    ${card("acceptance", `<p class="k-kicker">What remains trusted</p><ul class="plain" data-object-trust>${trustedOf(rec).map((t) => `<li class="fine">${code(t)}</li>`).join("")}</ul>`)}
    ${card("commercial")}
    ${card("settlement", `<p class="fine" data-object-said>${esc(rec.settlement.said)}</p>`)}</div>`;
}

// ---- 8. procurement: offers, budgets, approvals, and one deliverable's seven answers ---------------------------------------------------------
// The data and every sentence come from web/procure.js (src/knos/controls.py and src/knos/approvals.py in the
// browser); these functions only lay them out. Nothing on these screens names a key, an address or a digest: the
// reader sees outcomes, prices, limits, people and dates. A statement is twelve words at most.
export const procure = proc;
export const PROC_STYLE = `.k-bar{display:flex;height:14px;border-radius:999px;overflow:hidden;background:var(--paper-2);border:1px solid var(--line);margin:8px 0}
.k-bar span{display:block;width:0;transition:width var(--dur-2) var(--ease)}
.k-env [data-part=spent]{background:var(--ink)}.k-env [data-part=held]{background:var(--ink-2)}.k-env [data-part=committed]{background:var(--accent)}
.k-env [data-part=draft]{background:var(--accent);opacity:.5}.k-bar[data-over="1"]{border-color:var(--bad)}
.k-key{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.k-tabs{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.k-tabs [aria-selected=true]{background:var(--accent);color:var(--accent-fg)}
.k-env{margin:12px 0}.k-seven dt{font-weight:600}.k-file{white-space:pre-wrap;overflow-wrap:anywhere}
@media (prefers-reduced-motion: reduce){.k-bar span{transition:none}}`;
const usd = proc.money;
const pctOf = (part, whole) => (whole > 0 ? Math.min(100, Math.max(0, (part * 100) / whole)) : 0).toFixed(2);

/** One envelope as a bar that fills: spent, held, committed, and `draft` (what an offer or a funding not yet made would add). */
export function envelopeHtml(env, state = proc.envelopeState(env), draft = 0, over = 0) {
  const part = (name, units) => `<span data-part="${name}" data-units="${units}" style="width:${pctOf(units, state.limit)}%"></span>`;
  const left = state.left - draft, key = (name, label, units) => `<dt><span class="k-key" data-part="${name}"></span>${label}</dt><dd data-fact="${name}">${esc(usd(units))}</dd>`;
  return `<div class="k-env" data-envelope="${esc(env.name)}" data-left="${left}" data-committed="${state.committed + draft}">
    <p class="k-kicker">${esc(env.name)} · ${esc(env.cost_centre)} · @${esc(env.owner)}</p>
    <p><span class="k-num" data-fact="left">${esc(usd(left))}</span> left of ${esc(usd(state.limit))} test USDC</p>
    <div class="k-bar" data-over="${over ? 1 : 0}" role="img" aria-label="Spent ${esc(usd(state.spent))}, held ${esc(usd(state.held))}, committed ${esc(usd(state.committed + draft))}, left ${esc(usd(left))}">
      ${part("spent", state.spent)}${part("held", state.held)}${part("committed", state.committed)}${part("draft", draft)}</div>
    <dl class="facts k-bar-key">${key("spent", "Spent", state.spent)}${key("held", "Held", state.held)}${key("committed", "Committed", state.committed + draft)}</dl>
    <p class="fine">${esc(env.period_from)} to ${esc(env.period_to)}${env.as_of ? `. Figures as of ${esc(env.as_of)}.` : "."}</p></div>`;
}

/** Before and after for one envelope: `fitted` is procure.fit's answer. Over the limit it says by how much, and shakes once. */
export function fitHtml(env, fitted, leaves) {
  return `<div data-fit="${fitted.ok ? 1 : 0}" data-over="${fitted.over}">
    <p class="k-kicker">Before</p>${envelopeHtml(env, fitted.before)}
    <p class="k-kicker">After</p><div data-after>${envelopeHtml(env, fitted.before, fitted.ok ? leaves : 0, fitted.over)}</div>
    <p class="status ${fitted.ok ? "ok" : "bad k-shake"}" data-fit-said>${esc(fitted.sentence)}</p></div>`;
}

/** Where a new file is opened on the forge, already filled in: the reader reviews it there and commits. */
export const newFileLink = (repo, branch, path, text) => `https://github.com/${repo}/new/${encodeURIComponent(branch)}?filename=${encodeURIComponent(path)}&value=${encodeURIComponent(text)}`;

/** What creating an offer gives: the file to commit, the comment that funds each supplier on devnet, and what approval it needs. */
export function offerHtml({ offer, text, path, link, comments, need }) {
  return `<h4>The file to commit</h4>
    <p class="fine" data-offer-path>${esc(path)}</p>
    <pre class="k-file" id="proc-file">${esc(text)}</pre>
    <p><a class="k-btn" id="proc-file-open" href="${esc(link)}" target="_blank" rel="noopener">Open it as a new file</a>
      <button type="button" class="k-btn quiet" id="proc-file-copy">Copy the file</button></p>
    <h4>The comment that funds it</h4>
    ${comments.length ? `<p class="fine">Post one per supplier, each ${esc(offer.period)}. Devnet: test USDC.</p>${comments.map((c) => `<pre class="k-file" data-offer-comment>${esc(c)}</pre>`).join("")}
      <p><button type="button" class="k-btn quiet" id="proc-comment-copy">Copy the comment</button></p>`
    : `<p class="fine" data-offer-comment-none>Devnet funds one named supplier per comment. Name a supplier to fund.</p>`}
    <h4>Approval</h4><p class="status" data-offer-need>${esc(need)}</p>`;
}

/** The open offers, one row each. `rows`: [{ offer, row (the card's outcome), sized (procure.commitment), status }]. */
export function offersTableHtml(rows) {
  if (!rows.length) return `<p class="fine">No offer yet.</p>`;
  return `<div class="k-table"><table><thead><tr><th>Offer</th><th>Outcome</th><th>Supplier</th><th>Cap</th><th>Until</th><th>Approval</th></tr></thead><tbody>${rows.map((r) => `<tr data-offer="${esc(r.offer.name)}">
    <td>${esc(r.offer.name)}</td><td>${esc(r.offer.outcome)}, ${esc(usd(proc.unitsOf(r.row?.price) || 0))}</td><td>${esc(r.offer.suppliers === "anyone" ? "anyone" : r.offer.suppliers.map((s) => `@${s}`).join(", "))}</td>
    <td>${esc(usd(r.sized.cap))} a ${esc(r.offer.period)}</td><td>${esc(r.offer.ends)}</td><td>${esc(r.status)}</td></tr>`).join("")}</tbody></table></div>`;
}

/** What waits for whom, and who approved what with which authority. `requests`: [{ title, requester, chain (procure.chain), line }]. */
export function approvalsHtml(requests) {
  if (!requests.length) return `<p class="fine">Nothing asks for approval.</p>`;
  const who = (w) => (w.who.length ? w.who.map((a) => `@${esc(a)}`).join(" or ") : "nobody the policy names");
  return requests.map((r) => `<section class="k-card" data-request="${esc(r.chain.subject)}" data-met="${r.chain.met ? 1 : 0}">
    <p class="k-kicker">${esc(r.title)} · ${esc(usd(r.chain.amount))} test USDC · asked by @${esc(r.requester)}</p>
    <p class="status ${r.chain.met ? "ok" : ""}" data-request-said>${esc(r.chain.sentence)}</p>
    <ol class="plain">${r.chain.counted.map((c) => `<li class="k-step" data-state="done" data-approved="${esc(c.approver)}"><strong>@${esc(c.approver)}</strong> approved on ${esc(c.at.slice(0, 10))}.
        <span class="fine" data-authority>Authority: ${esc(c.authority)}.</span>${/^https:\/\/github\.com\//.test(c.source) ? ` <a href="${esc(c.source)}" target="_blank" rel="noopener">The comment</a>` : ""}</li>`).join("")}
      ${r.chain.refused.map((x) => `<li class="k-step" data-state="bad" data-refused="${esc(x.approver)}">${esc(x.sentence)}</li>`).join("")}
      ${r.chain.waiting.map((w) => `<li class="k-step" data-state="live" data-waiting="${esc(w.role)}">Waits for ${esc(w.count)} of ${esc(w.role)}: ${who(w)}.</li>`).join("")}</ol>
    ${r.chain.met ? "" : `<details class="k-more"><summary>How to approve</summary><p class="fine">Post this line on the forge, from your own account.</p><pre class="k-file" data-approve-line>${esc(r.line)}</pre>
      <p class="fine">Then record it: <code>knos approve record --repo OWNER/NAME --comment NUMBER</code></p></details>`}</section>`).join("");
}

export const QUESTIONS = ["What did we authorize?", "What did the supplier deliver?", "Which requirements passed?", "Has this deliverable already been billed?",
  "Who approved it, and did they have authority?", "What is disputed, credited, or still owed?", "Can I explain this decision next quarter?"];
/** The seven answers for one deliverable: [{ q, a, ok, more: [sentence] }]. `d`: the deliverable (buyer_templates.json's
 *  sample shows the shape); `ctx`: { offer, card, chain (procure.chain of the offer), directory }. `ok` false marks an exception. */
export function sevenOf(d, { offer, card, chain, directory = proc.PROCUREMENT }) {
  const row = proc.outcomeOf(card, d.outcome) || {}, u = (v) => usd(proc.unitsOf(v) || 0), reqs = d.requirements || [], passed = reqs.filter((r) => r.passed).length, n = Number(d.invoice_lines || 0);
  const owed = proc.unitsOf(d.owed) || 0, by = chain.counted.map((c) => `@${c.approver}`);
  return [
    { q: QUESTIONS[0], ok: true, a: `One ${d.outcome} at ${u(row.price)}, up to ${u(offer.cap)} a ${offer.period}.`,
      more: [`Offer ${offer.name}, ${offer.starts} to ${offer.ends}.`, `Unit: ${row.unit}. Acceptance terms: ${row.terms}.`, `One deliverable may take ${offer.retries} evaluations.`, proc.REOPENED[offer.reopened]] },
    { q: QUESTIONS[1], ok: d.verdict === "accepted", a: `@${d.supplier} delivered ${d.artifact}. Verdict: ${String(d.verdict).replace(/_/g, " ")}.`, more: [`It took ${d.evaluations} evaluations.`, `Deliverable ${d.id}.`] },
    { q: QUESTIONS[2], ok: reqs.length > 0 && passed === reqs.length, a: reqs.length ? `${passed} of ${reqs.length} passed.` : "The record names no requirement.", more: reqs.map((r) => `${r.name}: ${r.passed ? "passed" : "failed"}.`) },
    { q: QUESTIONS[3], ok: n <= 1, a: n > 1 ? `Yes. ${n} invoice lines name it; pay one.` : n === 1 ? "No. One invoice line names it." : "No. No invoice line names it yet.",
      more: ["A deliverable is billed once, however many evaluations it took."] },
    { q: QUESTIONS[4], ok: chain.met, a: chain.met ? `${by.join(" and ")} approved, each with authority.` : chain.sentence,
      more: [...chain.counted.map((c) => `@${c.approver}: ${c.authority}, on ${c.at.slice(0, 10)}.`), ...chain.refused.map((r) => r.sentence),
        ...chain.waiting.map((w) => `Waits for ${w.count} of ${w.role}: ${w.who.map((a) => `@${a}`).join(" or ") || "nobody the policy names"}.`)] },
    { q: QUESTIONS[5], ok: !d.disputed && owed === 0, a: `${d.disputed ? "Disputed." : "Nothing is disputed."} ${u(d.credited)} credited, ${u(d.owed)} owed.`, more: [`Paid: ${u(d.paid)} test USDC.`, `Held: ${u(d.held)} test USDC.`] },
    { q: QUESTIONS[6], ok: true, a: "Yes. Five files in your repository rebuild it.",
      more: [`${directory}/rate-cards/${card.name}.yaml`, `${directory}/offers/${offer.name}.yaml`, `${directory}/envelopes/${offer.envelope}.yaml`, `${directory}/policy.yaml`, `${directory}/approvals.jsonl`,
        `The statement: ${d.evidence}.`, "Evaluation logs stay on the forge. Export the statement to keep them."] },
  ];
}
/** The seven answers on one screen: exceptions first in the count, each answer with its evidence one click away. */
export function sevenHtml(rows, title) {
  const open = rows.filter((r) => !r.ok).length;
  return `<p class="k-kicker">${esc(title)}</p>
    <p class="status ${open ? "bad" : "ok"}" data-seven-open="${open}">${open ? `${open} of 7 answers need${open === 1 ? "s" : ""} a person.` : "All 7 answers are clean."}</p>
    <dl class="parts k-seven">${rows.map((r, n) => `<dt data-q="${n + 1}">${esc(r.q)}</dt><dd data-a="${n + 1}" data-ok="${r.ok ? 1 : 0}"><strong class="${r.ok ? "" : "status bad"}">${esc(r.a)}</strong>
      <details class="k-more"><summary>Evidence</summary><ul class="plain">${r.more.map((m) => `<li class="fine">${esc(m)}</li>`).join("")}</ul></details></dd>`).join("")}</dl>`;
}
/** A deliverable for `sevenOf` out of one record of web/finance_data.js recordsOf, where the statement has one. The
 *  record names the policy that judged, not each requirement, so `requirements` holds the verdict alone. */
export function deliverableOfRecord(rec, offerName = "") {
  const m = rec.commercial, s = rec.settlement, whole = (u) => proc.typed(Number(u) || 0), accepted = Boolean(rec.acceptance.accepted);
  return { id: rec.id, offer: offerName, outcome: "", supplier: rec.authorisation.supplier.map((x) => x.github_id).join(", "), artifact: rec.acceptance.artifact || "nothing yet",
    requirements: rec.acceptance.verdict ? [{ name: "the agreed acceptance", passed: accepted }] : [], verdict: rec.acceptance.verdict || "insufficient_evidence", evaluations: rec.acceptance.evaluators.length,
    invoice_lines: m.billed_before ? 2 : m.invoice_ref ? 1 : 0, amount: whole(m.amount_units), paid: whole(s.paid_units), held: whole(s.held_units), credited: whole(s.refunded_units + s.reverted_units),
    owed: whole(s.status === "payable" ? s.held_units : 0), disputed: Boolean(m.dispute), evidence: `line ${m.lines.join(", ")} of the month's statement` };
}
