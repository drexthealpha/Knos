// A round anyone can watch: the canary's latest round on devnet, as a timeline, and the next one as it happens.
//
// The canary (examples/knos-canary.yml, `knos canary`) runs on a timer in a repository kept for it. Each round opens an
// issue called "knos canary <stamp>" whose description funds it with test USDC, opens a pull request of the same name
// that closes it, merges it once its checks pass, and waits for Knos's comment that it was paid. Everything this page
// shows of a round is read from where it happened, by whoever is looking, with no account, wallet or repository:
//
//   GitHub (public API)   the issue and when it was opened; Knos's comment that the money is in escrow; the pull request,
//                         when it was opened and merged; the workflow runs at the merge commit; Knos's comment that it paid
//   Solana devnet         the transactions of the escrow account the funding comment links: when each was confirmed
//   this site             stats.json (the measured wait from merge to payment), operations.json (the canary's runs)
//
// THE FIVE STATES of the payment (received, accepted, submitted, confirmed, finalized: docs/RELAY.md) are shown by name
// under the timeline, each with the time Knos's workflow wrote into its one comment on the pull request (the line
// `knos-states`, which `knos settle` edits as each state is reached). A state not reached has no time.
//
// Every time shown is the time GitHub or devnet gives. A stage that has not happened has no time. A round older than
// two hours is shown as the last round with the sentence that the canary has not run since, never as something happening
// now. Nothing here is signed or sent.
import { cache as kept, ghKey, asOf, ago } from "./cache.js";

export const CANARY_REPO = "drexthealpha/knos-e2e";     // the repository examples/knos-canary.yml says Knos runs one in
export const EVERY = 30 * 60;           // seconds: the workflow's timer, `*/30 * * * *`
export const STALE = 2 * 3600;          // a round older than this is history, not "live"
export const ROUND_LIMIT = 20 * 60;     // the canary job's timeout-minutes: a round still unpaid after this did not finish
export const POLL = 30, WATCH_FOR = 20 * 60;       // seconds between looks while watching, and how long one press watches. GitHub gives a
                                                   // reader with no login 60 answers an hour: a look asks it one thing, two when a round starts
