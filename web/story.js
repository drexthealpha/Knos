// The story on one page: the number, the three-minute demonstration in seven beats that play in order, and what the
// project needs next. docs/STORY.md says the same seven beats with the same evidence (tests/web/story.mjs holds the two
// together), docs/submission/demo_script.md is the same seven, timed, and the first screen's round (web/demo.js) plays
// them under the same names: Agree, Fails, Passes, Statement, Replay, Pay, Verify.
//
//   renderStory(el[, ctx])   draws it into el. ctx: { repo, front, merged, failed, reduced }, each optional
//   storyHtml(ctx)           the same as text, for a test with no browser
//   play(root[, opts])       beats go idle -> live -> done (a refusal: bad), one after the other; resolves when the last has
//
// Each beat is a card (.k-step under .story-steps, drawn by web/app.css): numbered, dim until it plays, lifted while it
// is live, then settled green, or red with one shake for the refusal. The first screen is the sentence, the number and
// the seven cards: what the project needs next waits in a fold under them (the page's first screen says 40 words at most).
// Every beat is in the page from the start, so a reader who asked for no movement sees all seven, in their last state,
// and nothing moves. Nothing is requested from any host: the evidence is links, and the reader follows them or not.
// A beat whose evidence ran on staging program ids says so beside its link (`staging`), until a run on the public
// program ids replaces it.
import { prefersReduced } from "./motion.js";

export const SENTENCE = "The neutral meter for AI agent work: neither side keeps the count.";
export const MERGED = 241, FAILED = 30;            // docs/backtest.json, sample.merged.overall (tests/web/story.mjs compares)
export const REPO = "https://github.com/drexthealpha/Knos/blob/main/";
export const FRONT = "https://drexthealpha.github.io/Knos/";
const TX = "https://explorer.solana.com/tx/";
export const STEP_MS = 480;                         // --dur-3: how long a step is live before the next one starts

// `ends`: the state a step rests in. `path` is a file of the repository; `url` is a transaction: the three are those of
// web/demo_data.json, the round at the public program ids (tests/web/story.mjs compares). `staging`: a transaction that
// ran on staging program ids instead; none does today.
export const STAGING = "Staging program ids";
export const STEPS = [
  { title: "Buyer and supplier agree one task.", says: "Price and acceptance terms come first.", ends: "done",
    evidence: "The funding transaction (devnet, public program ids)", url: `${TX}177CEpZ8N4r5CGNjSEWBEouTTqMDwAao9LFzwSNYiFjJZUfJdtLDeusHbmmawWxzKLp1SozNAyNCEeGxSvvBm5s?cluster=devnet` },
  { title: "A claimed success fails the condition.", says: "Payment is withheld, with the reason.", ends: "bad",
    evidence: "The tamper benchmark", path: "docs/TAMPER.md" },
  { title: "Valid work passes.", says: "The corrected submission meets the same check.", ends: "done",
    evidence: "The test that accepts correct work", path: "tests/test_tamper_bench.py" },
  { title: "Both sides make the same statement.", says: "Two independent records reconcile.", ends: "done",
    evidence: "The test that reconciles two ledgers", path: "tests/test_ledger.py" },
  { title: "A replay pays nothing.", says: "No second payment.", ends: "done",
    evidence: "The refused replay (devnet, public program ids)", url: `${TX}4hCf7a3FpKiTexPUxX4jvPbYUUQMvgHmyjHSVjbUJ2yqe3srzxLJrsZ8QY4dpT2pt4VFSRJ4j4kQMwEcapvk3Rrp?cluster=devnet` },
  { title: "The payment executes.", says: "The supplier gets a portable receipt.", ends: "done",
    evidence: "The paying transaction (devnet, public program ids)", url: `${TX}59AfaYHTvWHhbAhiiNHCbCfEcGCxG1kCydJwfRNjZqry9bCnMF3ox6bd4P7favA9hjgzB5nk283g2Mdq3LruyNWV?cluster=devnet` },
  { title: "A verifier checks it offline.", says: "The deployment identity is one page.", ends: "done",
    evidence: "The release manifest", path: "docs/MANIFEST.md" },
];
export const NEXT = "Check your own invoice";      // after the last beat: the reader's own invoice, at the front door

// What the project needs next. Each is a need: none of the three exists.
export const ASK = [
  "Needed: an outside key holder for both multisigs. Nobody has been asked.",
  "Needed: first buyers to run a shadow count. None has run.",
  "Needed: an outside review of the programs. None is commissioned.",
];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const linkOf = (step, ctx = {}) => step.url || (ctx.repo || REPO) + step.path;

