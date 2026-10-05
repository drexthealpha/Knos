// One round, driven by the visitor: fund, a claim refused, the fix signed, paid, a replay refused, the two counts.
// renderDemo(el, env) fills `el` (the first screen's <div id="demo">). Every figure, address and signature shown is read
// from demo_data.json, which scripts/demo_data.py cuts out of this repository's own records; nothing is typed in here.
// Nothing plays by itself: each state change is one click or one key, and each step takes ONE key: the button that acts
// on a step names the next step's action once it has acted, and "Next" stands only before the two steps that show
// something to read first (the claim, the two counts). Enter and Space act, the arrows move between steps, Escape
// starts over. A reader who asked for reduced motion gets the same states with no movement.
// What is shown is what was recorded, and nothing else: the token sent again was refused because its order was already
// paid (the error the rehearsal recorded for it, not the single-use one), and the two counts are the two the chain
// holds, 3 apart from the start; the last step compares them, it never makes them up.
// The look is the site's design contract (the .k-* classes of app.css, web/motion.js). Both may be absent: the import
// is guarded, and the style block below is a fallback of zero specificity for the contract's classes.

const STEPS = ["Fund", "A claim", "Fixed", "Paid", "Replay", "Both sides"];
const DUR = [120, 240, 480], EASE = "cubic-bezier(.2,.7,.2,1)";
const REPO = "https://github.com/drexthealpha/Knos/blob/main/";
const esc0 = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const short = (s) => `${s.slice(0, 4)}…${s.slice(-4)}`;
const thousands = (n) => String(n).replace(/\B(?=(\d{3})+$)/g, ",");
const explorer0 = (kind, id) => `https://explorer.solana.com/${kind}/${id}?cluster=devnet`;

let motion = null;          // web/motion.js, when the site has it
const motionReady = import("./motion.js").then((m) => { motion = m; }).catch(() => {});
const reduced = () => { try { return motion?.prefersReduced ? motion.prefersReduced() : matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; } };