export const TITLE = /^knos canary (\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$/;      // src/knos/flow.py canary: the issue's and the pull request's title
const GITHUB = "https://api.github.com", DEVNET_RPC = "https://api.devnet.solana.com";

const ms = (iso) => { const t = Date.parse(iso || ""); return Number.isFinite(t) ? t : null; };
const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const clock = (t) => (t === null || t === undefined ? "" : `${new Date(t).toISOString().slice(0, 19).replace("T", " ")} UTC`);
// "48 s", "3 min 05 s": a stage's seconds as a person reads a stopwatch
export const took = (s) => (s === null || s === undefined ? "" : s < 120 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")} s`);
// when the timer is next due: the next half hour of the clock, UTC. GitHub may start it late.
export const nextDue = (now) => (Math.floor(now / (EVERY * 1000)) + 1) * EVERY * 1000;
const knosSays = (comments, ...marks) => (comments || []).find((c) => String(c.body || "").startsWith("Knos") && marks.some((m) => c.body.includes(m))) || null;
// the links to devnet's explorer a comment of Knos's carries: [{ kind: "tx" | "address", id, text }]
export const explorerLinks = (body) => [...String(body || "").matchAll(/\[([^\]]{1,80})\]\(https:\/\/explorer\.solana\.com\/(tx|address)\/([1-9A-HJ-NP-Za-km-z]{32,90})(?:\?cluster=devnet)?\)/g)]
  .map((m) => ({ text: m[1], kind: m[2], id: m[3] }));

// The five states of a payment, in order, and what each means in a few words (docs/RELAY.md has the table).
export const STATES = [["received", "the merge reached the workflow"], ["accepted", "terms checked, run signed"], ["submitted", "first transaction sent"],
  ["confirmed", "payment confirmed"], ["finalized", "cluster finalized it"]];
// What Knos's comment says of them: { since, received, accepted, submitted, confirmed, finalized (ms, or absent), tx } or null.
export function statesOf(body) {
  const m = /<!-- knos-states ([^\n]*)/.exec(String(body || ""));
  if (!m) return null;
  const out = {};
  for (const part of m[1].split(" ")) {
    const i = part.indexOf("="), key = part.slice(0, i), value = part.slice(i + 1);
    if (key === "tx" && /^[1-9A-HJ-NP-Za-km-z]{32,90}$/.test(value)) out.tx = value;
    else if ((key === "since" || STATES.some(([name]) => name === key)) && /^\d+(\.\d+)?$/.test(value)) out[key] = Math.round(Number(value) * 1000);
  }
  return out;
}
// the workflow run that signs: Knos's own, never the check
const signs = (r) => /settle|knos/i.test(`${r.name} ${r.path}`) && !/check/i.test(r.name || "");
const ENDED = ["paid.", "held for", "not paid", "nothing to pay", "stopped"];      // Knos's last words on a pull request (src/knos/flow.py canary)

// The newest round among a repository's issues (GitHub lists pull requests with them): { issue, pull } or null.
export function newestRound(items) {
  const rounds = (items || []).filter((i) => TITLE.test(i.title || ""));
  const issue = rounds.filter((i) => !i.pull_request).sort((a, b) => b.number - a.number)[0];
  if (!issue) return null;
  return { issue, pull: rounds.find((i) => i.pull_request && i.title === issue.title) || null };
}

// One round as stages, from what GitHub and devnet gave. Each stage: { id, name, at (ms, or null: not yet), seconds (since
// the stage before, or null), links: [{ text, href }], note }. `state`: paid | held | failed | running | unfinished.
export function roundOf({ issue, comments = [], pull = null, pullComments = [], runs = [], chain = [] }, now, explorer) {
  const link = (text, href) => ({ text, href });
  const started = ms(issue.created_at);
  const funded = knosSays(comments, "is in escrow"), refused = !funded && knosSays(comments, "nothing was funded", "not confirmed", "stopped");
  const escrow = explorerLinks(funded?.body).find((l) => l.kind === "address") || null;
  const paid = knosSays(pullComments, "paid.", "held for"), unpaid = !paid && knosSays(pullComments, "not paid", "nothing to pay", "stopped");
  const merged = ms(pull?.merged_at);
  // devnet's own times for the escrow account: its first transaction funded it, a later one paid it
  const onChain = [...chain].filter((s) => !s.err && s.blockTime).sort((a, b) => a.blockTime - b.blockTime);
  const fundTx = onChain[0] || null, payTx = merged && onChain.length > 1 && onChain.at(-1).blockTime * 1000 >= merged - 5000 ? onChain.at(-1) : null;
  const txs = explorerLinks(paid?.body).filter((l) => l.kind === "tx");
  // Knos's one comment on the pull request carries the five states from "received" on (it is edited, so its creation
  // is when the merge was received, not when it was paid)
  const said = statesOf((pullComments || []).map((c) => (String(c.body || "").startsWith("Knos") ? c.body : "")).reverse().find((b) => b.includes("knos-states")));
  const paidAt = payTx ? payTx.blockTime * 1000 : said?.confirmed ?? ms(paid?.created_at);
  const run = [...runs].sort((a, b) => (ms(a.run_started_at || a.created_at) ?? 0) - (ms(b.run_started_at || b.created_at) ?? 0))
    .find(signs) || runs[0] || null;
  const stages = [
    { id: "ask", name: "Issue opened, asking for 5 test USDC", at: started, links: [link(`issue #${issue.number}`, issue.html_url)] },
    { id: "fund", name: "In escrow on devnet", at: ms(funded?.created_at), links: [...(funded ? [link("funding comment", funded.html_url)] : []), ...(escrow ? [link("escrow account", explorer("address", escrow.id))] : []),
      ...(fundTx ? [link("funding transaction", explorer("tx", fundTx.signature))] : [])],
      note: fundTx ? `devnet confirmed it at ${clock(fundTx.blockTime * 1000)}` : refused ? String(refused.body).split("\n")[0].slice(0, 200) : "" },
    { id: "open", name: "Pull request opened", at: ms(pull?.created_at), links: pull ? [link(`pull request #${pull.number}`, pull.html_url)] : [] },
    { id: "merge", name: "Checks passed, merged", at: merged, links: [] },
    { id: "sign", name: "GitHub ran the workflow that signs", at: run ? ms(run.run_started_at || run.created_at) : null, links: run ? [link("the signed run", run.html_url)] : [],
      note: run ? (run.status === "completed" ? `finished: ${run.conclusion}` : "running") : "" },
    { id: "pay", name: paid && String(paid.body).startsWith("Knos: held for") ? "Held for the payee on devnet" : "Paid on devnet", at: paid || payTx ? paidAt : null,
      links: [...(paid ? [link("payment comment", paid.html_url)] : []), ...txs.map((t, i) => link(txs.length > 1 ? (i === txs.length - 1 ? "the payment" : "the verifier transaction") : "the transaction that verified and paid", explorer("tx", t.id))),
        ...(!txs.length && payTx ? [link("the payment", explorer("tx", payTx.signature))] : [])],
      note: payTx ? "the time devnet confirmed it" : paid && said?.confirmed ? "the time Knos's workflow recorded (devnet's own time was not read)" : paid ? "the time of Knos's comment (devnet's own time was not read)" : unpaid ? String(unpaid.body).split("\n")[0].slice(0, 200) : "" },
  ];
  // seconds: fund from the issue, open from the funding, merge from the pull request, sign and pay from the merge
  const since = { fund: "ask", open: "fund", merge: "open", sign: "merge", pay: "merge" }, by = Object.fromEntries(stages.map((s) => [s.id, s]));
  for (const s of stages) s.seconds = s.at !== null && since[s.id] && by[since[s.id]].at !== null ? Math.max(0, Math.round((s.at - by[since[s.id]].at) / 1000)) : null;
  const done = by.pay.at !== null, failed = !!(refused || unpaid) || (pull && pull.state === "closed" && !merged);
  const state = done ? (by.pay.name.startsWith("Held") ? "held" : "paid") : failed ? "failed" : now - started > ROUND_LIMIT * 1000 ? "unfinished" : "running";
  // the five states by name: each with the workflow's own time, and its seconds from the state before (received: from the merge)
  let before = merged;
  const states = STATES.map(([name, means]) => {
    const at = said && Number.isFinite(said[name]) ? said[name] : null;
    const row = { name, means, at, seconds: at !== null && before !== null ? Math.max(0, Math.round((at - before) / 1000)) : null };
    if (at !== null) before = at;
    return row;
  });
  return { number: issue.number, title: issue.title, started, state, stages, states, tx: said?.tx || null, escrow: escrow?.id || null, total: done ? Math.round((by.pay.at - started) / 1000) : null,
    mergeToPaid: done && merged ? by.pay.seconds : null, stale: now - started > STALE * 1000 };
}

// Read one round whole: the fewest requests that give every stage (4 of GitHub at most after the list, 1 of devnet).
export async function readRound(env, found) {
  const { gh, rpc, repo } = env, { issue, pull } = found;
  const [comments, pr, pullComments] = await Promise.all([gh(`/repos/${repo}/issues/${issue.number}/comments?per_page=100`),
    pull ? gh(`/repos/${repo}/pulls/${pull.number}`) : null, pull ? gh(`/repos/${repo}/issues/${pull.number}/comments?per_page=100`) : []]);
  const sha = pr?.merged_at ? pr.merge_commit_sha : null;
  const escrow = explorerLinks(knosSays(comments, "is in escrow")?.body).find((l) => l.kind === "address");
  const [runs, chain] = await Promise.all([
    sha ? gh(`/repos/${repo}/actions/runs?head_sha=${sha}&per_page=20`).then((r) => r.workflow_runs || [], () => []) : [],
    escrow ? rpc("getSignaturesForAddress", [escrow.id, { limit: 20, commitment: "confirmed" }]).then((r) => r || [], () => []) : []]);
  return { issue, comments, pull: pr, pullComments, runs, chain };
}

// A round in progress, looked at again: only what is still missing is asked for, one thing of GitHub at a look, and
// devnet for the escrow account's transactions once the funding comment has named it.
export async function advance(env, raw) {
  const { gh, rpc, repo } = env, r = { ...raw }, n = r.issue.number;
  const funded = knosSays(r.comments, "is in escrow");
  if (!funded) { r.comments = await gh(`/repos/${repo}/issues/${n}/comments?per_page=100`); return r; }
  const escrow = explorerLinks(funded.body).find((l) => l.kind === "address");
  if (escrow) r.chain = await rpc("getSignaturesForAddress", [escrow.id, { limit: 20, commitment: "confirmed" }]).then((x) => x || r.chain, () => r.chain);
  if (!r.pull) {
    const item = newestRound(await gh(`/repos/${repo}/issues?state=all&sort=created&direction=desc&per_page=20`))?.pull;
    if (item && item.title === r.issue.title) r.pull = { ...item, merged_at: item.pull_request?.merged_at ?? null };
    return r;
  }
  if (!r.pull.merged_at || !r.pull.merge_commit_sha) { r.pull = await gh(`/repos/${repo}/pulls/${r.pull.number}`); return r; }
  const askRuns = () => gh(`/repos/${repo}/actions/runs?head_sha=${r.pull.merge_commit_sha}&per_page=20`).then((x) => x.workflow_runs || [], () => r.runs);
  if (!r.runs.some(signs) && !r.askedRuns) { r.askedRuns = true; r.runs = await askRuns(); return r; }
  r.askedRuns = false;
  r.pullComments = await gh(`/repos/${repo}/issues/${r.pull.number}/comments?per_page=100`);
  // The round ends with this look when Knos has said its last word, and nothing looks again after that. GitHub may not
  // have listed the signing run when it was asked for (right after the merge), so it is asked for once more now: without
  // this the "signed" stage stayed without its time until the page was loaded again.
  if (!r.runs.some(signs) && knosSays(r.pullComments, ...ENDED)) r.runs = await askRuns();
  return r;
}

const STYLE = `.live-line{list-style:none;margin:12px 0;padding:0}.live-line li{position:relative;padding:0 0 14px 26px;border-left:2px solid var(--line,#ccc);margin-left:7px}
.live-line li:last-child{border-left-color:transparent}.live-line li::before{content:"";position:absolute;left:-8px;top:2px;width:12px;height:12px;border-radius:50%;background:var(--card,#fff);border:2px solid var(--line,#ccc)}
.live-line li[data-state="done"]::before{background:var(--ok,#17703f);border-color:var(--ok,#17703f)}.live-line li[data-state="now"]::before{border-color:var(--accent,#2b3bb5);animation:live-pulse 1.2s ease-in-out infinite}
.live-line li[data-state="failed"]::before{background:var(--bad,#b3261e);border-color:var(--bad,#b3261e)}.live-line li[data-state="wait"]{color:var(--muted,#666)}
.live-line .live-took{font-variant-numeric:tabular-nums;font-weight:600}
.live-states{list-style:none;margin:4px 0 12px;padding:0;display:flex;flex-wrap:wrap;gap:8px}.live-states li{flex:1 1 150px;min-width:0;padding:8px 10px;border:1px solid var(--line,#ccc);border-radius:var(--radius,8px)}
.live-states li[data-state="done"]{border-color:var(--ok,#17703f)}.live-states li[data-state="live"]{border-color:var(--accent,#2b3bb5)}.live-states li[data-state="bad"]{border-color:var(--bad,#b3261e)}
.live-states li[data-state="idle"]{color:var(--ink-2,var(--muted,#666))}.live-states strong{display:block}.live-states .k-num{font-variant-numeric:tabular-nums}@keyframes live-pulse{50%{transform:scale(1.35)}}@media (prefers-reduced-motion: reduce){.live-line li[data-state="now"]::before{animation:none}}`;

// The timeline of one round. The first stage with no time is the one in progress while the round runs: its seconds count
// up from the stage before it, by the clock, until GitHub or devnet gives its time.
export function timelineHtml(round, now, esc = escHtml) {
  const links = (s) => s.links.filter((l) => /^https:\/\/(github\.com|explorer\.solana\.com)\//.test(String(l.href)));      // GitHub's and the explorer's pages, nothing else
  const waiting = round.stages.findIndex((s) => s.at === null), ended = round.state === "paid" || round.state === "held";
  return `<ol class="live-line" id="live-line" data-round="${round.number}" data-state="${round.state}">${round.stages.map((s, i) => {
    const state = s.at !== null ? "done" : ended ? "wait" : i !== waiting ? "wait" : round.state === "running" ? "now" : "failed";
    const before = round.stages.slice(0, i).reverse().find((x) => x.at !== null);
    const right = s.at !== null ? `${esc(clock(s.at))}${s.seconds !== null ? `, <span class="live-took">${esc(took(s.seconds))}</span>` : ""}`
      : state === "now" && before ? `<span class="live-took" data-since="${before.at}">${esc(took(Math.max(0, (now - before.at) / 1000)))}</span> so far`
      : state === "failed" ? "did not happen" : ended ? "not read" : "not yet";
    return `<li data-stage="${s.id}" data-state="${state}"><strong>${esc(s.name)}</strong> <span class="fine">${right}</span>
      ${links(s).length ? `<br>${links(s).map((l) => `<a href="${esc(l.href)}" target="_blank" rel="noopener">${esc(l.text)}</a>`).join(" · ")}` : ""}${s.note ? `<br><span class="fine">${esc(s.note)}</span>` : ""}</li>`;
  }).join("")}</ol>`;
}

// The five states of the round's payment, by name, each with its time. `.k-step` and data-state (idle | live | done | bad)
// are the site's design contract: a state reached is done; the first one not reached is live while the round runs after
// its merge, bad when the round failed there; the rest are idle. Nothing here moves: a state changes, and says so.
export function statesHtml(round, esc = escHtml) {
  const rows = round.states || [], merged = round.stages.find((s) => s.id === "merge")?.at ?? null;
  const next = rows.findIndex((s) => s.at === null), ended = round.state === "paid" || round.state === "held";
  return `<ol class="live-states" id="live-states" aria-label="The five states of this payment">${rows.map((s, i) => {
    const state = s.at !== null ? "done" : i !== next || merged === null || ended ? "idle" : round.state === "running" ? "live" : "bad";
    const right = s.at !== null ? `<span class="k-num">${esc(clock(s.at).slice(11))}</span>${s.seconds !== null ? `, <span class="k-num">${esc(took(s.seconds))}</span>` : ""}`
      : state === "live" ? "now" : state === "bad" ? "did not happen" : ended ? "not recorded" : "not yet";
    return `<li class="k-step" data-step="${s.name}" data-state="${state}" title="${esc(s.means)}"><strong>${esc(s.name)}</strong> <span class="fine">${right}</span></li>`;
  }).join("\n")}</ol>`;
}

// Whether a round that was paid still lacks something GitHub will give on another look: devnet can show the payment
// before GitHub lists the signing run or Knos's comment says it, and the comment gets "finalized" some seconds after "paid".
export const EXTRA_LOOKS = 4;
export function incomplete(round) {
  if (round.state !== "paid" && round.state !== "held") return false;
  const reached = (round.states || []).filter((s) => s.at !== null).length;
  return round.stages.some((s) => s.at === null) || !round.stages.at(-1).links.some((l) => l.text === "payment comment") || (reached > 0 && reached < STATES.length);
}

// What the round is, in one sentence, with nothing claimed that the data does not say.
export function headline(round, now) {
  const when = `${clock(round.started)} (${ago(now - round.started)} ago)`;
  if (round.stale) return { kind: "", words: `The canary has not run since ${when}. This is its last round, not a live one.` };
  if (round.state === "running") return { kind: "", words: `A round is running now: it started at ${clock(round.started)}.` };
  if (round.state === "paid" || round.state === "held") return { kind: "ok", words: `The latest round started ${when} and ${round.state === "paid" ? "was paid" : "is held for its payee"} ${took(round.total)} later${round.mergeToPaid !== null ? `, ${took(round.mergeToPaid)} after the merge` : ""}.` };
  if (round.state === "failed") return { kind: "bad", words: `The latest round, started ${when}, failed: the stage marked below did not happen.` };
  return { kind: "bad", words: `The latest round, started ${when}, did not finish within ${ROUND_LIMIT / 60} minutes: the stage marked below did not happen.` };
}

// renderLive(el, env): fill `el` (the section with id `status`) and keep it true.
//   env.gh(path)            GitHub's public API, as web/app.js `gh` (default: fetch, no login)
//   env.rpc(method, params) Solana devnet (default: fetch to api.devnet.solana.com)
//   env.repo                the canary's repository (default CANARY_REPO)
//   env.EXPLORER(kind, id)  a link to devnet's explorer;  env.esc;  env.file(path): a JSON file of this site, or null
//   env.now()               the clock, in ms (a test's is fixed)
// Returns { stop() } : the timers end; nothing else is held.
export function renderLive(el, env = {}) {
  const doc = el.ownerDocument, esc = env.esc || escHtml, now = env.now || (() => Date.now()), repo = env.repo || CANARY_REPO;
  const explorer = env.EXPLORER || ((kind, id) => `https://explorer.solana.com/${kind}/${id}?cluster=devnet`);
  const gh = env.gh || (async (path) => { const r = await fetch(GITHUB + path, { headers: { Accept: "application/vnd.github+json" } }); if (!r.ok) throw new Error(r.status === 403 || r.status === 429 ? "GitHub's free limit for this network is used up (60 reads an hour without login). Try again in an hour." : `GitHub said ${r.status}`); return r.json(); });
  const rpc = env.rpc || (async (method, params) => { const r = await fetch(DEVNET_RPC, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) }); const j = await r.json(); if (j.error) throw new Error(j.error.message); return j.result; });
  const file = env.file || (async (path) => { const r = await fetch(path, { cache: "no-cache" }); return r.ok ? r.json() : null; });
  const io = { gh, rpc, repo };
  if (!doc.getElementById("live-style")) { const st = doc.createElement("style"); st.id = "live-style"; st.textContent = STYLE; doc.head.appendChild(st); }
  el.innerHTML = `<div class="card" id="live">
    <p class="devnet">Solana devnet. The money here is test USDC: it is worth nothing.</p>
    <h3>A round you can watch</h3>
    <p>The canary is a workflow in <a href="https://github.com/${esc(repo)}" target="_blank" rel="noopener">${esc(repo)}</a>, set to run every 30 minutes. A round funds an issue with 5 test USDC, opens a pull request
      that closes it, merges it and waits to be paid. You need no account, wallet or repository to follow one: this page reads GitHub and Solana devnet, as you could.</p>
    <p id="live-head" class="status" role="status" aria-live="polite">Reading the canary's latest round…</p>
    <div id="live-round"></div>
    <p id="live-next" class="fine"></p>
    <p><button type="button" id="live-watch">Watch it happen</button> <span id="live-watching" class="fine" role="status" aria-live="polite"></span></p>
    <p id="live-measured" class="fine"></p>
  </div>`;
  const $ = (id) => doc.getElementById(id);
  let moves = null;
  const motion = () => (moves ??= (env.motion ? Promise.resolve(env.motion) : import("./motion.js")).catch(() => null));      // guarded: a site without motion.js loses nothing
  let shown = null, cur = null, watchUntil = 0, poll = null, stopped = false, seenAtPress = null, unread = false, extra = 0, extraFor = null;

  function show(round, asof = null) {
    const was = round && shown && shown.number === round.number ? new Set((shown.states || []).filter((s) => s.at !== null).map((s) => s.name)) : null;
    const landed = Boolean(was && shown.state !== "paid" && round.state === "paid");          // paid while someone watched
    shown = round; unread = false;
    const head = round ? headline(round, now()) : { kind: "", words: `The canary has not run: ${repo} has no round among its newest issues. Nothing is shown as live.` };
    $("live-head").className = `status ${head.kind}`;
    $("live-head").textContent = head.words;
    $("live-round").innerHTML = (round ? timelineHtml(round, now(), esc) + statesHtml(round, esc) : "")
      + (asof !== null ? `<p class="fine" id="live-asof">Shown ${esc(asOf(asof, now()))}. Reading it again…</p>` : "");
    // a state reached while someone watches arrives once (web/motion.js, when the site has it; the page is whole without it)
    const fresh = was ? [...el.querySelectorAll('#live-states .k-step[data-state="done"]')].filter((li) => !was.has(li.dataset.step)) : [];
    if (fresh.length) motion().then((m) => { if (m && !stopped && !(m.prefersReduced && m.prefersReduced())) for (const li of fresh) if (li.isConnected && m.reveal) m.reveal(li); });
    // the payment landed while someone watched: the mark flies from the merge to the payment, once
    if (landed) motion().then((m) => { const line = el.querySelectorAll("#live-line li"); if (m?.raven && !stopped && line.length > 1) m.raven(el.querySelector('#live-line li[data-stage="merge"]') || line[0], line[line.length - 1]); });
    tick();
  }

  // the clock's part: the countdown, and the seconds of the stage in progress
  function tick() {
    if (stopped) return;
    const t = now(), due = nextDue(t), left = Math.max(0, Math.round((due - t) / 1000));
    const running = shown?.state === "running";
    const due_ = `${clock(due).slice(11, 16)} UTC, in ${took(left)}`;
    $("live-next").textContent = running ? "This round is in progress: each stage gets its time when GitHub or devnet reports it."
      : unread ? `The timer is set for every half hour (next: ${due_}). Whether the canary has been running could not be read.`
      : !shown || shown.stale ? `The timer is set for every half hour (next: ${due_}), but the canary has not been running, so a round may not start then.`
      : `The next round is due at ${due_}. GitHub starts a timer when it has a runner free, often some minutes late.`;
    for (const span of el.querySelectorAll("[data-since]")) span.textContent = took(Math.max(0, (t - Number(span.dataset.since)) / 1000));
    if (watchUntil && t > watchUntil) endWatch(`Stopped watching after ${WATCH_FOR / 60} minutes. Press to watch again.`);
  }

  async function latest(read) {
    const items = await read(ghKey(`/repos/${repo}/issues?state=all&sort=created&direction=desc&per_page=20`), () => gh(`/repos/${repo}/issues?state=all&sort=created&direction=desc&per_page=20`));
    const found = newestRound(items);
    if (!found) return null;
    return read(`live:${repo}:${found.issue.number}`, () => readRound(io, found));
  }

  // first: what this tab kept, at once and saying its age; then what GitHub and devnet say now (cache.js)
  async function load() {
    try {
      await kept.twice(async (read, pass) => {
        const raw = await latest(read);
        if (stopped) return;
        cur = raw;
        if (pass.same()) { $("live-asof")?.remove(); return; }
        show(raw ? roundOf(raw, now(), explorer) : null, pass.kept ? pass.at() : null);
      });
    } catch (e) {
      if (stopped) return;
      if (Number.isFinite(e?.kept) && $("live-asof")) { $("live-asof").textContent = `Shown ${asOf(e.kept, now())}. It could not be read again just now: ${e.message}`; return; }
      $("live-head").className = "status bad";
      $("live-head").textContent = `The canary's round could not be read just now (${e.message}), so none is shown.`;
      $("live-round").innerHTML = "";
      unread = true; tick();
    }
  }

  // watching: look again every few seconds, and show the newest round as GitHub and devnet report its stages
  async function look() {
    if (stopped || !watchUntil) return;
    const at = () => `${clock(now()).slice(11, 19)} UTC`, list = `/repos/${repo}/issues?state=all&sort=created&direction=desc&per_page=20`;
    try {
      const was = cur ? roundOf(cur, now(), explorer) : null;
      if (was && was.number !== extraFor) { extraFor = was.number; extra = 0; }
      // a round that ended is looked at a few times more while a stage or a state is still without its time: watching used
      // to stop at the first sight of the payment, and what GitHub had not said by then stayed blank until a reload
      if (was && (was.state === "running" || (incomplete(was) && extra++ < EXTRA_LOOKS))) cur = await advance(io, cur);
      else {
        const found = newestRound(kept.set(ghKey(list), await gh(list)).value);
        if (found && found.issue.number !== cur?.issue.number) cur = { issue: found.issue, comments: [], pull: null, pullComments: [], runs: [], chain: [] };
      }
      if (stopped || !watchUntil) return;
      const round = cur ? roundOf(cur, now(), explorer) : null;
      if (cur) kept.set(`live:${repo}:${cur.issue.number}`, cur);
      show(round);
      if (round?.state === "running" || (round && incomplete(round) && extra < EXTRA_LOOKS)) $("live-watching").textContent = `Watching round ${round.number}. Looked at ${at()}; looking again every ${POLL} s.`;
      else if (round && round.number !== seenAtPress) endWatch(`Round ${round.number} ended (${round.state}). That was a real round: every time above is GitHub's or devnet's.`);
      else $("live-watching").textContent = `Waiting for the next round to start. Looked at ${at()}; looking again every ${POLL} s (GitHub answers 60 reads an hour without login).`;
    } catch (e) { $("live-watching").textContent = `Could not look just now (${e.message}); trying again in ${POLL} s.`; }
  }
  function endWatch(words) {
    watchUntil = 0;
    if (poll) (env.clearInterval || clearInterval)(poll);
    poll = null;
    $("live-watch").disabled = false;
    $("live-watch").textContent = "Watch it happen";
    $("live-watching").textContent = words;
  }
  $("live-watch").onclick = () => {
    if (watchUntil) return endWatch("Stopped watching.");
    watchUntil = now() + WATCH_FOR * 1000;
    seenAtPress = shown?.state === "running" ? null : shown?.number ?? null;      // a round already running when pressed is the one to watch
    $("live-watch").textContent = "Stop watching";
    $("live-watching").textContent = "Looking…";
    poll = (env.setInterval || setInterval)(look, POLL * 1000);
    look();
  };

  // what was measured over many rounds, from the site's own files: said only when the file has it
  Promise.all([file("stats.json").catch(() => null), file("operations.json").catch(() => null)]).then(([stats, ops]) => {
    if (stopped) return;
    const m = stats?.latency?.merge_to_paid, c = ops?.canary, parts = [];
    if (m && Number.isFinite(m.p50) && m.n) parts.push(`Over ${esc(m.n)} timed payments on devnet, the wait from merge to payment had a median of ${esc(took(Number(m.p50)))} and a 95th percentile of ${esc(took(Number(m.p95)))} (<a href="stats.json">stats.json</a>).`);
    if (c && c.runs > 0 && c.all_runs_read) parts.push(`Of the canary's ${esc(c.all_runs_read.runs)} finished runs GitHub lists, ${esc(c.all_runs_read.failed)} failed (<a href="operations.json">operations.json</a>).`);
    $("live-measured").innerHTML = parts.join(" ");
  });

  const timer = (env.setInterval || setInterval)(tick, 1000);
  load();
  return { stop() { stopped = true; (env.clearInterval || clearInterval)(timer); if (poll) (env.clearInterval || clearInterval)(poll); } };
}
