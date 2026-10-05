// Buy: the console of the person who authorises a payment and has to defend it later. Four steps on one screen: what is
// bought, when it is accepted (terms from a template, said in one sentence, with what is still trusted in that mode), how
// it is paid (a passkey wallet, or the comment `/knos fund`), and what happened (the order's state, read from Solana
// devnet). Beside the amount, before anything is funded: the fee as an amount and as a share of the order, whether the
// organisation's budget would let this funding through and which rule decides, any earlier order or payment for the
// same issue, and what a supplier can and cannot do alone when the repository is private. After: the receipt's five
// parts, who answers when the service fails, and the orders that wait for a person. The words and the rules of those
// panels are web/console.js; this file reads the chain and draws. docs/CONSOLE.md is the operator's guide.
// renderBuyer(el, env) draws it into `el`. The page sends nothing to Solana: the passkey signs one intent
// (passkey_fund.js) and the page shows the one line `/knos passkey-fund ...` to post on the issue, which a relay
// carries and pays for. It asks GitHub for the repository's id and the issue, devnet for the wallet and the order, and
// this site for its own files; nobody else. Money is test USDC.
//
// The templates are web/buyer_templates.json, written by scripts/buyer_templates.py from src/knos/terms_templates.py.
// sentenceOf and commentOf below say a template with the buyer's own numbers; tests/test_site_buyer.py holds them to the
// sentence and the comment that file carries (knos.terms_templates.sentence, in JavaScript).
import * as settle from "./settle.js";
import * as passkey from "./passkey.js";
import { passkeyFundIntent, intentComment } from "./passkey_fund.js";
import { termsOf, parseIssueUrl, workflowPin, orderAddress, listOf, F_NEUTRAL, SEQ_TRIES, MAX_DAYS, Refused } from "./anyissue.js";
import { priceConstants, quote, unitsOf, show } from "./price.js";
import { renderOrderStatement } from "./statements.js";
import { jsonFile } from "./records.js";
import * as con from "./console.js";

const RPC = "https://api.devnet.solana.com", GH = "https://api.github.com";
const DEVNET = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG";      // the hash of devnet's first block
const STORE = "knos-passkey";                                        // where claim.js keeps the passkey wallet's details: the same wallet
const LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const ADDRESS = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
export const SLOTS = 9000;            // how long a signed intent is good for: about an hour, at devnet's 0.4 s a slot
const JUDGES = { 0: "the order's own repository", 1: "a neutral run, started by hand by the owner of the repository it ran in", 2: "the judge repository the order named",
  3: "the arbiter the order named", 9: "no token: a payment the program had already accepted" };                                             // audit.py JUDGES
export const STATES = ["funded", "reserved", "accepted", "paid", "held", "refunded"];

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const code = (s) => esc(s).replace(/`([^`]*)`/g, "<code>$1</code>");
const hex = (u8) => [...u8].map((b) => b.toString(16).padStart(2, "0")).join("");
const unhex = (s) => (/^([0-9a-f]{2})+$/i.test(s) ? Uint8Array.from(s.match(/../g), (h) => parseInt(h, 16)) : new Uint8Array(0));
const b64 = (u8) => btoa(String.fromCharCode(...u8));
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const when = (t) => `${new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC`;
const byCode = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
// millionths as people write them, and as knos.commands.amount does: 20, 12.5
const typed = (units) => { const part = units % 1_000_000; return `${Math.trunc(units / 1_000_000)}${part ? `.${String(part).padStart(6, "0").replace(/0+$/, "")}` : ""}`; };

// ---- a template with the buyer's own numbers ------------------------------------------------------------------------------------------
const dirs = (globs) => globs.map((g) => (g.endsWith("/**") ? g.slice(0, -2) : g)).join(" and ");
const sorted = (list) => [...new Set(list)].sort(byCode);

/** knos.terms_templates.sentence: the order in one sentence. `v`: { kind, mode, checks, paths, amount, rate, vendor, holdback, warranty, days, private },
 *  amounts as text ("50"), checks and paths as lists. */
export function sentenceOf(v, money = "test USDC") {
  const checks = sorted(v.checks), names = checks.map((c) => `\`${c}\``).join(", ");
  const only = v.paths.length ? `only touches ${dirs(sorted(v.paths))}` : "";
  const on = v.mode === "tests" ? `on a pull request that also passes the issue's black-box acceptance suite${only ? ` and ${only}` : ""}` : `on a merge${only ? ` that ${only}` : ""}`;
  const whenPaid = names ? `when check${checks.length !== 1 ? "s" : ""} ${names} pass${checks.length === 1 ? "es" : ""} ${on}`
    : v.mode === "merge" ? `when a maintainer merges a pull request that closes the issue${only ? ` and ${only}` : ""}` : on;
  const head = v.kind === "offer" ? `Pays @${v.vendor} ${v.rate} ${money} for each pull request of theirs, up to ${v.amount} ${money} in all, ${whenPaid}` : `Pays ${v.amount} ${money} ${whenPaid}`;
  const held = v.holdback && v.warranty ? `; ${v.holdback}% of it waits ${v.warranty} days and goes back if the change is reverted` : "";
  const hidden = v.private ? "; funded and paid by the organisation's attestor repository, so nothing public names the private one" : "";
  return `${head}${held}${hidden}; refund after ${v.days} days`;
}

/** The comment that funds it, as knos.commands reads one: `/knos fund 50 checks: unit, lint paths: src/** days 30`. */
export function commentOf(v, defaultDays = 14) {
  const head = v.kind === "offer" ? `/knos offer @${v.vendor} rate ${v.rate} budget ${v.amount}` : `/knos fund ${v.amount}`;
  return [head, v.checks.length ? `checks: ${v.checks.join(", ")}` : "", v.paths.length ? `paths: ${v.paths.join(", ")}` : "",
    v.holdback ? `holdback ${v.holdback}` : "", v.warranty ? `warranty ${v.warranty}` : "", Number(v.days) !== defaultDays ? `days ${v.days}` : ""].filter(Boolean).join(" ");
}

