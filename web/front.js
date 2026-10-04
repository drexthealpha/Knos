// Front door: paste an agent PR, see in seconds whether its "tests pass" claim is true -- from GitHub's own CI at the
// PR's head commit, read in the browser with the public GitHub REST API (no login, no install). The claim regexes are
// ported from scripts/agent_pr_ci.py (the Agent PR Index uses the same ones), so the page and the index agree.

const $ = (id) => document.getElementById(id);
const API = "https://api.github.com";
// The commit the templates below name is the example's own (scripts/front_workflow.py writes them from examples/).
// The Pages build stamps its own commit into these two constants for templates that still use them; a template that
// names its workflows in drexthealpha/knos-workflows at a commit uses neither, and the page never hands out a file
// whose commit is not a full one (see pinned).
export const KNOS_SHA = "KNOS_COMMIT_SHA";
export const KNOS_RELAY_SHA = "KNOS_COMMIT_SHA";

// ---- claim detection (port of scripts/agent_pr_ci.py) -----------------------------------------------------------
const PASS = String.raw`(?:pass(?:es|ed|ing)?|green)`;
export const CLAIM_RE = new RegExp(
  String.raw`(?:\ball\s+(?:\w+\s+){0,2}tests?\s+(?:are\s+|now\s+)*` + PASS +
  String.raw`|\btests?\s+(?:are\s+|now\s+|still\s+)*` + PASS + String.raw`\b` +
  String.raw`|\btests?\b[^\n.]{0,40}?\band\s+passing\b` +
  String.raw`|\bCI\b(?:[\s:/,]+(?:is|are|now|run|runs|job|jobs|checks?|build|pipeline|workflows?|all|CD|#?\d+))*[\s:,]+` +
  PASS + String.raw`\b` +
  String.raw`|\b(?:all\s+(?:CI\s+)?checks?|(?:CI\s+)?checks)\s+(?:are\s+|have\s+)?` + PASS + String.raw`\b` +
  String.raw`|\bpass(?:es|ed|ing)?\s+all\s+(?:\w+\s+){0,2}(?:tests|checks|CI)\b` +
  String.raw`|` + "`" + String.raw`[^` + "`" + String.raw`\n]*test[^` + "`" + String.raw`\n]*` + "`" +
  String.raw`\s*(?:[-:—]\s*)?(?:all\s+)?` + PASS + String.raw`\b` +
  String.raw`|\b\d[\d,]*\s*(?:/\s*\d[\d,]*\s*)?(?:\w+\s+){0,2}passed\b` +
  String.raw`|✅\s*[^\n]{0,40}?\btests?\b` +
  String.raw`|\btests?\b[^\n]{0,30}?✅)`, "i");
// an unticked box of a task list (any marker: -, *, +, 1., 1), nested or quoted), or a conditional, instruction,
// negation or partial failure: the line claims nothing
export const NONCLAIM_RE = new RegExp(
  String.raw`^[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)+\[ \](?:[ \t]|$)|` +
  String.raw`\b(ensure|make sure|verify that|should|would|will|to confirm|until|` +
  String.raw`once|if|before|whether|need|needs|must|expect|expected|todo|not|` +
  String.raw`fail|fails|failing|failed|failure|failures|errors?|except|unless|pending|flaky|skip|` +
  String.raw`red|broken)\b|n't\b`, "i");
export const BOILER_RE = new RegExp(String.raw`\*\*Your PR cannot be merged unless tests pass\*\*|` +
  String.raw`\bfail[- ](?:closed|safe|fast|open)\b|\b0 failed\b`, "gi");

function stripBody(body) {
  return (body || "").replace(/<!--[\s\S]*?-->/g, " ").replace(
    /<details>\s*<summary>[^<]*(original prompt|original issue)[^<]*<\/summary>[\s\S]*?<\/details>/gi, " ");
}

