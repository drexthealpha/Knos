// The playground: two buttons and a live list. A stranger with a GitHub account funds a test task or takes one, with
// nothing installed. docs/PLAYGROUND.md says what it is, what the limits are and how it is counted.
//
//   renderPlayground(el, env)   draws into `el` and keeps the list fresh; returns { refresh, stop }
//   playgroundHtml(state)       the same as a string, from what was read
//   tasksOf(issues, bounties)   the rows: GitHub's open issues of the playground, each with its state on devnet
//   fundUrl(), takeUrl(tasks)   where the two buttons go
//
// What it reads, and nothing else:
//   GitHub      api.github.com/repos/drexthealpha/knos-playground/issues (open issues; no token), as app.js reads GitHub
//   this site   bounties.json (the open funded tasks counted from Solana devnet by scripts/pages_data.py) and
//               outsiders.json (outside funders, repositories and payees: three numbers that are never added)
// `env` replaces any of it: { gh(path), file(path), every (ms between reads; 0: read once), now() }.
//
// It uses the design contract's names (.k-card, .k-btn, .k-kicker, .k-num, .k-table, .k-step) and adds only what
// keeps it inside a 320 px screen. Every sentence on it is 12 words or fewer; the rest is in the document.

export const REPO = "drexthealpha/knos-playground";
export const TEMPLATE = "fund-a-test-task.md";
export const TASK_FILE = "words.py";
export const DOC = "https://github.com/drexthealpha/Knos/blob/main/docs/PLAYGROUND.md";
export const FUND_LABEL = "Fund a test task (one click, then Submit)";
export const TAKE_LABEL = "Take one";
export const LABEL_KNOS_FAUCET = "outside funder, Knos repository, faucet money";      // scripts/outsiders.py's own words

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
const whole = (n) => (Number.isInteger(n) && n >= 0 ? n : null);

// GitHub opens a new issue with the template's text in it; the text holds the fund line. One click here, then Submit.
export const fundUrl = () => `https://github.com/${REPO}/issues/new?template=${encodeURIComponent(TEMPLATE)}`;
export const editUrl = () => `https://github.com/${REPO}/edit/main/${TASK_FILE}`;
export const listUrl = () => `https://github.com/${REPO}/issues`;
// The oldest funded task first: it has waited longest. With none funded, GitHub's own list.
export const takeUrl = (tasks) => (tasks || []).filter((t) => t.state === "funded").sort((a, b) => a.number - b.number)[0]?.url || listUrl();

const amount = (units, decimals = 6) => {
  const n = Number(units) / 10 ** decimals;
  return Number.isFinite(n) ? n.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "?";
};

// issues: GitHub's list (pull requests are in it and are left out). bounties: bounties.json, or null when it was not read.
export function tasksOf(issues, bounties) {
  const funded = new Map();
  for (const b of (bounties && Array.isArray(bounties.bounties) ? bounties.bounties : [])) {
    if (String(b.repository || "").toLowerCase() === REPO.toLowerCase() && Number.isInteger(b.issue)) funded.set(b.issue, b);
  }
  return (Array.isArray(issues) ? issues : []).filter((i) => i && !i.pull_request && Number.isInteger(i.number) && i.state !== "closed").map((i) => {
    const b = funded.get(i.number);
    return { number: i.number, title: String(i.title || ""), by: String(i.user?.login || ""), url: `https://github.com/${REPO}/issues/${i.number}`,
      state: b ? "funded" : bounties ? "opened" : "unread", amount: b ? amount(b.amount, b.decimals) : null, currency: b ? String(b.currency || "test USDC") : null };
  }).sort((a, b) => b.number - a.number);
}

const STATE = { funded: ["done", (t) => `Funded: ${esc(t.amount)} ${esc(t.currency)}`], opened: ["live", () => "Waiting for devnet"], unread: ["idle", () => "Devnet not read"] };

function listHtml(s) {
  if (s.tasks === undefined) return `<p class="pg-note" role="status">Reading GitHub…</p>`;
  if (s.tasks === null) return `<p class="pg-note" role="status">GitHub did not answer. <a href="${listUrl()}" rel="noopener">Open the list there.</a></p>`;
  if (!s.tasks.length) return `<p class="pg-note" id="pg-none">No open task now.</p>`;
  return `<div class="k-table"><table id="pg-tasks"><thead><tr><th scope="col">Task</th><th scope="col">State</th><th scope="col">Do it</th></tr></thead><tbody>${s.tasks.map((t) => {
    const [state, words] = STATE[t.state];
    return `<tr data-issue="${esc(t.number)}" data-state="${esc(t.state)}"><th scope="row"><a href="${esc(t.url)}" rel="noopener"><span class="k-num">#${esc(t.number)}</span> ${esc(t.title)}</a></th>
      <td><span class="k-step" data-state="${state}">${words(t)}</span></td>
      <td>${t.state === "funded" ? `<a href="${editUrl()}" rel="noopener">Edit ${esc(TASK_FILE)}</a>` : ""}</td></tr>`;
  }).join("")}</tbody></table></div>`;
}

