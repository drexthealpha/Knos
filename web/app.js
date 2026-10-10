// The pages of Knos that read Solana: add money to a Balance from your wallet, read an escrow, look up a GitHub account,
// the public numbers and who can change the programs. Everything is read in the browser from GitHub's public API and
// Solana devnet. The only writes are links to GitHub (where GitHub asks you to confirm) and the transactions your own
// wallet signs, each built by sdk/settle (settle.js here). No link carries an address: binding a wallet is done by hand
// on GitHub (see "Get paid" in index.html). Devnet only.
// This file is not part of the first screen: web/front.js asks for it when one of these pages is first opened (its
// PAGES), shows which page is on and calls open(name) on every arrival. Each page's own module is asked for here, the
// first time that page is opened (PARTS below).
import * as knos from "./settle.js";
import { esc } from "./front.js";
import { VIEWS, ALIAS } from "./views.js";
import { pendingUpgrades, upgradeWords, runDay, feedLine, inWords } from "./upgrade.js";

const $ = (id) => document.getElementById(id);
const FIRST_PAY = $("first-deployment")?.querySelectorAll(".mono")[1]?.textContent.trim();
const RPC = "https://api.devnet.solana.com";
const GH = "https://api.github.com";
const CHAIN = "solana:devnet";
// What makes an endpoint devnet: the hash of its first block. Anything else is refused before a transaction is built.
const DEVNET = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG";
const EXPLORER = (kind, id) => `https://explorer.solana.com/${kind}/${id}?cluster=devnet`;
const link = (kind, id, text = id) => `<a class="mono" href="${esc(EXPLORER(kind, id))}" target="_blank" rel="noopener">${esc(text)}</a>`;
const money = (u, decimals = 6, digits = 2) => (u / 10 ** decimals).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: Math.max(2, digits) });
const say = (el, html, kind = "") => { el.innerHTML = `<p class="status ${kind}">${html}</p>`; };
const when = (t) => (t ? `${new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC` : "never");
const took = (s) => (s == null ? "n/a" : s < 120 ? `${s} s` : s < 7200 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`);
const short = (a) => `${a.slice(0, 4)}…${a.slice(-4)}`;
const le = (...nums) => { const out = new Uint8Array(8 * nums.length), dv = new DataView(out.buffer); nums.forEach((n, i) => dv.setBigUint64(8 * i, BigInt(n), true)); return out; };
const b64 = (u8) => btoa(String.fromCharCode(...u8));

// ---- what each arrival at a page does ---------------------------------------------------------------------------------------
export { VIEWS, ALIAS };          // web/views.js holds the two lists; web/front.js reads the same ones
async function route() {
  const at = location.hash, [raw, ...rest] = at.replace(/^#/, "").split("=");
  const arg = rest.length ? decodeURIComponent(rest.join("=")) : "";
  const name = ALIAS[raw] || raw, view = VIEWS.includes(name) ? name : "check";
  await (PARTS[PART_OF[raw] || view] || PARTS[raw])?.();
  if (location.hash !== at) return;          // the reader has gone on: the newer arrival does its own
  if (view === "network") loadNetwork();
  if (view === "fund") { fillLatency(); anyShow(); }
  if (view === "pricing") upgradesP.then((u) => showVersion(u.upgrades.length ? (runDay(u.upgrades, "knos_pay") ? `an upgrade of knos_pay is approved and can be run from ${runDay(u.upgrades, "knos_pay")}` : "an upgrade of knos_pay is pending, not yet approved") : ""));
  if (view === "records") {
    showRecords(raw === "records" || raw === "statement" || !arg ? "records" : raw, arg);
    if (raw === "statement") showStatement(arg);
  }
  if (view === "fund" && arg && raw !== "anyissue") { $("st-issue").value = arg; readEscrow(); }
  if (view === "claim" && arg) { $("due-login").value = arg; readAccount(); }
  if (raw === "money") $("money").scrollIntoView?.();
  if (raw === "task") $("task").scrollIntoView?.();
  if (raw === "anyissue") { if (arg) $("any-issue").value = arg; $("anyissue").scrollIntoView?.(); }
}
export const open = () => route();

// ---- the deployed programs, GitHub, Solana --------------------------------------------------------------------------
let idsP;
const ids = () => (idsP ||= fetch("program_ids.json").then((r) => { if (!r.ok) throw new Error("program_ids.json is missing from this build"); return r.json(); }));
const client = async () => knos.v2.client(await ids());

async function gh(path) {
  const r = await fetch(GH + path, { headers: { Accept: "application/vnd.github+json" } });
  if ((r.status === 403 || r.status === 429) && r.headers.get("x-ratelimit-remaining") === "0") {
    throw new Error("GitHub's free limit for this network is used up (60 reads an hour without login). Try again in an hour.");
  }
  if (r.status === 404) throw new Error("GitHub has no such public repository, issue or user.");
  if (!r.ok) throw new Error(`GitHub said ${r.status}`);
  return r.json();
}

// Solana's answer to "is this devnet?": the hash of its first block.
async function devnet() {
  if ((await knos.rpc(RPC, "getGenesisHash", [])) !== DEVNET) throw new Error("This page's Solana endpoint is not devnet, so nothing was sent.");
}

function parseIssue(s) {
  const m = /^(?:https:\/\/github\.com\/)?([\w.-]+)\/([\w.-]+?)(?:#|\/issues\/)(\d+)\/?$/.exec((s || "").trim());
  return m ? { owner: m[1], repo: m[2], number: Number(m[3]) } : null;
}

// What a mint's money is called: devnet's is all test USDC.
const moneyName = (mint, faucet) => (faucet || mint === knos.USDC_DEVNET ? "test USDC" : `of the test token ${short(mint)}`);

// ---- add money: a Balance, from your wallet ------------------------------------------------------------------------
const wallet = { pick: null, w: null, address: null, owner: null, mint: null, balance: null, pending: null, listeners: [] };

// "20", "0.5": digits with at most `decimals` decimals, in the mint's smallest units. null for anything else, or too big.
export function units(text, decimals = 6) {
  const m = /^(\d{1,15})(?:\.(\d{1,18}))?$/.exec(String(text).trim());
  if (!m || (m[2] || "").length > decimals) return null;
  const n = BigInt(m[1]) * 10n ** BigInt(decimals) + BigInt((m[2] || "").padEnd(decimals, "0") || 0);
  return n <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(n) : null;          // a number the page cannot hold exactly is not sent
}

// The two cards that ask for a wallet (Add money, Fund any issue) share it: connecting in one shows in both.
const SPOTS = [["wallet-status", "wallet-connect", "wallet-address"], ["any-wallet", "any-connect", "any-address"]];
async function connectTo(w, from = "wallet-status") {
  const st = $(from);
  try {
    say(st, `Asking ${esc(w.name)}…`);
    const address = await w.connect(CHAIN);
    await devnet();
    Object.assign(wallet, { w, address, balance: null, pending: null });
    for (const [status, button, id] of SPOTS) {
      $(status).innerHTML = `<p class="status ok">Connected: <span class="mono" id="${id}">${esc(address)}</span> (${esc(w.name)}). Solana devnet.</p>
      <p class="fine">It needs a little devnet SOL for fees and, to put money in, test USDC from
      <a href="https://faucet.circle.com/" target="_blank" rel="noopener">Circle's devnet faucet</a>.</p>`;
      $(button).textContent = "Switch wallet";
    }
    for (const listener of wallet.listeners) listener();
  } catch (e) { say(st, esc(e.message), "bad"); }
}

