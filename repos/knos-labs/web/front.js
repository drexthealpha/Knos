// Front door: paste an agent PR, see in seconds whether its "tests pass" claim is true -- from GitHub's own CI at the
// PR's head commit, read in the browser with the public GitHub REST API (no login, no install). The claim regexes are
// ported from scripts/agent_pr_ci.py (the Agent PR Index uses the same ones), so the page and the index agree.

const $ = (id) => document.getElementById(id);
const API = "https://api.github.com";
// Knos's reusable workflows, pinned by full commit sha (the escrow checks the token's job_workflow_sha).
export const KNOS_SHA = "d8ead42dbf120024afda78bed0602077689c279d";
export const KNOS_RELAY_SHA = "d8ead42dbf120024afda78bed0602077689c279d";

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

// The caller workflow: exactly examples/knos-workflow.yml (tests/test_ghrelay.py checks they match).
export const WORKFLOW = `# .github/workflows/knos.yml - Knos on GitHub, with no secret, wallet or faucet in this repo.
#
# "Protect this repo" (https://drexthealpha.github.io/Knos/) prefills this file. Then:
#   1. A maintainer writes the acceptance tests for issue N in .knos/acceptance/N/ on the default branch and comments
#          /knos bounty <amount> [stake]
#      on the issue. fund.yml mints a GitHub OIDC token bound to (issue, amount, hash of those tests, stake); relay.yml
#      posts it; Knos's always-on worker funds the escrow with it (Knos pays the gas) and the issue gets
#      "knos-job: <id>".
#   2. An agent opens a pull request whose body says "Fixes #N" and "knos-payout: <Solana address>". prove.yml runs
#      the pull request's code against the base branch's checks in a job with no token and no secret; only if they
#      pass does a second job, which runs no pull request code, mint a token bound to (job, head commit, checks,
#      payout). relay.yml posts it, the worker proves it on chain, the payout address is paid, and the pull request
#      gets the verdict and the receipt link.
#
# Security model:
#   - pull_request_target runs THIS file from the base branch, so a pull request cannot edit what runs here. This file
#     checks out nothing and reads the pull request body only through environment variables.
#   - Knos's workflows are referenced by full commit sha; the escrow checks job_workflow_sha, so a token minted by any
#     other workflow (or another commit of these) is refused.
#   - /knos bounty counts only from OWNER, MEMBER or COLLABORATOR (fund.yml).
#   - Tokens posted as comments are single-use, audience-bound and expire in about 5 minutes (relay.yml).
#   - To make the Knos check required before merge: Settings > Rules > New branch ruleset > Require status checks >
#     add "prove / check" (the Protect page links there).
name: knos

on:
  pull_request_target:
    types: [opened, synchronize, reopened, edited]
  issue_comment:
    types: [created]

permissions: {}

jobs:
  # ---- /knos bounty <amount> [stake] on an issue ------------------------------------------------------------------
  fund:
    if: github.event_name == 'issue_comment' && !github.event.issue.pull_request && startsWith(github.event.comment.body, '/knos bounty ')
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
      kind: fund
      number: \${{ fromJSON(needs.fund.outputs.issue) }}

  # ---- a pull request that says "Fixes #N" and "knos-payout: <address>" ------------------------------------------
  job:
    if: github.event_name == 'pull_request_target'
    runs-on: ubuntu-latest
    permissions:
      issues: read
    outputs:
      id: \${{ steps.id.outputs.id }}
      payout: \${{ steps.id.outputs.payout }}
      issue: \${{ steps.id.outputs.issue }}
    steps:
      - id: id
        env:
          BODY: \${{ github.event.pull_request.body }}
          GH_TOKEN: \${{ github.token }}
        run: |
          issue=$(printf '%s\\n' "$BODY" | grep -oiE '\\b(fixes|closes|resolves)[[:space:]]+#[0-9]+' | head -1 | grep -oE '[0-9]+$' || true)
          payout=$(printf '%s\\n' "$BODY" | grep -oE '^knos-payout:[[:space:]]*[1-9A-HJ-NP-Za-km-z]{32,44}' | head -1 | grep -oE '[1-9A-HJ-NP-Za-km-z]{32,44}$' || true)
          # a job posted from the web app (PostGithub) is named in the body; the escrow binds it to this repo and ref
          id=$(printf '%s\\n' "$BODY" | grep -oiE '^knos-job:[[:space:]]*[0-9a-f]{64}' | head -1 | grep -oiE '[0-9a-f]{64}$' | tr 'A-F' 'a-f' || true)
          if [ -z "$id" ] && [ -n "$issue" ] && [ -n "$payout" ]; then
            # the job id fund-relay posted on the issue (only this repo's own workflow comments as github-actions[bot])
            id=$(gh api "repos/$GITHUB_REPOSITORY/issues/$issue/comments?per_page=100" \\
                   --jq '.[] | select(.user.login == "github-actions[bot]") | .body' \\
                 | grep -oE 'knos-job: [0-9a-f]{64}' | tail -1 | cut -d' ' -f2 || true)
          fi
          echo "issue=$issue" >> "$GITHUB_OUTPUT"
          echo "payout=$payout" >> "$GITHUB_OUTPUT"
          echo "id=$id" >> "$GITHUB_OUTPUT"
          echo "issue=#$issue payout=$payout job=$id"

  prove:
    needs: job
    if: needs.job.outputs.id != ''
    permissions:
      contents: read
      id-token: write
    uses: drexthealpha/Knos/.github/workflows/prove.yml@${KNOS_SHA}
    with:
      job: \${{ needs.job.outputs.id }}
      issue: \${{ needs.job.outputs.issue }}
      knos-ref: ${KNOS_SHA}

  prove-relay:
    needs: prove
    permissions:
      issues: write
      pull-requests: write
    uses: drexthealpha/Knos/.github/workflows/relay.yml@${KNOS_RELAY_SHA}
    with:
      kind: proof
      number: \${{ github.event.pull_request.number }}

  prove-refused:
    needs: [job, prove]
    if: always() && needs.job.outputs.id != '' && needs.prove.result == 'failure'
    permissions:
      issues: write
      pull-requests: write
    uses: drexthealpha/Knos/.github/workflows/relay.yml@${KNOS_RELAY_SHA}
    with:
      kind: refused
      number: \${{ github.event.pull_request.number }}
`;

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
  out.innerHTML = `<a class="button" id="protect-open" href="${esc(protectUrl(o, r, $("protect-branch")?.value || "main"))}" target="_blank" rel="noopener">Commit .github/workflows/knos.yml to ${esc(o)}/${esc(r)}</a>
    <p class="fine">Then <a id="protect-rules" href="${esc(rulesetUrl(o, r))}" target="_blank" rel="noopener">make the Knos check required</a>
      (one extra click on GitHub: Require status checks &gt; add "prove / check").</p>`;
}

