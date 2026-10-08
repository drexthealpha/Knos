// ONE TRANSACTION, from agreement through disagreement to resolution, in seven beats the visitor drives:
//   1 Agree           price, acceptance, deadline and remedy are fixed, and the order is funded
//   2 Fails           a submission fails the agreed check: rejected, with the judge's exact reason
//   3 Passes          the corrected submission is accepted, and GitHub signs the run
//   4 Same statement  buyer and supplier each hash the statement: two panes, one root; and the counts the chain holds
//   5 Replay          the order's fund token sent again is refused, and a line billed twice is owed once
//   6 Pay             the program releases test USDC; or a payment instruction file for a bank rail (web/rails.js)
//   7 Verify          the exported file is checked again: its root derived anew, its totals added anew
// renderDemo(el, env) fills `el`. WHAT IS RECORDED AND WHAT IS COMPUTED is said under every beat. Recorded: every
// figure, address and signature of demo_data.json, which scripts/demo_data.py cuts out of this repository's records
// (the devnet round, the tamper benchmark). Computed here, in the reader's browser, from the sample statement this site
// publishes (statement_sample.json): the root both panes show, the duplicate line and the last beat's check. Nothing
// is typed in, nothing plays by itself: each state change is one key (Enter or Space; arrows move, Escape starts
// over), and "Next" stands only before the beats that show something to read first. A verdict and a line's state are
// the words of src/knos/ids.py. Reduced motion: the same states, nothing moving. Styles: the .k-* contract of
// app.css; the block below adds the demo's own.

const STEPS = ["Agree", "Fails", "Passes", "Statement", "Replay", "Pay", "Verify"];
const DUR = [120, 240, 480], EASE = "cubic-bezier(.2,.7,.2,1)";
const REPO = "https://github.com/drexthealpha/Knos/blob/main/";
export const WHY_SOLANA = "Money is released with no custodian, and the count is anchored where neither side can alter it.";
const esc0 = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const short = (s) => `${s.slice(0, 4)}…${s.slice(-4)}`;
const thousands = (n) => String(n).replace(/\B(?=(\d{3})+$)/g, ",");
const explorer0 = (kind, id) => `https://explorer.solana.com/${kind}/${id}?cluster=devnet`;
// statement.canonical and statement.digest (src/knos/statement.py; web/finance_data.js holds the same two): JSON with
// sorted keys and no spaces, one final newline; the root is its sha256 with the sha256 field empty.
const canon = (d) => (d === null || d === undefined ? "null" : typeof d !== "object" ? JSON.stringify(d) : Array.isArray(d) ? `[${d.map(canon)}]`
  : `{${Object.keys(d).sort().map((k) => `${JSON.stringify(k)}:${canon(d[k])}`)}}`);
export async function rootOf(st) {
  const got = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${canon({ ...st, sha256: "" })}\n`));
  return [...new Uint8Array(got)].map((x) => x.toString(16).padStart(2, "0")).join("");
}
const cents = (a) => Math.round(parseFloat(a) * 100);
// every total of the statement, added again from its lines
export const totalsHold = (st) => Object.entries(st.totals).every(([k, t]) => { const l = st.lines.filter((x) => k === "billed" || x.state === k);
  return l.length === t.lines && l.reduce((n, x) => n + cents(x.amount), 0) === cents(t.amount); });

let motion = null;          // web/motion.js, when the site has it
const motionReady = import("./motion.js").then((m) => { motion = m; }).catch(() => {});
const reduced = () => { try { return motion?.prefersReduced ? motion.prefersReduced() : matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; } };

const STYLE = `
.kd { --k-mono: var(--code, ui-monospace, Menlo, Consolas, monospace); color: var(--ink); min-width: 0; max-width: 100%; box-sizing: border-box; text-align: left; }
.kd *, .kd *::before { box-sizing: border-box; }
:where(.kd).k-card { background: var(--paper-2); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px;
  box-shadow: var(--depth-2); }
:where(.kd) .k-kicker { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-2); margin: 0; font-weight: 600; }
:where(.kd) .k-num { font-variant-numeric: tabular-nums; }
:where(.kd) .k-btn.quiet { background: transparent; color: var(--ink); border-color: var(--line); }
.kd-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.kd-keys { font-size: 12px; color: var(--ink-2); margin: 0; }
.kd-steps { list-style: none; margin: 0 0 16px; padding: 0; display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; }
.kd-steps li { min-width: 0; margin: 0; }
.kd .kd-steps .k-step { display: flex; align-items: center; gap: 6px; width: 100%; min-height: 36px; padding: 6px 8px; margin: 0; font-size: 13px; font-weight: 600;
  line-height: 1.2; text-align: left; background: transparent; color: var(--ink-2); border: 1px solid var(--line); border-radius: 999px; cursor: pointer;
  transition: color var(--dur-1) var(--ease), border-color var(--dur-1) var(--ease), background-color var(--dur-1) var(--ease); filter: none; }