// ---- the order's state, from its account and from what the program logged ----------------------------------------------------------------
/** The `knos3:` lines of one order in a transaction's log, as { event, ...fields }. */
export function orderLines(logs, order, program, knos = settle) {
  return knos.said(logs || [], program).filter((l) => l.startsWith("knos3:") && l.includes(`order=${order}`)).map((l) => {
    const [name, ...rest] = l.slice(6).split(" ");
    return { event: name, ...Object.fromEntries(rest.map((p) => { const i = p.indexOf("="); return [p.slice(0, i), p.slice(i + 1)]; })) };
  });
}

/** What became of an order. `o`: knos.v2.readOrder of its account (null when the account is gone); `events`: its log lines, oldest
 *  first, each with `at` and `tx`; `now`: the chain's time. Returns { state, reached: [names of STATES], words }. */
export function orderState(o, events, now) {
  const has = (name) => events.some((e) => e.event === name), last = (name) => [...events].reverse().find((e) => e.event === name);
  const reached = new Set();
  if (o || has("funded")) reached.add("funded");
  if (has("reserved") || (o && o.reservedBy)) reached.add("reserved");
  if (has("paid") || has("held")) reached.add("accepted");
  if (has("paid")) reached.add("paid");
  if (has("held") || o?.state === "held") reached.add("held");
  if (has("refunded")) reached.add("refunded");
  let state, words;
  if (o?.state === "held") { state = "held"; words = `Accepted, and held: the person it pays has bound no wallet yet. Until ${when(o.holdUntil)} they can bind one and be paid; after that it can be sent back.`; reached.add("accepted"); reached.add("held"); }
  else if (o?.state === "warranty") { state = "paid"; words = `Paid, with a holdback in warranty until ${when(o.holdUntil)}: ${show(o.amount - o.paid)} waits, and goes back to the funder if the change is reverted before then.`; reached.add("accepted"); reached.add("paid"); }
  else if (o && o.reservedBy && o.reservedUntil > now) { state = "reserved"; words = `Funded, and reserved until ${when(o.reservedUntil)} by the GitHub account with id ${o.reservedBy}.`; reached.add("reserved"); }
  else if (o) { state = "funded"; words = `Funded: ${show(o.amount - o.paid)} is in the order's own escrow account. Unpaid by ${when(o.deadline)}, anyone can send it back.`; }
  else if (has("reverted")) { state = "refunded"; words = `Paid, then reverted inside the warranty: the holdback of ${show(Number(last("reverted").amount))} went back to the funder.`; reached.add("refunded"); }
  else if (has("refunded") && has("paid")) { state = "refunded"; words = `Paid in part; the rest, ${show(Number(last("refunded").amount))}, went back to the funder.`; }
  else if (has("refunded")) { state = "refunded"; words = `Refunded: ${show(Number(last("refunded").amount))} went back to where it came from. Nothing was paid.`; }
  else if (has("paid")) { state = "paid"; words = "Paid in full. The order is closed."; }
  else { state = "none"; words = "There is no order at that address on devnet. If the line was just posted, the relay has not carried it yet: read again in a minute."; }
  return { state, reached: STATES.filter((s) => reached.has(s)), words };
}