for (const [status, button] of SPOTS) {
  $(button).onclick = () => {
    const list = knos.wallets();
    if (!list.length) return say($(status), "No Solana wallet found in this browser. Install Phantom, Solflare or Backpack, set it to devnet and reload this page.", "bad");
    if (list.length === 1) return connectTo(list[0], status);
    wallet.pick = list;
    $(status).innerHTML = `<p class="fine">Which wallet?</p>${list.map((w, i) => `<button type="button" class="small" data-wallet="${i}">${esc(w.name)}</button>`).join(" ")}`;
  };
  $(status).addEventListener("click", (ev) => {
    const i = ev.target.closest?.("[data-wallet]")?.dataset.wallet;
    if (i !== undefined && wallet.pick?.[i]) connectTo(wallet.pick[i], status);
  });
}
try { knos.wallets(); } catch { /* the page still reads without one */ }       // so a wallet that loads after this page is heard

// Everything about the Balance this wallet would have for this GitHub owner and mint, read now.
async function readBalance() {
  const k = await client(), { owner, mint, address } = wallet;
  const balance = await k.balance(owner.id, address, mint.address), baltok = await k.baltok(balance);
  const mine = await knos.ata(address, mint.address, mint.program);
  const [raw, held, have, lamports] = await Promise.all([knos.account(RPC, balance), knos.account(RPC, baltok), knos.account(RPC, mine),
    knos.rpc(RPC, "getBalance", [address, { commitment: "confirmed" }]).then((r) => r.value)]);
  const data = knos.v2.readBalance(raw);
  const spenders = await Promise.all((data?.spenders || []).map((id) => gh(`/user/${id}`).then((u) => u.login).catch(() => null)));
  return { k, balance, baltok, mine, data, spenders, holds: knos.readTokenAccount(held)?.amount ?? 0, have: knos.readTokenAccount(have)?.amount ?? null, lamports };
}