export function findClaim(body) {
  for (const line of stripBody(body).split(/\r?\n/)) {
    const m = CLAIM_RE.exec(line);
    if (!m || NONCLAIM_RE.test(line.replace(BOILER_RE, " "))) continue;
    return { phrase: m[0].trim(), line: line.trim().slice(0, 200) };
  }
  return null;
}

// check runs that are the agent's own session, not project CI (same list as agent_pr_ci.py)
const AGENT_RUN_RE = /^(copilot|claude|claude[-_ ]?(code|review|code[-_ ]review|pr[-_ ]review)|codex|devin)$/i;
const FAIL = new Set(["failure", "timed_out", "startup_failure"]);
const OK = new Set(["success", "neutral", "skipped"]);

export function ciVerdict(runs, statuses) {
  const ci = runs.filter((x) => !AGENT_RUN_RE.test(x.name.trim()));
  const failed = ci.filter((x) => FAIL.has(x.conclusion)).map((x) => x.name)
    .concat(statuses.filter((s) => s.state === "failure" || s.state === "error").map((s) => s.context));
  if (failed.length) return { cls: "failed", failed };
  if (!ci.length && !statuses.length) return { cls: "no-ci", failed };
  if (ci.some((x) => x.status !== "completed") || statuses.some((s) => s.state === "pending")) return { cls: "pending", failed };
  if (ci.every((x) => OK.has(x.conclusion)) && statuses.every((s) => s.state === "success")) return { cls: "passed", failed };
  return { cls: "other", failed };
}

export function agentOf(pr) {
  const login = (pr.user?.login || "").toLowerCase(), body = pr.body || "";
  if (login.startsWith("copilot")) return "copilot";
  if (login.startsWith("devin-ai-integration")) return "devin";
  if (login === "claude[bot]" || login === "claude") return "claude-bot";
  if (/Generated with Claude Code/.test(body)) return "claude-code";
  if (/chatgpt\.com\/codex\/tasks/.test(body)) return "codex";
  return null;
}

// ---- GitHub, unauthenticated ------------------------------------------------------------------------------------
class RateLimited extends Error {}

async function gh(path) {
  const r = await fetch(API + path, { headers: { Accept: "application/vnd.github+json" } });
  if ((r.status === 403 || r.status === 429) && r.headers.get("x-ratelimit-remaining") === "0") {
    const reset = Number(r.headers.get("x-ratelimit-reset")) * 1000;
    throw new RateLimited(reset ? new Date(reset).toLocaleTimeString() : "");
  }
  if (r.status === 404) throw new Error("not found (private repo, or no such PR)");
  if (!r.ok) throw new Error(`GitHub said ${r.status}`);
  return r.json();
}

let indexP = null;
const loadIndex = () => (indexP ??= fetch("index.json").then((r) => (r.ok ? r.json() : null)).catch(() => null));

export function parsePr(s) {
  const m = /github\.com\/([\w.-]+)\/([\w.-]+)\/pull\/(\d+)/i.exec(s || "") || /^([\w.-]+)\/([\w.-]+)#(\d+)$/.exec((s || "").trim());
  return m ? { owner: m[1], repo: m[2], number: Number(m[3]) } : null;
}

