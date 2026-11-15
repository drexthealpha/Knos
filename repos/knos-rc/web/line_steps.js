// The four steps of one invoice line, as one compact row: policy satisfied -> parties accepted -> payment authorised ->
// settled (src/knos/ids.py STEPS; src/knos/statement.py steps_of). Each is recorded apart, so a line whose evidence
// met its policy is never shown as accepted, authorised or paid until someone did each.
//
//   stepRowHtml(steps)        the row, from [{ step, state: done | open | failed, said }] (statement.lines_now `steps`)
//   shadowSteps(row, decided) the steps of a front-door row (web/shadow.js), before any statement: the policy from the
//                             checks, and acceptance and authorisation once `decided` ({ by, on }) says who did them
//   markSteps(el, steps)      the same row brought up to date in place: a step that changes animates (app.css .k-step),
//                             the others stay still; with reduced motion the change is simply drawn
//   stepStyle(doc)            the row's few rules, added once
//
// Small on purpose: the front door loads it with its first screen.
export const STEPS = ["policy", "accepted", "authorised", "settled"];
export const STEP_SHORT = { policy: "Policy met", accepted: "Accepted", authorised: "Authorised", settled: "Settled" };
const SHORT_NOT = { policy: { failed: "Policy not met", open: "Policy unknown" }, accepted: { failed: "Refused" }, settled: { failed: "Refunded" } };
const short = (x) => (SHORT_NOT[x.step] && SHORT_NOT[x.step][x.state]) || STEP_SHORT[x.step];
export const STEP_WORDS = { policy: "policy satisfied", accepted: "parties accepted", authorised: "payment authorised", settled: "settled" };
const DRAWN = { done: "done", open: "idle", failed: "bad", owed: "live" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STYLE = `.ls-row{display:flex;flex-wrap:wrap;gap:4px 14px;margin:8px 0 8px;padding:0}
.ls-row .k-step{padding:0 0 0 18px;font-size:12px;line-height:1.5}.ls-row .k-step::before{left:0;top:4px;width:10px;height:10px}.ls-row .k-step::after{display:none}
.ls-row .k-step[data-state=bad]{animation:none}.ls-row .k-step[data-state=bad].ls-now{animation:k-shake var(--dur-2) linear 1}
.ls-row .k-step[data-state=idle]{color:var(--ink-2)}.ls-row .k-step.ls-now::before{transition-duration:var(--dur-3)}`;

export function stepStyle(doc) {
  if (!doc || doc.getElementById("ls-style")) return;
  const s = doc.createElement("style"); s.id = "ls-style"; s.textContent = STYLE; doc.head.appendChild(s);
}

const label = (x) => `${STEP_WORDS[x.step]}: ${x.state === "done" ? "yes" : x.state === "failed" ? "no" : "not yet"}${x.said ? `, ${x.said}` : ""}`;

/** The row of four steps. Each says its state in words to a screen reader, and in full on hover. */
export function stepRowHtml(steps) {
  return `<ol class="ls-row" data-steps aria-label="Four steps">${steps.map((x) => `<li class="k-step" data-step="${x.step}" data-state="${DRAWN[x.state] || "idle"}" title="${esc(label(x))}">`
    + `<span aria-hidden="true">${esc(short(x))}</span><span class="visually-hidden" style="position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)">${esc(label(x))}</span></li>`).join("")}</ol>`;
}

/** The steps of a front-door row: its checks decide the policy; `decided` ({ by, on }) is who accepted and authorised it here. */
export function shadowSteps(row, decided = null) {
  const met = row.class === "clean", unknown = row.class === "unverified" || row.class === "unreadable";
  const yes = met && decided ? "done" : "open", by = decided ? `${decided.by} on ${decided.on}` : "nobody yet";
  return [{ step: "policy", state: met ? "done" : unknown ? "open" : "failed", said: met ? "checks passed at merge" : row.why || row.class.replace(/_/g, " ") },
    { step: "accepted", state: yes, said: met ? by : "not for this line" }, { step: "authorised", state: yes, said: met ? by : "not for this line" },
    { step: "settled", state: "open", said: "not paid" }];
}

/** Bring a drawn row up to date: only the steps whose state changed are touched, and those animate once. */
export function markSteps(el, steps) {
  const row = el && el.querySelector("[data-steps]");
  if (!row) return;
  for (const x of steps) {
    const li = row.querySelector(`[data-step="${x.step}"]`), want = DRAWN[x.state] || "idle";
    if (!li) continue;
    li.title = label(x);
    li.firstElementChild.textContent = short(x);
    li.lastElementChild.textContent = label(x);
    if (li.dataset.state === want) continue;
    li.classList.remove("ls-now"); void li.offsetWidth;            // a second change replays the motion
    li.dataset.state = want; li.classList.add("ls-now");
  }
}
