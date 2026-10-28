// Proposed terms, as a short list the reader can accept: used by the front door ("Install the meter"), the Console
// ("Offers") and the Terms page. web/propose_terms.js reads the repository (GitHub's public API, no sign-in) and is
// asked for only when somebody presses; this file draws what it answers.
//
//   renderProposal(el, repo[, env])   draws into `el`; resolves to the proposal, or null when nothing is proposed
//   termsFileLink(proposal[, branch]) GitHub's new-file page of that repository with .knos/terms.json filled in
//   derived(proposal)                 the fields read from the repository itself (the rest are the template's defaults)
//
// What is drawn: a pending line at once; then the date of the last merge (nothing is proposed for a repository with no
// merge in 30 days: propose_terms.js refuses and the page says why), each answer with the line that says where it came
// from, the answers the repository itself gave first and the template's defaults behind a fold; one button that opens
// GitHub's new-file page with .knos/terms.json prefilled (nothing is written until the reader commits it there), one
// that copies the comment that funds an order on these terms. env: { propose, proposeEnv } stand in for the reader in
// tests, { branch } the branch the file goes to (GitHub's HEAD is the default branch), { install } a link to the
// workflow file, { onAccept(proposal) } called when either button is pressed, { copy(text) }.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ticked = (s) => esc(s).replace(/`([^`]*)`/g, "<code>$1</code>");
const QUESTIONS = { deliverable: "One deliverable", evidence: "Whose signature counts", checks: "What decides", window: "Reopened for", changes: "What may change",
  dispute: "Who may appeal", evaluators: "Who judges", price: "What it pays", deadline: "When it ends", policy: "Who changes terms" };
const ORDER = ["checks", "changes", "policy", "evaluators", "deliverable", "price", "deadline", "window", "dispute", "evidence"];
const STYLE = `.pt{display:grid;gap:10px;min-width:0;margin:16px 0 8px;padding:16px;border:1px solid var(--line);border-radius:var(--radius,12px);background:var(--paper-2)}
.pt[hidden]{display:none}.pt>*{margin:0;min-width:0}.pt ol{list-style:none;padding:0;display:grid;gap:0}
.pt li{display:grid;grid-template-columns:minmax(0,9.5em) minmax(0,1fr);gap:2px 16px;padding:10px 0;border-top:1px solid var(--line);overflow-wrap:anywhere}
.pt li strong{font-weight:600;color:var(--ink)}.pt li span{color:var(--ink)}.pt li small{grid-column:2;color:var(--ink-2);font-size:var(--s-1,13px);line-height:1.45}
.pt li small::before{content:"From: ";font-weight:600}
.pt .pt-act{display:flex;flex-wrap:wrap;gap:10px 12px;align-items:center}.pt .pt-act .k-btn{margin:0}
.pt pre{margin:0;overflow-x:auto;max-width:100%;white-space:pre-wrap;overflow-wrap:anywhere}
.pt details.k-more{margin:0}.pt details.k-more>ol{max-width:none}
@media (max-width:520px){.pt li{grid-template-columns:minmax(0,1fr)}.pt li small{grid-column:1}}
@media (prefers-reduced-motion:no-preference){.pt[data-state=done] li{animation:pt-in var(--dur-2,240ms) var(--ease,ease-out) both;animation-delay:calc(var(--i,0)*40ms)}}
@keyframes pt-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}`;

