// The Agent PR Index's own rules, in the browser: what counts as a "tests pass" claim, how a head commit's checks are
// classed, and which failed checks are tests or builds. A port of scripts/agent_pr_ci.py (find_claim, verdict,
// is_testish_failure). The patterns below are Python's, character for character; `py` makes each one mean in
// JavaScript what it means in Python (\w, \b and \d are Unicode there). tests/test_check_rules.py holds them equal to
// the Python source and runs both on the recorded pull requests of docs/agent_pr_ci.json: they must agree.
// No DOM and no network here: web/check.js reads GitHub and draws.

export const PY = {
  CLAIM: String.raw`(?:\ball\s+(?:\w+\s+){0,2}tests?\s+(?:are\s+|now\s+)*(?:pass(?:es|ed|ing)?|green)|\btests?\s+(?:are\s+|now\s+|still\s+)*(?:pass(?:es|ed|ing)?|green)\b|\btests?\b[^\n.]{0,40}?\band\s+passing\b|\bCI\b(?:[\s:/,]+(?:is|are|now|run|runs|job|jobs|checks?|build|pipeline|workflows?|all|CD|#?\d+))*[\s:,]+(?:pass(?:es|ed|ing)?|green)\b|\b(?:all\s+(?:CI\s+)?checks?|(?:CI\s+)?checks)\s+(?:are\s+|have\s+)?(?:pass(?:es|ed|ing)?|green)\b|\bpass(?:es|ed|ing)?\s+all\s+(?:\w+\s+){0,2}(?:tests|checks|CI)\b|` + "`[^`\\n]*test[^`\\n]*`" + String.raw`\s*(?:[-:—]\s*)?(?:all\s+)?(?:pass(?:es|ed|ing)?|green)\b|\b\d[\d,]*\s*(?:/\s*\d[\d,]*\s*)?(?:\w+\s+){0,2}passed\b|✅\s*[^\n]{0,40}?\btests?\b|\btests?\b[^\n]{0,30}?✅)`,
  NONCLAIM: String.raw`^[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)+\[ \](?:[ \t]|$)|\b(ensure|make sure|verify that|should|would|will|to confirm|until|once|if|before|whether|need|needs|must|expect|expected|todo|not|fail|fails|failing|failed|failure|failures|errors?|except|unless|pending|flaky|skip|red|broken)\b|n't\b`,
  BOILER: String.raw`\*\*Your PR cannot be merged unless tests pass\*\*|\bfail[- ](?:closed|safe|fast|open)\b|\b0 failed\b`,
  AGENT_RUN: String.raw`^(copilot|claude|claude[-_ ]?(code|review|code[-_ ]review|pr[-_ ]review)|codex|devin)$`,
  TESTISH: String.raw`test|build|compil|\bci\b|unit|integration|e2e|pytest|jest|vitest|lint|clippy|rustfmt|fmt|typecheck|tsc|linux|windows|macos|ubuntu|cargo|gradle|maven|mvn|smoke|julia|python|node|run:|benchmark|analy[sz]e`,
  ANCILLARY: String.raw`vercel|netlify|cloudflare|workers builds|deploy|publish|label|\bcla\b|metadata|commitlint|contributor|review|lighthouse|snyk|codecov|sonar|security|audit|title|changelog|governance|evidence|non-empty|gate|lifecycle|compliance|aegis|ci-success`,
};

// Python's \w is a letter, a number or "_" of any script; \d a decimal digit of any script; \s also takes \x1c-\x1f
// and not U+FEFF. JavaScript's are ASCII (\w, \b, \d) or a little different (\s), so each is spelled out.
const W = String.raw`\p{L}\p{N}_`, S = String.raw`\s\x1c-\x1f\x85`;
export function py(source, flags = "") {
  let out = "", inClass = false;
  for (let i = 0; i < source.length; i++) {
    const c = source[i];
    if (c === "\\") {
      const e = source[++i];
      if (e === "w") out += inClass ? W : `[${W}]`;
      else if (e === "W" && !inClass) out += `[^${W}]`;
      else if (e === "d") out += String.raw`\p{Nd}`;
      else if (e === "s") out += inClass ? S : String.raw`(?:(?!\uFEFF)[${S}])`;
      else if (e === "b") out += `(?:(?<=[${W}])(?![${W}])|(?<![${W}])(?=[${W}]))`;
      else out += `\\${e}`;
      continue;
    }
    if (c === "[" && !inClass) inClass = true;
    else if (c === "]" && inClass) inClass = false;
    out += c;
  }
  return new RegExp(out, `u${flags}`);
}

export const CLAIM_RE = py(PY.CLAIM, "i");
export const NONCLAIM_RE = py(PY.NONCLAIM, "i");
const BOILER_RE = py(PY.BOILER, "gi");
export const AGENT_RUN_RE = py(PY.AGENT_RUN, "i");
export const TESTISH_RE = py(PY.TESTISH, "i");
export const ANCILLARY_RE = py(PY.ANCILLARY, "i");
const FAIL_CONCL = new Set(["failure", "timed_out", "startup_failure"]);
const OK_CONCL = new Set(["success", "neutral", "skipped"]);