const STYLE = `
.kd { --k-ink: var(--ink, var(--fg, #15171c)); --k-ink2: var(--ink-2, var(--muted, #5a606b)); --k-paper: var(--paper, var(--bg, #f6f5f1));
  --k-paper2: var(--paper-2, var(--card, #fff)); --k-line: var(--line, #e1dfd7); --k-acc: var(--accent, #2b3bb5); --k-ok: var(--ok, #17703f);
  --k-bad: var(--bad, #b3261e); --k-r: var(--radius, 12px); --k-ease: var(--ease, ${EASE}); --k-d1: var(--dur-1, 120ms); --k-d2: var(--dur-2, 240ms);
  --k-mono: var(--code, ui-monospace, Menlo, Consolas, monospace);
  color: var(--k-ink); min-width: 0; max-width: 100%; box-sizing: border-box; text-align: left; }
.kd *, .kd *::before { box-sizing: border-box; }
:where(.kd).k-card { background: var(--k-paper2); border: 1px solid var(--k-line); border-radius: var(--k-r); padding: 20px;
  box-shadow: var(--depth-2, 0 1px 0 rgba(0,0,0,.03), 0 12px 32px -18px rgba(0,0,0,.28)); }
:where(.kd) .k-kicker { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--k-ink2); margin: 0; font-weight: 600; }
:where(.kd) .k-num { font-variant-numeric: tabular-nums; }
:where(.kd) .k-btn.quiet { background: transparent; color: var(--k-ink); border-color: var(--k-line); }
.kd-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.kd-keys { font-size: 12px; color: var(--k-ink2); margin: 0; }
.kd-steps { list-style: none; margin: 0 0 16px; padding: 0; display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 6px; }
.kd-steps li { min-width: 0; margin: 0; }
.kd .kd-steps .k-step { display: flex; align-items: center; gap: 6px; width: 100%; min-height: 36px; padding: 6px 8px; margin: 0; font-size: 13px; font-weight: 600;
  line-height: 1.2; text-align: left; background: transparent; color: var(--k-ink2); border: 1px solid var(--k-line); border-radius: 999px; cursor: pointer;
  transition: color var(--k-d1) var(--k-ease), border-color var(--k-d1) var(--k-ease), background-color var(--k-d1) var(--k-ease); filter: none; }
.kd .k-step i { font-style: normal; flex: none; width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; font-size: 11px;
  background: var(--k-line); color: var(--k-ink); font-variant-numeric: tabular-nums; }
.kd .kd-steps .k-step::before, .kd .kd-steps .k-step::after, .kd td .k-step::before { content: none; }
.kd [hidden] { display: none !important; }
.kd .k-step span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kd .k-step[data-state="live"] { color: var(--k-ink); border-color: var(--k-acc); }
.kd .k-step[data-state="live"] i { background: var(--k-acc); color: var(--k-paper2); }
.kd .k-step[data-state="done"] i { background: var(--k-ok); color: var(--k-paper2); }
.kd .k-step[data-state="bad"] i { background: var(--k-bad); color: var(--k-paper2); }
.kd .k-step[aria-current="step"] { color: var(--k-ink); border-color: var(--k-ink); }
.kd-rail { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; margin: 0 0 16px; padding: 0; list-style: none; position: relative; }
.kd-rail::before { content: ""; position: absolute; left: 12.5%; right: 12.5%; top: 9px; border-top: 1px dashed var(--k-line); }
.kd-node { position: relative; display: grid; justify-items: center; gap: 4px; min-width: 0; margin: 0; font-size: 12px; color: var(--k-ink2); text-align: center; }
.kd-node b { width: 18px; height: 18px; border-radius: 50%; background: var(--k-paper2); border: 2px solid var(--k-line);
  transition: border-color var(--k-d2) var(--k-ease), background-color var(--k-d2) var(--k-ease); }
.kd-node[data-s="ok"] b { border-color: var(--k-ok); background: var(--k-ok); }
.kd-node[data-s="bad"] b { border-color: var(--k-bad); background: var(--k-bad); }
.kd-node[data-s="on"] b { border-color: var(--k-acc); }
.kd-node span { font-weight: 600; color: var(--k-ink); }
.kd-node em { font-style: normal; font-variant-numeric: tabular-nums; min-height: 1.3em; }
.kd-scene { min-height: 172px; display: grid; align-content: start; gap: 10px; padding: 14px; border: 1px solid var(--k-line); border-radius: var(--k-r);
  background: var(--k-paper); min-width: 0; }
.kd-scene > * { margin: 0; min-width: 0; }
.kd-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; }
.kd-tag { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--k-ink2); }
.kd-mono { font-family: var(--k-mono); font-size: 13px; overflow-wrap: anywhere; }
.kd .kd-input { width: 100%; min-width: 0; font-family: var(--k-mono); font-size: 14px; padding: 10px 12px; border: 1px solid var(--k-line); border-radius: 8px;
  background: var(--k-paper2); color: var(--k-ink); margin: 0; }
.kd-box { padding: 10px 12px; border: 1px solid var(--k-line); border-radius: 8px; background: var(--k-paper2); display: grid; gap: 6px; }
.kd-quote { font-size: 20px; font-weight: 600; margin: 0; padding: 0; border: 0; }
.kd-checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.kd-checks li { display: flex; align-items: baseline; gap: 8px; margin: 0; min-width: 0; }
.kd-checks li::before { content: "•"; width: 1em; flex: none; text-align: center; color: var(--k-ink2); font-weight: 700; }
.kd-checks li[data-s="ok"]::before { content: "✓"; color: var(--k-ok); }
.kd-checks li[data-s="bad"]::before { content: "✗"; color: var(--k-bad); }
.kd-badge { display: inline-block; font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
.kd-badge[data-s="ok"] { color: var(--k-ok); } .kd-badge[data-s="bad"] { color: var(--k-bad); } .kd-badge[data-s="wait"] { color: var(--k-ink2); }
.kd-pills { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; list-style: none; }
.kd-pills li { margin: 0; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--k-line); background: var(--k-paper2); font-size: 13px; }
.kd-big { font-size: 44px; line-height: 1; font-weight: 700; letter-spacing: -.02em; }
.kd-big small { font-size: 16px; font-weight: 600; color: var(--k-ink2); letter-spacing: 0; }
.kd-sides { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.kd-sides > div { display: grid; gap: 4px; }
.kd-fine { font-size: 12px; color: var(--k-ink2); }
.kd .kd-fine.k-num, .kd .kd-row > .k-num { white-space: normal; }
.kd-mark { font-size: 13px; color: var(--k-ink2); margin: -6px 0 14px; }
.kd-seller[data-s="bad"] { border-color: var(--k-bad); } .kd-big .kd-apart { color: var(--k-bad); }
.kd-say { margin: 14px 0 12px; font-size: 17px; font-weight: 600; min-height: 2.6em; }
.kd-act { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.kd .kd-act button { margin: 0; }
.kd-src { margin: 14px 0 0; font-size: 12px; color: var(--k-ink2); }
.kd-token { width: 14px; height: 14px; border-radius: 50%; background: var(--accent, #2b3bb5); box-shadow: 0 0 0 4px rgba(127,127,127,.18); }
.kd-raven { width: 28px; height: 28px; color: var(--accent, #2b3bb5); }
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
  const state = { step: 0, done: STEPS.map(() => false), run: 0 };
  const BAD = [false, true, false, false, true, true];
  const READ = [false, true, false, false, false, true];          // a step that shows something to read before its action
  const day = String(d.date).replace(/^(\d+ \w{3})\w*/, "$1"), where = d.ids === "public" ? "public program ids" : "staging program ids";

  el.classList.add("kd", "k-card");
  el.setAttribute("role", "group");
  el.setAttribute("aria-label", "One round, step by step");
  el.innerHTML = `
    <div class="kd-top"><p class="k-kicker">One round. You drive.</p><p class="kd-keys" aria-hidden="true">Enter: act · arrows: steps · Esc: start over</p></div>
    <p class="kd-mark" data-ids="${esc(d.ids || "staging")}">A replay of a real round on ${esc(d.cluster)} (${esc(where)}, ${esc(day)}).</p>
    <ol class="kd-steps">${STEPS.map((s, i) => `<li><button type="button" class="k-step" data-step="${i}" data-state="idle"><i>${i + 1}</i><span>${esc(s)}</span></button></li>`).join("")}</ol>
    <ul class="kd-rail k-stage" aria-hidden="true">${["Buyer", "GitHub", "Solana", "Seller"].map((n) => `<li class="kd-node" data-node="${n.toLowerCase()}"><b></b><span>${n}</span><em class="k-num"></em></li>`).join("")}</ul>
    <div class="kd-scene"></div>
    <p class="kd-say" role="status" aria-live="polite"></p>
    <div class="kd-act"><button type="button" class="k-btn kd-go"></button><button type="button" class="k-btn quiet ghost kd-reset" hidden>Start over</button></div>
    <p class="kd-src">Sources:
      <a href="${REPO}docs/CAPABILITIES.md#the-0314-rehearsal-on-devnet">rehearsal</a>, <a href="${REPO}docs/TAMPER.md">tamper benchmark</a>, <a href="${REPO}docs/RELAY.md">timing</a>.</p>`;
  const q = (s) => el.querySelector(s), node = (n) => q(`[data-node="${n}"]`);
  const scene = q(".kd-scene"), say = q(".kd-say"), go = q(".kd-go"), resetB = q(".kd-reset");

  // ---- what each step shows, before and after its one action ------------------------------------------------------
  const views = [
    (on) => ({
      html: `<label class="kd-tag" for="kd-comment">Comment on the issue</label>
        <input id="kd-comment" class="kd-input" type="text" readonly value="${esc(d.fund.comment)}">
        ${on ? `<div class="kd-box"><div class="kd-row"><span class="kd-tag">Order</span><span class="kd-mono">${esc(short(d.fund.order))}</span><span class="kd-badge" data-s="ok">funded</span></div>
          <div class="kd-row"><span class="k-num"><strong>${esc(d.fund.amount)}</strong> ${esc(d.money)} held</span><span class="kd-fine k-num">fee ${esc(d.fund.fee)}</span>${tx(d.fund.tx, "transaction")}</div></div>` : ""}`,
      say: on ? `Order funded: ${d.fund.amount} ${d.money} held, fee ${d.fund.fee}.` : "Press Enter to post the funding comment.",
      act: "Post the comment",
    }),
    (on) => ({
      html: `<div class="kd-box"><div class="kd-row"><span class="kd-tag">Pull request</span><span>${esc(d.claim.pull)}</span></div>
          <blockquote class="kd-quote">“${esc(d.claim.says)}”</blockquote></div>
        <ul class="kd-checks"><li data-s="${on ? "bad" : "wait"}"><span class="kd-mono">${esc(check)}</span><span class="kd-badge" data-s="${on ? "bad" : "wait"}">${on ? "failed" : "not read"}</span></li></ul>
        ${on ? `<p class="kd-row kd-verdict"><span class="kd-badge" data-s="bad">Refused</span><span class="kd-fine k-num">${esc(d.claim.failed)} of ${esc(d.claim.of)} first agent pull requests: a failed check.</span></p>` : ""}`,
      say: on ? `Refused: ${test} failed.` : "An agent's pull request says its tests pass.",
      act: "Check the claim",
    }),
    (on) => ({
      html: `<ul class="kd-checks">${[["CI", d.fixed.ci], ["Knos, tests", d.fixed.tests], ["Knos, black box", d.fixed.black_box]].map(([n, v]) =>
        `<li data-s="${on ? "ok" : "wait"}"><span>${esc(n)}</span><span class="kd-badge" data-s="${on ? "ok" : "wait"}">${on ? esc(v) : "waiting"}</span></li>`).join("")}</ul>
        ${on ? `<div class="kd-box"><div class="kd-row"><span class="kd-tag">Signed by GitHub</span><span class="kd-badge" data-s="ok">signed</span></div>
          <ul class="kd-pills">${d.fixed.claims.map((c) => `<li>${esc(c.is)} <span class="kd-mono">${esc(c.name)}</span></li>`).join("")}</ul></div>` : ""}`,
      say: on ? "Checks pass. GitHub signs the repository, commit and workflow." : "The agent pushes a fix.",
      act: "Push the fix",
    }),
    (on) => ({
      html: `<p class="kd-big"><span class="k-num kd-secs" data-to="${on ? d.paid.seconds : 0}">${on ? esc(d.paid.seconds) : 0}</span> <small>seconds</small></p>
        <p class="kd-fine k-num">Merge to paid, median of ${esc(d.paid.payments)} payments.</p>
        ${on ? `<p class="kd-row"><span class="kd-badge" data-s="ok">Paid</span><span class="k-num"><strong>${esc(d.paid.amount)}</strong> ${esc(d.money)}</span>${tx(d.paid.tx, "See it on the explorer")}</p>` : ""}`,
      say: on ? `Paid ${d.paid.amount} ${d.money}. Median wait: ${d.paid.seconds} seconds.` : "Send the signed token to the Solana program.",
      act: "Pay",
    }),
    (on) => ({
      html: `<div class="kd-box kd-shake"><div class="kd-row"><span class="kd-tag">Pay token</span><span class="kd-badge" data-s="${on ? "bad" : "wait"}">${on ? "Refused: already paid" : "used once"}</span></div>
          ${on ? `<p class="kd-fine k-num">Error ${esc(d.replay.error)}: ${esc(d.replay.means)}. ${tx(d.replay.tx, "transaction")}</p>` : ""}</div>`,
      say: on ? `Refused: already paid. Error ${d.replay.error}.` : "Send the same token a second time.",
      act: "Send the same token again",
    }),
    (on) => ({
      html: `<div class="kd-sides"><div class="kd-box"><span class="kd-tag">Buyer counted</span><span class="kd-big k-num kd-buyer">${thousands(d.count.buyer)}</span>
            <span class="kd-fine">${d.count.buyer_tx.map((t, n) => tx(t, `batch ${n + 1}`)).join(" ")}</span></div>
          <div class="kd-box kd-seller" data-s="${on ? "bad" : ""}"><span class="kd-tag">Seller counted</span><span class="kd-big k-num">${thousands(d.count.seller)}${on ? ` <small class="kd-apart">+${esc(d.count.apart)}</small>` : ""}</span>
            <span class="kd-fine">${d.count.seller_tx.map((t, n) => tx(t, `claim ${n + 1}`)).join(" ")}</span></div></div>
        <p class="kd-row"><span class="kd-tag">The month</span><span class="kd-badge kd-row-state" data-s="${on ? "bad" : "wait"}">${on ? "disputed" : "not compared"}</span>
          ${on ? `<span class="kd-fine k-num">${esc(d.count.apart)} the buyer's ledger left out, each named.</span>` : ""}</p>`,
      say: on ? `Disputed: the buyer's ledger left out ${d.count.apart} evaluations.` : `Buyer counted ${thousands(d.count.buyer)}. Seller counted ${thousands(d.count.seller)}.`,
      act: "Compare the two counts",
    }),
  ];

  function draw() {
    const i = state.step, on = state.done[i], v = views[i](on);
    state.run += 1;
    const inside = scene.contains(document.activeElement);
    scene.innerHTML = v.html;
    scene.setAttribute("aria-label", `Step ${i + 1} of ${STEPS.length}: ${STEPS[i]}`);
    scene.setAttribute("role", "group");
    say.textContent = v.say;
    const next = i + 1, straight = next < STEPS.length && !READ[next] && !state.done[next];          // the next step needs no reading: one key does it
    go.textContent = !on ? v.act : next >= STEPS.length ? "Start over" : straight ? views[next](false).act : `Next: ${STEPS[next]}`;
    resetB.hidden = !(state.done.some(Boolean) || i > 0) || (on && i === STEPS.length - 1);
    el.querySelectorAll(".k-step").forEach((b, k) => {
      b.dataset.state = state.done[k] ? (BAD[k] ? "bad" : "done") : k === i ? "live" : "idle";
      if (k === i) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
      b.setAttribute("aria-label", `Step ${k + 1}: ${STEPS[k]}${state.done[k] ? (BAD[k] ? ", refused" : ", done") : ""}`);
    });
    const [funded, , signed, paid, replayed] = state.done;
    const set = (n, s, text) => { node(n).dataset.s = s; node(n).querySelector("em").textContent = text; };
    set("buyer", funded ? "ok" : i === 0 ? "on" : "", "");
    set("github", state.done[1] && !signed ? "bad" : signed ? "ok" : i === 1 || i === 2 ? "on" : "", signed ? "signed" : state.done[1] ? "1 failed" : "");
    set("solana", replayed && i === 4 ? "bad" : funded || paid ? "ok" : i === 3 ? "on" : "", replayed && i === 4 ? "refused" : paid ? "0.00 held" : funded ? `${d.fund.amount} held` : "");
    set("seller", paid ? "ok" : "", paid ? `+${d.paid.amount}` : "");
    if (inside) go.focus({ preventScroll: true });
  }

  // ---- the movement that explains a change; the change itself is already drawn ---------------------------------------
  function move(i) {
    if (reduced()) return;
    const run = state.run;
    if (i === 0) fly(token(), node("buyer").querySelector("b"), node("solana").querySelector("b"), DUR[2]);
    if (i === 3) {
      const secs = q(".kd-secs"), to = Number(secs.dataset.to), t0 = performance.now();
      secs.textContent = "0";
      const tick = (t) => {
        if (state.run !== run || !secs.isConnected) return;
        const p = Math.min(1, (t - t0) / (DUR[2] * 2));
        secs.textContent = String(Math.round(to * p));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      fly(token(), node("github").querySelector("b"), node("solana").querySelector("b"), DUR[1]).then(() => {
        if (state.run !== run) return;
        const a = node("solana").querySelector("b"), b = node("seller").querySelector("b");
        if (motion?.raven) { try { motion.raven(a, b); } catch { /* the payment is drawn either way */ } } else fly(ravenMark(), a, b, DUR[2]);
      });
    }
    if (i === 4) fly(token(), node("github").querySelector("b"), node("solana").querySelector("b"), DUR[1]).then(() => {
      if (state.run !== run) return;
      q(".kd-shake")?.animate([{ transform: "translateX(0)" }, { transform: "translateX(-6px)" }, { transform: "translateX(6px)" }, { transform: "translateX(-3px)" },
        { transform: "translateX(0)" }], { duration: DUR[1], easing: EASE });
    });
  }

  const goTo = (i) => { state.step = Math.max(0, Math.min(STEPS.length - 1, i)); draw(); };
  const reset = () => { state.step = 0; state.done.fill(false); draw(); go.focus({ preventScroll: true }); };
  function primary() {
    const i = state.step;
    const act = (k) => { state.done[k] = true; draw(); move(k); };
    if (!state.done[i]) return act(i);
    if (i >= STEPS.length - 1) return reset();
    state.step = i + 1;
    if (!READ[i + 1] && !state.done[i + 1]) act(i + 1); else draw();
  }

  go.addEventListener("click", primary);
  resetB.addEventListener("click", reset);
  el.querySelector(".kd-steps").addEventListener("click", (e) => { const b = e.target.closest(".k-step"); if (b) goTo(Number(b.dataset.step)); });
  el.addEventListener("keydown", (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const t = e.target, native = t.closest?.("button, a");
    if (e.key === "Escape") { e.preventDefault(); reset(); }
    else if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); goTo(state.step + 1); if (t.closest?.(".k-step")) el.querySelector(`[data-step="${state.step}"]`).focus(); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); goTo(state.step - 1); if (t.closest?.(".k-step")) el.querySelector(`[data-step="${state.step}"]`).focus(); }
    else if ((e.key === "Enter" || e.key === " ") && !native) { e.preventDefault(); primary(); }
  });

  el.hidden = false;
  draw();
  return { state, goTo, reset, primary };
}
