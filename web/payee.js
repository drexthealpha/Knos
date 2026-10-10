// #payee=<login>: the page a held payment's reply links to. It shows what knos_pay holds for that GitHub account, makes
// a passkey (WebAuthn, P-256: no seed phrase, no app) whose knos_passkey address is where the money will go, and gives
// the one next link on GitHub. The page signs and sends nothing; the person presses GitHub's buttons themselves.
//
// Why it is not one click (programs-v2/knos_pay/src/pay.rs `bind`, deployed 2.1 and 2.2 alike): a Bind token counts only
// from the pinned claim workflow, in the person's own repository named knos-claim, in a run they started by hand
// (`workflow_dispatch`, first attempt). A push does not count, not even the first push of a repository made from the
// template: a link can fill GitHub's new-repository form, so a push could carry an address someone else chose. So the
// address reaches GitHub as the run's input, pasted by its owner. Clicks, counted in CLICKS below:
//   before (docs, `knos claim` page): a wallet app and its seed phrase, the template, Actions, the run, the address.
//   after (this page): Make a passkey (the address is copied), Create repository (once), Run workflow, paste, Run.
//   13 steps before, 8 now; 4 once the repository exists (CLICKS.again).
//
// What it reads, and only when opened: api.github.com (the login's numeric id, whether <login>/knos-claim exists) and
// Solana devnet (held jobs and orders by payee id, the Bind account). The passkey's id and public key are kept where
// the Get paid page (claim.js) keeps them, so that page withdraws from the same address; with no storage the page works.
import * as knos from "./settle.js";
import * as passkey from "./passkey.js";

export const RPC = "https://api.devnet.solana.com";
export const GITHUB = "https://api.github.com";
export const TEMPLATE_OWNER = "drexthealpha", TEMPLATE_NAME = "knos-claim";
export const WORKFLOW = "knos-claim.yml";         // src/knos/settle/knos-claim.yml: what the template repository holds
export const STORE = "knos-passkey";              // claim.js and buyer.js keep the same passkey under this key
const LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const JOB_LEN = 320, ORDER_LEN = 512, JOB_PAYEE = 56, ORDER_PAYEE = 152, ORDER_HELD = 3;

// The clicks to a first payout, counted on GitHub's and a wallet app's own screens as of October 2026 (docs/PAYEE.md).
export const CLICKS = {
  before: ["install a wallet app", "create a wallet, write down its seed phrase", "copy its address", "open the template",
    "Use this template", "Create a new repository", "type the name knos-claim", "Create repository", "Actions", "knos claim",
    "Run workflow", "paste the address", "Run workflow"],
  after: ["Make a passkey", "confirm on the device", "Create knos-claim on GitHub", "Create repository", "Run knos claim on GitHub",
    "Run workflow", "paste the address", "Run workflow"],
  // a person whose knos-claim exists already (an earlier bind, or a change of address): only the run is left
  again: ["Run knos claim on GitHub", "Run workflow", "paste the address", "Run workflow"],
};

/** The login (and, when the reply carries it, the numeric id) from what follows "#payee=": "octo" or "octo:583231". */
export function parseArg(arg) {
  const [login, id] = String(arg || "").replace(/^@/, "").split(":");
  if (!LOGIN.test(login || "")) return null;
  return { login, id: /^\d{1,19}$/.test(id || "") ? Number(id) : null };
}

/** GitHub's new-repository form, filled in: the template, the owner, the name the program needs, public. */
export const newRepoLink = (login) => `https://github.com/new?template_owner=${TEMPLATE_OWNER}&template_name=${TEMPLATE_NAME}`
  + `&owner=${encodeURIComponent(login)}&name=knos-claim&visibility=public`;
/** The claim workflow's page in the person's repository: "Run workflow" is there. */
export const runLink = (login) => `https://github.com/${encodeURIComponent(login)}/knos-claim/actions/workflows/${WORKFLOW}`;

const u64 = (v) => { const b = new Uint8Array(8); new DataView(b.buffer).setBigUint64(0, BigInt(v), true); return b; };

/** What knos_pay holds for GitHub account `userId`, in what the payee will receive: [{ address, kind, mint, amount }].
 *  A held job pays its amount less the job fee; a held order pays what it has not paid yet (its fee was taken at funding). */
