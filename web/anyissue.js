// Fund any issue: put test USDC in escrow, from a wallet, for an issue of any public repository. This page reads the issue from
// GitHub, fixes the terms (shown whole before anything is asked of the wallet), and builds the one transaction that funds the order
// with sdk/settle (settle.js here). It sends nothing itself: the wallet shows the transaction and signs it, or does not.
//
// What it hands the client is the arguments of `fundOrderWalletIx` (src/knos/settle/v2/pay.py fund_order_wallet_ix: the same names in
// camelCase). That call is made in ONE place, `orderFunding`, which looks for it where sdk/settle puts it (a method of the client of
// `knos.v2.client(ids)`) and in the two other places a library could export it, and says "not there" when it finds none: the page
// then shows what the order would be and says why nothing can be sent. The terms are worked out here, in the form
// src/knos/terms.py `canonical` writes (tests/test_fund_any_issue.py records Python's answers, and tests/web/site.mjs holds this file
// to them), with a check named in the box counting from any source, as `describe` words it.
import { priceConstants, quote, unitsOf, show, plain, feeRate, feeNote } from "./price.js";
import { programVersion } from "./version.js";
import { pinsOf, WORKFLOW } from "./front.js";
import { runDay } from "./upgrade.js";
import { cache as kept, ghKey, asOf } from "./cache.js";

export const MAX_TERMS = 600;               // knos-pay's MAX_TERMS
export const DENY = [".github/**", ".knos/**"];
export const DAYS = 14, MAX_DAYS = 90;      // until an unpaid order can go back; knos-pay's MAX_WORK is 90 days
export const SEQ_TRIES = 8;                 // how many orders of one wallet for one issue are looked for before it is said there are too many
export const F_NEUTRAL = 4;                 // programs-v2/knos_pay/src/order.rs: opts flags u8 @0 (PRIVATE 2, NEUTRAL 4, STANDING 8)
const enc = new TextEncoder();

export class Refused extends Error {}
const refuse = (words) => { throw new Refused(words); };