async function showBalance() {
  const out = $("balance-state"), st = $("money-status");
  $("money-preview").innerHTML = "";
  wallet.pending = null;
  const b = wallet.balance = await readBalance();
  const { owner, mint } = wallet, d = mint.decimals, words = moneyName(mint.address, b.data?.faucet);
  const people = b.data ? (b.data.spenders.length ? `the owner and ${b.data.spenders.map((id, i) => esc(b.spenders[i] || `GitHub id ${id}`)).join(", ")}` : "the owner only") : "";
  out.innerHTML = `<h4>${b.data ? "Your Balance" : "No Balance yet"} for ${esc(owner.login)} (GitHub id ${owner.id}, ${esc(owner.type.toLowerCase())})</h4>
    ${b.data ? `<dl class="facts" id="balance-facts">
      <dt>Holds</dt><dd><strong id="balance-amount">${money(b.holds, d, d)}</strong> ${esc(words)}</dd>
      <dt>One task may take</dt><dd>${b.data.capPerJob ? `at most ${money(b.data.capPerJob, d, d)}` : "any amount (no cap)"}</dd>
      <dt>May spend it by comment</dt><dd>${people}</dd>
      <dt>Spent on tasks so far</dt><dd>${money(b.data.spent, d, d)}</dd>
      <dt>Balance</dt><dd>${link("address", b.balance)}</dd>
      <dt>Its token account</dt><dd>${link("address", b.baltok)}</dd>
    </dl>` : `<p class="fine">Opening it creates the Balance for ${esc(owner.login)}'s repositories, and only this wallet can take money out of it.</p>`}
    <p class="fine">This wallet holds ${b.have === null ? `no ${esc(words)} token account yet` : `${money(b.have, d, d)} ${esc(words)}`} and
      ${(b.lamports / 1e9).toFixed(3)} SOL.</p>
    <form id="money-form" autocomplete="off">
      <label for="money-amount">${b.data ? "Add" : "Put in"} (${esc(words)})</label>
      <input id="money-amount" inputmode="decimal" placeholder="20">
      <label for="money-cap">The most one task may take (blank: no cap)</label>
      <input id="money-cap" inputmode="decimal" placeholder="blank" value="${b.data?.capPerJob ? money(b.data.capPerJob, d, d).replace(/,/g, "") : ""}">
      <label for="money-spenders">Who else may spend it by comment: GitHub logins, up to four</label>
      <input id="money-spenders" placeholder="octocat, mona" value="${b.data && b.spenders.every(Boolean) ? esc(b.spenders.join(", ")) : ""}">
      ${b.data && !b.spenders.every(Boolean) ? `<p class="fine">Saving replaces the whole list.</p>` : ""}
      <button type="button" id="money-add">${b.data ? "Add money" : "Open the Balance"}</button>
      ${b.data ? `<button type="button" id="money-set" class="ghost">Save who may spend it, and the cap</button>
      <label for="money-out">Take back (blank: everything)</label>
      <input id="money-out" inputmode="decimal" placeholder="blank">
      <button type="button" id="money-withdraw" class="ghost">Withdraw to this wallet</button>` : ""}
    </form>`;
  $("money-add").onclick = () => plan(b.data ? "add" : "open");
  if (b.data) { $("money-set").onclick = () => plan("set"); $("money-withdraw").onclick = () => plan("withdraw"); }
  st.textContent = "";
}

async function lookup(ev) {
  ev?.preventDefault();
  const out = $("owner-result");
  if (!wallet.address) return say(out, "Connect a wallet first.", "bad");
  const login = $("owner-login").value.trim().replace(/^@/, ""), mintText = $("money-mint").value.trim();
  if (!/^[\w-]+$/.test(login)) return say(out, "Enter a GitHub login.", "bad");
  if (!knos.isAddress(mintText)) return say(out, "That is not a Solana address. Use the mint's address.", "bad");
  say(out, "Reading GitHub and Solana…");
  try {
    await devnet();
    const [user, info] = await Promise.all([gh(`/users/${login}`), knos.accountInfo(RPC, mintText)]);
    const decimals = info && knos.readMint(info.data)?.decimals;
    if (!info || ![knos.TOKEN, knos.TOKEN_2022].includes(info.owner) || decimals === null || decimals === undefined) {
      throw new Error("That address is not a token mint on devnet.");
    }
    wallet.owner = { id: user.id, login: user.login, type: user.type || "User" };
    wallet.mint = { address: mintText, program: info.owner, decimals };
    out.innerHTML = "";
    await showBalance();
  } catch (e) { say(out, esc(e.message), "bad"); }
}
$("owner-form").onsubmit = lookup;

async function spendersOf(text) {
  const logins = [...new Set(text.split(/[\s,]+/).map((s) => s.replace(/^@/, "")).filter(Boolean))];
  if (logins.length > 4) throw new Error("A Balance lists at most four people besides its owner.");
  return Promise.all(logins.map((l) => gh(`/users/${l}`).then((u) => u.id)));
}

// The words for what a transaction would do, one line per instruction.
function describe(e, d, words) {
  const a = e.args, cap = (n) => (n ? `no task may take more than ${money(n, d, d)}` : "no cap on one task");
  if (e.name === "OpenBalance") return `Open a Balance for GitHub owner ${a.ownerId}: ${cap(a.cap)}; ${a.spenders.length ? `GitHub ids ${a.spenders.join(", ")} may spend it by comment, besides the owner` : "only the owner may spend it by comment"}.`;
  if (e.name === "SetBalance") return `Change who may spend the Balance and its cap: ${cap(a.cap)}; ${a.spenders.length ? `GitHub ids ${a.spenders.join(", ")}, besides the owner` : "only the owner"}.`;
  if (e.name === "Withdraw") return `Move ${a.amount ? money(a.amount, d, d) : "everything"} out of the Balance into your own token account.`;
  if (e.name === "TransferChecked") return `Move ${money(a.amount, d, d)} ${words} from your token account into the Balance's token account.`;
  if (e.name === "CreateIdempotent") return "Create your token account for this mint, unless you have one. You pay its small deposit.";
  return `${e.program}: ${e.name}`;
}

// Build the transaction for one action, check it against devnet, and show it. Nothing is signed until "Sign" is pressed.
async function plan(kind) {
  const st = $("money-status"), pre = $("money-preview"), b = wallet.balance, { owner, mint, address } = wallet, d = mint.decimals;
  const name = moneyName(mint.address), amountText = $("money-amount")?.value.trim() || "";
  pre.innerHTML = "";
  wallet.pending = null;
  try {
    const amount = units(amountText, d), out = kind === "withdraw" ? units($("money-out").value || "0", d) : 0;
    const cap = kind === "open" || kind === "set" ? units($("money-cap").value || "0", d) : 0;
    if (cap === null) throw new Error("The cap is a number like 5 or 2.5, or blank for none.");
    if (out === null) throw new Error("Write the amount to take back as a number, or leave it blank for everything.");
    if ((kind === "add" || (kind === "open" && amountText)) && !amount) throw new Error(`Write how much to add as a number like 20 or 2.5, with at most ${d} decimals.`);
    if (kind === "withdraw" && (!b.holds || out > b.holds)) throw new Error(b.holds ? `The Balance holds ${money(b.holds, d, d)}, so that much cannot be taken back.` : "The Balance holds nothing to take back.");
    say(st, "Checking…");
    await devnet();
    const spenders = kind === "open" || kind === "set" ? await spendersOf($("money-spenders").value) : [];
    const base = { authority: address, tokenProgram: mint.program }, k = b.k, ixs = [];
    if (kind === "open") ixs.push(await k.openBalanceIx({ ...base, ownerId: owner.id, mint: mint.address, cap, spenders }));
    if (kind === "set") ixs.push(k.setBalanceIx({ authority: address, balance: b.balance, cap, spenders }));
    if (amount && (kind === "open" || kind === "add")) {
      if (b.have === null || b.have < amount) {
        throw new Error(`This wallet holds ${money(b.have || 0, d, d)} ${name}, and ${money(amount, d, d)} is to go in. `
          + (mint.address === knos.USDC_DEVNET ? "Circle's devnet faucet gives test USDC." : "Get some of that token first."));
      }
      ixs.push(knos.transferCheckedIx(b.mine, mint.address, b.baltok, address, amount, d, mint.program));
    }
    if (kind === "withdraw") {
      if (b.have === null) ixs.push(await knos.createAtaIx(address, address, mint.address, mint.program));
      ixs.push(await k.withdrawIx({ ...base, balance: b.balance, mint: mint.address, amount: out }));
    }
    if (!ixs.length) throw new Error("Nothing to do: write an amount to put in.");
    const sim = await knos.rpc(RPC, "simulateTransaction", [b64(await sendable(ixs)), { encoding: "base64", sigVerify: false, replaceRecentBlockhash: true, commitment: "confirmed" }]);
    if (sim.value.err) throw new Error(whyFailed(sim.value.err, sim.value.logs));
    wallet.pending = { ixs, kind };
    const lines = ixs.map((ix) => { const e = k.explain(ix); return `<li>${esc(describe(e, d, name))}
      <details><summary class="fine">${esc(e.program)}: ${esc(e.name)}</summary><ul class="mono">${e.accounts.map((a) => `<li>${esc(a.name)}: ${esc(a.pubkey)}${a.signer ? " (signs)" : ""}${a.writable ? " (changes)" : ""}</li>`).join("")}</ul></details></li>`; });
    pre.innerHTML = `<h4>This is what you would sign</h4><p class="fine">On Solana devnet, from <span class="mono">${esc(address)}</span>. Devnet checked it just now and accepts it.</p>
      <ol id="money-steps">${lines.join("")}</ol><button type="button" id="money-send">Sign in my wallet</button>`;
    $("money-send").onclick = send;
    st.textContent = "";
  } catch (e) { say(st, esc(e.message), "bad"); }
}

