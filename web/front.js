// Front door: paste an agent PR, see in seconds whether its "tests pass" claim is true -- from GitHub's own CI at the
// PR's head commit, read in the browser with the public GitHub REST API (no login, no install). The claim regexes are
// ported from scripts/agent_pr_ci.py (the Agent PR Index uses the same ones), so the page and the index agree.

const $ = (id) => document.getElementById(id);
const API = "https://api.github.com";
// Knos's reusable workflows, pinned by full commit sha: a bounty records that sha on chain when it is funded, and
// knos-pay refuses a token from any other commit. The Pages build (network.yml) writes the commit it was built from
// in place of the placeholder, so the site always hands out the workflows of its own commit.
export const KNOS_SHA = "KNOS_COMMIT_SHA";
export const KNOS_RELAY_SHA = "KNOS_COMMIT_SHA";

// ---- claim detection (port of scripts/agent_pr_ci.py) -----------------------------------------------------------
const PASS = String.raw`(?:pass(?:es|ed|ing)?|green)`;
const CLAIM_RE = new RegExp(
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
const NONCLAIM_RE = new RegExp(
  String.raw`- \[ \]|\b(ensure|make sure|verify that|should|would|will|to confirm|until|` +
  String.raw`once|if|before|whether|need|needs|must|expect|expected|todo|not|` +
  String.raw`fail|fails|failing|failed|failure|failures|errors?|except|unless|pending|flaky|skip|` +
  String.raw`red|broken)\b|n't\b`, "i");
const BOILER_RE = new RegExp(String.raw`\*\*Your PR cannot be merged unless tests pass\*\*|` +
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
export const WORKFLOW = `# .github/workflows/knos.yml - Knos on GitHub, with no secret, wallet or faucet in this repo.
#
# "Protect this repo" (https://drexthealpha.github.io/Knos/) prefills this file. Then:
#   1. A maintainer comments on issue N (or writes the same line in a new issue's description):
#          /knos bounty <amount>
#      fund.yml asks GitHub for a token that says so; relay.yml posts it; anyone (Knos's always-on worker does) carries
#      it to Solana, where knos-oidc checks GitHub's signature and knos-pay opens the bounty. Knos pays the gas.
#   2. Someone opens a pull request whose body says "Fixes #N". No wallet, no address. prove.yml's check job runs
#      on it: the repo's own rules, and whether a "tests pass" in its description is true at its head commit.
#   3. A maintainer merges it. prove.yml runs that same check once more at the merged head and, only if it holds,
#      asks GitHub for a token that says "pull request by GitHub user U closing issue N was merged"; on Solana the
#      bounty is held for U's GitHub account and released an hour later (until then /knos veto on the issue takes
#      it back; "/knos bounty <amount> review 0" pays at once). A pull request an agent opened under a bot account
#      pays the person who ran it. U claims it whenever they like, to any address: knos claim <address>, or
#      https://drexthealpha.github.io/Knos/#claim.
#      An issue that is assigned to someone pays only their pull request; an unassigned one is open to anyone.
#   Optional, pay without waiting for a merge: put acceptance checks for issue N in .knos/acceptance/N/ on the default
#   branch before funding. prove.yml then runs them against each pull request in a sandbox, in a job with no token
#   and no secret, and only if they pass does a second job, which runs no pull request code, mint the token. That
#   payment waits a review window (default 24 hours) in which /knos veto takes it back.
#
# Security model:
#   - pull_request_target runs THIS file from the base branch, so a pull request cannot edit what runs here. This file
#     checks out nothing and reads the pull request body only through environment variables.
#   - Knos's workflows are referenced by full commit sha. A bounty pins that sha on chain when it is funded, and
#     knos-pay refuses a token from any other workflow or any other commit of these. The judge prove.yml runs is
#     the code at that same commit; this file cannot choose another.
#   - /knos bounty and /knos veto count only from OWNER, MEMBER or COLLABORATOR (fund.yml).
#   - Tokens posted as comments name one action each and are accepted for at most an hour (relay.yml).
#   - To make the Knos check required before merge: Settings > Rules > New branch ruleset > Require status checks >
#     add "prove / check" (the Protect page links there).
name: knos

on:
  pull_request_target:
    types: [opened, synchronize, reopened, edited, closed]
  issue_comment:
    types: [created]
  issues:
    types: [opened]

permissions: {}

jobs:
  # ---- /knos bounty <amount>, /knos veto on an issue ---------------------------------------------------------------
  fund:
    if: >-
      (github.event_name == 'issue_comment' && !github.event.issue.pull_request &&
       (startsWith(github.event.comment.body, '/knos bounty ') || startsWith(github.event.comment.body, '/knos veto'))) ||
      (github.event_name == 'issues' && contains(github.event.issue.body, '/knos bounty '))
    permissions:
      contents: read
      id-token: write
    uses: drexthealpha/Knos/.github/workflows/fund.yml@${KNOS_SHA}

  fund-relay:
    needs: fund
    if: needs.fund.outputs.issue != ''
    permissions:
      issues: write
      pull-requests: write
    uses: drexthealpha/Knos/.github/workflows/relay.yml@${KNOS_RELAY_SHA}
    with:
      kind: \${{ needs.fund.outputs.kind }}
      number: \${{ fromJSON(needs.fund.outputs.issue) }}

  # ---- a pull request that says "Fixes #N" -------------------------------------------------------------------------
  job:
    if: github.event_name == 'pull_request_target'
    runs-on: ubuntu-latest
    outputs:
      issue: \${{ steps.id.outputs.issue }}
    steps:
      - id: id
        env:
          BODY: \${{ github.event.pull_request.body }}
        run: |
          issue=$(printf '%s\\n' "$BODY" | grep -oiE '\\b(fixes|closes|resolves)[[:space:]]+#[0-9]+' | head -1 | grep -oE '[0-9]+$' || true)
          echo "issue=$issue" >> "$GITHUB_OUTPUT"
          echo "issue=#$issue"

  prove:
    needs: job
    if: needs.job.outputs.issue != ''
    permissions:
      contents: read
      checks: read
      issues: read
      id-token: write
    uses: drexthealpha/Knos/.github/workflows/prove.yml@${KNOS_SHA}
    with:
      issue: \${{ needs.job.outputs.issue }}

  prove-relay:
    needs: prove
    if: needs.prove.outputs.passed == 'true'
    permissions:
      issues: write
      pull-requests: write
    uses: drexthealpha/Knos/.github/workflows/relay.yml@${KNOS_RELAY_SHA}
    with:
      kind: proof
      number: \${{ github.event.pull_request.number }}

  prove-refused:
    needs: [job, prove]
    if: always() && needs.job.outputs.issue != '' && needs.prove.result == 'failure'
    permissions:
      issues: write
      pull-requests: write
    uses: drexthealpha/Knos/.github/workflows/relay.yml@${KNOS_RELAY_SHA}
    with:
      kind: refused
      number: \${{ github.event.pull_request.number }}
`;

// The free check alone: exactly examples/knos-check.yml.
export const CHECK_WORKFLOW = `# .github/workflows/knos-check.yml - the free Knos check on every pull request. No bounty, no money, no chain.
#
# When a pull request's description says its tests pass or CI is green, Knos compares that with GitHub's own record of
# the head commit and fails the status "check / claims" when a check failed. It also applies this repository's
# CONTRIBUTING rules and remembers what was caught before. It runs none of the pull request's code.
#
# Security: pull_request_target runs THIS file from the base branch, so a pull request cannot edit what runs here; the
# job has contents: read and checks: read and nothing else; the Knos workflow is referenced by full commit sha.
# To require it before merge: Settings > Rules > New branch ruleset > Require status checks > add "check / claims".
name: knos check

on:
  pull_request_target:
    types: [opened, synchronize, reopened, edited]

permissions: {}

jobs:
  check:
    permissions:
      contents: read
      checks: read
    uses: drexthealpha/Knos/.github/workflows/check.yml@${KNOS_SHA}
`;

export function checkUrl(owner, repo, branch) {
  return `https://github.com/${owner}/${repo}/new/${encodeURIComponent(branch)}?filename=.github/workflows/knos-check.yml&value=${encodeURIComponent(CHECK_WORKFLOW)}`;
}

export function protectUrl(owner, repo, branch) {
  return `https://github.com/${owner}/${repo}/new/${encodeURIComponent(branch)}?filename=.github/workflows/knos.yml&value=${encodeURIComponent(WORKFLOW)}`;
}

// GitHub has no URL to prefill a ruleset's required checks: this opens a new active branch ruleset; the one extra
// step is "Require status checks to pass" > add "prove / check" > Create.
export function rulesetUrl(owner, repo) {
  return `https://github.com/${owner}/${repo}/settings/rules/new?target=branch&enforcement=active`;
}

function protectRepo(ev) {
  ev?.preventDefault();
  const m = /^(?:https:\/\/github\.com\/)?([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/.exec(($("protect-repo")?.value || "").trim());
  const out = $("protect-result");
  if (!m) { out.textContent = "Enter owner/repo"; return; }
  const [, o, r] = m;
  const branch = $("protect-branch")?.value || "main";
  out.innerHTML = `<a class="button" id="protect-open" href="${esc(protectUrl(o, r, branch))}" target="_blank" rel="noopener">Check and pay: commit knos.yml to ${esc(o)}/${esc(r)}</a>
    <a class="button quiet" id="protect-check" href="${esc(checkUrl(o, r, branch))}" target="_blank" rel="noopener">Check only, no money: commit knos-check.yml</a>
    <p class="fine">Both check every pull request's "tests pass" against GitHub's record and run none of its code. With the
      first, fund an issue by commenting <code>/knos bounty 20</code> on it (<a href="#bounty">or open a funded issue</a>).
      Optional: <a id="protect-rules" href="${esc(rulesetUrl(o, r))}" target="_blank" rel="noopener">make the Knos check required</a>
      (on GitHub: Require status checks &gt; add "prove / check", or "check / claims" for the check alone).</p>`;
}

// ---- UI ------------------------------------------------------------------------------------------------------------
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const CI_TEXT = { passed: "passed", failed: "FAILED", pending: "still running", "no-ci": "no CI ran", other: "no clear result (cancelled or waiting)" };

function agentRecord(index, agent) {
  if (!index) return `<p class="fine">Agent PR Index not loaded here (it is built with the site).</p>`;
  const a = agent && index.agents?.[agent];
  if (!a) return `<p class="fine">No record for ${agent ? esc(agent) : "this author"} in the Agent PR Index (${esc(index.date || "")}).</p>`;
  const pct = (x) => `${(x * 100).toFixed(1)}%`;
  const ci = (c) => (c ? `, 95% interval ${pct(c[0])}–${pct(c[1])}` : "");
  const all = `Counting every such pull request: ${a.actually_failed} of ${a.claimed_green}${a.share == null ? "" : ` (${pct(a.share)})`}.`;
  const r = a.by_repo;
  const lead = r && r.repos
    ? `in <strong>${r.repos}</strong> repositories, its first pull request that said tests pass had a failing check in
       <strong>${r.failed}</strong> (<strong>${pct(r.share)}</strong>${ci(r.ci95)}). ${all}`
    : `said tests pass on <strong>${a.claimed_green}</strong> pull requests with finished CI; a check had failed on
       <strong>${a.actually_failed}</strong> (<strong>${a.share == null ? "n/a" : pct(a.share)}</strong>${ci(a.ci95)}).`;
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
      <a class="button" id="protect" href="${esc(protectUrl(repo.owner.login, repo.name, repo.default_branch))}" target="_blank" rel="noopener">Protect ${esc(repo.full_name)}</a>
      <a class="button" href="${esc(rulesetUrl(repo.owner.login, repo.name))}" target="_blank" rel="noopener">Make it required</a>
      <p class="fine">Adds one workflow file; GitHub asks you to commit it. From then on, a pull request that closes a
        funded issue gets a Knos check that reads its description the way this page just did, and a bounty is paid
        only when GitHub's own signature, checked by Solana, proves the pull request was merged (or passed the
        funder's checks). "Make it required" opens GitHub's ruleset page: Require status checks &gt; add
        "prove / check". 2.5% fee, only when someone is paid.</p>`;
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
  loadIndex();
}