// ---- the words a funder types, as src/knos/commands.py and src/knos/terms.py read them --------------------------------------------
// Python's str.strip() takes off these; JavaScript's trim() takes off a slightly different set
const SPACE = "\\t-\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const strip = (s) => s.replace(new RegExp(`^[${SPACE}]+|[${SPACE}]+$`, "g"), "");
const points = (s) => [...s];
// strings in the order Python sorts them: by code point (JavaScript's own is by UTF-16 unit, which differs above the BMP)
const byCode = (a, b) => {
  const x = points(a), y = points(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) { const d = x[i].codePointAt(0) - y[i].codePointAt(0); if (d) return d; }
  return x.length - y.length;
};
// JSON as Python's json.dumps writes it with ensure_ascii: everything past ASCII as \uXXXX, in lower case, one per UTF-16 unit
const ascii = (s) => JSON.stringify(s).replace(/[\u007f-￿]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0")}`);

// "test, lint": the names in a list, commas inside ( [ { belonging to the name and a name in " or ` taken whole (commands._list); no repeat
export function listOf(text) {
  const items = [];
  let cur = "", depth = 0, quote = "";
  for (const ch of points(String(text))) {
    if (quote) { if (ch === quote) quote = ""; else cur += ch; }
    else if ((ch === '"' || ch === "`") && !strip(cur)) quote = ch;
    else if (ch === "," && !depth) { items.push(cur); cur = ""; }
    else { depth += "([{".includes(ch) ? 1 : 0; if (")]}".includes(ch) && depth > 0) depth--; cur += ch; }
  }
  if (quote || depth) refuse("A name's quote or bracket is not closed.");
  items.push(cur);
  return [...new Set(items.map(strip).filter(Boolean))];
}

const oneLine = (v) => { const n = points(v).length; return n >= 1 && n <= 200 && !/[\x00-\x1f\x7f]/.test(v); };
// the names Knos's own jobs have (terms._KNOS_JOBS): a bounty cannot require them
const KNOS_JOBS = /^(?:prove|fund)(?:-relay|-refused)? \/ |^knos| \/ claims$/;

export function checkName(name) {
  if (!oneLine(name)) refuse("A check's name is 1 to 200 characters on one line.");
  if (KNOS_JOBS.test(name)) refuse(`"${name}" is Knos's own job, and a bounty cannot require it. Name your repository's checks, or leave the box empty.`);
  return name;
}

// a glob from the repository's root, as a workflow's `paths:` filter writes it: a leading ./ or / is dropped, as the comment command does
export function glob(value) {
  const g = String(value).replace(/^(?:\.\/|\/)+/, "");
  if (!oneLine(g) || g !== strip(g) || g.startsWith("/") || g.startsWith("!") || g.includes("\\") || g.split("/").includes("..")) {
    refuse("A path is a glob from the repository's root, like src/** or docs/*.md.");
  }
  return g;
}

// The terms of the order, in the canonical form src/knos/terms.py writes: one JSON object, its keys sorted, no spaces, ASCII, every list
// sorted by code point. `checks` and `paths`: the names and the globs. Merge mode, nobody may reserve it (a `/knos take` is a comment to a
// workflow the repository may not have), and the pull request may not change the files that judge it. A named check counts from any source.
// Returns { terms, text, bytes }.
export function termsOf({ checks = [], paths = [] } = {}) {
  const names = [...new Set(checks.map(checkName))].sort(byCode), globs = [...new Set(paths.map(glob))].sort(byCode);
  const text = `{"accept":"","checks":[${names.map((n) => `{"app":-1,"name":${ascii(n)}}`).join(",")}],"deny":[${DENY.map(ascii).join(",")}],"mode":"merge","paths":[${globs.map(ascii).join(",")}],"reserve":0,"v":1}`;
  const bytes = enc.encode(text);
  if (bytes.length > MAX_TERMS) refuse(`These terms take ${bytes.length} bytes, and an order's terms hold at most ${MAX_TERMS}. Name fewer checks, or use fewer or shorter paths.`);
  return { terms: { accept: "", checks: names.map((name) => ({ app: -1, name })), deny: [...DENY], mode: "merge", paths: globs, reserve: 0, v: 1 }, text, bytes };
}

// The terms in plain sentences: terms.describe(terms, "funder") of src/knos/terms.py, except that an order with no check is not "your
// merge" (the funder is not the one who merges).
export function describeTerms(terms) {
  const out = [], kind = { 0: " (a commit status)", [-1]: " (any source)" };
  const how = terms.mode === "tests" ? "when its acceptance checks (.knos/acceptance/ for this issue) pass on a pull request" : "when a maintainer merges a pull request that closes this issue";
  const code = (g) => `\`${g}\``;
  if (terms.checks.length) {
    out.push(`It is paid ${how}, if these checks passed at that pull request's last commit: ${terms.checks.map((c) => `${code(c.name)}${kind[c.app] ?? ""}`).join(", ")} (the checks you named).`);
  } else out.push("No check is required: the maintainer's merge alone is the acceptance.");
  const may = terms.deny.length ? `The pull request may not change ${terms.deny.map(code).join(" or ")}` : "";
  const only = terms.paths.length ? `may only change files matching ${terms.paths.map(code).join(" or ")}` : "";
  if (may || only) out.push(`${may && only ? `${may}, and ${only}` : may || `The pull request ${only}`}.`);
  out.push(terms.reserve ? `\`/knos take\` reserves the issue for ${terms.reserve} day${terms.reserve === 1 ? "" : "s"}.` : "Nobody can reserve it: the first accepted pull request is paid.");
  return out;
}

// ---- the issue ----------------------------------------------------------------------------------------------------------------------
// "https://github.com/owner/repo/issues/7" (a query or a #fragment after it is fine), "owner/repo/issues/7" or "owner/repo#7":
// { owner, repo, number, kind: "issues" | "pull" }; null for anything else
export function parseIssueUrl(text) {
  const t = String(text || "").trim(), owner = "([A-Za-z0-9-]{1,39})", repo = "([\\w.-]+)";
  const m = new RegExp(`^(?:https?://)?(?:www\\.)?github\\.com/${owner}/${repo}/(issues|pull)/(\\d{1,9})(?:[/?#].*)?$`, "i").exec(t)
    || new RegExp(`^${owner}/${repo}/(issues|pull)/(\\d{1,9})/?$`, "i").exec(t) || new RegExp(`^${owner}/${repo}()#(\\d{1,9})$`).exec(t);
  if (!m || m[2] === "." || m[2] === ".." || Number(m[4]) < 1) return null;
  return { owner: m[1], repo: m[2], number: Number(m[4]), kind: (m[3] || "issues").toLowerCase() };
}

// Every box of the form, checked in order; the first one wrong is said in a sentence that tells what to type. `c`: price.js constants.
// Returns { ref, amount, days, workS, ...termsOf }.
export function readBoxes({ issue, amount, days, checks, paths }, c = priceConstants()) {
  const ref = parseIssueUrl(issue);
  if (!ref) refuse("Write the issue's address on GitHub: https://github.com/owner/repo/issues/7, or owner/repo#7.");
  if (ref.kind === "pull") refuse("That is a pull request. Fund the issue it closes: its address ends in /issues/ and a number.");
  const units = unitsOf(amount);
  if (units === null) refuse("Write the amount as a number like 20 or 7.5, with at most six decimals.");
  if (units < c.minAmount) refuse(`An order takes at least ${show(c.minAmount)} test USDC.`);
  if (units > c.maxAmount) refuse(`An order takes at most ${show(c.maxAmount)} test USDC on devnet.`);
  const d = /^\d{1,3}$/.test(String(days).trim()) ? Number(days) : 0;
  if (d < 1 || d > MAX_DAYS) refuse(`The days are a whole number from 1 to ${MAX_DAYS}.`);
  return { ref, amount: units, days: d, workS: d * 86_400, ...termsOf({ checks: listOf(checks), paths: listOf(paths) }) };
}

// ---- the order's address and the call that funds it ---------------------------------------------------------------------------------
const le = (n, size) => { const out = new Uint8Array(size); new DataView(out.buffer)[size === 8 ? "setBigUint64" : "setUint32"](0, size === 8 ? BigInt(n) : Number(n), true); return out; };
const cat = (...parts) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };

