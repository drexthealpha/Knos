// The four pages of index.html that hold nothing until a module fills them: Status, Index, Pilot, Reproduce.
//
//   #status      the public relay, from its own log (web/status_data.js `summarise`), and the canary's latest round on
//                devnet (web/live.js `renderLive`). Both are read from GitHub and Solana by whoever is looking, and only
//                when the page is opened: a reader with no login gets 60 answers an hour from GitHub, and a page nobody
//                looks at should use none of them.
//   #index       the Agent PR Index by week (web/index_board.js), from agent_weekly.json, the build's copy of docs/.
//   #pilot       the one thing offered for money, in the words of docs/PILOT.md and the price book: who it is for,
//                what the buyer gets, what it costs, and that nobody has bought it. No form: the page collects nothing.
//   #reproduce   the three lines of docs/REPRODUCE.md, and how many reproductions people outside have sent: the names
//                in reproductions.json, which the build writes from the repository's reproductions/ folder.
//
// Every sentence here is true with nothing read: a file that is not there, a GitHub that does not answer and a relay
// that has written nothing are each said as that. Nothing is sent anywhere, and nothing is asked of any host but
// GitHub's API and Solana devnet.
//
// ---- HOW A NEW PAGE IS MOUNTED (0.3.20) -------------------------------------------------------------------------------------
// A page registers BY NAME, in one line of `ADDED` in web/views.js (this file is fetched with the pages that read
// Solana, so the list itself lives in the small file the first screen already has):
//
//     approve: { file: "./approver.js", draw: "renderApprover", nav: "Approve", bar: true },
//
// web/front.js then makes its <section id="name" class="mount">, its link in the menu and its lazy mount; the module
// is fetched when the page is first opened, and grey bars stand there until it has drawn.
//     file   the module, beside this one
//     draw   the function it exports: draw(el, ctx), ctx = { esc, go, EXPLORER, data, arg }; it fills el, once
//            (arg: what follows "=" in the hash it was opened at, #vendor=<agent>; a later arrival is the module's to read)
//     nav    the words of its link (three at most)
//     bar    true: the link stands in the bar itself; otherwise under "More"
//     json   a file of the build the page cannot be drawn without: read first and handed over as ctx.data
// A build that lacks the file (or the json) does not offer the page: scripts/build_site.sh drops the line from its
// copy of views.js, so the menu never holds a link to nothing. A page's title is an <h2> of 3 to 6 words with at most
// one line under it (tests/web/words.mjs); add its name to PAGES of tests/web/words.mjs and tests/web/overflow.mjs.
import { summarise, statesHtml, RECENT } from "./status_data.js";
import { renderLive, clock } from "./live.js";
import { renderIndexBoard } from "./index_board.js";
import { priceBook, priceConstants } from "./price.js";
import { cache as kept, ghKey, fileKey, asOf } from "./cache.js";