// ---- UI ------------------------------------------------------------------------------------------------------------
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const CI_TEXT = { passed: "passed", failed: "FAILED", pending: "still running", "no-ci": "no CI ran", other: "no clear result (cancelled or waiting)" };

function agentRecord(index, agent) {
  if (!index) return `<p class="fine">Agent PR Index not loaded here (it is built with the site).</p>`;
  const a = agent && index.agents?.[agent];
  if (!a) return `<p class="fine">No record for ${agent ? esc(agent) : "this author"} in the Agent PR Index (${esc(index.date || "")}).</p>`;
  const pct = (x) => `${(x * 100).toFixed(1)}%`;
  const share = a.share == null ? "n/a" : pct(a.share);
  const ci = a.ci95 ? `, 95% interval ${pct(a.ci95[0])}–${pct(a.ci95[1])}` : "";
  return `<p><strong>${esc(agent)}</strong> in the Agent PR Index (${esc(index.date)}): claimed tests pass on
    <strong>${a.claimed_green}</strong> PRs with CI; CI actually failed on <strong>${a.actually_failed}</strong>
    (<strong>${share}</strong>${ci}). Paid on a verified proof by <strong>${a.proven ?? 0}</strong> distinct
    funder${a.proven === 1 ? "" : "s"}.${index.excluded_self_repo ? ` PRs on the author's own repos are excluded
    (${index.excluded_self_repo}).` : ""}</p>`;
}

async function check(ev) {
  ev?.preventDefault();
  const out = $("pr-result"), ref = parsePr($("pr-url").value);
  if (!ref) { out.innerHTML = `<p class="status bad">Paste a PR link like https://github.com/owner/repo/pull/123</p>`; return; }
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
      <p class="fine">Adds one workflow file; GitHub asks you to commit it. "Make it required" opens GitHub's ruleset page:
        Require status checks &gt; add "prove / check" (one extra click). From then on an agent is paid only when
        GitHub's own signature, checked by Solana, proves its PR passed. 2.5% fee, only on proven work.</p>`;
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