// ["ord", scope, funder, seq u32 LE] under the program, scope = sha256("knos3:scope" || repo id u64 LE || issue u64 LE) (pay.py order_pda, scope_of)
export async function orderAddress(knos, program, repoId, issue, funder, seq = 0) {
  const scope = await knos.sha256(cat(enc.encode("knos3:scope"), le(repoId, 8), le(issue, 8)));
  return (await knos.findProgramAddress([enc.encode("ord"), scope, knos.unb58(funder), le(seq, 4)], program))[0];
}

// The options a funder fixes beside the amount: 48 bytes, flags u8 first. NEUTRAL: an order for an issue of a repository that has no Knos file
// is not paid by that repository's own workflow (order.rs, opts).
export const optionsOf = () => { const o = new Uint8Array(48); o[0] = F_NEUTRAL; return o; };

// THE ADAPTER. The function that builds the instruction funding an order, or null when this build of settle.js has none: the method
// `fundOrderWalletIx` of the client (`knos.v2.client(ids)`, where sdk/settle puts it), else the same name on `knos.v2` or on the module,
// each taking the one object of arguments. Nothing else in this site names it.
export function orderFunding(knos, k) {
  for (const holder of [k, knos?.v2, knos]) if (typeof holder?.fundOrderWalletIx === "function") return (args) => holder.fundOrderWalletIx(args);
  return null;
}

// The reusable workflows the order will name, read from the file the Protect view hands out (never typed here): { repo, sha }, or null
// until every workflow it calls is named by one full commit
export function workflowPin(file = WORKFLOW) {
  const pins = pinsOf(file);
  if (!pins.length || pins.some((p) => p.repo !== pins[0].repo || p.ref !== pins[0].ref || !/^[0-9a-f]{40}$/.test(p.ref))) return null;
  return { repo: pins[0].repo, sha: pins[0].ref };
}