// The three outside counts as they are today. A zero that was counted is a zero; a build that read nothing says so.
function countsHtml(o) {
  if (o === undefined) return "";
  const n = o && o.measured !== false ? [whole(o.funders), whole(o.repositories), whole(o.payees), whole(o.funders_in_knos_repositories_faucet)] : null;
  if (!n || n.slice(0, 3).some((x) => x === null)) return `<p class="pg-note" id="pg-counts" data-measured="false">Outside counts: not read in this build. <a href="${DOC}" rel="noopener">How they are counted.</a></p>`;
  const d = (o && o.definitions) || {}, cell = (id, value, name, def) => `<span class="pg-count" id="${id}" title="${esc(def || "")}"><strong class="k-num">${value}</strong> ${name}</span>`;
  return `<p class="pg-note" id="pg-counts" data-measured="true">${cell("pg-funders", n[0], "outside funders", d.funders)}, ${cell("pg-repos", n[1], "outside repositories", d.repositories)}, ${cell("pg-payees", n[2], "outside payees", d.payees)}.
    Add none of them together. <a href="${DOC}#how-it-is-counted" rel="noopener">Read the definitions.</a></p>
    <p class="pg-note" id="pg-faucet" title="${esc(d.funders_in_knos_repositories_faucet || "")}"><strong class="k-num">${n[3] ?? 0}</strong> of those funders: ${esc(LABEL_KNOS_FAUCET)}.</p>`;
}

const STYLE = `<style>
.playground{overflow-wrap:anywhere;min-width:0}
.playground .pg-acts{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.playground .pg-acts .k-btn{max-width:100%;white-space:normal;text-align:center}
.playground .pg-note{margin:8px 0}
.playground table{border-collapse:collapse;width:100%}
.playground th,.playground td{text-align:left;vertical-align:top;padding:6px 8px;font-weight:inherit}
.playground .pg-count{white-space:nowrap}
</style>`;

export function playgroundHtml(s = {}) {
  return `${STYLE}<div class="playground k-card">
  <p class="k-kicker">Playground</p>
  <h2>Try it with test money</h2>
  <p class="pg-note">Spend nothing: the devnet faucet pays in test USDC.</p>
  <div class="pg-acts"><a class="k-btn" id="pg-fund" href="${fundUrl()}" rel="noopener">${FUND_LABEL}</a>
    <a class="k-btn quiet" id="pg-take" href="${esc(takeUrl(s.tasks))}" rel="noopener">${TAKE_LABEL}</a>
    <button class="k-btn quiet" id="pg-again" type="button">Read again</button></div>
  <div id="pg-list" aria-live="polite">${listHtml(s)}</div>
  ${countsHtml(s.outsiders)}
  <p class="pg-note"><a href="${DOC}" rel="noopener">Read the limits.</a></p>
</div>`;
}

const json = (url) => fetch(url, { headers: { Accept: "application/json" } }).then((r) => { if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.json(); });

export function renderPlayground(el, env = {}) {
  const gh = env.gh || ((path) => json(`https://api.github.com/${path}`)), file = env.file || ((path) => json(path));
  const every = env.every ?? 300_000, state = {};
  let timer = null, stopped = false, round = 0;
  const draw = () => {
    if (stopped) return;
    el.innerHTML = playgroundHtml(state);
    el.querySelector?.("#pg-again")?.addEventListener("click", () => refresh());
  };
  async function refresh() {
    const mine = ++round;
    const [issues, bounties, outsiders] = await Promise.all([
      Promise.resolve().then(() => gh(`repos/${REPO}/issues?state=open&per_page=50`)).catch(() => null),
      Promise.resolve().then(() => file("bounties.json")).catch(() => null),
      Promise.resolve().then(() => file("outsiders.json")).catch(() => null)]);
    if (stopped || mine !== round) return state;       // a newer read is on its way: this one is not drawn over it
    state.tasks = Array.isArray(issues) ? tasksOf(issues, bounties) : null;
    state.outsiders = outsiders;
    draw();
    return state;
  }
  const stop = () => { stopped = true; if (timer) clearInterval(timer); };
  draw();
  // env.wait: a promise the caller resolves when the page is first shown. Until then the page is laid out and GitHub is
  // asked nothing: a visitor who never opens the playground spends none of the 60 reads an hour GitHub gives without login.
  const first = env.wait ? Promise.resolve(env.wait).then(() => (stopped ? state : refresh())) : refresh();
  const repeat = () => {
    if (stopped) return;
    timer = setInterval(() => {
      if (el.isConnected === false) return stop();                                   // the view is gone: ask nobody
      if (typeof document === "undefined" || document.visibilityState !== "hidden") refresh();
    }, every);
  };
  if (every > 0 && typeof setInterval === "function") { if (env.wait) Promise.resolve(env.wait).then(repeat); else repeat(); }
  return { refresh, stop, first };
}