export async function heldFor(rpc, payProgram, userId) {
  const id = u64(userId);
  const [jobs, orders] = await Promise.all([knos.programAccounts(rpc, payProgram, JOB_LEN, JOB_PAYEE, id),
    knos.programAccounts(rpc, payProgram, ORDER_LEN, ORDER_PAYEE, id)]);
  const out = [];
  for (const { address, data } of jobs) {
    const j = knos.v2.readJob(data);
    if (j && j.state === "held" && j.payeeId === userId) out.push({ address, kind: "job", mint: j.mint, amount: j.amount - knos.v2.feeOf(j.amount) });
  }
  for (const { address, data } of orders) {
    const o = data[1] === ORDER_HELD ? knos.v2.readOrder(data) : null;
    if (o && o.payeeId === userId) out.push({ address, kind: "order", mint: o.mint, amount: Math.max(0, o.amount - o.paid) });
  }
  return out.sort((a, b) => (a.address < b.address ? -1 : 1));
}

/** The address GitHub account `userId` is bound to, or null. */
export async function boundTo(rpc, ids, userId) {
  const at = await knos.v2.client(ids).bind(userId);
  return knos.v2.readBind(await knos.account(rpc, at))?.wallet ?? null;
}

const money = (units) => (units / 1e6).toFixed(2);
const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Draws the page in `el`. ctx: { arg, esc?, rpc?, github?, ids?, rpId? } (the last four: what a test replaces). */
export function renderPayee(el, ctx = {}) {
  const esc = ctx.esc || escHtml, rpc = ctx.rpc || RPC, github = ctx.github || GITHUB;
  const rpId = ctx.rpId || globalThis.location?.hostname;
  const idsP = ctx.ids ? Promise.resolve(ctx.ids) : fetch("program_ids.json").then((r) => { if (!r.ok) throw new Error("program_ids.json is missing"); return r.json(); });
  idsP.catch(() => {});        // not unhandled: web/retry.js shows the retry line, and each step that awaits it says what failed
  let who = parseArg(ctx.arg), me = null, repo = null;
  el.innerHTML = `<div class="payee">
    <h2>Collect your payout</h2>
    <p>Make a passkey. Paste its address into one GitHub run.</p>
    <form id="py-who" class="row"${who ? ' style="display:none"' : ""}><label for="py-login">GitHub login</label>
      <input id="py-login" autocomplete="username" spellcheck="false" required><button class="k-btn" type="submit">Look up</button></form>
    <ol class="k-stage">
      <li class="k-step" data-state="live" id="py-held"><span class="k-kicker">Held</span><p data-py-held tabindex="-1" aria-live="polite">Reading devnet…</p></li>
      <li class="k-step" data-state="idle" id="py-key"><span class="k-kicker">Passkey</span>
        <p><button type="button" class="k-btn" id="py-make">Make a passkey</button></p><p data-py-key></p></li>
      <li class="k-step" data-state="idle" id="py-link"><span class="k-kicker">GitHub</span><p data-py-link>Make a passkey first.</p></li>
      <li class="k-step" data-state="idle" id="py-done"><span class="k-kicker">Result</span>
        <p><button type="button" class="k-btn quiet" id="py-check">Check</button></p><p data-py-done aria-live="polite"></p></li>
    </ol>
    <details class="k-more"><summary>Clicks</summary><table class="k-table" data-py-clicks>
      <thead><tr><th>Before: ${CLICKS.before.length}</th><th>Now: ${CLICKS.after.length}</th></tr></thead><tbody>${[...Array(CLICKS.before.length).keys()].map((i) =>
        `<tr><td>${esc(CLICKS.before[i])}</td><td>${esc(CLICKS.after[i] || "")}</td></tr>`).join("")}</tbody></table></details>
  </div>`;
  const $ = (sel) => el.querySelector(sel), step = (id, state) => { el.querySelector(`#${id}`).dataset.state = state; };

  const remember = () => { try { localStorage.setItem(STORE, JSON.stringify({ credentialId: me.credentialId ? btoa(String.fromCharCode(...me.credentialId)) : null, key: [...me.key].map((b) => b.toString(16).padStart(2, "0")).join("") })); } catch { /* none: same page */ } };
  const recall = () => { try { return JSON.parse(localStorage.getItem(STORE) || "null"); } catch { return null; } };

  async function held() {
    const out = $("[data-py-held]");
    if (!who) { out.textContent = "Enter your GitHub login."; return; }
    out.textContent = "Reading devnet…";
    try {
      if (!who.id) {
        const r = await fetch(`${github}/users/${encodeURIComponent(who.login)}`);
        if (!r.ok) throw new Error(r.status === 404 ? `No GitHub account is called ${who.login}` : `GitHub answered ${r.status}`);
        who.id = (await r.json()).id;
      }
      const ids = await idsP, rows = await heldFor(rpc, ids.knos_pay, who.id), sum = rows.reduce((n, r) => n + r.amount, 0);
      out.innerHTML = rows.length ? `<strong class="k-num" data-py-amount>${esc(money(sum))}</strong> test USDC held for @${esc(who.login)}.`
        : `Nothing held for @${esc(who.login)} now.`;
      step("py-held", "done");
    } catch (e) { out.textContent = `Could not read: ${e.message}.`; step("py-held", "bad"); ask(); }
  }
  // a login that could not be read (mistyped, or GitHub did not answer): the box comes back with it, the cursor in it
  function ask() {
    const form = $("#py-who"), box = $("#py-login");
    form.style.display = "";
    if (who && !box.value) box.value = who.login;
    box.focus();
  }

  async function link() {
    const out = $("[data-py-link]");
    if (!me || !who) return;
    try { repo ??= (await fetch(`${github}/repos/${encodeURIComponent(who.login)}/knos-claim`)).ok; } catch { repo = null; }
    const href = repo === false ? newRepoLink(who.login) : runLink(who.login);
    out.innerHTML = `<a class="k-btn" id="py-go" href="${esc(href)}" target="_blank" rel="noopener">${repo === false
      ? "Create knos-claim on GitHub" : "Run knos claim on GitHub"}</a> ${repo === false ? "Then press Run workflow there." : "Paste the address, press Run workflow."}`;
    step("py-link", "live");
    $("#py-go").addEventListener("click", () => { if (repo === false) { repo = true; setTimeout(link, 0); } });
  }

  async function showKey() {
    $("[data-py-key]").innerHTML = `<span class="mono" style="overflow-wrap:anywhere" data-py-address>${esc(me.wallet)}</span>
      <button type="button" class="k-btn quiet" id="py-copy">Copy</button>`;
    $("#py-copy").onclick = () => copy();
    $("#py-make").style.display = "none";      // .k-btn sets display, so the hidden attribute alone would not hide it
    step("py-key", "done");
    await link();
  }
  async function copy() {
    const b = $("#py-copy");
    try { await navigator.clipboard.writeText(me.wallet); if (b) b.textContent = "Copied"; } catch { if (b) b.textContent = "Select it and copy"; }
  }

  $("#py-make").onclick = async () => {
    const out = $("[data-py-key]");
    out.textContent = "Asking your device…";
    try {
      const made = await passkey.create({ rpId, rpName: "Knos", userName: who ? `Knos payouts for ${who.login}` : "Knos payouts" });
      me = { credentialId: made.credentialId, key: made.key, wallet: await passkey.wallet(made.key, (await idsP).knos_passkey) };
      remember();
      await showKey();
      await copy();
    } catch (e) {
      const no = /NotAllowed|Abort|cancel/i.test(`${e.name} ${e.message}`);
      out.textContent = no ? "Cancelled. Nothing was made." : `Not made: ${e.message}.`;
    }
  };

  $("#py-check").onclick = async () => {
    const out = $("[data-py-done]");
    if (!who) { out.textContent = "Enter your GitHub login first."; return; }
    out.textContent = "Reading devnet…";
    try {
      const ids = await idsP, at = await boundTo(rpc, ids, who.id ?? (await held(), who.id));
      if (!at) { out.textContent = "Not bound yet. Runs take about a minute."; return; }
      const mine = me && at === me.wallet;
      out.innerHTML = `Bound to <span class="mono" data-py-bound>${esc(at)}</span>${mine ? "" : " (not this passkey)"}. The relay sends held payments there.`;
      step("py-done", mine ? "done" : "bad");
    } catch (e) { out.textContent = `Could not read: ${e.message}.`; }
  };

  $("#py-who").onsubmit = (ev) => {
    ev.preventDefault();
    who = parseArg($("#py-login").value.trim());
    if (!who) { $("[data-py-held]").textContent = "A login is letters, digits and single hyphens."; return; }
    $("#py-who").style.display = "none"; repo = null;
    $("[data-py-held]").focus();      // the box is gone: the focus moves to the answer, and Tab goes on to the passkey
    held(); link();
  };

  held();
  const saved = recall();
  if (saved && typeof saved.key === "string") {
    (async () => {
      const key = passkey.compressed(Uint8Array.from(saved.key.match(/../g) || [], (h) => parseInt(h, 16)));
      const credentialId = saved.credentialId ? Uint8Array.from(atob(saved.credentialId), (c) => c.charCodeAt(0)) : null;
      me = { credentialId, key, wallet: await passkey.wallet(key, (await idsP).knos_passkey) };
      await showKey();
    })().catch(() => { me = null; });
  }
  return { held, check: () => $("#py-check").click() };
}