export const RELAY_REPO = "drexthealpha/Knos";      // where the public relay keeps its log: the open issue labelled knos-relay
export const RELAY_LABEL = "knos-relay";
export const LOG_PAGES = 3;                         // of 100 comments each: what one look reads of the last 24 hours, at most
const DOCS = "https://github.com/drexthealpha/Knos/blob/main/docs";
const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const span = (s) => (s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : s < 172800 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} days`);
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const jsonFile = async (path) => { const r = await fetch(path, { cache: "no-cache" }); return r.ok ? r.json() : null; };

// ---- Status: the relay ------------------------------------------------------------------------------------------------
/** The relay's log of the last 24 hours, as GitHub returns it: { issue, comments, full }. `full`: every page read was
 *  full, so there may be more than was read. null when the repository has no open log issue. One read for the issue,
 *  then one per hundred comments. `since` is cut to the minute so that a second look inside it is the same question. */
export async function readRelayLog(gh, now, repo = RELAY_REPO) {
  const found = await gh(`/repos/${repo}/issues?labels=${RELAY_LABEL}&state=open&per_page=5`);
  const issue = (Array.isArray(found) ? found : []).filter((i) => !i.pull_request).sort((a, b) => a.number - b.number)[0];
  if (!issue) return null;
  const since = new Date(Math.floor((now - 86_400_000) / 60_000) * 60_000).toISOString().replace(".000Z", "Z"), comments = [];
  let page = 1, got;
  do {
    got = await gh(`/repos/${repo}/issues/${issue.number}/comments?since=${since}&per_page=100${page > 1 ? `&page=${page}` : ""}`);
    comments.push(...(Array.isArray(got) ? got : []));
  } while (Array.isArray(got) && got.length === 100 && ++page <= LOG_PAGES);
  return { issue: { number: issue.number, html_url: issue.html_url, updated_at: issue.updated_at }, comments, full: page > LOG_PAGES };
}

/** What the relay card says, from a log (readRelayLog's answer) and stats.json: { kind, headline, facts: [[name, html]], note }.
 *  Nothing is said that the log does not say: a relay that writes no status line has no last round and no queue here. */
export function relayView(log, stats, nowMs, esc = escHtml) {
  const now = Math.floor(nowMs / 1000), s = summarise(log.comments, stats, now), at = (t) => esc(clock(t * 1000));
  const link = `<a href="${esc(log.issue.html_url || `https://github.com/${RELAY_REPO}/issues/${log.issue.number}`)}" target="_blank" rel="noopener">the relay's log</a>`;
  const silent = s.worker.lastSeen === null, changed = Date.parse(log.issue.updated_at || "");
  const headline = silent
    ? `The relay has written nothing in its log in the last 24 hours${Number.isFinite(changed) ? ` (the log was last changed ${clock(changed)})` : ""}. Tokens posted now wait until it runs again, or relay them yourself with \`knos relay\`.`
    : s.headline;
  const none = `<span class="fine">The log does not say: this relay writes no status line.</span>`;
  const reasons = s.refused.reasons.slice(0, 5).map((r) => `<li>${esc(r.count)} × ${esc(r.reason)} <span class="fine">(last ${at(r.last)})</span></li>`).join("");
  const facts = [
    ["Ran in the last 10 minutes", silent ? `<strong class="status bad">No.</strong> Nothing of its own in the log for 24 hours.`
      : s.worker.ranRecently ? `<strong class="status ok">Yes.</strong> It last wrote ${esc(span(s.worker.ago))} ago, at ${at(s.worker.lastSeen)}.`
        : `<strong class="status bad">No.</strong> It last wrote ${esc(span(s.worker.ago))} ago, at ${at(s.worker.lastSeen)}.`],
    ["Last round", s.lastRound ? `${at(s.lastRound.at)}; it took ${esc(span(s.lastRound.seconds))} and looked at ${esc(plural(s.lastRound.tokens, "token"))}.` : none],
    ["Tokens waiting", s.waiting ? (s.waiting.tokens ? `${esc(plural(s.waiting.tokens, "token"))}, the oldest for ${esc(span(s.waiting.oldestSeconds))} (as of ${at(s.waiting.asOf)}).` : `None (as of ${at(s.waiting.asOf)}).`) : none],
    ["Carried in 24 hours", `${esc(plural(s.answered.ok, "token"))}.`],
    ["Refused in 24 hours", s.refused.count ? `${esc(plural(s.refused.count, "token"))}.<ul class="plain">${reasons}</ul>` : "None."],
    ["Retries in 24 hours", `${esc(s.retries.count)}${s.retries.count ? ` (${esc(s.retries.carried)} on tokens that went through in the end)` : ""}.`],
    ["Merge to paid, measured", s.measured && Number.isFinite(Number(s.measured.p50)) ? `Median ${esc(span(Math.round(Number(s.measured.p50))))}${Number.isFinite(Number(s.measured.p95)) ? `, 95th percentile ${esc(span(Math.round(Number(s.measured.p95))))}` : ""}, over ${esc(plural(s.measured.n, "payment"))} (<a href="stats.json">stats.json</a>${s.measured.updated ? `, counted ${esc(s.measured.updated)}` : ""}).`
      : `<span class="fine">Not in this build's stats.json.</span>`],
  ];
  const note = `Read from ${link} (issue #${esc(log.issue.number)} of ${esc(RELAY_REPO)}), the lines its own workflow wrote since ${esc(clock(nowMs - 86_400_000))}.`
    + (log.full ? ` The log has more than ${LOG_PAGES * 100} comments in that time: the counts are of the first ${LOG_PAGES * 100}.` : "");
  return { kind: silent || !s.worker.ranRecently ? "bad" : "ok", headline, facts, note, summary: s };
}