// The unsigned transaction on a recent devnet blockhash (another cluster would refuse it).
async function sendable(ixs) {
  const { blockhash } = (await knos.rpc(RPC, "getLatestBlockhash", [{ commitment: "confirmed" }])).value;
  return knos.serializeTx(ixs, wallet.address, blockhash);
}

function whyFailed(err, logs = []) {
  const known = knos.v2.errorWords(err);
  if (known) return known;
  if (err === "AccountNotFound") return "This wallet has no SOL on devnet, so it cannot pay the fee. Get some from a devnet faucet and try again.";
  if (typeof err === "string" && /Insufficient/.test(err)) return "This wallet needs more devnet SOL for the fee and the deposits. Get some from a devnet faucet and try again.";
  const clue = (logs || []).filter((l) => /fail|error|insufficient|invalid/i.test(l)).at(-1);
  return `Devnet would refuse it (${JSON.stringify(err).slice(0, 120)})${clue ? `: ${clue}` : ""}.`;
}

// Ask the wallet to sign and send, then wait for devnet to show the transaction: the link to it. When devnet does not show it within a
// minute that is said in `st`, and the answer is null. Nothing is sent to a cluster that is not devnet.
async function signAndConfirm(ixs, st) {
  await devnet();
  say(st, `Approve it in ${esc(wallet.w.name)}…`);
  const signature = await wallet.w.signAndSend(await sendable(ixs), CHAIN);
  if (!/^[1-9A-HJ-NP-Za-km-z]{64,90}$/.test(signature)) throw new Error("The wallet did not give back a transaction signature.");
  const where = `<a href="${esc(EXPLORER("tx", signature))}" target="_blank" rel="noopener">transaction</a>`;
  say(st, `Sent. Waiting for devnet to confirm… ${where}`);
  const done = await knos.confirmed(RPC, signature);
  if (!done) {
    st.innerHTML = `<p class="status bad">Devnet did not show the ${where} within a minute. If your wallet is set to another network, nothing happened there: other networks refuse a devnet transaction.</p>`;
    return null;
  }
  if (!done.ok) throw new Error(whyFailed(done.err));
  return where;
}

async function send() {
  const st = $("money-status"), todo = wallet.pending, button = $("money-send");
  if (!todo) return;
  button.disabled = true;
  try {
    const where = await signAndConfirm(todo.ixs, st);
    if (!where) return;
    await showBalance();
    st.innerHTML = `<p class="status ok" id="money-done">Done. ${where}.</p>`;
  } catch (e) {
    button.disabled = false;
    say(st, esc(e.message), "bad");
  }
}

// ---- what is in escrow for an issue ----------------------------------------------------------------------------------
async function jobHtml(address, j, now) {
  const d = 6, words = moneyName(j.mint, j.faucet), fee = knos.v2.feeOf(j.amount);
  const state = j.state === "held"
    ? `<strong>held</strong> for GitHub user ${esc(await gh(`/user/${j.payeeId}`).then((u) => u.login).catch(() => j.payeeId))} until ${when(j.holdUntil)}; if they bind a wallet before then it can be sent there, and otherwise it goes back to the funder`
    : `<strong class="status ok">open</strong>: ${j.mode === knos.MERGE ? "paid when a maintainer merges the pull request that closes the issue" : "paid without a merge, when its black-box check passes"}`;
  const left = Math.max(0, j.deadline - now);
  return `<dl class="facts">
    <dt>In escrow</dt><dd><strong>${money(j.amount, d, d)} ${esc(words)}</strong> (fee when paid: ${money(fee, d, d)})</dd>
    <dt>State</dt><dd>${state}</dd>
    <dt>Funded by</dt><dd>${j.fromBalance ? `the Balance of GitHub owner ${j.ownerId}${j.faucet ? ", free faucet money" : ""}, by GitHub user ${j.funderId}` : `wallet <span class="mono">${esc(j.source)}</span>`}</dd>
    <dt>If unpaid</dt><dd>${j.state === "open" ? `goes back to where it came from ${left ? `in ${Math.ceil(left / 3600)} h` : "now (anyone may send it)"}` : `held until ${when(j.holdUntil)}`}</dd>
    <dt>Terms (hash)</dt><dd class="mono">${esc(j.terms)}</dd>
    <dt>Account</dt><dd>${link("address", address)}</dd>
  </dl>`;
}