/** The page as text. With `ctx.reduced` every step is already in its last state. */
export function storyHtml(ctx = {}) {
  const merged = ctx.merged ?? MERGED, failed = ctx.failed ?? FAILED;
  const steps = STEPS.map((s, i) => `<li class="k-step" data-step="${i + 1}" data-ends="${s.ends}" data-state="${ctx.reduced ? s.ends : "idle"}">`
    + `<strong>${esc(s.title)}</strong> <span>${esc(s.says)}</span><br>`
    + `<a href="${esc(linkOf(s, ctx))}" target="_blank" rel="noopener">${esc(s.evidence)}</a>`
    + `${s.staging ? ` <small class="story-staging">${esc(STAGING)}</small>` : ""}</li>`).join("");
  return `<p class="k-kicker">${esc(SENTENCE)}</p>`
    + `<h2>One task, seven steps</h2>`
    + `<p class="story-number"><strong class="k-num">${esc(merged)}</strong> merged agent “tests pass” pull requests: <strong class="k-num">${esc(failed)}</strong> had a failed check.</p>`
    + `<ol class="story-steps k-stage" aria-label="The demonstration in seven steps" data-not-prose data-keep>${steps}</ol>`
    + `<p><a class="k-btn story-next" href="${esc(ctx.front || FRONT)}">${esc(NEXT)}</a> <button type="button" class="k-btn quiet story-play"${ctx.reduced ? " hidden" : ""}>Play again</button></p>`
    + `<details class="k-more story-ask-fold"><summary>The ask: three needs</summary><ol class="story-ask" data-keep>${ASK.map((a) => `<li>${esc(a)}</li>`).join("")}</ol></details>`;
}

/** Plays the steps under `root` in order. `wait(ms)` is the clock (a test passes its own). Resolves when the last step
 *  rests. A second call while one runs takes over: the first stops at its next step. */
export async function play(root, { wait = (ms) => new Promise((r) => setTimeout(r, ms)), ms = STEP_MS } = {}) {
  const steps = [...root.querySelectorAll(".k-step")], run = (root.storyRun = (root.storyRun || 0) + 1);
  for (const li of steps) li.dataset.state = "idle";
  for (const li of steps) {
    if (root.storyRun !== run) return false;
    li.dataset.state = "live";
    await wait(ms);
    if (root.storyRun !== run) return false;
    li.dataset.state = li.dataset.ends;
  }
  return true;
}

// The cards' look. It is put in the page's head once (never in the story's own markup, which carries no style): a beat is
// a .k-step whose dot is its number; idle it is dim, live it lifts and takes the accent, done its number turns green,
// and the refusal turns red and shakes once (web/app.css .k-step). Nothing loops; with reduced motion nothing moves.
export const STYLE = `.story-number { font-size: var(--s2); color: var(--ink-2); margin: 0 0 20px; } .story-number .k-num { color: var(--ink); }
.story-steps { list-style: none; padding: 0; margin: 0 0 24px; display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); counter-reset: beat; }
.story-steps > .k-step { counter-increment: beat; min-width: 0; padding: 16px 18px 16px 56px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--card); color: var(--ink);
overflow-wrap: anywhere; transition: opacity var(--dur-2) var(--ease), border-color var(--dur-2) var(--ease), box-shadow var(--dur-2) var(--ease), translate var(--dur-2) var(--ease); }
.story-steps > .k-step::before { content: counter(beat); left: 16px; top: 15px; width: 26px; height: 26px; display: grid; place-items: center; border-width: 1.5px; font: 600 13px/1 var(--text); color: var(--ink-2);
font-variant-numeric: tabular-nums; }
.story-steps > .k-step::after { display: none; }
.story-steps > .k-step:last-child { padding-bottom: 16px; }
.story-steps > .k-step strong { display: block; margin: 0 0 2px; }
.story-steps > .k-step span { color: var(--ink-2); }
.story-steps > .k-step a { display: inline-block; margin-top: 8px; font-size: var(--s0); }
.story-steps > .k-step .story-staging { display: block; color: var(--ink-2); font-size: var(--s-1); }
.story-steps > .k-step[data-state="idle"] { opacity: .5; }
.story-steps > .k-step[data-state="live"] { border-color: var(--accent); box-shadow: var(--depth-2); translate: 0 -2px; }
.story-steps > .k-step[data-state="live"]::before { color: var(--accent); }
.story-steps > .k-step[data-state="done"]::before { color: var(--paper); }
.story-steps > .k-step[data-state="bad"] { border-color: color-mix(in srgb, var(--bad) 60%, var(--line)); }
.story-steps > .k-step[data-state="bad"] strong { color: var(--bad); }
.story-steps > .k-step[data-state="bad"]::before { color: var(--paper); }
.story-ask { margin: 4px 0 0; padding-left: 1.3em; }
@media (prefers-reduced-motion: reduce) { .story-steps > .k-step { transition: none; } }`;

/** Draws the story into `el`. It plays once when it comes into view, and again when the reader asks. */
export function renderStory(el, ctx = {}) {
  if (!el) return null;
  const reduced = ctx.reduced ?? prefersReduced();
  const doc = el.ownerDocument;
  if (doc && !doc.getElementById("story-style")) { const st = doc.createElement("style"); st.id = "story-style"; st.textContent = STYLE; doc.head.appendChild(st); }
  el.innerHTML = storyHtml({ ...ctx, reduced });
  if (reduced) return el;
  const start = () => play(el, ctx);
  el.querySelector(".story-play").addEventListener("click", start);
  if (typeof IntersectionObserver === "undefined") start();
  else {
    const seen = new IntersectionObserver((list) => { if (list.some((e) => e.isIntersecting)) { seen.disconnect(); start(); } }, { threshold: 0.2 });
    seen.observe(el);
  }
  return el;
}
