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
import { quote, show, percent } from "./price.js";
import * as rules from "./controls_data.js";

export const SMALL = 20_000_000;          // under this the page warns: the minimum fee is a large share of a small order

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const when = (t) => `${new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC`;
const short = (a) => `${String(a).slice(0, 6)}…`;
/** A fee as a share of the amount, to two decimals: 400000 of 5000000 -> "8.00%". */
export const share = (fee, amount) => `${((fee * 100) / amount).toFixed(2)}%`;

/** web/controls_data.js: `explainFunding` and `feeTable`, the same decisions and the same table as the Python's. */
export const controls = rules;

// ---- 1. the fee, before funding --------------------------------------------------------------------------------------------------------
/** What an order of `units` costs its funder: { fee, pays, pct, words, warning }. `warning` is "" from 20 test USDC up. */
export function feeView(units, c) {
  const q = quote(units, c), pct = share(q.fee, units), least = quote(c.minAmount, c);
  const binds = Math.ceil((c.feeMin * 10_000) / c.feeBps);        // below this the minimum is the fee
  const words = `You pay ${show(q.funderPays)} test USDC: ${show(q.amount)} for whoever does the work, and a fee of ${show(q.fee)} on top, which is ${pct} of the amount. The person paid receives the whole ${show(q.amount)}.`;
  const warning = units >= SMALL ? "" : `A small order pays a high fee. The fee is never less than ${show(c.feeMin)} test USDC, so under ${show(binds)} it is more than ${percent(c.feeBps)}: an order of ${show(c.minAmount)} costs ${share(least.fee, c.minAmount)}. `
    + `This order's fee is ${pct}. Small purchases are cheaper pooled into one order with milestones, or bought at a standing rate.`;
  return { fee: q.fee, pays: q.funderPays, pct, words, warning };
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
    <p class="fine">The program pays one order's milestone once, whatever is sent to it. What it cannot know is that two orders buy the same thing: that is what this list is for.${found.privates ? ` ${found.privates} private order${found.privates > 1 ? "s" : ""} of the organisation name no repository in public and cannot be matched here.` : ""}</p>`;
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
      const left = show(o.amount - o.paid);
      if (o.cancelAt) add("cancelled", `Cancelled by its funder: it ends ${when(o.cancelAt)}, and ${left} test USDC goes back then.`, o.cancelAt <= now ? "Send the refund." : "Wait for the notice to end, then send the refund.", "anyone");
      else if (o.deadline <= now) add("refundable", `Past its deadline (${when(o.deadline)}) and unpaid: ${left} test USDC can go back to the funder.`, "Send the refund. The money can only go back to where it came from.", "anyone");
      else if (o.reservedBy && o.reservedUntil <= now) add("stale", `Reserved by GitHub id ${o.reservedBy}, and the reservation ran out ${when(o.reservedUntil)} with nothing delivered.`,
        `Ask them, or let someone else take it: the order is open to any supplier again until ${when(o.deadline)}.`, "the buyer");
    }
  }
  if (refused) rows.push({ kind: "refused", order: "", where: repo || "this repository", what: `${refused} token${refused > 1 ? "s were" : " was"} refused by the relay at a merge: a payment or a proof that the program or the relay would not accept. This site keeps the count; the reason is in the relay's answer on each pull request.`,
    action: "Read the relay's answer on the pull request, fix what it names, and run the workflow again.", who: "the supplier", tx: "" });
  return rows;
}

const KIND = { held: "Held for a wallet", review: "In a review window", reverted: "Reverted", challenged: "Challenged", cancelled: "Cancelled", refundable: "Past deadline, refundable", stale: "Reserved and stale", refused: "Refused tokens" };
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