async function readEscrow(ev) {
  ev?.preventDefault();
  const out = $("st-result"), ref = parseIssue($("st-issue").value);
  if (!ref) return say(out, "Enter the issue as owner/repo#7.", "bad");
  say(out, "Reading GitHub and Solana…");
  try {
    const [repo, k, now] = await Promise.all([gh(`/repos/${ref.owner}/${ref.repo}`), client(), knos.chainTime(RPC)]);
    const found = (await knos.programAccounts(RPC, k.ids.knos_pay, knos.v2.JOB_LEN, 8, le(repo.id, ref.number)))
      .map((f) => ({ address: f.address, job: knos.v2.readJob(f.data) })).filter((f) => f.job);
    if (!found.length) {
      out.innerHTML = `<p class="status">Nothing is in escrow for ${esc(ref.owner)}/${esc(ref.repo)}#${ref.number}.</p>
        <p class="fine">The repository's owner funds it by commenting <code>/knos fund 20</code> on the issue.</p>`;
      return;
    }
    out.innerHTML = (await Promise.all(found.map((f) => jobHtml(f.address, f.job, now)))).join("<hr>");
  } catch (e) { say(out, esc(e.message), "bad"); }
}
$("status-form").onsubmit = readEscrow;

// How long a comment took to become money, as measured (stats.json), in the sentence on the Fund view.
let statsP;
const stats = () => (statsP ||= fetch("stats.json").then((r) => (r.ok ? r.json() : null)).catch(() => null));
async function fillLatency() {
  const l = (await stats())?.latency?.comment_to_funded;
  if (l && l.count > 0) {
    $("fund-latency").innerHTML = `the median is ${took(l.median)} and the slowest ${took(l.slowest)}, over ${l.count} funded task${l.count === 1 ? "" : "s"}
      (<a href="#network">Numbers</a>)`;
  }
}

// ---- a GitHub account: its bound wallet, what is held for it, its record ------------------------------------------------
async function readAccount(ev) {
  ev?.preventDefault();
  const out = $("due-result"), login = $("due-login").value.trim().replace(/^@/, "");
  if (!/^[\w-]+(\[bot\])?$/.test(login)) return say(out, "Enter a GitHub login.", "bad");
  say(out, "Reading GitHub and Solana…");
  try {
    const [user, k] = await Promise.all([gh(`/users/${login}`), client()]);
    // The first deployment is read on its own: when it cannot be read, that is said, and the second deployment's
    // wallet, holds and record are still shown.
    const firstRead = (FIRST_PAY ? knos.programAccounts(RPC, FIRST_PAY, knos.DUE_LEN, 8, le(user.id))
      : Promise.reject(new Error("the page does not name its program"))).then((dues) => ({ dues }), (e) => ({ error: e }));
    const [bindRaw, repRaw, jobs, first] = await Promise.all([knos.account(RPC, await k.bind(user.id)), knos.account(RPC, await k.rep(user.id)),
      knos.programAccounts(RPC, k.ids.knos_pay, knos.v2.JOB_LEN, 56, le(user.id)), firstRead]);
    const bind = knos.v2.readBind(bindRaw), rep = knos.v2.readRep(repRaw);
    const held = jobs.map((f) => knos.v2.readJob(f.data)).filter((j) => j && j.state === "held" && j.payeeId === user.id);
    const oldDues = (first.dues || []).map((f) => knos.parseDue(f.data)).filter((d) => d && d.userId === user.id && d.amount > 0);
    const bound = bind ? `<p class="verdict ok" id="due-bound">Paid at ${esc(bind.wallet)}</p><p class="fine">Bound ${when(bind.iat)}. Every task now pays this wallet.</p>`
      : `<p class="status" id="due-bound">No wallet is bound for ${esc(user.login)}.</p>`;
    const holds = held.length ? held.map((j) => `<p class="verdict ok">${money(j.amount)} ${esc(moneyName(j.mint, j.faucet))} is held for ${esc(user.login)} until ${when(j.holdUntil)}.</p>
      <p class="fine">${bind ? "A wallet is bound, so it can be sent there now: comment <code>/knos settle</code> on the merged pull request." : "Bind a wallet before then and it can be sent there. After that date it goes back to the funder."}</p>`).join("")
      : `<p class="status">Nothing is held for ${esc(user.login)} ${oldDues.length || first.error ? "on the second deployment" : "right now"}.</p>`;
    const firstHolds = oldDues.length ? `<section id="due-v1"><h4>First deployment (v1)</h4>${oldDues.map((d) => `<p class="verdict ok">${money(d.amount)} ${esc(moneyName(d.mint, false))} is still held for ${esc(user.login)} on the first deployment.</p>`).join("")}
      <p class="fine">First authenticate GitHub CLI as ${esc(user.login)} with <code>gh auth login</code>, then send it to an address you choose with <code>knos claim --v1 &lt;address&gt;</code>.</p></section>`
      : first.error ? `<p class="status bad" id="due-v1-unread">Could not read the first deployment just now (${esc(first.error.message)}), so anything still held there is not shown. Try again in a moment.</p>` : "";
    const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
    out.innerHTML = `${bound}${holds}${firstHolds}<h4>The record on Solana</h4><dl class="facts" id="due-record">
      <dt>Paid by others</dt><dd><strong>${plural(rep.paid, "payment")}</strong> from <strong>${plural(rep.funders, "different funder")}</strong>, ${money(rep.total)} test USDC in all${rep.paid ? ` (${when(rep.first)} to ${when(rep.last)})` : ""}</dd>
      <dt>From the faucet</dt><dd>${plural(rep.testPaid, "payment")}, ${money(rep.testTotal)} of the faucet's free test USDC. Counted apart.</dd>
      <dt>Paid by themselves</dt><dd>${plural(rep.selfPaid, "payment")}, where the funder was the person paid. Counted apart.</dd>
    </dl><p class="fine">GitHub account id ${user.id}. All of it is test USDC on devnet. Only a payment adds to this record, and the three kinds are never added together.</p>
      <p class="fine"><a id="due-public" href="#u=${encodeURIComponent(user.login)}">The public record of ${esc(user.login)}</a>: what was paid and refunded, by kind of money, and the README badge line.</p>`;
  } catch (e) { say(out, esc(e.message), "bad"); }
}
$("due-form").onsubmit = readAccount;