.kd .k-step i { font-style: normal; flex: none; width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; font-size: 11px;
  background: var(--line); color: var(--ink); font-variant-numeric: tabular-nums; }
.kd .kd-steps .k-step::before, .kd .kd-steps .k-step::after, .kd td .k-step::before { content: none; }
.kd [hidden] { display: none !important; }
.kd .k-step span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kd .k-step[data-state="live"] { color: var(--ink); border-color: var(--accent); }
.kd .k-step[data-state="live"] i { background: var(--accent); color: var(--paper-2); }
.kd .k-step[data-state="done"] i { background: var(--ok); color: var(--paper-2); }
.kd .k-step[data-state="bad"] i { background: var(--bad); color: var(--paper-2); }
.kd .k-step[data-end="disputed"] i { background: var(--paper-2); color: var(--bad); box-shadow: inset 0 0 0 2px var(--bad); }
.kd .k-step[aria-current="step"] { color: var(--ink); border-color: var(--ink); }
.kd-rail { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; margin: 0 0 16px; padding: 0; list-style: none; position: relative; }
.kd-rail::before { content: ""; position: absolute; left: 12.5%; right: 12.5%; top: 9px; border-top: 1px dashed var(--line); }
.kd-node { position: relative; display: grid; justify-items: center; gap: 4px; min-width: 0; margin: 0; font-size: 12px; color: var(--ink-2); text-align: center; }
.kd-node b { width: 18px; height: 18px; border-radius: 50%; background: var(--paper-2); border: 2px solid var(--line);
  transition: border-color var(--dur-2) var(--ease), background-color var(--dur-2) var(--ease); }
.kd-node[data-s="ok"] b { border-color: var(--ok); background: var(--ok); }
.kd-node[data-s="bad"] b { border-color: var(--bad); background: var(--bad); }
.kd-node[data-s="on"] b { border-color: var(--accent); }
.kd-node span { font-weight: 600; color: var(--ink); }
.kd-node em { font-style: normal; font-variant-numeric: tabular-nums; min-height: 1.3em; }
.kd-scene { min-height: 214px; display: grid; align-content: start; gap: 10px; padding: 14px; border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--paper); min-width: 0; }
.kd-scene > * { margin: 0; min-width: 0; }
.kd-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; }
.kd-tag { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-2); }
.kd-mono { font-family: var(--k-mono); font-size: 13px; overflow-wrap: anywhere; }
.kd .kd-input { width: 100%; min-width: 0; font-family: var(--k-mono); font-size: 14px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px;
  background: var(--paper-2); color: var(--ink); margin: 0; }