// str.splitlines() and str.strip() of Python, and its slicing by code point
const LINES = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/u;
const SPACE = String.raw`(?:(?!\uFEFF)[${S}])+`, ENDS = new RegExp(`^${SPACE}|${SPACE}$`, "gu");
const strip = (s) => s.replace(ENDS, "");
const cut = (s, n) => Array.from(s).slice(0, n).join("");

export function stripBody(body) {
  return (body || "").replace(/<!--[\s\S]*?-->/g, " ").replace(
    /<details>\s*<summary>[^<]*(original prompt|original issue)[^<]*<\/summary>[\s\S]*?<\/details>/giu, " ");
}

/** The first line of a description that claims tests or CI pass: { phrase, line }, or null. find_claim of Python. */
export function findClaim(body) {
  const text = stripBody(body), lines = text.split(LINES);
  if (lines.length && lines[lines.length - 1] === "" && text !== "") lines.pop();
  for (const line of lines) {
    const m = CLAIM_RE.exec(line);
    if (!m || NONCLAIM_RE.test(line.replace(BOILER_RE, " "))) continue;
    return { phrase: strip(m[0]), line: cut(strip(line), 200) };
  }
  return null;
}

/** Every failed check at a head commit, by name: the project's check runs that failed, then failed commit statuses. */
export function failedNames(runs, statuses) {
  return runs.filter((x) => !AGENT_RUN_RE.test(strip(x.name)) && FAIL_CONCL.has(x.conclusion)).map((x) => x.name)
    .concat(statuses.filter((s) => s.state === "failure" || s.state === "error").map((s) => s.context));
}

/** The class of a head commit from its check runs ({name, status, conclusion}), its commit statuses ({context, state})
 *  and its check suites ({conclusion}): verdict() of Python, field for field. */
export function verdict(runs, statuses, suites = []) {
  const agent = runs.filter((x) => AGENT_RUN_RE.test(strip(x.name))), ci = runs.filter((x) => !AGENT_RUN_RE.test(strip(x.name)));
  const concl = ci.filter((x) => x.status === "completed").map((x) => x.conclusion);
  const pending = ci.filter((x) => x.status !== "completed"), states = statuses.map((s) => s.state);
  const failed = failedNames(runs, statuses);
  const awaiting = suites.filter((s) => s.conclusion === "action_required");
  let cls;
  if (failed.length) cls = "failed";
  else if (!ci.length && !statuses.length) cls = awaiting.length ? "blocked-awaiting-approval" : "no-ci";
  else if (pending.length || states.includes("pending")) cls = "pending";
  else if (concl.every((c) => OK_CONCL.has(c)) && states.every((s) => s === "success")) cls = "passed";
  else cls = "other";
  return { n_check_runs: ci.length, n_agent_runs_excluded: agent.length, n_statuses: statuses.length,
    failed_checks: failed.slice(0, 10), awaiting_approval_suites: awaiting.length, class: cls,
    other_conclusions: [...new Set(concl.filter((c) => !OK_CONCL.has(c)))].sort() };
}

/** A failed check that is, by its name, a test, build, lint or type-check job and not a deploy, a gate or a bot. */
export const isTestish = (name) => TESTISH_RE.test(name) && !ANCILLARY_RE.test(name);
/** Every failed check (not only the first ten), split as the index splits them. */
export const byClass = (failed) => ({ test: failed.filter(isTestish), other: failed.filter((n) => !isTestish(n)) });

/** The answer in one line, from a claim (findClaim) and a class (verdict) and its failed checks split (byClass). */
export function sentence(claim, cls, split) {
  const said = claim ? "Claims tests pass" : "Claims nothing about tests";
  if (cls === "failed" && split.test.length) return `${said}; a test or build check failed.`;
  if (cls === "failed") return `${said}; only checks that test nothing failed.`;
  if (cls === "passed") return `${said}; every check passed.`;
  if (cls === "pending") return `${said}; checks still running. Check again soon.`;
  if (cls === "no-ci") return `${said}; no check ran at the head commit.`;
  if (cls === "blocked-awaiting-approval") return `${said}; checks wait for a maintainer to approve them.`;
  return `${said}; no check failed, some did not finish.`;
}

/** A public pull request named as a github.com link, owner/repo#123 or owner/repo/123 (the form a #check= link uses). */
export function parsePr(s) {
  const t = String(s || "").trim();
  const m = /^(?:https?:\/\/)?(?:www\.)?github\.com\/([\w.-]+)\/([\w.-]+)\/pull\/(\d+)(?:[/?#].*)?$/i.exec(t) ||
    /^([\w.-]+)\/([\w.-]+)(?:#|\/(?:pull\/)?)(\d+)$/.exec(t);
  return m && m[1] !== "." && m[1] !== ".." ? { owner: m[1], repo: m[2], number: Number(m[3]) } : null;
}