// ---- the public numbers ----------------------------------------------------------------------------------------------
const stat = (n, label) => `<div class="stat"><b>${esc(n)}</b><span>${esc(label)}</span></div>`;
const KINDS = [["outside", "Outside use"], ["own", "Knos's own accounts"], ["self", "Paid to themselves"], ["test", "Free faucet money"]];

function numbersHtml(s) {
  const o = s.outside, t = s.totals, f = s.funnel, l = s.latency || {}, by = s.by_deployment || {}, live = s.live || {};
  const side = (k) => (k === "outside" ? o : s.apart[k]);
  const spread = (name, x) => `<tr><td>${esc(name)}</td><td>${x?.count ?? 0}</td><td>${took(x?.median)}</td><td>${took(x?.p90)}</td><td>${took(x?.slowest)}</td></tr>`;
  const funnel = (label, n, note) => `<li>${esc(label)}: <strong>${n === null || n === undefined ? "not measured" : esc(n)}</strong>${note && note !== "not measured" ? ` <span class="fine">(${esc(note)})</span>` : ""}</li>`;
  const recent = (s.recent || []).map((p) => `<tr><td>${esc(p.kind)}</td><td>${/^[1-9A-HJ-NP-Za-km-z]{60,90}$/.test(p.tx || "") ? `<a href="${EXPLORER("tx", p.tx)}" target="_blank" rel="noopener">${money(p.amount)}</a>` : money(p.amount)}</td>
    <td>repository ${esc(p.repo)}, issue #${esc(p.issue)}</td><td>GitHub user ${esc(p.payee)}</td><td>${took(p.seconds)}</td><td>${p.deployment === 1 ? "first" : "second"}</td></tr>`).join("");
  return `<h3>Outside use</h3>
    <p class="fine">Someone who is not Knos put their own test USDC in, and was not the one paid. Funders and the people paid are counted separately.</p>
    <div class="stats">${stat(o.completed, "tasks paid")}${stat(o.funded, "tasks funded")}${stat(o.funders, "funders")}${stat(o.payees, "people paid")}
      ${stat(o.repositories, "repositories")}${stat(o.repeat_funders, "funders who funded again")}${stat(money(o.paid_amount), "test USDC paid out")}${stat(money(o.fees), "test USDC in fees")}</div>
    <h3>Everything counted, kept apart</h3>
    <p class="fine">Knos's own accounts: the funder, the person paid or the wallet is one of Knos's own. Paid to themselves: the funder and the person paid are the same.
      Free faucet money: test USDC the escrow's faucet minted. Each task is in exactly one row, and the rows are never added to outside use.</p>
    <div class="table-wrap"><table id="network-kinds"><tr><th></th><th>Funded</th><th>Paid</th><th>Funders</th><th>People paid</th><th>Test USDC paid out</th></tr>
      ${KINDS.map(([k, name]) => `<tr><th>${esc(name)}</th><td>${side(k).funded}</td><td>${side(k).completed}</td><td>${side(k).funders}</td><td>${side(k).payees}</td><td>${money(side(k).paid_amount)}</td></tr>`).join("")}</table></div>
    <h3>The funnel</h3>
    <ol id="network-funnel">${funnel("Repositories with the workflow", f.installed, f.installed_note)}
      ${f.funded_of_installed === undefined ? "" : funnel("Of those, repositories that funded a task", f.funded_of_installed)}
      ${funnel("Repositories that funded a task, not Knos's own", f.funded)}${funnel("Outside tasks completed", f.completed)}${funnel("Funders who funded again after a payment", f.funded_again)}</ol>
    <h3>How long it took</h3>
    <div class="table-wrap"><table id="network-latency"><tr><th></th><th>Count</th><th>Median</th><th>90th percentile</th><th>Slowest</th></tr>
      ${spread("Comment to funded", l.comment_to_funded)}${spread("Merge to paid", l.merge_to_paid)}${spread("Funded to paid", l.funded_to_paid)}
      ${l.relay ? `${spread("The relay's part, funding", l.relay.fund)}${spread("The relay's part, paying", l.relay.pay)}` : ""}</table></div>
    <p class="fine">${esc(l.note || "")} The first two start at the comment or the merge as GitHub recorded it, and end at the block time of the transaction on Solana.
      Funded to paid is what the work and the merge took. The relay's part starts at the comment that carried the signed statement.</p>
    <h3>Both deployments</h3>
    <div class="stats">${stat(`${by.second?.completed ?? 0} of ${by.second?.funded ?? 0}`, "second deployment: paid of funded")}${stat(`${by.first?.completed ?? 0} of ${by.first?.funded ?? 0}`, "first deployment: paid of funded")}
      ${stat(`${live.second?.open ?? 0}`, `open now (${money(live.second?.open_amount ?? 0)} test USDC)`)}${stat(`${live.second?.held ?? 0}`, `held for people with no wallet (${money(live.second?.held_amount ?? 0)})`)}
      ${stat(t.refunded, "refunded unpaid")}${stat(t.bound, "wallets bound")}${stat(t.balances, "Balances opened from a wallet")}${stat(t.withdrawn, "withdrawals")}</div>
    ${recent ? `<h3>Latest payments</h3><div class="table-wrap"><table id="network-recent"><tr><th>Kind</th><th>Test USDC</th><th>Task</th><th>Paid to</th><th>Funded to paid</th><th>Deployment</th></tr>${recent}</table></div>` : ""}`;
}

async function programRows(names) {
  const rows = [];
  for (const [name, address] of names) {
    const auth = knos.upgradeAuthority(await knos.account(RPC, await knos.programData(address)));
    rows.push({ name, address, auth });
  }
  return rows;
}

const member = (m) => `${m.threshold} of ${m.members.length} members must approve`;