const code = (text, esc) => esc(text).replace(/`([^`]+)`/g, "<code>$1</code>");

/** Fill the Status page. Reads nothing until `start()` is called (the first time the page is shown).
 *  env: { gh, rpc, EXPLORER, esc, now (ms), file(path) } as web/app.js has them. Returns { start, stop }. */
export function renderStatus(el, env = {}) {
  const esc = env.esc || escHtml, now = env.now || (() => Date.now()), file = env.file || jsonFile, doc = el.ownerDocument, $ = (id) => doc.getElementById(id);
  el.innerHTML = `<h2>Relay and canary status</h2>
    <p class="lede">Check the relay and a whole round.</p>
    <div class="card" id="relay-status">
      <h3>The public relay</h3>
      <details class="k-more"><summary>What the relay does</summary><p>A signed token is a comment on GitHub until someone carries it to Solana. The public relay does that about once a minute and pays the transaction fee;
        anyone else can carry the same token with <code>knos relay</code>. It writes one line in a public log for every token it answers for.</p></details>
      <p id="relay-head" class="status" role="status" aria-live="polite">Open this page to read the relay's log.</p>
      <div id="relay-latest"></div>
      <dl class="facts" id="relay-facts"></dl>
      <div id="relay-rounds"></div>
      <p id="relay-note" class="fine"></p>
      <p><button type="button" id="relay-again" class="ghost small" hidden>Read it again</button></p>
    </div>
    <div id="status-live"></div>
    <div class="card" id="status-who">
      <h3>Who answers when it fails</h3>
      <p>Today the founder alone. There is no support contract, no on-call team and no service-level agreement, and nobody else to call.</p>
      <p class="fine">The money does not wait on that person: a refund after the deadline, the release of a holdback and the settling of a held payment can each be sent by anyone.
        What was measured over many runs (the canary's runs, the relay's attempts) is in this site's <a href="operations.json">operations.json</a>.</p>
    </div>`;
  const gh = env.gh || (async (path) => { const r = await fetch(`https://api.github.com${path}`, { headers: { Accept: "application/vnd.github+json" } }); if (!r.ok) throw new Error(r.status === 403 || r.status === 429 ? "GitHub's free limit for this network is used up (60 reads an hour without login). Try again in an hour." : `GitHub said ${r.status}`); return r.json(); });
  let live = null, started = false, stopped = false;

  function draw(log, stats, asof) {
    if (!log) {
      $("relay-head").className = "status bad";
      $("relay-head").textContent = `${RELAY_REPO} has no open issue labelled ${RELAY_LABEL}, so the relay's log was not found and nothing is said about the relay.`;
      $("relay-facts").innerHTML = ""; $("relay-note").textContent = ""; $("relay-latest").innerHTML = ""; $("relay-rounds").innerHTML = "";
      return;
    }
    const v = relayView(log, stats, now(), esc);
    $("relay-head").className = `status ${v.kind}`;
    $("relay-head").innerHTML = code(v.headline, esc);
    // the newest payment the relay carried, in the five states every part of Knos names the same way, and its last rounds
    const latest = v.summary.latest, rounds = v.summary.rounds;
    $("relay-latest").innerHTML = latest ? `<p class="k-kicker">Newest payment carried: ${esc(latest.kind)}, ${esc(latest.where)}</p>${statesHtml(latest, esc)}` : "";
    $("relay-latest").querySelector("ol")?.setAttribute("style", "padding:0;margin:12px 0");          // a timeline of .k-step, not a numbered list
    $("relay-rounds").innerHTML = rounds.length ? `<h4>Last rounds</h4><div class="k-table"><table id="relay-rounds-table"><thead><tr><th scope="col">Where</th><th scope="col">Kind</th><th scope="col">State</th><th scope="col">Seconds</th><th scope="col">Order</th></tr></thead>
      <tbody>${rounds.map((r) => `<tr><td>${esc(r.where)}</td><td>${esc(r.kind || "")}</td><td>${esc(r.state || "")}</td><td class="k-num">${r.seconds === null ? "" : esc(r.seconds)}</td>
        <td>${r.order && env.EXPLORER ? `<a class="mono" href="${esc(env.EXPLORER("address", r.order))}" target="_blank" rel="noopener">${esc(r.order.slice(0, 6))}…</a>` : esc(r.order ? `${r.order.slice(0, 6)}…` : "")}</td></tr>`).join("")}</tbody></table></div>` : "";
    $("relay-facts").innerHTML = v.facts.map(([name, html]) => `<dt>${esc(name)}</dt><dd>${html}</dd>`).join("");
    $("relay-note").innerHTML = v.note + (asof !== null ? ` <span id="relay-asof">Shown ${esc(asOf(asof, now()))}. Reading it again…</span>` : "");
  }

  // first what this tab kept, saying its age; then what GitHub says now (cache.js)
  async function load() {
    const key = ghKey(`/repos/${RELAY_REPO}/issues?labels=${RELAY_LABEL}:log24`);
    $("relay-again").hidden = true;
    if (!$("relay-facts").childElementCount) { $("relay-head").className = "status"; $("relay-head").textContent = "Reading the relay's log…"; }
    try {
      await kept.twice(async (read, pass) => {
        const log = await read(key, () => readRelayLog(gh, now())), stats = await read(fileKey("stats.json"), () => file("stats.json").catch(() => null));
        if (stopped) return;
        draw(log, stats, pass.kept ? pass.at() : null);
      });
    } catch (e) {
      if (stopped) return;
      if (Number.isFinite(e?.kept) && $("relay-asof")) $("relay-asof").textContent = `Shown ${asOf(e.kept, now())}. It could not be read again just now: ${e.message}`;
      else {
        $("relay-head").className = "status bad";
        $("relay-head").textContent = `The relay's log was not read (${e.message}). Nothing is said about the relay.`;
        $("relay-facts").innerHTML = "";
        $("relay-note").innerHTML = `The log is the open issue labelled ${esc(RELAY_LABEL)} in <a href="https://github.com/${esc(RELAY_REPO)}/issues?q=label%3A${esc(RELAY_LABEL)}" target="_blank" rel="noopener">${esc(RELAY_REPO)}</a>.`;
      }
    }
    if (!stopped) $("relay-again").hidden = false;
  }
  $("relay-again").onclick = load;

  return {
    start() {
      if (started || stopped) return;
      started = true;
      load();
      live = renderLive($("status-live"), { gh, rpc: env.rpc, EXPLORER: env.EXPLORER, esc, now: env.now, file: env.file, repo: env.canary, setInterval: env.setInterval, clearInterval: env.clearInterval });
    },
    stop() { stopped = true; live?.stop(); },
  };
}