// ---- whether it can be sent ---------------------------------------------------------------------------------------------------------
// What the page says about this, and whether the button may work. `version`: programVersion's answer for knos_pay (1: 2.1 is live, 0: 2.0,
// null: not told); `funding`: whether the client has the call; `up`: { upgrades, failed } as app.js reads them from the upgrade multisig.
export function availability({ version, funding, up = { upgrades: [] } }) {
  if (version === 0) {
    const day = runDay(up.upgrades, "knos_pay");
    const words = day ? `Available when the upgrade of ${day} executes. The upgrade multisig has approved it, and it can be run from that day.`
      : up.upgrades.some((p) => p.name === "knos_pay") ? "Available when the upgrade of knos_pay executes. One is pending and not yet approved, so it has no date yet."
        : up.failed ? "Available when the upgrade of knos_pay executes. This page could not read the upgrade multisig just now, so it has no date."
          : "Available when the upgrade of knos_pay executes. None is proposed that this page can see, so it has no date.";
    return { ok: false, kind: "upgrade", words };
  }
  if (version === null || version === undefined) return { ok: false, kind: "unread", words: "Devnet did not say which knos_pay is live. Nothing can be sent. Reload to try again." };
  if (!funding) return { ok: false, kind: "client", words: "This copy of the page's client library (settle.js) has no call that builds the funding of an order yet, so nothing can be sent from here." };
  return { ok: true, kind: "live", words: version === 1 ? "The program on devnet is 2.1: it takes this." : `knos_pay on devnet answers version ${version}: it takes this.` };
}

// ---- the card -----------------------------------------------------------------------------------------------------------------------
const ROLES = ["the funder (you, signing)", "the order", "the order's token account", "your token account", "the mint", "the escrow's authority", "the token program", "the system program", "the pause switch"];