async function programsHtml() {
  const all = await ids(), rows = await programRows([["knos-oidc", all.knos_oidc], ["knos-pay", all.knos_pay]]);
  const [up, guard] = await Promise.all([knos.account(RPC, all.upgrade_multisig).then(knos.readMultisig), knos.account(RPC, all.guardian_multisig).then(knos.readMultisig)]);
  const vault = await knos.squadsVault(all.upgrade_multisig);
  const verdict = (r) => (r.auth === undefined ? `<span class="status" data-state="missing">not on devnet yet</span>`
    : r.auth === null ? `<strong class="status" data-state="no-authority">no upgrade authority is set on chain: nothing can upgrade this program, which is not the plan stated above</strong>`
    : r.auth === all.upgrade_authority && r.auth === vault ? `<strong class="status ok" data-state="multisig">upgradeable only by the upgrade multisig's vault ${esc(short(r.auth))}</strong>`
    : `<strong class="status bad" data-state="other">upgradeable by ${esc(r.auth)}, which is not the upgrade multisig of this deployment</strong>`);
  const hours = (m) => (m.timeLock % 3600 === 0 ? `${m.timeLock / 3600} hour${m.timeLock === 3600 ? "" : "s"}` : `${m.timeLock} seconds`);
  return `<h3>Who can change the second deployment, read from Solana now</h3>
    <p class="fine">The plan: upgradeable only through a multisig with a public 48-hour delay, until an outside review.
      What the chain says now:</p>
    <dl class="facts" id="programs-now">${rows.map((r) => `<dt>${esc(r.name)}</dt><dd>${link("address", r.address)}<br>${verdict(r)}</dd>`).join("")}</dl>
    <dl class="facts" id="multisigs-now">
      <dt>Upgrade multisig</dt><dd>${link("address", all.upgrade_multisig)}<br>${up ? `${esc(member(up))}, and an approved upgrade waits <strong>${esc(hours(up))}</strong> before it can run${up.timeLock === 172800 ? "" : ` <strong class="status bad">(not the 48 hours stated above)</strong>`}.`
        : `<span class="status">not on devnet yet</span>`}</dd>
      <dt>Guardian multisig</dt><dd>${link("address", all.guardian_multisig)}<br>${guard ? `${esc(member(guard))}; no delay${guard.timeLock ? ` (it reads ${esc(hours(guard))})` : ""}. The guardian can approve or revoke a signing key and pause new funding for at most ${knos.v2.PAUSE_MAX / 86400} days.`
        : `<span class="status">not on devnet yet</span>`}</dd>
    </dl>`;
}

async function firstLive() {
  const spans = [...document.querySelectorAll("#first-deployment .mono")];
  const rows = await programRows(spans.map((el, i) => [i ? "knos-pay" : "knos-oidc", el.textContent.trim()]));
  return `<dl class="facts" id="first-now">${rows.map((r) => `<dt>${esc(r.name)}</dt><dd>${r.auth === undefined ? `<span class="status">not found on devnet</span>`
    : r.auth === null ? `<strong class="status ok" data-state="immutable">no upgrade authority is set: the program can no longer be upgraded</strong>`
    : `<strong class="status bad" data-state="other">upgradeable by ${esc(r.auth)}</strong>`}</dd>`).join("")}</dl>`;
}

const KEY_ISSUERS = { 0: "GitHub", 1: "GitLab" };
async function keysHtml() {
  const all = await ids();
  const [now, small, large, pd] = await Promise.all([knos.chainTime(RPC),
    knos.programAccounts(RPC, all.knos_oidc, knos.v2.K_HDR + 512, 2, Uint8Array.of(64)), knos.programAccounts(RPC, all.knos_oidc, knos.v2.K_HDR + 1024, 2, Uint8Array.of(128)),
    knos.account(RPC, await knos.programData(all.knos_oidc))]);
  const found = [...small, ...large].map((f) => ({ ...f, key: knos.v2.readKey(f.data) })).filter((f) => f.key);
  const keys = await Promise.all(found.map(async (f) => ({ ...f.key, address: f.address, hash: (await knos.v2.keyAccountHash(f.data)).slice(0, 12) })));
  keys.sort((a, b) => a.issuer - b.issuer || a.expiresAt - b.expiresAt);
  const label = (k) => (k.state !== 1 ? "registered, not ready" : k.revoked ? "revoked for good" : !(k.genesis || k.approved) ? "waiting for the guardian's approval"
    : now < k.activeAt ? `usable from ${when(k.activeAt)}` : now >= k.expiresAt ? `expired ${when(k.expiresAt)}` : `usable until ${when(k.expiresAt)}`);
  const rows = keys.map((k) => `<tr><td>${esc(KEY_ISSUERS[k.issuer] || `issuer ${k.issuer}`)}</td><td>${k.bits} bits</td><td class="mono">${esc(k.hash)}</td><td>${k.genesis ? "built in" : "attested"}</td>
    <td data-key="${esc(k.hash)}">${esc(label(k))}</td><td>${esc(when(k.expiresAt))}</td></tr>`).join("");
  return `<h3>The issuers' signing keys on Solana</h3>
    <p class="fine">A token verifies only against a key listed here as usable, and only until its expiry: a key that nobody attests again stops working then.
      Read from the second deployment's knos-oidc at ${esc(when(now))}.</p>
    ${rows ? `<div class="table-wrap"><table id="keys-table"><tr><th>Issuer</th><th>Size</th><th>Key (start of its hash)</th><th>How it got in</th><th>Now</th><th>Expires</th></tr>${rows}</table></div>`
      : `<p class="status" id="keys-none">${pd ? "No signing key is on chain yet." : "The second deployment's knos-oidc is not on devnet yet, so it holds no keys."}</p>`}`;
}

let networkLoaded = false;
async function loadNetwork() {
  if (networkLoaded) return;
  networkLoaded = true;
  // what Solana says is shown as it is read; when it cannot be read, that is said, never a guess ("not deployed")
  const fill = (id, make) => make().then((h) => $(id).insertAdjacentHTML("beforeend", h)).catch((e) => {
    $(id).insertAdjacentHTML("beforeend", `<p class="status bad">Devnet did not answer (${esc(e.message)}). Reload to try again.</p>`);
  });
  fill("network-programs", programsHtml);
  fill("network-keys", keysHtml);
  fill("first-deployment", firstLive);
  const s = await stats(), box = $("network-stats");
  if (!s || !s.outside || !s.apart) {
    box.innerHTML = `<p class="status">${esc(s?.error || "The numbers are built with the site; none here yet.")}</p>`;
    return;
  }
  box.innerHTML = numbersHtml(s);
  $("network-note").textContent = `Counted ${s.updated} by scripts/network_stats.py from the transaction history of both escrow programs.${s.error ? ` Not everything could be read: ${s.error}.` : ""}`;
}