// ---- Index ------------------------------------------------------------------------------------------------------------
/** Fill the Index page from agent_weekly.json (`weekly`: the parsed file, or null when the build has none). */
export function renderIndex(el, weekly, esc = escHtml, feed = null) {
  const has = weekly && weekly.agents && Object.keys(weekly.agents).length > 0;
  el.innerHTML = `<h2>Agent PR Index</h2>
    <p class="lede">How often GitHub's checks agree with “tests pass”, per agent, per week.</p>
    <div class="card" id="index-card">${has ? "" : `<p class="status" id="index-none">This build has no agent_weekly.json, or the file holds no agent, so no table is shown. The table of the repository is in <a href="${DOCS}/INDEX.md" target="_blank" rel="noopener">docs/INDEX.md</a>.</p>`}</div>
    ${has ? `<div class="card" id="index-limits"><h3>What this is, and what it is not</h3>
      <p class="fine" id="index-source">Read ${esc(weekly.read || "on a day the file does not name")}. ${esc(String(weekly.source || "").replace(/([^.])$/, "$1."))}</p>
      ${Array.isArray(weekly.limits) && weekly.limits.length ? `<ul class="fine">${weekly.limits.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
      <p class="fine">The numbers are the file <a href="agent_weekly.json">agent_weekly.json</a>, written by
        <a href="https://github.com/drexthealpha/Knos/blob/main/scripts/agent_pr_index.py" target="_blank" rel="noopener">scripts/agent_pr_index.py</a>; how a pull request is told to be an agent's, what counts as a claim and what the script cannot see are in
        <a href="${DOCS}/INDEX.md" target="_blank" rel="noopener">docs/INDEX.md</a>. To check one pull request yourself: <a href="#check">Check</a>.</p></div>` : ""}`;
  if (has) renderIndexBoard(el.querySelector("#index-card"), weekly, { feed });
  return el;
}

// ---- Pilot ------------------------------------------------------------------------------------------------------------
// docs/PILOT.md, shortened. The price is the price book's Pilot row (price.js), so the page and the book cannot differ.
export const PILOT_DELIVERABLES = [
  ["One reconciled invoice", "The buyer's accepted work for the 30 days, from both suppliers, set against what each billed, as one list of deliverables: the order, the milestone, the artifact, the policy version that judged it and the verdict. A deliverable is counted once, whatever number of pull requests carried it."],
  ["A mismatch list", "Every difference between what was accepted and what was billed, named: billed and not accepted; accepted and not billed; billed twice; judged differently by the two sides. A mismatch is a dispute line, never an invoice line."],
  ["A statement both sides verify", "For each supplier, one statement that the buyer computes from its ledger and the supplier computes from its own, to the same totals. It counts only what both sides have and describe alike."],
  ["Quantified findings", "Invoice preparation time, disputed lines, acceptance-to-approval time and repeat use, before and after, written down with their sample sizes and given to the buyer whether or not they flatter Knos."],
];
export const PILOT_BLOCKERS = [
  ["Nobody has bought it.", "No buyer has been asked. Whether any buyer has this problem badly enough to pay is not known."],
  ["There is no legal entity to invoice from yet.", "No company has been formed, so the invoice cannot be issued today and nothing can sign terms or a data-processing agreement. Until that changes, the Pilot cannot be sold."],
  ["It has never been run.", "The reconciliation is tested on example ledgers. It has not been run on a real buyer's invoices, so the 30 days and the price are estimates."],
  ["The founder is one pseudonymous person.", "A buyer's procurement process may refuse on that alone, and would be right to ask who answers if that person is unavailable. Today: nobody."],
];

export function renderPilot(el, esc = escHtml) {
  const row = priceBook(priceConstants()).find((r) => r[0] === "Pilot") || ["Pilot", "", ""];
  el.innerHTML = `<h2>The 30-day Pilot</h2>
    <p class="lede">Close a supplier's invoice with evidence both sides can check.</p>
    <div class="card" id="pilot-price">
      <p class="status" id="pilot-honest">An offer, not a record. Nobody has bought it. Nobody has been asked. No legal entity to invoice from yet.</p>
      <h3>What it costs</h3>
      <dl class="facts"><dt>${esc(row[0])}</dt><dd>${esc(row[1])}</dd><dt>Price</dt><dd id="pilot-price-words">${esc(row[2])}</dd></dl>
      <p class="fine">The suppliers pay nothing. No fee is taken on chain: any settlement during a Pilot is on devnet in test USDC, and a fee in test money is not revenue. Its price, 2,500 USD, is credited against year one, and it commits the buyer to none. <a href="#pricing">The whole price book</a>.</p>
    </div>
    <div class="card" id="pilot-who">
      <h3>Who it is for</h3>
      <p>A company that buys software work per outcome from two or more suppliers (agent vendors, agencies, contractors paid per merged change or per milestone) and has their invoices to reconcile.
        The person who signs is whoever must authorise those payments and defend them afterwards: an engineering director or a finance controller.</p>
      <p class="fine">It is not for a company with one supplier (there is nothing to compare), for work billed by the hour or the seat, or for a maintainer with a bounty: the free check and <a href="#fund">funding by a comment</a> already serve that.</p>
    </div>
    <div class="card" id="pilot-gets">
      <details class="k-more"><summary>What the buyer gets: four deliverables</summary>
      <ol id="pilot-deliverables">${PILOT_DELIVERABLES.map(([name, what]) => `<li><strong>${esc(name)}.</strong> ${esc(what)}</li>`).join("")}</ol></details>
      <p class="fine" data-fold="Checked from two ledger files">Each statement can be checked from the two ledger files alone. Totals are also written to Solana devnet as test data, to show the mechanism; nothing in the Pilot depends on devnet keeping its history.</p>
    </div>
    <div class="card" id="pilot-blockers">
      <details class="k-more"><summary>What stands in the way, plainly</summary>
      <ul>${PILOT_BLOCKERS.map(([head, what]) => `<li><strong>${esc(head)}</strong> ${esc(what)}</li>`).join("")}</ul></details>
      <p class="fine">Not included: private repositories under a contract, single sign-on, a service-level agreement, payment of suppliers in real money (mainnet is not touched), a second person to call, or a security review of Knos by anyone outside it. There has been none.</p>
      <p class="fine">This page has no form and collects nothing. What the buyer and each supplier do, what is measured and how: <a href="${DOCS}/PILOT.md" target="_blank" rel="noopener">docs/PILOT.md</a>.</p>
    </div>`;
  return el;
}

// ---- Reproduce --------------------------------------------------------------------------------------------------------
export const REPRODUCE_COMMAND = "pipx run --spec knos knos reproduce";
/** The names of the reproductions a build carries: reproductions.json is { files: [name] } (scripts/build_site.sh). null: no such file. */
export const reproductionsOf = (listed) => (listed && Array.isArray(listed.files) ? listed.files.filter((f) => typeof f === "string" && /^[\w.-]+\.json$/.test(f)) : null);

export function renderReproduce(el, listed, esc = escHtml) {
  const files = reproductionsOf(listed);
  const count = files === null ? `<p class="status" id="repro-count" data-count="">This build does not list the reproductions sent. The folder itself: <a href="https://github.com/drexthealpha/Knos/tree/main/reproductions" target="_blank" rel="noopener">reproductions/</a>.</p>`
    : files.length ? `<p class="status ok" id="repro-count" data-count="${files.length}">${esc(plural(files.length, "reproduction"))} from outside Knos ${files.length === 1 ? "is" : "are"} in this build.</p>
        <ul class="plain" id="repro-files">${files.map((f) => `<li><a class="mono" href="reproductions/${esc(encodeURIComponent(f))}">${esc(f)}</a></li>`).join("")}</ul>`
      : `<p class="status" id="repro-count" data-count="0">Outside reproductions so far: none yet. No capability is marked as reproduced.</p>`;
  el.innerHTML = `<h2>Reproduce it yourself</h2>
    <p class="lede">Do not take the maintainer's word. Run one command.</p>
    <pre>${esc(REPRODUCE_COMMAND)}</pre>
    <div class="card" id="repro-count-card"><h3>Reproductions from outside</h3>${count}
      <p class="fine" data-fold="Which files count">A file counts only when GitHub signed the run in a repository that is not Knos's own; a run in one of Knos's accounts is refused by the same check that accepts everyone else's.
        Each capability's stage: <a href="#capabilities">Capabilities</a>.</p></div>
    <div class="card" id="repro-how">
      <details class="k-more"><summary>Three lines: run, fork, send the result</summary>
      <ol class="steps" id="repro-lines">
        <li><strong>The one command.</strong> On any machine with Python 3.10 or later; a report on your screen and in <code>report.json</code>, not signed:
          <pre id="repro-command">${esc(REPRODUCE_COMMAND)}</pre></li>
        <li><strong>Fork and run, signed by GitHub.</strong> Fork <a href="https://github.com/drexthealpha/Knos" target="_blank" rel="noopener">drexthealpha/Knos</a> and enable Actions in the fork (or copy
          <a href="https://github.com/drexthealpha/Knos/blob/main/examples/knos-reproduce.yml" target="_blank" rel="noopener">examples/knos-reproduce.yml</a> into any repository of yours), then Actions, <strong>knos reproduce</strong>, <strong>Run workflow</strong>.
          It needs no secret, no wallet and no money, and it writes nothing to your repository. This is the one that counts.</li>
        <li><strong>Send the result.</strong> Download the run's artifact <code>knos-reproduction</code> and open a pull request to drexthealpha/Knos that adds the file in it as
          <code>reproductions/&lt;owner&gt;-&lt;repo&gt;-&lt;run id&gt;.json</code> and nothing else. A check that failed is a bug, not a reproduction: open an issue and attach <code>report.json</code>.</li>
      </ol></details>
      <p class="fine"><a href="${DOCS}/REPRODUCE.md" target="_blank" rel="noopener">What each check proves, and what it does not</a></p>
    </div>`;
  return el;
}

// ---- all four, as web/app.js calls it ----------------------------------------------------------------------------------
/** ctx: { $, esc, knos, RPC, EXPLORER, gh }. Pilot is words and is filled at once; Index and Reproduce when their file
 *  has come; Status is laid out at once and reads GitHub and devnet the first time its page is shown. */
export function fillMounts(ctx) {
  const { $, esc, knos, RPC, EXPLORER, gh } = ctx, file = ctx.file || jsonFile;
  if ($("pilot")) renderPilot($("pilot"), esc);
  if ($("index")) Promise.all([file("agent_weekly.json").catch(() => null), file("agent_index.json").catch(() => null)]).then(([weekly, feed]) => renderIndex($("index"), weekly, esc, feed));
  if ($("reproduce")) file("reproductions.json").catch(() => null).then((listed) => renderReproduce($("reproduce"), listed, esc));
  if (!$("status")) return null;
  const status = renderStatus($("status"), { gh, rpc: (m, p) => knos.rpc(RPC, m, p), EXPLORER, esc, file });
  const shown = () => { if (location.hash.replace(/^#/, "").split("=")[0] === "status") status.start(); };
  addEventListener("hashchange", shown);
  shown();
  return status;
}