/** The fields whose answer was read from the repository itself: every other one is the template's default. */
export const derived = (proposal) => ORDER.filter((f) => !(proposal.from[f] || []).every((s) => /^Template default/.test(s)));
/** GitHub's new-file page for the terms file: the reader reviews it there and commits it, or does not. */
export function termsFileLink(proposal, branch = "HEAD") {
  const q = encodeURIComponent, value = `${JSON.stringify(proposal.terms, null, 2)}\n`;
  return `https://github.com/${proposal.repo.split("/").map(q).join("/")}/new/${String(branch).split("/").map(q).join("/")}?filename=${q(proposal.file)}&value=${q(value)}`;
}
// Why nothing is proposed, in the page's twelve words: propose_terms.js says it at the length the command line does.
export function refusal(why) {
  const m = String((why && why.message) || ""), stale = /last merged a pull request on (\S+), (\d+) days ago/.exec(m);
  if (stale) return `Last merge: ${stale[1]}, ${stale[2]} days ago. Nothing proposed after 30 days.`;
  if (/^Name the repository/.test(m)) return "Name it as owner/name.";
  if (/was not found/.test(m)) return "Not found. Only a public repository is read.";
  if (/no merged pull request/.test(m)) return "No merged pull request there. Nothing proposed.";
  if (/60 answers an hour|rate limit|403/.test(m)) return "GitHub's hourly limit reached. Try again in an hour.";
  return "GitHub gave no answer. Try again.";
}
const line = (proposal, f, i) => `<li data-field="${f}" style="--i:${i}"><strong>${esc(QUESTIONS[f])}</strong><span>${ticked(proposal.terms[f]?.says || "")}</span><small>${ticked((proposal.from[f] || [])[0] || "")}</small></li>`;

export async function renderProposal(el, repo, env = {}) {
  const doc = el.ownerDocument;
  if (!doc.getElementById("pt-style")) { const s = doc.createElement("style"); s.id = "pt-style"; s.textContent = STYLE; doc.head.appendChild(s); }
  el.classList.add("pt"); el.hidden = false; el.dataset.state = "wait"; el.setAttribute("data-keep", "");
  el.innerHTML = `<p data-pt="said" role="status" aria-live="polite">Reading ${esc(String(repo).trim() || "the repository")}.</p>`;      // the pending state, at once
  let proposal;
  try {
    const run = env.propose || (await import("./propose_terms.js")).proposeTerms;
    proposal = await run(repo, env.proposeEnv || {});
  } catch (why) {
    el.dataset.state = "error";
    el.querySelector('[data-pt="said"]').textContent = refusal(why);
    return null;
  }
  const own = derived(proposal), rest = ORDER.filter((f) => !own.includes(f)), day = String(proposal.last_merge).slice(0, 10);
  el.innerHTML = `<p class="k-kicker">Proposed terms for ${esc(proposal.repo)}</p>
    <p data-pt="said" role="status" aria-live="polite">Draft from ${esc(proposal.merges)} merges. Last merge: ${esc(day)}.</p>
    <ol data-pt="own" class="pt-list" data-not-prose>${own.map((f, i) => line(proposal, f, i)).join("")}</ol>
    ${rest.length ? `<details class="k-more"><summary>${rest.length} template defaults</summary><ol data-pt="rest" class="pt-list" data-not-prose>${rest.map((f, i) => line(proposal, f, i)).join("")}</ol></details>` : ""}
    <p class="pt-act"><a class="k-btn" data-pt="file" href="${esc(termsFileLink(proposal, env.branch))}" target="_blank" rel="noopener">Accept on GitHub</a>
      <button type="button" class="k-btn quiet" data-pt="comment">Copy the fund comment</button>
      ${env.install ? `<a data-pt="install" href="${esc(env.install)}" target="_blank" rel="noopener">Add the workflow</a>` : ""}</p>
    <pre data-pt="line" hidden><code></code></pre>
    <p class="fine">Nothing is written until you commit the file.</p>`;
  el.dataset.state = "done"; el.dataset.repo = proposal.repo; el.dataset.hash = proposal.hash;
  const button = el.querySelector('[data-pt="comment"]'), shown = el.querySelector('[data-pt="line"]');
  const copy = env.copy || ((text) => doc.defaultView.navigator.clipboard.writeText(text));
  button.addEventListener("click", async () => {
    shown.hidden = false; shown.firstElementChild.textContent = proposal.comment;      // what is copied stays in view: a clipboard that refuses leaves it to select
    button.textContent = "Copying";
    try { await copy(proposal.comment); button.textContent = "Comment copied"; } catch { button.textContent = "Select it below"; }
    env.onAccept?.(proposal, "comment");
  });
  el.querySelector('[data-pt="file"]').addEventListener("click", () => env.onAccept?.(proposal, "file"));
  return proposal;
}
