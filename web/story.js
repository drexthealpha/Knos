// The story on one page: the number, one round in eight steps that play in order, and what the project needs next.
// docs/STORY.md says the same eight steps with the same evidence (tests/web/story.mjs holds the two together).
//
//   renderStory(el[, ctx])   draws it into el. ctx: { repo, front, merged, failed, reduced }, each optional
//   storyHtml(ctx)           the same as text, for a test with no browser
//   play(root[, opts])       steps go idle -> live -> done (a refusal: bad), one after the other; resolves when the last has
//
// Every step is in the page from the start, so a reader who asked for no movement sees all eight, in their last state,
// and nothing moves. Nothing is requested from any host: the evidence is links, and the reader follows them or not.
import { prefersReduced } from "./motion.js";

export const SENTENCE = "The neutral meter for AI agent work: neither side keeps the count.";
export const MERGED = 241, FAILED = 30;            // docs/backtest.json, sample.merged.overall (tests/web/story.mjs compares)
export const REPO = "https://github.com/drexthealpha/Knos/blob/main/";
export const FRONT = "https://drexthealpha.github.io/Knos/";
const TX = "https://explorer.solana.com/tx/";
export const STEP_MS = 480;                         // --dur-3: how long a step is live before the next one starts

// `ends`: the state a step rests in. `path` is a file of the repository; `url` is a transaction or the site.
export const STEPS = [
  { title: "Buyer authorises.", says: "One comment fixes the budget and terms before work starts.", ends: "done",
    evidence: "The funding transaction (devnet, staging program ids)", url: `${TX}4zeX8845JQkkBgqvRqUgAYiMPNaSWQJsxDTGyayyKATQ1ZXeDTJDpuTrMzkCd4pT1E9rrbYHw6Z4vWRnb1FKhYCL?cluster=devnet` },
  { title: "Supplier submits.", says: "A correct fix arrives with its own regression test.", ends: "done",
    evidence: "The correct submissions and the test that runs them", path: "tests/test_tamper_bench.py" },
  { title: "Accepted under the original terms.", says: "The signed run pays the posted amount.", ends: "done",
    evidence: "The paying transaction (devnet, staging program ids)", url: `${TX}63wT5rhYhEKbgmF5k8vEKdexzoCaXZCiDvRG2GQMGSMBBsc9avGfDw3izER9D6LHoe4ucJeinTBiWaWGWpnFWvfq?cluster=devnet` },
  { title: "A tampered submission fails.", says: "All 63 cheating pull requests were refused.", ends: "bad",
    evidence: "The tamper benchmark", path: "docs/TAMPER.md" },
  { title: "A duplicate settlement changes nothing.", says: "The second try moves no money.", ends: "done",
    evidence: "The test that sends every accepted proof twice", path: "tests/test_double_pay.py" },
  { title: "Both sides rebuild the same record.", says: "Each ledger gives the same statement.", ends: "done",
    evidence: "The test that reconciles two ledgers", path: "tests/test_ledger.py" },
  { title: "Finance approves the agreed lines.", says: "The exception stays visible and unbilled.", ends: "done",
    evidence: "The four records and the exports", path: "docs/FINANCE.md" },
  { title: "Your invoice next.", says: "Paste it. Nobody has paid for this yet.", ends: "live",
    evidence: "Check your own invoice", url: FRONT },
];

// What the project needs next. Each is a need: none of the three exists.
export const ASK = [
  "Needed: an outside key holder for both multisigs. Nobody has been asked.",
  "Needed: first buyers to run a shadow count. None has run.",
  "Needed: an outside review of the programs. None is commissioned.",
];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const linkOf = (step, ctx = {}) => (step.url === FRONT ? ctx.front || FRONT : step.url || (ctx.repo || REPO) + step.path);

/** The page as text. With `ctx.reduced` every step is already in its last state. */
export function storyHtml(ctx = {}) {
  const merged = ctx.merged ?? MERGED, failed = ctx.failed ?? FAILED;
  const steps = STEPS.map((s, i) => `<li class="k-step" data-step="${i + 1}" data-ends="${s.ends}" data-state="${ctx.reduced ? s.ends : "idle"}">`
    + `<strong>${esc(s.title)}</strong> <span>${esc(s.says)}</span><br>`
    + `<a href="${esc(linkOf(s, ctx))}"${s.url === FRONT ? "" : ' target="_blank" rel="noopener"'}>${esc(s.evidence)}</a></li>`).join("");
  return `<p class="k-kicker">${esc(SENTENCE)}</p>`
    + `<h2>One round, eight steps</h2>`
    + `<p class="story-number"><strong class="k-num">${esc(merged)}</strong> merged agent “tests pass” pull requests: <strong class="k-num">${esc(failed)}</strong> had a failed check.</p>`
    + `<ol class="story-steps k-stage" aria-label="One round in eight steps" data-not-prose data-keep>${steps}</ol>`
    + `<p><button type="button" class="k-btn quiet story-play"${ctx.reduced ? " hidden" : ""}>Play again</button></p>`
    + `<h3>The ask</h3><ol class="story-ask">${ASK.map((a) => `<li>${esc(a)}</li>`).join("")}</ol>`;
}

/** Plays the steps under `root` in order. `wait(ms)` is the clock (a test passes its own). Resolves when the last step
 *  rests. A second call while one runs takes over: the first stops at its next step. */
export async function play(root, { wait = (ms) => new Promise((r) => setTimeout(r, ms)), ms = STEP_MS } = {}) {
  const steps = [...root.querySelectorAll(".k-step")], run = (root.storyRun = (root.storyRun || 0) + 1);
  for (const li of steps) li.dataset.state = "idle";
  for (const li of steps) {
    if (root.storyRun !== run) return false;
    li.dataset.state = "live";
    if (li.dataset.ends === "live") break;             // the last step is the reader's: it stays open
    await wait(ms);
    if (root.storyRun !== run) return false;
    li.dataset.state = li.dataset.ends;
  }
  return true;
}

/** Draws the story into `el`. It plays once when it comes into view, and again when the reader asks. */
export function renderStory(el, ctx = {}) {
  if (!el) return null;
  const reduced = ctx.reduced ?? prefersReduced();
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