export function initAnyIssue(ctx) {
  const { $, esc, knos, RPC, EXPLORER, gh, ids, client, devnet, wallet, sendable, whyFailed, sign, say, upgrades } = ctx;
  let c = priceConstants();              // the fee follows the build that is live: set again below from the program's own answer
  const state = { avail: null, preview: null, pending: null };
  const link = (kind, id, text = id) => `<a class="mono" href="${esc(EXPLORER(kind, id))}" target="_blank" rel="noopener">${esc(text)}</a>`;

  function refresh() {
    $("any-next").hidden = !state.preview;
    const why = !state.avail ? "Asking devnet which version of knos_pay is live…" : !state.avail.ok ? state.avail.words : !wallet.address ? "Connect a wallet first." : "";
    $("any-plan").disabled = !!why;
    $("any-why").textContent = why;
  }

  let asked = null;
  async function ask() {
    const out = $("any-available");
    try {
      const [i, up, k] = await Promise.all([ids(), upgrades, client().catch(() => null)]);
      const version = await programVersion(knos, RPC, i.knos_pay).catch(() => null);
      c = priceConstants(knos, version);   // the 0.3.14 fee until knos_pay 2.2 answers, the 0.3.18 fee after; nobody answered: this tree's own, and the page says both
      state.avail = availability({ version, funding: !!k && !!orderFunding(knos, k), up });
    } catch { state.avail = availability({ version: null, funding: false }); }
    out.className = `status ${state.avail.ok ? "ok" : ""}`;
    out.textContent = state.avail.words;
    refresh();
    auto();
  }

  let reads = 0, checks = 0, checked = null;       // which read of GitHub, and which check on devnet, is the one whose answer is still wanted; and the terms and wallet the check last ran for by itself
  function clear() {
    reads++; checks++; checked = null;
    state.preview = state.pending = null;
    $("any-result").innerHTML = ""; $("any-tx").innerHTML = ""; $("any-status").innerHTML = "";
    refresh();
  }

  $("any-form").addEventListener("input", clear);
  $("any-form").onsubmit = async (ev) => {
    ev.preventDefault();
    clear();
    const out = $("any-result"), field = (id) => $(id).value;
    let read;
    try { read = readBoxes({ issue: field("any-issue"), amount: field("any-amount"), days: field("any-days"), checks: field("any-checks"), paths: field("any-paths") }, c); }
    catch (e) { return say(out, esc(e.message), "bad"); }
    say(out, "Reading GitHub…");
    const asked = ++reads;
    // Twice (cache.js): an issue this tab has read before is shown at once, as it was then and saying so, while GitHub is read
    // again. It can be funded only from what GitHub says now: the kept one never fills `state.preview`.
    try {
      await kept.twice(async (seen, pass) => {
        if (asked !== reads) return;      // a box changed, or it was pressed again: this answer is for a form that is gone
        const { owner, repo: name, number } = read.ref;
        const [repo, issue] = await Promise.all([`/repos/${owner}/${name}`, `/repos/${owner}/${name}/issues/${number}`].map((path) => seen(ghKey(path), () => gh(path))));
        const full = /^[\w.-]+\/[\w.-]+$/.test(repo.full_name || "") ? repo.full_name : `${owner}/${name}`;
        if (!Number.isSafeInteger(repo.id) || repo.id < 1) throw new Error("GitHub did not give this repository an id.");
        if (issue.pull_request) throw new Error("That is a pull request. Fund the issue it closes.");
        if (repo.archived) throw new Error(`${full} is archived: no pull request can be merged in it.`);
        if (issue.state !== "open") throw new Error(`${full}#${number} is closed. Fund an open issue.`);
        const pin = workflowPin();
        if (!pin) throw new Error("This copy of the page names no published workflow commit yet, so an order cannot be made from it.");
        const hash = knos.hex(await knos.sha256(read.bytes)), q = quote(read.amount, c), title = String(issue.title ?? "").slice(0, 150);
        const preview = { ...read, repoId: repo.id, full, pin, hash, q };
        if (pass.same()) { $("any-asof")?.remove(); state.preview = preview; return; }     // GitHub says now what was shown: only now can it be funded
        state.preview = pass.kept ? null : preview;
        out.innerHTML = `${pass.kept ? `<p class="fine" id="any-asof">Shown ${esc(asOf(pass.at(), kept.now()))}. Reading GitHub again before anything can be funded…</p>` : ""}<h4>What you would fund</h4>
          <dl class="facts" id="any-facts">
            <dt>Issue</dt><dd><a id="any-issue-link" href="https://github.com/${esc(full)}/issues/${number}" target="_blank" rel="noopener">${esc(full)}#${number}</a>: ${esc(title)}</dd>
            <dt>Repository</dt><dd>GitHub repository id ${repo.id}. The order is for this repository's issue number ${number}.</dd>
            <dt>You pay</dt><dd><strong id="any-pay">${show(q.funderPays)}</strong> test USDC: ${show(q.amount)} for the person who does the work, and ${show(q.fee)} fee on top (${esc(feeRate(c).replace("% to ", "% from there to ").replace(", at least", "; at least"))}, no maximum).</dd>
            <dt>Which fee</dt><dd id="any-fee-note" data-fee="${esc(c.fee.release)}">${esc(feeNote(q.amount, c))}</dd>
            <dt>Time to do it</dt><dd id="any-time">${read.days} day${read.days === 1 ? "" : "s"}. Unpaid by then, the order can be sent back to your wallet.</dd>
            <dt>Paid when</dt><dd><ul id="any-sentences">${describeTerms(read.terms).map((s) => `<li>${esc(s).replace(/`([^`]*)`/g, "<code>$1</code>")}</li>`).join("")}</ul></dd>
            <dt>Paid only by</dt><dd id="any-pin">a signed run of the workflows of <a href="https://github.com/${esc(pin.repo)}" target="_blank" rel="noopener">${esc(pin.repo)}</a> at commit
              <a href="https://github.com/${esc(pin.repo)}/commit/${pin.sha}" target="_blank" rel="noopener"><code>${pin.sha.slice(0, 7)}</code></a>. The order records that commit, and the escrow takes a pay token from no other.</dd>
            <dt>Terms</dt><dd><pre id="any-terms">${esc(read.text)}</pre>sha256 <span class="mono" id="any-hash">${hash}</span></dd>
          </dl>
          <p class="fine">The funding transaction carries these bytes and the order stores their hash, so the terms cannot change afterwards. No file is needed in the repository: it is funded
            as a neutral order, which the repository's own workflow does not have to judge. Nothing is sent yet. The next step asks devnet whether it would accept the transaction, and shows
            it to you before your wallet is asked.</p>`;
      });
    } catch (e) { if (asked === reads) { state.preview = null; say(out, esc(e.message), "bad"); } }
    refresh();
    if (asked === reads) auto();
  };

  // Build the transaction, check it against devnet and show it. Nothing is signed until "Sign" is pressed.
  async function plan() {
    const st = $("any-status"), tx = $("any-tx"), p = state.preview, { address } = wallet, mine = ++checks, late = () => mine !== checks;
    tx.innerHTML = "";
    state.pending = null;
    if (!p || !address || !state.avail?.ok) return;
    try {
      say(st, "Checking…");
      await devnet();
      const [i, k] = await Promise.all([ids(), client()]), funding = orderFunding(knos, k);
      if (!funding) throw new Error(availability({ version: 1, funding: false }).words);
      const mint = knos.USDC_DEVNET, mine = await knos.ata(address, mint);
      const [raw, orders] = await Promise.all([knos.account(RPC, mine), Promise.all(Array.from({ length: SEQ_TRIES }, (_, s) => orderAddress(knos, i.knos_pay, p.repoId, p.ref.number, address, s)))]);
      const taken = await knos.accounts(RPC, orders), seq = taken.findIndex((a) => !a);
      if (seq < 0) throw new Error(`This wallet has already funded this issue ${SEQ_TRIES} times. Use another wallet, or wait until one of those orders is paid or sent back.`);
      const have = knos.readTokenAccount(raw)?.amount ?? null;
      if (have === null || have < p.q.funderPays) {
        throw new Error(`This wallet holds ${show(have || 0)} test USDC, and ${show(p.q.funderPays)} is needed: the amount and the fee. Circle's devnet faucet gives test USDC.`);
      }
      const ix = await funding({ funder: address, funderToken: mine, mint, repoId: p.repoId, issue: p.ref.number, amount: p.amount, wfRepo: p.pin.repo, wfSha: p.pin.sha,
        terms: p.bytes, mode: knos.MERGE ?? 0, workS: p.workS, seq, options: optionsOf() });
      const sim = await knos.rpc(RPC, "simulateTransaction", [btoa(String.fromCharCode(...await sendable([ix]))), { encoding: "base64", sigVerify: false, replaceRecentBlockhash: true, commitment: "confirmed" }]);
      if (late()) return;       // the form, the wallet or a newer check has taken its place
      if (sim.value.err) throw new Error(whyFailed(sim.value.err, sim.value.logs));
      state.pending = { ixs: [ix], address, order: orders[seq] };
      tx.innerHTML = `<h4>This is what you would sign</h4><p class="fine">On Solana devnet, from <span class="mono">${esc(address)}</span>. Devnet checked it just now and accepts it.</p>
        <ol id="any-steps"><li>Fund the order for ${esc(p.full)}#${p.ref.number}: ${show(p.q.amount)} test USDC for the person who does the work and ${show(p.q.fee)} fee, ${show(p.q.funderPays)} in all, from your token account
          into the order's own escrow account${seq ? ` (this wallet has funded this issue ${seq} time${seq === 1 ? "" : "s"} before, so this is order ${seq})` : ""}. Its terms hash is <span class="mono">${p.hash.slice(0, 16)}…</span>.
          <details><summary class="fine">knos_pay: FundOrderWallet</summary><ul class="mono">${ix.accounts.map((a, n) => `<li>${esc(ROLES[n] ?? "account")}: ${esc(a.pubkey)}${a.signer ? " (signs)" : ""}${a.writable ? " (changes)" : ""}</li>`).join("")}</ul></details></li></ol>
        <p class="fine">The order's account will be ${link("address", orders[seq])}.</p><button type="button" id="any-send">Sign in my wallet</button>`;
      $("any-send").onclick = send;
      st.textContent = "";
    } catch (e) { if (!late()) say(st, esc(e.message), "bad"); }
  }
  $("any-plan").onclick = plan;

  // The check asks devnet and signs nothing, so it does not wait to be asked for: once the terms are shown as GitHub has
  // them now, a wallet is connected and the program takes the order, it runs, and what would be signed is on the page.
  // The button stays, to check again. Each set of terms and wallet is checked by itself once.
  function auto() {
    const p = state.preview, { address } = wallet;
    if (!p || !address || !state.avail?.ok || state.pending) return;
    const what = `${address} ${p.repoId} ${p.ref.number} ${p.hash} ${p.amount} ${p.workS}`;
    if (what === checked) return;
    checked = what;
    plan();
  }

  async function send() {
    const st = $("any-status"), todo = state.pending, button = $("any-send");
    if (!todo) return;
    if (todo.address !== wallet.address) return say(st, "The wallet changed since the check. Check it again.", "bad");
    button.disabled = true;
    try {
      const where = await sign(todo.ixs, st);
      if (!where) return;
      state.pending = null;
      $("any-tx").innerHTML = "";
      st.innerHTML = `<p class="status ok" id="any-done">Done. ${where}. The order's account is ${link("address", todo.order)}.</p>`;
    } catch (e) { button.disabled = false; say(st, esc(e.message), "bad"); }
  }

  wallet.listeners.push(() => { refresh(); auto(); });
  refresh();
  return () => (asked ||= ask());
}