.kd-box { padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--paper-2); display: grid; gap: 6px; }
.kd-box p { margin: 0; }
.kd-quote { font-size: 20px; font-weight: 600; margin: 0; padding: 0; border: 0; }
.kd-checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.kd-checks li { display: flex; align-items: baseline; gap: 8px; margin: 0; min-width: 0; }
.kd-checks li::before { content: "•"; width: 1em; flex: none; text-align: center; color: var(--ink-2); font-weight: 700; }
.kd-checks li[data-s="ok"]::before { content: "✓"; color: var(--ok); }
.kd-checks li[data-s="bad"]::before { content: "✗"; color: var(--bad); }
.kd-badge { display: inline-block; font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
.kd-badge[data-s="ok"] { color: var(--ok); } .kd-badge[data-s="bad"] { color: var(--bad); } .kd-badge[data-s="wait"] { color: var(--ink-2); }
.kd-pills { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; list-style: none; }
.kd-pills li { margin: 0; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--line); background: var(--paper-2); font-size: 13px; }
.kd-big { font-size: 44px; line-height: 1; font-weight: 700; letter-spacing: -.02em; }
.kd-big small { font-size: 16px; font-weight: 600; color: var(--ink-2); letter-spacing: 0; }
.kd-sides { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.kd-sides > div { display: grid; gap: 4px; }
.kd-fine { font-size: 12px; color: var(--ink-2); }
.kd .kd-fine.k-num, .kd .kd-row > .k-num { white-space: normal; }
.kd-mark { font-size: 13px; color: var(--ink-2); margin: -6px 0 14px; }
.kd-seller[data-s="bad"] { border-color: var(--bad); } .kd-big .kd-apart { color: var(--bad); }
.kd-say { margin: 14px 0 12px; font-size: 17px; font-weight: 600; min-height: 2.6em; }
.kd-act { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.kd .kd-act button { margin: 0; }
.kd-src { margin: 14px 0 0; font-size: 12px; color: var(--ink-2); }
.kd-token { width: 14px; height: 14px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 4px rgba(127,127,127,.18); }
.kd-raven { width: 28px; height: 28px; color: var(--accent); }
.kd-terms { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 14px; margin: 0; }
.kd-terms dt { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-2); margin: 0; align-self: center; }
.kd-terms dd { margin: 0; font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
.kd-prov { font-size: 12px; color: var(--ink-2); padding-top: 8px; border-top: 1px dashed var(--line); }
.kd-root { font-family: var(--k-mono); font-size: 13px; overflow-wrap: anywhere; min-height: 1.4em; }
.kd-root[data-s="ok"] { color: var(--ok); } .kd-root[data-s="bad"] { color: var(--bad); }
.kd-why { font-size: 13px; } .kd-why summary { cursor: pointer; font-weight: 600; width: fit-content; } .kd-why p { margin: 6px 0 0; max-width: 46ch; }
.kd-scene[aria-busy="true"] { opacity: .7; }
@media (max-width: 600px) {
  :where(.kd).k-card { padding: 14px; }
  .kd .kd-steps .k-step { justify-content: center; padding: 6px 0; }
  .kd .k-step span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  .kd-keys { display: none; }
  .kd-big { font-size: 36px; }
  .kd-say { font-size: 16px; }
}
@media (prefers-reduced-motion: reduce) { .kd, .kd * { transition: none !important; animation: none !important; } }
`;


function style() {
  if (document.getElementById("kd-style")) return;
  const s = document.createElement("style");
  s.id = "kd-style";
  s.textContent = STYLE;
  document.head.prepend(s);          // first in the head: the site's stylesheet comes after it and wins where both speak
}

// A token moves from one element to another, then is gone. With motion.js it is the site's; without, the same in plain WAAPI.
async function fly(node, from, to, ms) {
  if (reduced() || !from || !to) return;
  const wait = new Promise((r) => setTimeout(r, ms));
  try {
    if (motion?.travel) await Promise.all([Promise.resolve(motion.travel(node, from, to, ms)), wait]);
    else {
      const a = from.getBoundingClientRect(), b = to.getBoundingClientRect();
      Object.assign(node.style, { position: "fixed", left: "0", top: "0", zIndex: "5", pointerEvents: "none" });
      document.body.append(node);
      const w = node.offsetWidth / 2, h = node.offsetHeight / 2;
      const at = (r) => `translate(${r.left + r.width / 2 - w}px, ${r.top + r.height / 2 - h}px)`;
      await node.animate([{ transform: at(a) }, { transform: at(b) }], { duration: ms, easing: EASE, fill: "forwards" }).finished;
    }
  } catch { /* a cancelled animation changes nothing: the state is already drawn */ }
  node.remove();
}
const token = () => Object.assign(document.createElement("span"), { className: "kd-token" });
const ravenMark = () => { const i = Object.assign(document.createElement("img"), { className: "kd-raven", alt: "" }); i.src = "brand/mark-small.svg"; return i; };

export async function renderDemo(el, env = {}) {
  if (!el) return null;
  const esc = env.esc || esc0, EXPLORER = env.EXPLORER || explorer0;
  let d = env.data;
  if (!d) {
    try { const r = await fetch(new URL("./demo_data.json", import.meta.url)); if (!r.ok) throw new Error(String(r.status)); d = await r.json(); } catch { return null; }
  }
  await Promise.race([motionReady, new Promise((r) => setTimeout(r, 300))]);
  style();

  const online = () => (env.online ? env.online() : navigator.onLine !== false);
  const tx = (sig, text) => (online() ? `<a href="${esc(EXPLORER("tx", sig))}" target="_blank" rel="noopener">${esc(text)}</a>` : "");
  const check = d.claim.check.split(".").slice(-1)[0], test = check.split("::").pop();
  const N = STEPS.length, state = { step: 0, done: STEPS.map(() => false), run: 0, busy: false, bank: null, changed: false };
  const agreed = Number(d.count.apart) === 0;          // the two counts the chain holds are the same: the month is agreed, not disputed
  const BAD = [false, true, false, false, true, false, false];
  const ENDS = ["funded", "rejected", "accepted", agreed ? "agreed" : "disputed", "not paid again", "paid", "verified"];          // how each beat ends, in the words of src/knos/ids.py
  const READ = [false, true, false, true, false, true, true];          // a beat that shows something to read before its action
  const LIVE = [false, false, false, true, true, true, true];          // a beat that reads the sample statement first
  const day = String(d.date).replace(/^(\d+ \w{3})\w*/, "$1"), where = d.ids === "public" ? "public program ids" : "staging program ids";
  const PROV = [`Recorded on ${d.cluster}, ${day}.`, "Recorded in the tamper benchmark.", "Recorded in the tamper benchmark.", `Counts recorded on ${d.cluster}. Sample statement hashed here.`,
    `Token recorded on ${d.cluster}. Line from the sample statement.`, `Payment recorded on ${d.cluster}, in ${d.money}.`, "The sample statement, checked in your browser."];

  // The sample statement this site publishes, read when the reader first acts, and what this page computes from it: the
  // root (twice: once a pane), whether the totals add up, the line billed twice, and the root of the same file with one
  // amount changed. No file (a build without it, no network): the beats show what is recorded and say so.
  let facts = null, factsP = null;
  const load = () => (factsP ||= (async () => {
    try {
      const st = env.statement || await (await fetch(new URL("./statement_sample.json", import.meta.url))).json();
      const [buyer, supplier] = await Promise.all([rootOf(st), rootOf(JSON.parse(JSON.stringify(st)))]);
      const other = JSON.parse(JSON.stringify(st)); other.lines[0].amount = (cents(other.lines[0].amount) / 100 + 1).toFixed(2);
      const pain = env.pain001 || (d.bank_file ? bankOf((await import("./rails.js")).pain001) : null);
      return { st, buyer, supplier, stated: st.sha256, totals: totalsHold(st), dup: st.lines.find((l) => l.state === "duplicate"), other: await rootOf(other), otherTotals: totalsHold(other), pain };
    } catch { return {}; }
  })().then((f) => { facts = f; return f; }));

  el.classList.add("kd", "k-card");
  el.setAttribute("role", "group");
  el.setAttribute("aria-label", "One transaction, in seven beats");
  el.innerHTML = `
    <div class="kd-top"><p class="k-kicker">One transaction. You drive.</p><p class="kd-keys" aria-hidden="true">Enter: act · arrows: steps · Esc: start over</p></div>
    <p class="kd-mark" data-ids="${esc(d.ids || "staging")}">A real ${esc(d.cluster)} round, replayed (${esc(where)}, ${esc(day)}).</p>
    <ol class="kd-steps">${STEPS.map((s, i) => `<li><button type="button" class="k-step" data-step="${i}" data-state="idle"><i>${i + 1}</i><span>${esc(s)}</span></button></li>`).join("")}</ol>
    <ul class="kd-rail k-stage" aria-hidden="true">${["Buyer", "GitHub", "Solana", "Supplier"].map((n) => `<li class="kd-node" data-node="${n.toLowerCase()}"><b></b><span>${n}</span><em class="k-num"></em></li>`).join("")}</ul>
    <div class="kd-scene"></div>
    <p class="kd-say" role="status" aria-live="polite"></p>
    <div class="kd-act"><button type="button" class="k-btn kd-go"></button><button type="button" class="k-btn quiet ghost kd-alt" hidden></button><button type="button" class="k-btn quiet ghost kd-reset" hidden>Start over</button></div>
    <p class="kd-src">Sources:
      <a href="${REPO}docs/CAPABILITIES.md#the-round-on-the-public-program-ids">round</a>, <a href="${REPO}docs/TAMPER.md">tamper benchmark</a>, <a href="${REPO}docs/RELAY.md">timing</a>, <a href="statement_sample.json">sample statement</a>.</p>`;
  const q = (s) => el.querySelector(s), node = (n) => q(`[data-node="${n}"]`);
  const scene = q(".kd-scene"), say = q(".kd-say"), go = q(".kd-go"), alt = q(".kd-alt"), resetB = q(".kd-reset");
  const badge = (s, text) => `<span class="kd-badge" data-s="${s}">${esc(text)}</span>`;
  const root = (r, s = "") => `<span class="kd-root" data-s="${s}" title="${esc(r || "")}">${r ? esc(`${r.slice(0, 12)}…${r.slice(-6)}`) : "not computed"}</span>`;
  const none = `<p class="kd-fine">This build has no sample statement to compute from.</p>`;

  // ---- what each beat shows, before and after its one action -------------------------------------------------------
  const views = [
    (on) => ({
      html: `<dl class="kd-terms"><dt>Price</dt><dd class="k-num">${esc(d.agree.price)} ${esc(d.money)}</dd><dt>Acceptance</dt><dd>Named checks pass at merge</dd>
          <dt>Deadline</dt><dd class="k-num">${esc(d.agree.days)} days</dd><dt>Remedy</dt><dd>Unproven: the money goes back</dd></dl>
        <label class="kd-tag" for="kd-comment">The buyer's comment on the issue</label>
        <input id="kd-comment" class="kd-input" type="text" readonly value="${esc(d.fund.comment)}">
        ${on ? `<div class="kd-box"><div class="kd-row"><span class="kd-tag">Order</span><span class="kd-mono">${esc(short(d.fund.order))}</span>${badge("ok", "funded")}</div>
          <div class="kd-row"><span class="k-num"><strong>${esc(d.fund.amount)}</strong> ${esc(d.money)} held</span><span class="kd-fine k-num" data-fee-rule="0.3.14" title="This is a recording: the fee is the one the program took then.">fee ${esc(d.fund.fee)}, charged under the 0.3.14 fee</span>${tx(d.fund.tx, "transaction")}</div></div>` : ""}`,
      say: on ? `Agreed and funded: ${d.fund.amount} ${d.money} held.` : "Buyer and supplier fix four terms first.",
      act: "Agree and fund",
    }),
    (on) => ({
      html: `<div class="kd-box"><div class="kd-row"><span class="kd-tag">Submission</span><span>${esc(d.claim.pull)}</span></div>
          <blockquote class="kd-quote">“${esc(d.claim.says)}”</blockquote></div>
        <ul class="kd-checks"><li data-s="${on ? "bad" : "wait"}"><span class="kd-mono">${esc(check)}</span>${badge(on ? "bad" : "wait", on ? "failed" : "not read")}</li></ul>
        ${on ? `<p class="kd-row kd-verdict">${badge("bad", "rejected")}<span class="kd-mono kd-reason">${esc(d.claim.reason)}: ${esc(test)}</span></p>` : ""}`,
      say: on ? `Rejected: ${test} failed.` : "A submission says its tests pass.",
      act: "Check the submission",
    }),
    (on) => ({
      html: `<ul class="kd-checks">${[["CI", d.fixed.ci], ["Knos, tests", d.fixed.tests], ["Knos, black box", d.fixed.black_box]].map(([n, v]) =>
        `<li data-s="${on ? "ok" : "wait"}"><span>${esc(n)}</span>${badge(on ? "ok" : "wait", on ? v : "waiting")}</li>`).join("")}</ul>
        ${on ? `<div class="kd-box"><div class="kd-row"><span class="kd-tag">Verdict</span>${badge("ok", "accepted")}<span class="kd-tag">Signed by GitHub</span>${badge("ok", "signed")}</div>
          <ul class="kd-pills">${d.fixed.claims.map((c) => `<li>${esc(c.is)} <span class="kd-mono">${esc(c.name)}</span></li>`).join("")}</ul></div>` : ""}`,
      say: on ? "Accepted: checks pass. GitHub signs repository, commit and workflow." : "The supplier pushes a corrected submission.",
      act: "Push the correction",
    }),
    (on) => {
      const f = on && facts, same = !!f?.buyer && f.buyer === f.supplier && f.buyer === f.stated;
      const pane = (who, n, txs, word, r, cls = "") => `<div class="kd-box ${cls}" data-s="${on && !agreed && cls ? "bad" : ""}"><span class="kd-tag">${who} counted</span><span class="kd-big k-num">${n}</span>
            <span class="kd-fine">${txs.map((t, k) => tx(t, `${word} ${k + 1}`)).join(" ")}</span><span class="kd-tag">${who}'s root</span>${root(r, same ? "ok" : "")}</div>`;
      return {
        html: `<div class="kd-sides">${pane("Buyer", thousands(d.count.buyer), d.count.buyer_tx, "batch", f?.buyer)}
          ${pane("Supplier", `${thousands(d.count.seller)}${on && !agreed ? ` <small class="kd-apart">+${esc(d.count.apart)}</small>` : ""}`, d.count.seller_tx, "claim", f?.supplier, "kd-seller")}</div>
        <p class="kd-row"><span class="kd-tag">The month</span><span class="kd-badge kd-row-state" data-s="${on ? (agreed ? "ok" : "bad") : "wait"}">${on ? (agreed ? "agreed" : "disputed") : "not compared"}</span>
          ${same ? badge("ok", "same root") : ""}${on && !agreed ? `<span class="kd-fine k-num">${esc(d.count.apart)} the buyer's ledger left out, each named.</span>` : ""}</p>${on && facts && !facts.st ? none : ""}`,
        say: on ? (agreed ? `Agreed: both counted ${thousands(d.count.buyer)}.${same ? " One root." : ""}` : `Disputed: the buyer's ledger left out ${d.count.apart} evaluations.`) : `Buyer counted ${thousands(d.count.buyer)}. Supplier counted ${thousands(d.count.seller)}.`,
        act: "Compute both statements",
      };
    },
    (on) => {
      const dup = on && facts?.dup;
      return {
        html: `<div class="kd-box kd-shake"><div class="kd-row"><span class="kd-tag">Fund token, sent again</span>${badge(on ? "bad" : "wait", on ? "Refused" : "used once")}</div>
          ${on ? `<p class="kd-fine k-num">Error ${esc(d.replay.error)}: ${esc(d.replay.means)}. ${tx(d.replay.tx, "transaction")}</p>` : ""}</div>
          ${dup ? `<div class="kd-box"><div class="kd-row"><span class="kd-tag">Invoice line ${esc(dup.line)}</span><span class="k-num">${esc(dup.amount)}</span>${badge("bad", "duplicate")}</div>
            <p class="kd-fine k-num kd-dup">${esc(dup.why.split(":")[0].replace(/^./, (c) => c.toUpperCase()))}: owed once.</p></div>` : ""}`,
        say: on ? `Refused: a token works once. Error ${d.replay.error}.` : "Send the same token a second time.",
        act: "Send the same token again",
      };
    },
    (on) => ({
      html: `<p class="kd-big"><span class="k-num kd-secs" data-to="${on ? d.paid.seconds : 0}">${on ? esc(d.paid.seconds) : 0}</span> <small>seconds</small></p>
        <p class="kd-fine k-num">Merge to paid, median of ${esc(d.paid.payments)} payments.</p>
        ${on ? `<p class="kd-row">${badge("ok", "Paid")}<span class="k-num"><strong>${esc(d.paid.amount)}</strong> ${esc(d.money)}</span>${tx(d.paid.tx, "See it on the explorer")}</p>` : ""}
        ${state.bank ? `<p class="kd-row kd-bank">${badge("ok", "Bank file written")}<a class="kd-mono" download="${esc(state.bank.name)}" href="${esc(state.bank.href)}">${esc(state.bank.name)}</a><span class="kd-fine k-num">${esc(thousands(state.bank.bytes))} bytes. No bank has taken this file.</span></p>` : ""}
        <details class="kd-why"><summary>Why Solana?</summary><p>${esc(WHY_SOLANA)}</p></details>`,
      say: state.bank && !on ? "Bank file written. No bank has taken it." : on ? `Paid ${d.paid.amount} ${d.money}. Median wait: ${d.paid.seconds} seconds.` : "Release the money on the signed acceptance.",
      act: `Pay in ${d.money}`,
      alt: facts?.pain && facts.st && !state.bank ? ["Write a bank file instead", bankFile] : null,
    }),
    (on) => {
      const f = on && facts?.st ? facts : null, bad = !!f && state.changed, r = f && (bad ? f.other : f.buyer), ok = f && !bad && r === f.stated && f.totals;
      const line = (good, text) => `<li data-s="${f ? (good ? "ok" : "bad") : "wait"}"><span>${text}</span>${badge(f ? (good ? "ok" : "bad") : "wait", f ? (good ? "matches" : "differs") : "not checked")}</li>`;
      return {
        html: `<div class="kd-box kd-shake"><div class="kd-row"><span class="kd-tag">Export</span><a class="kd-mono" href="statement_sample.json" download>statement_sample.json</a>${bad ? badge("bad", "one amount changed") : ""}</div>
            <div class="kd-row"><span class="kd-tag">Root, derived again</span>${root(r, f ? (ok ? "ok" : "bad") : "")}</div></div>
          <ul class="kd-checks">${line(f && r === f.stated, "The root the file states")}${line(f && (bad ? f.otherTotals : f.totals), "Every total, added again")}</ul>
          ${on && d.verify ? `<p class="kd-row kd-recorded">${badge("ok", "recorded")}<a href="${esc(REPO + d.verify.link)}">${esc(d.verify.says)}</a></p>` : ""}${on && facts && !facts.st ? none : ""}`,
        say: !on ? "Check the export again, from the file alone." : !f ? "No sample statement in this build." : ok ? "Verified: root and totals match the export." : "Not verified: the changed file has another root.",
        act: "Verify the export",
        alt: f ? [bad ? "Put the amount back" : "Change one amount", () => { state.changed = !state.changed; draw(); if (state.changed) shake(); }] : null,
      };
    },
  ];
  let altDo = null;

  function draw() {
    const i = state.step, on = state.done[i], v = views[i](on && !state.busy);
    state.run += 1;
    const inside = scene.contains(document.activeElement), wasAlt = document.activeElement === alt;
    scene.innerHTML = `${v.html}<p class="kd-fine kd-prov">${esc(PROV[i])}</p>`;
    scene.setAttribute("aria-label", `Step ${i + 1} of ${N}: ${STEPS[i]}`);
    scene.setAttribute("role", "group");
    if (state.busy) scene.setAttribute("aria-busy", "true"); else scene.removeAttribute("aria-busy");
    say.textContent = state.busy ? "Computing in your browser." : v.say;
    const next = i + 1, straight = next < N && !READ[next] && !state.done[next];          // the next beat needs no reading: one key does it
    go.textContent = !on ? v.act : next >= N ? "Start over" : straight ? views[next](false).act : `Next: ${STEPS[next]}`;
    altDo = v.alt?.[1] || null; alt.hidden = !altDo; alt.textContent = v.alt?.[0] || "";
    resetB.hidden = !(state.done.some(Boolean) || i > 0) || (on && i === N - 1);
    el.querySelectorAll(".k-step").forEach((b, k) => {
      // The design system's "bad" step is a refusal: red, and it shakes once. A disputed month is no refusal: two counts
      // differ. So that beat ends as a finished step, marked by its own word.
      b.dataset.state = state.done[k] ? (BAD[k] ? "bad" : "done") : k === i ? "live" : "idle";
      if (state.done[k]) b.dataset.end = ENDS[k]; else delete b.dataset.end;
      if (k === i) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
      b.setAttribute("aria-label", `Step ${k + 1}: ${STEPS[k]}${state.done[k] ? `, ${ENDS[k]}` : ""}`);
    });
    const [funded, failed, signed, , replayed, paid] = state.done;
    const set = (n, s, text) => { node(n).dataset.s = s; node(n).querySelector("em").textContent = text; };
    set("buyer", funded ? "ok" : i === 0 ? "on" : "", "");
    set("github", failed && !signed ? "bad" : signed ? "ok" : i === 1 || i === 2 ? "on" : "", signed ? "signed" : failed ? "1 failed" : "");
    set("solana", replayed && i === 4 ? "bad" : funded || paid ? "ok" : i === 5 ? "on" : "", replayed && i === 4 ? "not paid again" : paid ? "0.00 held" : funded ? `${d.fund.amount} held` : "");
    set("supplier", paid ? "ok" : "", paid ? `+${d.paid.amount}` : "");
    if (inside || wasAlt) (wasAlt && !alt.hidden ? alt : go).focus({ preventScroll: true });
  }

  // ---- the movement that explains a change; the change itself is already drawn ---------------------------------------
  const b = (n) => node(n).querySelector("b");
  function shake() { if (!reduced()) q(".kd-shake")?.animate([{ transform: "translateX(0)" }, { transform: "translateX(-6px)" }, { transform: "translateX(6px)" }, { transform: "translateX(-3px)" }, { transform: "translateX(0)" }], { duration: DUR[1], easing: EASE }); }
  function move(i) {
    if (reduced()) return;
    const run = state.run;
    if (i === 0) fly(token(), b("buyer"), b("solana"), DUR[2]);
    if (i === 3) for (const r of el.querySelectorAll('.kd-root[data-s="ok"]')) r.animate({ scale: ["1", "1.06", "1"] }, { duration: DUR[1], easing: EASE });
    if (i === 5) {
      const secs = q(".kd-secs"), to = Number(secs.dataset.to), t0 = performance.now();
      secs.textContent = "0";
      const tick = (t) => {
        if (state.run !== run || !secs.isConnected) return;
        const p = Math.min(1, (t - t0) / (DUR[2] * 2));
        secs.textContent = String(Math.round(to * p));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      fly(token(), b("github"), b("solana"), DUR[1]).then(() => {
        if (state.run !== run) return;
        if (motion?.raven) { try { motion.raven(b("solana"), b("supplier")); } catch { /* the payment is drawn either way */ } } else fly(ravenMark(), b("solana"), b("supplier"), DUR[2]);
      });
    }
    if (i === 4) fly(token(), b("github"), b("solana"), DUR[1]).then(() => { if (state.run === run) shake(); });
  }

  // web/rails.js `pain001(statement, payer, status)` instructs only lines that are agreed, approved and still payable, from
  // an account to an account. The demonstration approves the sample's agreed lines itself, on the statement's own day,
  // and names two accounts that are the standard's printed examples: nobody's.
  const EXAMPLE_PAYER = "GB33BUKB20201555555555", EXAMPLE_PAYEE = "DE89370400440532013000";
  function bankOf(pain001) {
    return (st, payer) => {
      const agreed = st.lines.filter((l) => l.state === "agreed");
      const status = { kind: "knos-statement-status", version: 1, statement: st.sha256, events: [{ type: "approval", scope: "agreed", by: "the demonstration", role: "approver", on: st.date,
        lines: agreed.map((l) => l.invoice_line), amount: (agreed.reduce((n, l) => n + cents(l.amount), 0) / 100).toFixed(2) }] };
      const payees = Object.fromEntries([...new Set(agreed.map((l) => l.supplier))].map((who) => [who, { name: who, account: EXAMPLE_PAYEE }]));
      return pain001(st, { name: payer.name, account: EXAMPLE_PAYER, on: st.date, payees }, status);
    };
  }

  // The payment instruction file for a bank rail (web/rails.js `pain001`), from the sample statement's agreed lines:
  // written in the browser and offered as a download. No bank has taken it, and the page says so beside it.
  function bankFile() {
    try {
      const xml = String(facts.pain(facts.st, { name: facts.st.buyer }));
      state.bank = { name: `pain001-${facts.st.invoice}.xml`, bytes: new TextEncoder().encode(xml).length, href: URL.createObjectURL(new Blob([xml], { type: "application/xml" })) };
    } catch { facts.pain = null; }
    draw();
  }

  const goTo = (i) => { state.step = Math.max(0, Math.min(N - 1, i)); draw(); };
  const reset = () => { Object.assign(state, { step: 0, bank: null, changed: false, busy: false }); state.done.fill(false); draw(); go.focus({ preventScroll: true }); };
  // A beat that reads the sample statement shows its pending state in the task of the press, and its answer when the
  // file has been read and hashed (once: the later beats find it there).
  async function act(k) {
    state.done[k] = true;
    if (LIVE[k] && !facts) { state.busy = true; draw(); const run = state.run; await load(); state.busy = false; if (state.run !== run) return draw(); }
    draw(); move(k);
  }
  function primary() {
    const i = state.step;
    load();
    if (state.busy) return undefined;
    if (!state.done[i]) return act(i);
    if (i >= N - 1) return reset();
    state.step = i + 1;
    if (!READ[i + 1] && !state.done[i + 1]) return act(i + 1);
    return draw();
  }

  go.addEventListener("click", primary);
  alt.addEventListener("click", () => altDo?.());
  resetB.addEventListener("click", reset);
  el.querySelector(".kd-steps").addEventListener("click", (e) => { const s = e.target.closest(".k-step"); if (s) goTo(Number(s.dataset.step)); });
  el.addEventListener("keydown", (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const t = e.target, native = t.closest?.("button, a, summary");
    if (e.key === "Escape") { e.preventDefault(); reset(); }
    else if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); goTo(state.step + 1); if (t.closest?.(".k-step")) el.querySelector(`[data-step="${state.step}"]`).focus(); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); goTo(state.step - 1); if (t.closest?.(".k-step")) el.querySelector(`[data-step="${state.step}"]`).focus(); }
    else if ((e.key === "Enter" || e.key === " ") && !native) { e.preventDefault(); primary(); }
  });

  el.hidden = false;
  draw();
  return { state, goTo, reset, primary, load };
}