// A repository named instead of a pull request: owner/repo, or its github.com address (a trailing path, .git and
// a query are ignored).
export function parseRepo(s) {
  const t = (s || "").trim();
  const m = /^(?:https?:\/\/)?(?:www\.)?github\.com\/([\w.-]+)\/([\w.-]+?)(?:\.git)?(?:[/?#].*)?$/i.exec(t) || /^([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/.exec(t);
  return m ? { owner: m[1], repo: m[2] } : null;
}

// The caller workflow: exactly examples/knos-workflow.yml (tests/test_ghrelay.py checks they match).
export const WORKFLOW = `# .github/workflows/knos.yml: Knos in this repository. This one file is the whole payment flow: a comment funds an
# issue, and the pull request that closes it is paid when it is merged. It needs no secret, and nothing in this
# repository holds a key or money.
#
# What starts it, and what it then does:
#
#   A new comment (\`issue_comment\`).
#       A comment with a line that starts with /knos is a command; any other comment starts no job. The command job
#       runs it and always answers with a comment. \`/knos fund 20\` on an issue puts 20 test USDC in escrow for it;
#       \`/knos help\` lists the rest. Commands are read on issues and on pull requests, from anyone who can comment.
#       Who may give which command is decided by the command itself and, where money moves, by the escrow on
#       Solana, which goes by GitHub's own signature of who commented.
#   A new issue (\`issues\`).
#       An issue whose description has a line \`/knos fund <amount>\` is funded as it is opened.
#   A push (\`push\`).
#       Merging a pull request pushes to the default branch. The settle job finds the pull requests that push merged.
#       For each one that closes a funded issue it checks the bounty's terms at the merged commit (the checks the
#       funder named must have passed there) and, only if they hold, asks GitHub for a signed statement that pays
#       the pull request's author. Pushes to other branches, and tags, start no job.
#       GitHub runs this file as it is at the pushed commit. A push made with a workflow's own token starts no run
#       (GitHub's rule), and a commit message with [skip ci] starts none either. For those, \`/knos settle\` on the
#       merged pull request does the same work.
#   A run started by hand (\`workflow_dispatch\`).
#       Actions > knos > Run workflow, with a merged pull request's number: tries its payment again.
#   The check has finished (\`workflow_run\`).
#       Only with the second, optional file, knos-check.yml (the check on every pull request). When that check ends,
#       GitHub runs this file's copy on the default branch, never the pull request's. The review job repeats the
#       check and, from here, may say the result in one comment on the pull request and remember what it learned
#       (in an issue labelled knos-memory). For an issue funded with acceptance checks (.knos/acceptance/<issue>/)
#       a job that cannot ask for a signed statement runs them against the pull request in a sandbox; only if they
#       pass does another job, which runs none of the pull request's code, ask for the statement that pays.
#       A first-time contributor's check waits for a maintainer's approval, and nothing here runs before it.
#
# What it can do in this repository: read the code, the checks and the workflow runs; write on issues and pull
# requests (it comments, assigns an issue to the person who takes it, and keeps its notes in an issue labelled
# knos-memory); ask GitHub for signed statements about what happened here (id-token). What it cannot do: change
# code, branches, tags, releases or settings. It has no write access to the repository's contents.
#
# Why it is safe to install. It does not use \`pull_request_target\`. No job that can ask for a signed statement
# checks out or runs anything from a pull request, or anything else from this repository: those jobs install Knos
# and read GitHub's own records. The one job that runs a pull request's code (the acceptance checks, in a sandbox)
# has a token that can only read this repository's contents, no secret, and no way to ask for a signed statement.
#
# No secret is needed. The signed statements are posted as comments, and Knos's public relay carries them to Solana
# and pays the transaction fees. They are public on purpose: each names one action and the escrow takes it once.
# Optional: with a repository secret KNOS_RELAY_KEY (a Solana key that holds a little SOL for fees, never a bounty's
# money) the jobs carry their own statements and do not wait for the relay.
#
# The Knos workflows are named by a full commit. The escrow records that commit when a bounty is funded and takes
# the pay token only from the same commit. They accept no inputs, so this file cannot change what they do:
# editing the conditions below only changes when they run. Keep the three names that start with "knos": by them
# Knos tells its own jobs from the checks a bounty can require.
name: knos

on:
  issue_comment:
    types: [created]
  issues:
    types: [opened]
  push:
    branches: ["**"]        # branches, not tags; the settle job's condition keeps the default branch only
  workflow_dispatch:
    inputs:
      pull:
        description: Number of the merged pull request whose payment to try again
        required: true
        type: number
  workflow_run:
    workflows: ["knos check"]
    types: [completed]

permissions: {}

jobs:
  # ---- a /knos comment, or a new issue that funds itself -------------------------------------------------------------
  # (startsWith and contains ignore case, so /Knos counts; fromJSON('"\\n/knos"') is "/knos" at the start of a later line)
  command:
    name: knos command
    if: >-
      (github.event_name == 'issue_comment' &&
       (startsWith(github.event.comment.body, '/knos') || contains(github.event.comment.body, fromJSON('"\\n/knos"')))) ||
      (github.event_name == 'issues' &&
       (contains(github.event.issue.body, '/knos fund') || contains(github.event.issue.body, '/knos bounty')))
    permissions:
      contents: read
      issues: write
      pull-requests: write
      checks: read
      statuses: read
      actions: read
      id-token: write
    uses: drexthealpha/knos-workflows/.github/workflows/fund.yml@bbaf6e1c850bcc1a12954ffe252b100ef67f16b8
    secrets:
      KNOS_RELAY_KEY: \${{ secrets.KNOS_RELAY_KEY }}       # optional: when the repository has none, this passes nothing

  # ---- a merge; a run started by hand; /knos settle or a funded /knos tip on a pull request ---------------------------
  settle:
    name: knos settle
    needs: command    # after the command, when there was one: it says when a payment follows (a tip is funded first)
    if: >-
      !cancelled() && (
        (github.event_name == 'push' && github.ref == format('refs/heads/{0}', github.event.repository.default_branch)) ||
        github.event_name == 'workflow_dispatch' ||
        (github.event_name == 'issue_comment' && needs.command.outputs.settle != ''))
    permissions:
      contents: read
      issues: write
      pull-requests: write
      checks: read
      statuses: read
      actions: read
      id-token: write
    uses: drexthealpha/knos-workflows/.github/workflows/prove.yml@bbaf6e1c850bcc1a12954ffe252b100ef67f16b8
    secrets:
      KNOS_RELAY_KEY: \${{ secrets.KNOS_RELAY_KEY }}       # optional, as above

  # ---- the check on a pull request has finished (only with knos-check.yml installed) ----------------------------------
  # The same permissions as settle: GitHub starts a called workflow only when the calling job grants what every job
  # in it asks for, and the last job of a review signs when the acceptance checks passed.
  review:
    name: knos review
    if: >-
      github.event_name == 'workflow_run' && github.event.workflow_run.event == 'pull_request' &&
      (github.event.workflow_run.conclusion == 'success' || github.event.workflow_run.conclusion == 'failure')
    permissions:
      contents: read
      issues: write
      pull-requests: write
      checks: read
      statuses: read
      actions: read
      id-token: write
    uses: drexthealpha/knos-workflows/.github/workflows/prove.yml@bbaf6e1c850bcc1a12954ffe252b100ef67f16b8
    secrets:
      KNOS_RELAY_KEY: \${{ secrets.KNOS_RELAY_KEY }}       # optional, as above
`;

// The free check alone: exactly examples/knos-check.yml.
export const CHECK_WORKFLOW = `# .github/workflows/knos-check.yml: the Knos check on every pull request. Optional, and it needs no secret: it only
# reads. Paying for merged work is the other file, knos.yml, which works with or without this one.
#
# What starts it, and what it then does:
#
#   A pull request is opened, gets new commits, is reopened, or its title or description is edited (\`pull_request\`).
#       When the description says the tests pass or CI is green, Knos compares that with GitHub's own record of the
#       head commit and fails the status "check / claims" when a check failed. It also applies this repository's
#       CONTRIBUTING rules, and for a pull request that closes a funded issue it says what the payment still needs.
#       It runs none of the pull request's code. The result is the status and the job's summary.
#
# What it can do in this repository: read the code, the pull request, the issue it closes, and the checks and
# workflow runs of its commit. What it cannot do: write anything. Every permission below is read. For a pull
# request from a fork GitHub gives the run a token that can only read, no secret and no id-token whatever a file asks.
#
# How GitHub runs it:
#   - The first run for a first-time contributor's pull request waits until a maintainer approves it, on the pull
#     request's page.
#   - GitHub runs this file as the pull request has it, so a pull request can change the file for its own run. That
#     is why this check is advice and nothing about money depends on it: knos.yml checks again at the merge, from
#     the default branch.
#   - Keep the name "knos check". knos.yml waits for a workflow of that name, to repeat the check where it may
#     comment on the pull request.
#
# To require the check before a merge: Settings > Rules > New branch ruleset > Require status checks > add
# "check / claims".
name: knos check

on:
  pull_request:
    types: [opened, synchronize, reopened, edited]

permissions: {}

jobs:
  check:
    permissions:
      contents: read
      pull-requests: read
      issues: read
      checks: read
      statuses: read
      actions: read
    uses: drexthealpha/knos-workflows/.github/workflows/check.yml@bbaf6e1c850bcc1a12954ffe252b100ef67f16b8
`;

export function checkUrl(owner, repo, branch) {
  return `https://github.com/${owner}/${repo}/new/${encodeURIComponent(branch)}?filename=.github/workflows/knos-check.yml&value=${encodeURIComponent(CHECK_WORKFLOW)}`;
}

export function protectUrl(owner, repo, branch) {
  return `https://github.com/${owner}/${repo}/new/${encodeURIComponent(branch)}?filename=.github/workflows/knos.yml&value=${encodeURIComponent(WORKFLOW)}`;
}

// GitHub has no URL to prefill a ruleset's required checks: this opens a new active branch ruleset; the one extra
// step is "Require status checks to pass" > add "check / claims" (the check knos-check.yml reports) > Create.
export function rulesetUrl(owner, repo) {
  return `https://github.com/${owner}/${repo}/settings/rules/new?target=branch&enforcement=active`;
}

// The reusable workflows a file calls, read from the file itself (never typed here): [{ repo, file, ref }].
export function pinsOf(text) {
  return [...String(text).matchAll(/^[ \t]*uses:[ \t]*([\w.-]+\/[\w.-]+)\/\.github\/workflows\/([\w.-]+)@(\S+)[ \t]*$/gm)]
    .map((m) => ({ repo: m[1], file: m[2], ref: m[3] }));
}

// A file may be handed out only when every workflow it calls is named by a full commit: a branch, a tag or the
// placeholder before a release would run code nobody chose, or nothing at all.
export const pinned = (text) => { const p = pinsOf(text); return p.length > 0 && p.every((x) => /^[0-9a-f]{40}$/.test(x.ref)); };

// What the two files call, said from the files themselves.
export function workflowFacts() {
  const el = $("workflow-facts");
  if (!el) return;
  const said = (file, text) => {
    const pins = pinsOf(text), refs = [...new Set(pins.map((p) => `${p.repo}@${p.ref}`))];
    const calls = pins.map((p) => `<code>${esc(p.file)}</code>`).join(" and ");
    const at = refs.map((r) => { const [repo, ref] = r.split("@"); return /^[0-9a-f]{40}$/.test(ref)
      ? `${esc(repo)} at commit <a href="https://github.com/${esc(repo)}/commit/${ref}"><code>${ref.slice(0, 7)}</code></a>`
      : `${esc(repo)} at <code>${esc(ref)}</code>, which is a placeholder: no release has named the commit yet`; }).join("; ");
    return `<code>${file}</code> calls ${calls} of ${at}`;
  };
  el.innerHTML = `<p class="fine">${said("knos.yml", WORKFLOW)}; ${said("knos-check.yml", CHECK_WORKFLOW)}. A bounty records that
    commit when it is funded, and the escrow takes the pay token only from the same commit.</p>`;
}

// The files themselves, to read or to copy where a prefilled link is not wanted.
const copyBox = (ready) => `<details id="protect-copy"><summary class="fine">${ready ? "Copy the files instead" : "Read the files"}</summary>
  <p class="fine"><code>.github/workflows/knos.yml</code></p><pre>${esc(WORKFLOW)}</pre>
  <p class="fine"><code>.github/workflows/knos-check.yml</code> (optional)</p><pre>${esc(CHECK_WORKFLOW)}</pre></details>`;

export function protectRepo(ev) {
  ev?.preventDefault();
  const m = /^(?:https:\/\/github\.com\/)?([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/.exec(($("protect-repo")?.value || "").trim());
  const out = $("protect-result");
  if (!m) { out.innerHTML = `<p class="status bad">Enter the repository as owner/repo.</p>`; return; }
  const [, o, r] = m;
  const branch = $("protect-branch")?.value.trim() || "main";
  if (!pinned(WORKFLOW) || !pinned(CHECK_WORKFLOW)) {
    out.innerHTML = `<p class="status bad">This copy of the page has no published workflow commit yet. The files below name a placeholder where
      the commit goes, so GitHub would refuse them, and the links that prefill them are off until a release names the commit.</p>${copyBox(false)}`;
    return;
  }
  out.innerHTML = `<a class="button" id="protect-open" href="${esc(protectUrl(o, r, branch))}" target="_blank" rel="noopener">1. Commit knos.yml to ${esc(o)}/${esc(r)}</a>
    <a class="button quiet" id="protect-check" href="${esc(checkUrl(o, r, branch))}" target="_blank" rel="noopener">2. Optional: commit knos-check.yml</a>
    <p class="fine">GitHub opens its "new file" page with the file filled in and asks you to commit it to <code>${esc(branch)}</code>.
      The first file is the whole payment flow. The second checks every pull request's "tests pass" against GitHub's record;
      it moves no money. To require that check before a merge:
      <a id="protect-rules" href="${esc(rulesetUrl(o, r))}" target="_blank" rel="noopener">open a new ruleset</a>,
      then "Require status checks to pass" and add <code>check / claims</code>.</p>${copyBox(true)}`;
}

// ---- UI ------------------------------------------------------------------------------------------------------------
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const CI_TEXT = { passed: "passed", failed: "FAILED", pending: "still running", "no-ci": "no CI ran", other: "no clear result (cancelled or waiting)" };

// One agent's counts in index.json. Two counts, each under the name of what it counts (scripts/agent_pr_index.py):
// any_check_failed (a failed check of any kind, a deploy preview or a label gate included) and
// test_or_build_check_failed (a failed check that is, by its name, a test or a build). An index published before both
// had names (claimed_green, actually_failed, by_repo) carries only the first; it is read as that.
export function agentCounts(a) {
  if (a.any_check_failed) {
    const r = a.first_pr_per_repo;
    return { prs: a.prs, any: a.any_check_failed.prs, tests: a.test_or_build_check_failed?.prs ?? null,
      repos: r?.repos || 0, repoAny: r?.any_check_failed?.repos ?? 0, repoTests: r?.test_or_build_check_failed?.repos ?? null };
  }
  const r = a.by_repo;
  return { prs: a.claimed_green, any: a.actually_failed, tests: null, repos: r?.repos || 0, repoAny: r?.failed ?? 0, repoTests: null };
}

// k of n as a percentage and its 95% Wilson interval, rounded once from the counts (the file's own `share` and `ci95`
// are already rounded to four places; rounding those again can land a tenth off).
const share = (k, n) => `${((100 * k) / n).toFixed(1)}%`;
function interval(k, n) {
  const z = 1.96, p = k / n, d = 1 + (z * z) / n;
  const mid = (p + (z * z) / (2 * n)) / d, half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return `${(100 * Math.max(0, mid - half)).toFixed(1)}%–${(100 * Math.min(1, mid + half)).toFixed(1)}%`;
}

export function agentRecord(index, agent) {
  if (!index) return `<p class="fine">Agent PR Index not loaded here (it is built with the site).</p>`;
  const a = agent && index.agents?.[agent];
  if (!a) return `<p class="fine">No record for ${agent ? esc(agent) : "this author"} in the Agent PR Index (${esc(index.date || "")}).</p>`;
  const c = agentCounts(a);
  const tests = (k, n, what) => (k == null || !n ? "" : ` In <strong>${k}</strong> of the ${n} ${what} (${share(k, n)}) a failed check was a test or a build, by its name.`);
  const all = c.prs ? `Counting every such pull request: ${c.any} of ${c.prs} (${share(c.any, c.prs)}).` : "";
  const lead = c.repos
    ? `in <strong>${c.repos}</strong> repositories, its first pull request that said tests pass had a failing check of any kind in
       <strong>${c.repoAny}</strong> (<strong>${share(c.repoAny, c.repos)}</strong>, 95% interval ${interval(c.repoAny, c.repos)}).${tests(c.repoTests, c.repos, "repositories")} ${all}`
    : `said tests pass on <strong>${c.prs}</strong> pull requests with finished CI; a check of any kind had failed on
       <strong>${c.any}</strong>${c.prs ? ` (<strong>${share(c.any, c.prs)}</strong>, 95% interval ${interval(c.any, c.prs)})` : ""}.${tests(c.tests, c.prs, "pull requests")}`;
  return `<p><strong>${esc(agent)}</strong> in the Agent PR Index (${esc(index.date)}): ${lead}${index.excluded_self_repo
    ? ` Pull requests on the author's own repositories are left out (${index.excluded_self_repo}).` : ""}</p>`;
}

// What the Agent PR Index (index.json, already loaded) holds for one repository: how many agent pull requests said
// tests pass, how many had a failing check, per agent, and each one. No request but index.json.
function repoRecord(index, ref) {
  const name = `${ref.owner}/${ref.repo}`, single = `Paste a pull request link above to check a single pull request.`;
  if (!index) return `<div id="repo-record"><p class="fine">Agent PR Index not loaded here (it is built with the site). ${single}</p></div>`;
  const prs = (Array.isArray(index.prs) ? index.prs : []).filter((p) => String(p.repo).toLowerCase() === name.toLowerCase());
  if (!prs.length) {
    return `<div id="repo-record"><p class="status">No agent pull requests for ${esc(name)} in the Agent PR Index (${esc(index.date || "")}).
      ${single}</p></div>`;
  }
  const failed = (p) => p.class === "failed", by = {};
  for (const p of prs) (by[p.agent || "unknown agent"] ??= []).push(p);
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  return `<div id="repo-record">
    <p><strong>${esc(name)}</strong> in the Agent PR Index (${esc(index.date || "")}): <strong>${plural(prs.length, "agent pull request")}</strong>
      that said tests pass, <strong>${prs.filter(failed).length} had a failing check</strong>.</p>
    <ul>${Object.entries(by).map(([a, l]) => `<li>${esc(a)}: ${l.filter(failed).length} of ${l.length} had a failing check</li>`).join("")}</ul>
    <ul>${prs.map((p) => `<li><a href="https://github.com/${esc(p.repo)}/pull/${esc(p.number)}">${esc(p.repo)}#${esc(p.number)}</a>
      (${esc(p.agent || "unknown agent")}): ${esc(CI_TEXT[p.class] || p.class)}${(p.failed_checks || []).length
        ? ` (${p.failed_checks.slice(0, 8).map(esc).join(", ")})` : ""}, said “${esc(p.phrase || "")}”</li>`).join("")}</ul>
    <p class="fine">${single}</p></div>`;
}

async function check(ev) {
  ev?.preventDefault();
  const out = $("pr-result"), ref = parsePr($("pr-url").value), repoRef = ref ? null : parseRepo($("pr-url").value);
  if (repoRef) { out.innerHTML = repoRecord(await loadIndex(), repoRef); return; }
  if (!ref) { out.innerHTML = `<p class="status bad">Paste a PR link like https://github.com/owner/repo/pull/123, or owner/repo to see a repository's record</p>`; return; }
  out.innerHTML = `<p class="status">Reading GitHub…</p>`;
  const base = `/repos/${ref.owner}/${ref.repo}`;
  try {
    // All reads in parallel: refs/pull/N/head is the PR's head commit, so CI needs no wait for the PR's SHA.
    const head = `${base}/commits/refs/pull/${ref.number}/head`;
    let [pr, cr, st, index] = await Promise.all([gh(`${base}/pulls/${ref.number}`),
      gh(`${head}/check-runs?per_page=100`), gh(`${head}/status`), loadIndex()]);
    const sha = pr.head.sha;
    if (st.sha && st.sha !== sha) {  // pushed to between the reads: read CI at the PR's SHA
      [cr, st] = await Promise.all([gh(`${base}/commits/${sha}/check-runs?per_page=100`), gh(`${base}/commits/${sha}/status`)]);
    }
    const claim = findClaim(pr.body), ci = ciVerdict(cr.check_runs || [], st.statuses || []), agent = agentOf(pr);
    let verdict, cls;
    if (!claim) { verdict = "No tests-pass claim in the PR description"; cls = ""; }
    else if (ci.cls === "failed") { verdict = "claim FALSE"; cls = "bad"; }
    else if (ci.cls === "passed") { verdict = "claim true"; cls = "ok"; }
    else { verdict = "claim unproven"; cls = ""; }
    const repo = pr.base.repo;
    out.innerHTML = `
      <p id="verdict" class="verdict ${cls}" data-verdict="${esc(verdict)}">${esc(verdict)}</p>
      <dl class="facts">
        <dt>PR</dt><dd><a href="${esc(pr.html_url)}">${esc(repo.full_name)}#${pr.number}</a> by ${esc(pr.user.login)}${agent ? ` (${esc(agent)})` : ""}</dd>
        <dt>Claims</dt><dd>${claim ? `“${esc(claim.line)}”` : "nothing about tests passing"}</dd>
        <dt>CI at <code>${esc(sha.slice(0, 7))}</code></dt><dd>${esc(CI_TEXT[ci.cls])}${ci.failed.length
          ? `: ${[...new Set(ci.failed)].slice(0, 8).map(esc).join(", ")}` : ""}</dd>
      </dl>
      ${agentRecord(index, agent)}
      <a class="button" id="check-protect" href="#protect=${encodeURIComponent(`${repo.full_name}@${repo.default_branch}`)}">Protect ${esc(repo.full_name)}</a>
      <p class="fine">One workflow file makes a funded issue's payment run on this repository: the merged pull request
        is paid when the funder's checks passed at the merged commit, as the workflow reads them from GitHub, and Solana has
        checked GitHub's signature of that workflow run. An optional second
        file runs this same check on every pull request. Fee: 2.5%, only when someone is paid.</p>`;
  } catch (e) {
    out.innerHTML = e instanceof RateLimited
      ? `<p class="status bad">GitHub's free limit for this network is used up (60 reads an hour without login).
         Try again after ${esc(e.message || "an hour")}, or open the PR's
         <a href="https://github.com/${esc(ref.owner)}/${esc(ref.repo)}/pull/${ref.number}/checks">checks on GitHub</a>.</p>`
      : `<p class="status bad">Could not read that PR: ${esc(e.message)}</p>`;
  }
}

if (typeof document !== "undefined" && $("pr-form")) {
  $("pr-form").addEventListener("submit", check);
  $("pr-url").addEventListener("paste", () => setTimeout(() => check(), 0));
  $("protect-form")?.addEventListener("submit", protectRepo);
  workflowFacts();
  loadIndex();
}