// ---- an upgrade of a program that is waiting: the upgrade multisig's proposals, read from devnet on every load ---------------------------
const SECURITY = "https://github.com/drexthealpha/Knos/blob/main/docs/SECURITY.md#7-the-upgrade-authority";
const upgradesP = (async () => {
  try {
    const { ms, upgrades } = await pendingUpgrades(knos, RPC, await ids());
    if (!upgrades.length) return { upgrades: [], ms, now: null };
    return { upgrades, ms, now: await knos.chainTime(RPC).catch(() => null) };
  } catch { return { upgrades: [], ms: null, now: null, failed: true }; }          // not readable just now: no banner, and nothing guessed
})();
upgradesP.then(({ upgrades, ms, now, failed }) => {
  // what the chain says takes the place of the first screen's line from upgrades.json (web/front.js); a chain that did not
  // answer leaves that line as it is: opened, it says when the file was written
  if (failed) return;
  document.documentElement.dataset.upgrades = "chain";
  if ($("hero-upgrades")) $("hero-upgrades").hidden = true;
  if (!upgrades.length) return;
  const each = upgrades.map((p) => { const w = upgradeWords(p, ms.timeLock, now);
    return `<p class="upgrade" data-program="${esc(p.name)}" data-status="${esc(p.status)}" data-index="${p.index}"><strong>${esc(w.what)}</strong>
      <a class="mono" href="${esc(EXPLORER("address", p.buffer))}" target="_blank" rel="noopener">${esc(short(p.buffer))}</a>. ${esc(w.state)}</p>`; }).join("");
  // more than two at once (a release that upgrades every program): one line that says how many, which and from when, and each one under it
  const approved = upgrades.filter((p) => p.status === "Approved"), first = approved.length ? Math.min(...approved.map((p) => p.executesAt)) : null;
  const names = [...upgrades].reverse().map((p) => p.name).join(", ");
  const state = approved.length === upgrades.length ? `The multisig has approved all of them; the first can be run from ${when(first)}${now !== null && now < first ? `, in ${inWords(first, now)}` : ""}.`
    : `${approved.length} of them ${approved.length === 1 ? "is" : "are"} approved${first !== null ? `, the first to run from ${when(first)}` : ""}; the others are short of votes or not yet put to the vote.`;
  $("upgrade-banner").innerHTML = (upgrades.length > 2 ? `<details id="upgrade-all"><summary><strong>${upgrades.length} upgrades of Knos's programs are pending</strong> (${esc(names)}). ${esc(state)}</summary>${each}</details>` : each)
    + `<details class="k-more" id="upgrade-exit"><summary>Exits: why an upgrade waits, and how to leave</summary><p class="fine">A program's upgrade can change what it does, and the delay is there so that it can be seen coming: the proposal and the new bytes are on chain for anyone to read.
      <code>knos exit --before-upgrade</code> lists what you hold and how to take it out before then.
      What it protects and what it does not: <a id="upgrade-security" href="${SECURITY}" target="_blank" rel="noopener">docs/SECURITY.md</a>, section 7.</p></details>` + feedLine;
  $("upgrade-banner").hidden = false;
});

// ---- each page's own module, asked for when the page is first opened -----------------------------------------------------
const once = (make) => { let p; return () => (p ||= make()); };
let showVersion = () => {}, showRecords = () => {}, showStatement = () => {}, anyShow = () => {};
const PARTS = {
  pricing: once(async () => { showVersion = (await import("./pricing.js")).initPricing({ $, esc, knos, RPC, ids }); }),
  claim: once(async () => { (await import("./claim.js")).initClaim({ $, esc, knos, RPC, EXPLORER, units, say, money, devnet, client }); }),
  records: once(async () => {
    const [r, s] = await Promise.all([import("./records.js"), import("./statements.js")]);
    showRecords = r.initRecords({ $, esc, rep: async (id) => knos.v2.readRep(await knos.account(RPC, await (await client()).rep(id))) });
    showStatement = s.initStatements({ $, esc, EXPLORER });
  }),
  fund: once(async () => {
    const [t, a] = await Promise.all([import("./task.js"), import("./anyissue.js")]);
    t.initTask({ $, esc, knos, gh });
    // the fee fold takes the version the Fund card asked devnet for (one question, not two); with no answer, upgrades.json
    let heard; const version = new Promise((r) => { heard = r; });
    anyShow = a.initAnyIssue({ $, esc, knos, RPC, EXPLORER, gh, ids, client, devnet, wallet, sendable, whyFailed, sign: signAndConfirm, say, upgrades: upgradesP, onVersion: heard });
    const live = version.then(async (v) => (v === null ? (await import("./fee_live.js")).liveFee({ knos }) : { version: v, source: "chain", c: (await import("./price.js")).priceConstants(knos, v) }));
    import("./fund_fee.js").then((f) => f.renderFundFee($("fund-fee"), { knos, RPC, ids, live })).catch(() => {});
  }),
  // Buy: web/buyer.js, which a build may not have; then the page stays empty and web/front.js does not offer it.
  buy: once(async () => { await (await import("./buyer.js")).renderBuyer?.($("buy"), { $, esc, knos, RPC, EXPLORER, ids, client, gh, devnet }); }),
  // Status, Index, Pilot, Reproduce (web/mounts.js)
  mounts: once(async () => { (await import("./mounts.js")).fillMounts({ $, esc, knos, RPC, EXPLORER, gh }); }),
};
const PART_OF = { status: "mounts", index: "mounts", pilot: "mounts", reproduce: "mounts" };
// what the first screen needs of this file when a transaction is pasted there (web/first.js)
export const ctx = { knos, RPC, ids, gh, devnet };