// ---- the page ---------------------------------------------------------------------------------------------------------------------------
export function renderBuyer(el, env = {}) {
  if (el.dataset.buyer) return;                // drawn once, whoever calls
  el.dataset.buyer = "1";
  const doc = el.ownerDocument, knos = env.knos || settle, rpc = env.RPC || RPC;
  const EXPLORER = env.EXPLORER || ((kind, id) => `https://explorer.solana.com/${kind}/${id}?cluster=devnet`);
  const $ = (id) => doc.getElementById(id);
  const gh = env.gh || (async (path) => {
    const r = await fetch(GH + path, { headers: { Accept: "application/vnd.github+json" } });
    if ((r.status === 403 || r.status === 429) && r.headers.get("x-ratelimit-remaining") === "0") throw new Error("GitHub's free limit for this network is used up (60 reads an hour without login). Try again in an hour.");
    if (r.status === 404) throw new Error("GitHub has no such public repository, issue or account.");
    if (!r.ok) throw new Error(`GitHub said ${r.status}`);
    return r.json();
  });
  let idsP;
  const ids = env.ids || (() => (idsP ||= fetch("program_ids.json").then((r) => { if (!r.ok) throw new Error("program_ids.json is missing from this build"); return r.json(); })));
  const c = priceConstants(), file = env.file || jsonFile;
  const clock = env.now || (() => Math.floor(Date.now() / 1000));
  const say = (node, html, kind = "") => { node.innerHTML = `<p class="status ${kind}">${html}</p>`; };
  const copyTo = (button, text, area) => { button.onclick = async () => { try { await navigator.clipboard.writeText(text); button.textContent = "Copied"; } catch { area?.select?.(); button.textContent = "Select it and copy by hand"; } }; };

  el.innerHTML = `
    <h2>Buy work per outcome</h2>
    <p class="lede">Fix the price and the acceptance terms before the work starts. The money waits in escrow and is paid when a signed CI run says the terms were met. No wallet app, and no command grammar to learn.</p>
    <p class="devnet">Solana devnet: test USDC, never real money</p>

    <section class="card" id="buy-step-1"><span class="pill">Step 1 of 4</span>
      <h3>What are you buying?</h3>
      <label for="buy-kind">The work</label>
      <select id="buy-kind"><option value="issue">One issue, done once</option><option value="rate">A rate per accepted pull request, from one vendor</option></select>
      <label for="buy-issue" id="buy-issue-label">The issue on GitHub</label>
      <input id="buy-issue" autocomplete="off" spellcheck="false" placeholder="https://github.com/owner/repo/issues/7">
      <div id="buy-rate-box" hidden><div class="row">
        <div><label for="buy-vendor">The vendor's GitHub account</label><input id="buy-vendor" autocomplete="off" spellcheck="false" placeholder="octocat"></div>
        <div><label for="buy-rate">Rate per accepted pull request (test USDC)</label><input id="buy-rate" inputmode="decimal" value="10"></div></div></div>
      <div class="row">
        <div><label for="buy-amount" id="buy-amount-label">Amount (test USDC)</label><input id="buy-amount" inputmode="decimal" value="50"></div>
        <div><label for="buy-days">Deadline: days until unpaid money goes back</label><input id="buy-days" inputmode="numeric" value="14"></div></div>
      <p id="buy-cost"></p>
      <div id="buy-fee-warning" role="note" hidden></div>
      <details id="buy-fee-table" open><summary class="fine">The fee as a share of the order, at five sizes</summary><div id="buy-fee-rows"></div></details>
      <div id="buy-private" hidden></div>
      <h4>Is this allowed? <span class="pill">the organisation's budget, read from devnet</span></h4>
      <div id="buy-allowed" role="status" aria-live="polite"><p class="fine">Write the issue above. The page then reads the budget of the organisation that owns the repository, and says whether this funding would pass and which rule decides.</p></div>
      <label for="buy-by">Who will post the funding comment (a GitHub account; leave empty to check the budget alone)</label>
      <input id="buy-by" autocomplete="off" spellcheck="false" placeholder="octocat">
      <h4>Was this billed before?</h4>
      <div id="buy-before" role="status" aria-live="polite"><p class="fine">Write the issue above. The page then lists every earlier order and payment for the same repository and issue, each with its transaction.</p></div>
    </section>

    <section class="card" id="buy-step-2"><span class="pill">Step 2 of 4</span>
      <h3>When is it accepted?</h3>
      <label for="buy-template">Terms, from a template</label>
      <select id="buy-template"></select>
      <div class="row">
        <div><label for="buy-checks">Checks that must pass (your CI's job names)</label><input id="buy-checks" autocomplete="off" spellcheck="false"></div>
        <div><label for="buy-paths">Only these paths may change (empty: any)</label><input id="buy-paths" autocomplete="off" spellcheck="false"></div></div>
      <h4>What it means, in one sentence</h4>
      <div class="receipt"><strong id="buy-sentence"></strong></div>
      <h4>What you still trust <span class="pill" id="buy-mode"></span></h4>
      <ul id="buy-trusted"></ul>
      <details><summary class="fine">The three ways an order can be judged</summary><dl class="parts" id="buy-modes"></dl></details>
    </section>

    <section class="card" id="buy-step-3"><span class="pill">Step 3 of 4</span>
      <h3>Pay</h3>
      <h4>With a passkey: no wallet app, no SOL</h4>
      <p>A passkey is the key your device keeps behind its fingerprint, face or screen lock. Its wallet is an address on Solana that holds test USDC. You sign one order with it; a relay sends the transaction and pays its fee.</p>
      <div id="buy-pk-no" hidden></div>
      <div id="buy-pk">
        <p><button type="button" id="buy-pk-create">Create a passkey wallet</button></p>
        <div id="buy-pk-status" role="status" aria-live="polite"></div>
        <div id="buy-pk-wallet" hidden>
          <dl class="facts"><dt>Wallet address</dt><dd><span class="mono" id="buy-pk-address"></span></dd>
            <dt>It holds</dt><dd><span id="buy-pk-balance">not read yet</span> <button type="button" id="buy-pk-refresh" class="ghost small">Check the balance</button></dd></dl>
          <p class="fine" id="buy-pk-faucet">To get test USDC: send it to the address above from any devnet wallet, or ask <a href="https://faucet.circle.com/" target="_blank" rel="noopener">Circle's devnet faucet</a> for USDC on Solana devnet to that address. It is free and worth nothing.</p>
          <p><button type="button" id="buy-pk-sign">Sign the order with the passkey</button></p>
        </div>
        <div id="buy-pk-result" role="status" aria-live="polite"></div>
      </div>
      <h4>With a comment: from your organisation's Balance, or the devnet faucet</h4>
      <p>Post this line on the issue. It needs the Knos workflow in the repository (<a href="#install">Install</a>). The money comes from the Balance the repository's owner opened, or on devnet from the free faucet: at most 100 test USDC per comment.</p>
      <pre id="buy-comment"></pre>
      <p><button type="button" id="buy-comment-copy" class="ghost small">Copy the comment</button> <a id="buy-comment-open" class="button quiet" target="_blank" rel="noopener" hidden>Open the issue</a></p>
      <h4>With a card or a bank transfer</h4>
      <p id="buy-card">Not available: it needs a licensed on-ramp partner, and Knos has none. Nothing here takes a card.</p>
    </section>

    <section class="card" id="buy-step-4"><span class="pill">Step 4 of 4</span>
      <h3>What happened</h3>
      <form id="buy-order-form"><label for="buy-order">The order's address (shown when you sign, and in Knos's reply on the issue)</label>
        <input id="buy-order" autocomplete="off" spellcheck="false" placeholder="a Solana address">
        <button type="submit">Read the order from devnet</button></form>
      <div id="buy-order-result" role="status" aria-live="polite"></div>
      <h4>When it does not go the plain way</h4>
      <dl class="parts" id="buy-exceptions">
        <dt>Nobody delivers by the deadline</dt><dd>Refund. Anyone can send it once the deadline has passed, and the money can only go back to where it came from: your passkey wallet, or the Balance.</dd>
        <dt>You want to stop early</dt><dd>Cancel, with 7 days' notice. A person with write access comments <code>/knos cancel</code> on the issue of an order funded by comment. A passkey wallet cannot sign a cancel today, so an order it funded runs to its deadline.</dd>
        <dt>The accepted change is reverted</dt><dd>Revert, inside the warranty window, when the order holds a share back. A signed run of the order's repository, or of its neutral judge, sends the held share back to you. After the window the share is released to the person who did the work; anyone can send that.</dd>
        <dt>The person paid has no wallet</dt><dd>Held. The payment waits for them to bind a wallet; then anyone can settle it. If they never do, it can be sent back after the hold.</dd>
      </dl>
    </section>

    <section class="card" id="buy-exc-card"><h3>What needs a person</h3>
      <p>The orders of an organisation, or of one repository, that will not finish by themselves. Each says what happened, the one thing that resolves it, and who can do it.</p>
      <form id="buy-exc-form"><label for="buy-exc-scope">The organisation, or one repository as owner/repo</label>
        <input id="buy-exc-scope" autocomplete="off" spellcheck="false" placeholder="acme, or acme/widgets">
        <button type="submit">Show what needs a person</button></form>
      <div id="buy-exc" role="status" aria-live="polite"></div>
    </section>

    <section class="card" id="buy-statement"><h3>The month's statement, for both sides</h3>
      <p>Every work order your organisation's money funded in one month, with the totals, as a file the supplier can recompute from the chain and compare by one hash.</p>
      <div id="buy-statement-box"></div>
    </section>`;

  // ---- steps 1 and 2: what is bought, and the terms -------------------------------------------------------------------------------------
  let book = null, me = null, signed = null;      // the templates file; the passkey wallet { credentialId, key, wallet, nonce, holds }; the last signed intent
  const template = () => book?.templates.find((t) => t.name === $("buy-template").value) || null;
  const lists = () => { try { return { checks: listOf($("buy-checks").value), paths: listOf($("buy-paths").value) }; } catch { return null; } };

  function values() {
    const t = template(), l = lists();
    if (!t || !l) return null;
    const days = /^\d{1,3}$/.test($("buy-days").value.trim()) ? Number($("buy-days").value) : 0;
    const amount = unitsOf($("buy-amount").value), rate = t.parts.kind === "offer" ? unitsOf($("buy-rate").value) : null;
    return { ...t.parts, ...l, days, units: amount, amount: amount === null ? "" : typed(amount), rate: rate === null ? "" : typed(rate), rateUnits: rate,
      vendor: $("buy-vendor").value.trim().replace(/^@/, "") };
  }

  // the first thing wrong with what was typed, in words; "" when an order can be made of it
  function wrong(v, forPasskey = false) {
    if (!lists()) return "A name's quote or bracket is not closed in the checks or the paths.";
    if (!v) return "The templates did not load. Reload the page.";
    if (v.units === null) return "Write the amount as a number like 50 or 7.5, with at most six decimals.";
    if (v.units < c.minAmount) return `An order takes at least ${show(c.minAmount)} test USDC.`;
    if (v.units > c.maxAmount) return `An order takes at most ${show(c.maxAmount)} test USDC until an outside review.`;
    if (v.days < 1 || v.days > MAX_DAYS) return `The deadline is a whole number of days from 1 to ${MAX_DAYS}.`;
    if (v.kind === "offer" && !LOGIN.test(v.vendor)) return "Write the vendor's GitHub account: letters, digits and single hyphens.";
    if (v.kind === "offer" && (v.rateUnits === null || v.rateUnits < c.minAmount || v.rateUnits > v.units)) return `The rate is a number from ${show(c.minAmount)} up to the budget.`;
    const ref = parseIssueUrl($("buy-issue").value);
    if (forPasskey && !ref) return "Write the issue's address on GitHub in step 1: https://github.com/owner/repo/issues/7, or owner/repo#7.";
    if (ref?.kind === "pull") return "That is a pull request. Name the issue it closes.";
    return "";
  }

  function redraw() {
    const t = template(), v = values(), ref = parseIssueUrl($("buy-issue").value), bad = wrong(v);
    const rate = $("buy-kind").value === "rate";
    $("buy-rate-box").hidden = !rate;
    $("buy-amount-label").textContent = rate ? "Budget in all (test USDC)" : "Amount (test USDC)";
    $("buy-issue-label").textContent = rate ? "The issue the offer is posted on" : "The issue on GitHub";
    if (!t) return;
    const q = v && v.units !== null && v.units >= c.minAmount && v.units <= c.maxAmount ? quote(v.units, c) : null;
    const fee = q ? con.feeView(v.units, c) : null;
    $("buy-cost").textContent = fee ? fee.words : bad;
    $("buy-cost").dataset.pct = fee ? fee.pct : "";
    $("buy-fee-warning").hidden = !fee?.warning;
    $("buy-fee-warning").innerHTML = fee?.warning ? `<div class="receipt"><strong>${esc(fee.warning)}</strong></div>` : "";
    drawChecks();
    $("buy-sentence").innerHTML = v && !bad ? `${code(sentenceOf(v, book.money))}.` : esc(bad || "");
    $("buy-mode").textContent = `judged ${t.assurance}`;
    $("buy-trusted").innerHTML = t.trusted.map((s) => `<li>${esc(s)}</li>`).join("");
    $("buy-modes").innerHTML = Object.entries(book.assurance).map(([name, means]) => `<dt>${esc(name)}${name === t.assurance ? " (this template)" : ""}</dt><dd>${esc(means)}</dd>`).join("");
    const line = v && !bad ? commentOf(v, book.default_days) : "";
    $("buy-comment").textContent = line || "Fill in steps 1 and 2.";
    copyTo($("buy-comment-copy"), line);
    $("buy-comment-copy").disabled = !line;
    const open = $("buy-comment-open");
    open.hidden = !ref || ref.kind !== "issues";
    if (ref) open.href = `https://github.com/${ref.owner}/${ref.repo}/issues/${ref.number}`;
    $("buy-pk").hidden = !t.passkey;
    $("buy-pk-no").hidden = t.passkey;
    $("buy-pk-no").innerHTML = t.passkey ? "" : `<p class="status" id="buy-pk-why">Not for this template yet: ${esc(t.passkey_why_not)}. Use the comment below.</p>`;
    $("buy-pk-result").innerHTML = ""; signed = null;       // what was signed was for the boxes as they were
  }

  function pick() {      // a template puts its own checks, paths and warranty in the boxes
    const t = template();
    if (!t) return;
    $("buy-checks").value = t.parts.checks.join(", ");
    $("buy-paths").value = t.parts.paths.join(", ");
    redraw();
  }
  function kinds() {     // the kind of work decides which templates are offered
    const rate = $("buy-kind").value === "rate", box = $("buy-template");
    box.innerHTML = book.templates.filter((t) => (t.parts.kind === "offer") === rate).map((t) => `<option value="${esc(t.name)}">${esc(t.title)}</option>`).join("");
    const t = template();
    if (t) { $("buy-amount").value = t.parts.amount; $("buy-days").value = String(t.parts.days); if (rate) { $("buy-rate").value = t.parts.rate; } }
    pick();
  }
  // ---- before funding: the fee table, the private case, the budget, and what was billed before ---------------------------------------
  // `facts` is what was read for the issue in the box: the repository and its owner from GitHub, the owner's Balances and the
  // issue's open orders from devnet, the owner's statement from this site. It is read once per issue, when the box is left
  // or typing stops, and drawn again with every change of the amount.
  let facts = null, turn = 0, timer = 0;
  const rules = con.controls;
  Promise.resolve().then(() => { drawFees(); drawChecks(); });       // once everything below is defined
  function drawFees() {
    const rows = rules.feeTable(c.feeBps, c);       // controls_data.js: [{ amount, fee, effectivePct: "8.00" }]
    const money = (n) => show(n), pct = (r) => `${String(r.effectivePct).replace(/%$/, "")}%`;
    $("buy-fee-rows").innerHTML = `<div class="table-wrap"><table><thead><tr><th>Order (test USDC)</th><th>Fee</th><th>Fee as a share</th></tr></thead><tbody>${
      rows.map((r) => `<tr><td>${esc(money(r.amount))}</td><td>${esc(money(r.fee))}</td><td>${esc(pct(r))}</td></tr>`).join("")}</tbody></table></div>
      <p class="fine">The fee is paid by the funder, on top of the amount. On devnet it is test money.</p>`;
  }
  const link = (kind, id) => EXPLORER(kind, id);
  function drawChecks() {
    const t = template(), v = values(), f = facts, why = t?.name === "private-attested" || t?.parts.private ? "template" : f?.repo?.private ? "github" : f?.hidden ? "hidden" : "";
    $("buy-private").hidden = !why;
    $("buy-private").innerHTML = why ? con.privateHtml(why) : "";
    $("buy-private").dataset.why = why;
    const allowed = $("buy-allowed"), before = $("buy-before");
    if (!f) return;
    const name = `${f.repo?.full_name || `${f.ref.owner}/${f.ref.repo}`}#${f.ref.number}`;
    if (f.loading) { say(allowed, "Reading GitHub and devnet…"); say(before, "Reading…"); return; }
    if (!f.repo) { say(allowed, `${esc(f.error)} The budget is read by the repository's owner, so it cannot be read for this one.`); say(before, "Nothing can be matched without the repository's id, which GitHub did not give."); return; }
    const org = f.repo.owner?.type === "Organization", who = `${esc(f.repo.owner?.login || f.ref.owner)} (${org ? "an organisation" : "a personal account"}, GitHub id ${esc(f.owner)})`;
    if (f.budgetError) say(allowed, `Devnet did not give the budget of ${who}: ${esc(f.budgetError)}. Nothing is known about whether this funding would pass.`, "bad");
    else if (!f.budgets.length) allowed.innerHTML = `<div class="receipt" data-ok="" data-rule="no Balance"><strong>${who} has opened no Balance on devnet, so no budget of its own governs this funding.</strong></div>
      <p class="fine">A funding comment on this issue would draw on the devnet faucet: at most 100.00 test USDC per comment, for anyone who may comment. To put a cap, a daily and a total limit, the allowed repositories and the people who may spend in force, the organisation's wallet opens a Balance on the <a href="#money">Balance page</a>.</p>`;
    else {
      const amount = v && v.units !== null && v.units >= c.minAmount && v.units <= c.maxAmount ? v.units : null, now = clock();
      allowed.innerHTML = `<p class="fine">Funder: ${who}${f.by ? `; comment by ${esc(f.by.login)} (GitHub id ${esc(f.by.id)})` : ""}. Read from devnet at ${esc(when(now))}.</p>` + f.budgets.map((b) => {
        const ask = { balance: b.balance, balx: b.balx, repoId: f.repo.id, amount: amount ?? c.minAmount, byId: f.by?.id || 0, holds: b.holds, now };
        let said = null;
        // controls_data.js (the decision of `knos budget check`) refuses a comment by nobody, so the budget alone is asked as its owner
        try { said = rules.explainFunding({ ...ask, byId: ask.byId || b.balance.ownerId, repoOwnerId: f.owner }) || null; } catch { said = null; }
        const local = con.explainLocal(ask, c), use = said && typeof said.sentence === "string" && !(said.ok && !local.ok) ? { ...local, ...said } : local;   // what the Balance holds is read here
        return con.budgetHtml(b, amount === null ? { ...use, ok: false, rule: "amount", sentence: "Write an amount an order can take, and this says whether the budget lets it through." } : use, now, link);
      }).join("");
    }
    if (f.statementError) say(before, `The site's statement of ${who} did not load: ${esc(f.statementError)}`, "bad");
    else before.innerHTML = con.earlierHtml(con.earlierOf(f.lines, f.repo.id, f.ref.number), f.live, name, link);
  }
  async function look(force = false) {
    clearTimeout(timer);
    const ref = parseIssueUrl($("buy-issue").value), by = $("buy-by").value.trim().replace(/^@/, "");
    if (!ref || ref.kind === "pull") return;
    const key = `${ref.owner}/${ref.repo}#${ref.number}@${by}`.toLowerCase();
    if (!force && facts?.key === key) return drawChecks();       // read already, or being read: that reading draws when it ends
    const mine = ++turn;
    const f = { key, ref, loading: true, budgets: [], lines: [], live: [], by: null };
    facts = f; drawChecks();
    try { f.repo = await gh(`/repos/${ref.owner}/${ref.repo}`); } catch (e) { f.repo = null; f.error = e.message; f.hidden = /no such public/.test(e.message); }
    if (f.repo && (!Number.isSafeInteger(f.repo.id) || !Number.isSafeInteger(f.repo.owner?.id))) { f.repo = null; f.error = "GitHub did not give this repository and its owner an id."; }
    if (f.repo) {
      f.owner = f.repo.owner.id;
      if (LOGIN.test(by)) try { const u = await gh(`/users/${by}`); if (Number.isSafeInteger(u.id)) f.by = { id: u.id, login: u.login || by }; } catch { /* an account GitHub does not know: the budget is checked alone */ }
      const i = await ids().catch(() => null);
      try {
        f.budgets = await con.readBudgets(knos, rpc, i, f.owner);
        // the issue's open orders: from each of the owner's Balances, and from this browser's passkey wallet
        const sources = [...f.budgets.map((b) => b.address), ...(me ? [me.wallet] : [])];
        const at = (await Promise.all(sources.map((s) => Promise.all(Array.from({ length: SEQ_TRIES }, (_, n) => orderAddress(knos, i.knos_pay, f.repo.id, ref.number, s, n)))))).flat();
        const got = at.length ? await knos.accounts(rpc, at) : [];
        for (const [n, a] of got.entries()) {
          const o = a && a.owner === i.knos_pay ? knos.v2.readOrder(a.data) : null;
          if (!o) continue;
          const sigs = await knos.rpc(rpc, "getSignaturesForAddress", [at[n], { limit: 25, commitment: "confirmed" }]).catch(() => []);
          f.live.push({ ...o, address: at[n], fundedTx: sigs.length ? sigs[sigs.length - 1].signature : "" });
        }
      } catch (e) { f.budgetError = e.message; }
      try { const got = await file(`audit/${f.owner}.json`); f.lines = got?.type === "knos.audit-statement" ? con.linesOf(got) : []; } catch (e) { f.statementError = e.message; }
      if (!$("buy-exc-scope").value) $("buy-exc-scope").value = f.repo.full_name || `${ref.owner}/${ref.repo}`;
    }
    f.loading = false;
    if (mine === turn) drawChecks();
  }
  $("buy-issue").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => look().catch(() => {}), 700); });
  $("buy-issue").addEventListener("change", () => look().catch(() => {}));
  $("buy-by").addEventListener("change", () => look().catch(() => {}));

  $("buy-kind").onchange = kinds;
  $("buy-template").onchange = () => { const t = template(); if (t) { $("buy-amount").value = t.parts.amount; $("buy-days").value = String(t.parts.days); } pick(); };
  for (const id of ["buy-issue", "buy-amount", "buy-days", "buy-vendor", "buy-rate", "buy-checks", "buy-paths"]) $(id).addEventListener("input", redraw);

  // ---- step 3: the passkey wallet -------------------------------------------------------------------------------------------------------
  const rpId = env.rpId || globalThis.location?.hostname, credentials = env.credentials;
  const remember = () => { try { localStorage.setItem(STORE, JSON.stringify({ credentialId: me.credentialId ? b64(me.credentialId) : null, key: hex(me.key) })); } catch { /* no storage: the page works the same */ } };
  const recall = () => { try { return JSON.parse(localStorage.getItem(STORE) || "null"); } catch { return null; } };
  async function devnet() { if ((await knos.rpc(rpc, "getGenesisHash", [])) !== DEVNET) throw new Error("This page's Solana endpoint is not devnet, so nothing was signed."); }

  async function balance() {
    const out = $("buy-pk-balance");
    try {
      const program = (await ids()).knos_passkey, token = await passkey.ata(me.wallet, knos.USDC_DEVNET);
      const [opened, held] = await knos.accounts(rpc, [me.wallet, token]);
      me.nonce = Number((opened?.owner === program ? passkey.readWallet(opened.data)?.nonce : 0) ?? 0);
      const account = held ? knos.readTokenAccount(held.data) : null;
      me.holds = account && account.mint === knos.USDC_DEVNET ? account.amount : 0;
      out.innerHTML = `<strong>${esc(show(me.holds))}</strong> test USDC`;
    } catch (e) { me.holds = null; out.textContent = `not read: devnet did not answer (${e.message})`; }
  }
  async function showWallet(words) {
    $("buy-pk-status").innerHTML = `<p class="status ok" id="buy-pk-made">${esc(words)}</p>`;
    $("buy-pk-wallet").hidden = false;
    $("buy-pk-create").textContent = "Create another passkey wallet";
    $("buy-pk-create").className = "ghost small";
    $("buy-pk-address").textContent = me.wallet;
    await balance();
  }
  $("buy-pk-create").onclick = async () => {
    const st = $("buy-pk-status");
    try {
      say(st, "Asking your device to make a passkey…");
      const made = await passkey.create({ rpId, rpName: "Knos", userName: "Knos wallet" }, credentials || globalThis.navigator?.credentials);
      // the wallet of THIS build's knos_passkey (program_ids.json), the program passkey_fund.js signs for: not the
      // address passkey.create derives under the pinned id, which a build of other ids would show and never fund from
      me = { credentialId: made.credentialId, key: made.key, wallet: await passkey.wallet(made.key, (await ids()).knos_passkey) };
      remember();
      await showWallet("Your passkey wallet is made. Its address is below.");
    } catch (e) {
      const ip = /^\d+\.\d+\.\d+\.\d+$|^\[/.test(rpId || "");
      say(st, `${esc(e.message || "The passkey was not made")}. ${ip ? "Passkeys need the site's own address, not an IP number. " : ""}Nothing was created.`, "bad");
    }
  };
  $("buy-pk-refresh").onclick = () => balance();

  $("buy-pk-sign").onclick = async () => {
    const out = $("buy-pk-result"), bad = (words) => say(out, `${esc(words)} Nothing was signed.`, "bad");
    const v = values(), t = template(), no = wrong(v, true);
    signed = null;
    if (!me) return bad("Make a passkey wallet first.");
    if (no) return bad(no);
    if (!t.passkey) return bad(`This template is funded by comment: ${t.passkey_why_not}.`);
    try {
      say(out, "Reading GitHub and devnet…");
      const ref = parseIssueUrl($("buy-issue").value), terms = termsOf({ checks: v.checks, paths: v.paths }), q = quote(v.units, c);
      const pin = workflowPin();
      if (!pin) return bad("This copy of the page names no published workflow commit yet, so an order cannot be made from it.");
      const [repo, issue] = await Promise.all([gh(`/repos/${ref.owner}/${ref.repo}`), gh(`/repos/${ref.owner}/${ref.repo}/issues/${ref.number}`)]);
      const full = /^[\w.-]+\/[\w.-]+$/.test(repo.full_name || "") ? repo.full_name : `${ref.owner}/${ref.repo}`;
      if (!Number.isSafeInteger(repo.id) || repo.id < 1) return bad("GitHub did not give this repository an id.");
      if (issue.pull_request) return bad("That is a pull request. Name the issue it closes.");
      if (repo.archived) return bad(`${full} is archived: no pull request can be merged in it.`);
      if (issue.state !== "open") return bad(`${full}#${ref.number} is closed. Fund an open issue.`);
      await devnet();
      await balance();
      if (me.holds === null) return bad("Devnet did not say what the wallet holds.");
      if (me.holds < q.funderPays) return bad(`The wallet holds ${show(me.holds)} test USDC, and ${show(q.funderPays)} is needed: the amount and the fee. Put test USDC in the wallet first.`);
      const i = await ids();
      const orders = await Promise.all(Array.from({ length: SEQ_TRIES }, (_, s) => orderAddress(knos, i.knos_pay, repo.id, ref.number, me.wallet, s)));
      const seq = (await knos.accounts(rpc, orders)).findIndex((a) => !a);
      if (seq < 0) return bad(`This wallet has already funded this issue ${SEQ_TRIES} times.`);
      const expirySlot = (await knos.rpc(rpc, "getSlot", [{ commitment: "confirmed" }])) + SLOTS;
      const options = knos.v2.opts({ flags: F_NEUTRAL, holdbackBps: v.holdback * 100, warrantyDays: v.warranty });
      say(out, "Asking your device to sign this order…");
      const intent = await passkeyFundIntent({ terms: { repoId: repo.id, issue: ref.number, wfRepo: pin.repo, wfSha: pin.sha, terms: terms.bytes, workS: v.days * 86_400, seq, options },
        amount: v.units, expirySlot, wallet: { key: me.key, credentialId: me.credentialId, nonce: me.nonce } }, { rpc, ids: i, rpId, credentials });
      const line = intentComment(intent), link = `https://github.com/${full}/issues/${ref.number}`;
      signed = { intent, line, order: intent.order };
      out.innerHTML = `<p class="status ok" id="buy-signed">Signed on your device. Nothing has been sent yet.</p>
        <p>The signature is for this order and nothing else: <strong>${esc(show(q.amount))} test USDC</strong> for <a href="https://github.com/${esc(full)}/issues/${ref.number}" target="_blank" rel="noopener">${esc(full)}#${ref.number}</a>,
          plus the fee (${esc(show(q.fee))}), from your passkey wallet, under the terms of step 2. It cannot be used for another amount, other terms, or a second time, and it stops being good in about an hour.</p>
        <dl class="facts"><dt>Order</dt><dd><span class="mono" id="buy-signed-order">${esc(intent.order)}</span></dd>
          <dt>Terms hash</dt><dd><span class="mono" id="buy-signed-terms">${esc(knos.hex(await knos.sha256(terms.bytes)))}</span></dd>
          <dt>Paid only by</dt><dd>a signed run of the workflows of ${esc(pin.repo)} at commit <code>${esc(pin.sha.slice(0, 7))}</code></dd></dl>
        <label for="buy-line">The one line to post as a comment on the issue</label>
        <textarea id="buy-line" class="mono" readonly rows="5" spellcheck="false">${esc(line)}</textarea>
        <p><a id="buy-open" class="button" href="${esc(link)}" target="_blank" rel="noopener">Copy the line and open the issue</a>
          <button type="button" id="buy-copy" class="ghost small">Copy the line</button></p>
        <p class="fine">GitHub cannot fill a comment box from a link, so the button copies the line and opens the issue: paste it in the comment box at the bottom, and press Comment. The public relay reads the line,
          pays the transaction and the order's rent, and answers on the issue. You need no SOL. Then read the order in step 4.</p>`;
      copyTo($("buy-copy"), line, $("buy-line"));
      $("buy-open").addEventListener("click", () => { navigator.clipboard?.writeText(line).catch(() => {}); });
      $("buy-order").value = intent.order;
    } catch (e) {
      const refused = /NotAllowed|AbortError|cancel/i.test(`${e.name} ${e.message}`);
      bad(refused ? "Signing was cancelled, or the device said no." : e instanceof Refused ? e.message : `${e.message || "That did not work"}.`);
    }
  };

  // ---- step 4: what happened ------------------------------------------------------------------------------------------------------------
  $("buy-order-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const out = $("buy-order-result"), order = $("buy-order").value.trim();
    if (!ADDRESS.test(order)) return say(out, "Write the order's address: 32 to 44 letters and digits, as step 3 or Knos's reply shows it.", "bad");
    say(out, "Reading devnet…");
    try {
      const i = await ids(), info = await knos.accountInfo(rpc, order), o = info?.owner === i.knos_pay ? knos.v2.readOrder(info.data) : null;
      const sigs = await knos.rpc(rpc, "getSignaturesForAddress", [order, { limit: 25, commitment: "confirmed" }]);
      const events = [];
      for (const s of [...sigs].reverse()) {
        if (s.err) continue;
        const tx = await knos.rpc(rpc, "getTransaction", [s.signature, { encoding: "json", commitment: "confirmed", maxSupportedTransactionVersion: 1 }]);
        for (const line of orderLines(tx?.meta?.logMessages, order, i.knos_pay, knos)) events.push({ ...line, at: tx.blockTime ?? s.blockTime ?? 0, tx: s.signature });
      }
      const now = Math.floor(Date.now() / 1000), st = orderState(o, events, now);
      const tx = (sig) => `<a href="${esc(EXPLORER("tx", sig))}" target="_blank" rel="noopener">${esc(sig.slice(0, 8))}…</a>`;
      const said = { funded: (e) => `funded with ${show(Number(e.amount))} and a fee of ${show(Number(e.fee))}`, terms: () => "its terms were logged", reserved: (e) => `reserved by GitHub id ${e.taker}`,
        cancelled: () => "cancelled: it ends 7 days after this", paid: (e) => `paid ${show(Number(e.amount))} to GitHub id ${e.payee}${Number(e.pr) ? ` for pull request #${e.pr}` : ""}`,
        settled: (e) => `accepted by ${JUDGES[e.judge] || "its judge"}; fee ${show(Number(e.fee) + Number(e.tip))}`, held: (e) => `held for GitHub id ${e.payee}, who has bound no wallet`,
        warranty: (e) => `${show(Number(e.held))} held back as the warranty`, released: (e) => `the holdback, ${show(Number(e.amount))}, released to GitHub id ${e.payee}`,
        refunded: (e) => `${show(Number(e.amount))} sent back to the funder`, reverted: (e) => `reverted: ${show(Number(e.amount))} went back to the funder`,
        kill: (e) => `a kill fee of ${show(Number(e.amount))} to the person who had reserved it`, topup: (e) => `topped up by ${show(Number(e.add))}`, assigned: () => "its payment was assigned" };
      const paid = events.filter((e) => e.event === "paid");
      const t = template(), accepted = paid.length || events.some((e) => e.event === "held");
      const receipt = accepted ? `<h4>Accepted: the receipt, in its five parts</h4><dl class="parts" id="buy-receipt">
          ${con.receiptParts(o, events, tx, t ? t.trusted.slice(1) : null).map(([head, line]) => `<dt>${esc(head)}</dt><dd>${line}</dd>`).join("")}</dl>
          <p class="fine">${paid.length ? `Paid ${esc(show(paid.reduce((n, e) => n + Number(e.amount), 0)))} test USDC to ${paid.length === 1 ? "one person" : `${paid.length} people`}. ` : ""}Each line is what the chain's log holds. The receipt as a file with every claim is specified in docs/RECEIPT.md.</p>` : "";
      const answers = `<h4>Who answers if this fails</h4><p id="buy-answers">${esc(con.ANSWERS)}</p>`;
      out.innerHTML = `<p class="verdict ${st.state === "none" ? "" : "ok"}" id="buy-state" data-state="${esc(st.state)}">${esc(st.state === "none" ? "No order yet" : st.state[0].toUpperCase() + st.state.slice(1))}</p>
        <p id="buy-state-words">${esc(st.words)}</p>
        <ul class="inline" id="buy-states" aria-label="The states an order goes through">${STATES.map((s) => `<li class="pill" data-reached="${st.reached.includes(s) ? 1 : 0}">${st.reached.includes(s) ? `<strong>${esc(s)}</strong>` : esc(s)}${s === st.state ? " (now)" : ""}</li>`).join("")}</ul>
        ${events.length ? `<h4>What the program logged</h4><ul class="plain" id="buy-events">${events.filter((e) => said[e.event]).map((e) => `<li>${esc(when(e.at))}: ${esc(said[e.event](e))} ${tx(e.tx)}</li>`).join("")}</ul>` : ""}
        ${receipt}
        ${st.state === "none" ? "" : answers}`;
    } catch (e) { say(out, `Devnet did not answer: ${esc(e.message)}. Try again.`, "bad"); }
  };

  // ---- what needs a person: an organisation's orders, or one repository's ---------------------------------------------------------------
  $("buy-exc-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const out = $("buy-exc"), asked = $("buy-exc-scope").value.trim().replace(/^@/, ""), [owner, repo] = asked.split("/");
    if (!(LOGIN.test(owner || "") || /^\d{1,15}$/.test(owner || "")) || (repo !== undefined && !/^[\w.-]+$/.test(repo)) || asked.split("/").length > 2) return say(out, "Write the organisation's GitHub name, or one repository as owner/repo.", "bad");
    say(out, "Reading this site and devnet…");
    try {
      const got = repo ? await gh(`/repos/${owner}/${repo}`) : null, id = got ? got.owner?.id : /^\d+$/.test(owner) ? Number(owner) : (await gh(`/users/${owner}`)).id;
      if (!Number.isSafeInteger(id) || (got && !Number.isSafeInteger(got.id))) throw new Error("GitHub did not give that account an id.");
      const statement = await file(`audit/${id}.json`), all = statement?.type === "knos.audit-statement" ? con.linesOf(statement) : [];
      const lines = got ? all.filter((r) => Number(r.repository_id) === got.id) : all, orders = [...new Set(lines.map((r) => r.order))].filter((a) => ADDRESS.test(a)).slice(0, 100);
      const i = await ids(), live = new Map();
      let chain = "";
      try { for (const [n, a] of (orders.length ? await knos.accounts(rpc, orders) : []).entries()) live.set(orders[n], a && a.owner === i.knos_pay ? knos.v2.readOrder(a.data) : null); }
      catch (e) { chain = `Devnet did not answer (${e.message}), so deadlines and reservations could not be read: this list is the statement's alone.`; }
      const record = got ? await file(`r/${got.full_name}.json`).catch(() => null) : null, refused = record?.as_earner?.refusals_at_merge ?? null;
      const rows = con.exceptionsOf({ lines, live, now: clock(), refused, repo: got?.full_name || "" });
      out.innerHTML = `${con.exceptionsHtml(rows, link, asked)}
        <p class="fine" id="buy-exc-source">From ${lines.length} line${lines.length === 1 ? "" : "s"} of the site's statement of GitHub id ${esc(id)}${all.length ? "" : " (this site has no statement for it)"} and the ${live.size} order account${live.size === 1 ? "" : "s"} read from devnet at ${esc(when(clock()))}. ${esc(chain)}
          ${refused === null ? "Tokens the relay refused are not in this site's files for this scope." : ""}</p>`;
    } catch (e) { say(out, esc(e.message), "bad"); }
  };

  // ---- the statement, the templates, and a wallet this browser kept ----------------------------------------------------------------------
  renderOrderStatement($("buy-statement-box"), { EXPLORER, gh, file: env.file });
  const ready = (env.templates ? Promise.resolve(env.templates) : fetch("buyer_templates.json").then((r) => { if (!r.ok) throw new Error(`buyer_templates.json did not load (${r.status})`); return r.json(); }))
    .then((got) => { book = got; kinds(); })
    .catch((e) => { $("buy-sentence").textContent = `The templates did not load: ${e.message}. Reload the page.`; });
  const saved = recall();
  if (saved?.key) {
    (async () => {
      const key = passkey.compressed(unhex(String(saved.key)));
      me = { credentialId: saved.credentialId ? unb64(String(saved.credentialId)) : null, key, wallet: await passkey.wallet(key, (await ids()).knos_passkey) };
      await showWallet("The passkey wallet this browser kept is in use.");
    })().catch(() => {});
  }
  return ready;
}
