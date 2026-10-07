// Terms proposed from a repository's own record, in the browser: the same reading as src/knos/propose_terms.py.
//
//   proposeTerms(repo, env)   -> { repo, terms, hash, from, last_merge, merges, comment, file }
//
// It reads a public repository through GitHub's public REST API with no sign-in (at most 17 requests; GitHub allows
// 60 an hour to a reader who has not signed in): its last 10 merged pull requests and the check runs of each, its
// top-level folders, its workflow files and its CODEOWNERS file. The checks that passed on every recent merge become
// the deciding checks, its test directories become protected paths, and everything else is the template's default.
// Every field carries the lines that say where it came from. A proposal is a draft: nothing is funded or posted.
// Nothing is proposed for a repository with no merge in the last 30 days, and the date of the last merge is said.
//
// `env`: { get(path) } another reader (the tests give a recorded one: parsed JSON, or null for a 404), { now } the
// time in seconds. tests/data/propose_terms.json holds this file and the Python module to one answer, hash included.
export const STANDARD = "Knos Terms 3";
export const API = "https://api.github.com/";
export const MERGES = 10, FRESH_DAYS = 30, FILE = ".knos/terms.json";
export const FIELDS = [
  ["deliverable", "What is one deliverable?"], ["evidence", "Whose signature counts?"], ["checks", "What decides?"],
  ["window", "How long can it be reopened?"], ["changes", "What may change?"], ["dispute", "Who may appeal, and to whom?"],
  ["evaluators", "Who may judge?"], ["price", "What does it pay?"], ["deadline", "When does it end?"], ["policy", "Who may change these terms?"],
];
const GITHUB = "https://token.actions.githubusercontent.com";
const ISSUERS = { [GITHUB]: "GitHub Actions", "https://gitlab.com": "GitLab CI" };
const WORKFLOWS = "drexthealpha/knos-workflows/.github/workflows/", PROVE = `${WORKFLOWS}prove.yml`, ATTEST = `${WORKFLOWS}attest.yml`;
const DENY = [".github/**", ".knos/**"], ACTIONS = 15368, ANY = -1, STATUS = 0, MAX_BYTES = 600;
const TEST_DIRS = ["__tests__", "e2e", "spec", "specs", "test", "testing", "tests"];
const CODEOWNERS = [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"];
const KNOS_JOBS = /^(?:prove|fund)(?:-relay|-refused)? \/ |^knos| \/ claims$/;
const REPO = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}$/, NAMED = /^[a-z0-9][a-z0-9._-]{0,39}\/[a-z0-9][a-z0-9._-]{0,39}$/i;
const OWNER = /^@[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:\/[A-Za-z0-9._-]{1,60})?$/;
const KINDS = {
  "pull-request": "One deliverable is the accepted pull request for one issue. A new commit, or another pull request for the same issue, is a retry: the same deliverable, judged again and counted once.",
  batch: "One deliverable is one batch file, named by its sha256. The same bytes sent again are a duplicate and counted once; changed bytes are a new attempt at the same batch number.",
  resolution: "One deliverable is one ticket resolved. A ticket reopened inside the window is the same deliverable, not a new one.",
};

export class Refused extends Error {}

const ordered = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const uniq = (list) => [...new Set(list)].sort(ordered);
const days = (n) => `${n} day${n === 1 ? "" : "s"}`;
const ticks = (names, none = "none") => (names.length ? names.map((n) => `\`${n}\``).join(", ") : none);
const check = (c) => `\`${c.name}\`` + (c.app === STATUS ? " (a commit status)" : c.app === ANY ? " (any source)" : ` (GitHub App ${c.app})`);

// The plain line of one field, written from its facts: word for word what knos.terms3.say writes for a built document.
export function say(field, d) {
  if (field === "deliverable") return `${KINDS[d.kind]} There is one for each ${d.one_per}.`;
  if (field === "evidence") return `Evidence counts only when signed by ${d.sources.map((s) => `${ISSUERS[s.issuer]} for a run of ${s.workflow}`).join("; or by ")}.`;
  if (field === "checks") {
    const by = d.mode === "merge" ? "A maintainer's merge decides" : `The acceptance suite decides (its files hash to ${d.accept.slice(0, 12)})`;
    const after = d.deciding.length ? `, after ${d.deciding.map(check).join(" and ")} pass${d.deciding.length === 1 ? "es" : ""} at the last commit` : ", and no named check has to pass";
    return `${by}${after}.${d.image ? ` The suite runs in the image ${d.image}.` : ""} The authoritative copy: ${d.authority}.`;
  }
  if (field === "window") {
    return d.warranty_days ? `${d.holdback_percent}% of the payment waits ${days(d.warranty_days)} in the order and goes back to the funder if the change is reverted in that time. What was already paid stays paid.`
      : "Payment is final when it is made: nothing is held back, and accepted work cannot be reopened.";
  }
  if (field === "changes") {
    return (d.paths.length ? `Only files matching ${ticks(d.paths)} may change.` : "Any file may change.")
      + (d.protected.length ? ` No change may touch ${ticks(d.protected)}.` : " No path is protected.")
      + (d.may_add.length ? ` Without asking, a contributor may add files matching ${ticks(d.may_add)}.` : " A contributor may add nothing outside that without the buyer's say.");
  }
  if (field === "dispute") {
    const who = d.evaluator === "arbiter"
      ? "There is no suite to run again. " + (d.arbiter ? `@${d.arbiter}, the arbiter, rules, and that ruling ends the appeal. ` : "No arbiter is named, so a rejection stands unless both sides agree on one. ")
      : `The evaluator \`${d.evaluator}\` runs the work again itself, and its verdict ends the appeal. `;
    return `The supplier may appeal a rejection within ${days(d.within_days)} of it, with \`/knos appeal <reason>\`. ${who}Meanwhile the money stays in the order. With no verdict by the deadline, the money goes back to its funder.`;
  }
  if (field === "evaluators") {
    const rows = d.list.map((e) => `\`${e.name}\` (${ISSUERS[e.issuer]}, workflow ${e.workflow}, in ${e.repository === "*" ? "any repository that neither party owns" : `${e.repository}, owned by ${e.owner}`})`).join("; ");
    return `These may judge: ${rows}. ${d.quorum === 1 ? "One of them is enough." : `${d.quorum} of them must accept the same work, and their owners differ.`}`;
  }
  if (field === "price") return `Pays ${d.amount} ${d.currency}, once, for an accepted deliverable. The funder pays the fee on top.`;
  if (field === "deadline") return `The order is open for ${days(d.days)} from funding, or less if the funder cancels, which takes 7 days' notice. A token presented after that is refused, and the money goes back to its funder.`;
  if (field === "policy") return `${d.may_change.join(", ")} may publish a new version. A version never changes: a change is the next version, with its own hash, and an order keeps the version it was funded on.`;
  throw new Error(field);
}

// JSON with sorted keys, no spaces, ASCII only: the bytes knos.terms3.canonical hashes.
export function canonicalJson(value) {
  const walk = (v) => (Array.isArray(v) ? `[${v.map(walk).join(",")}]`
    : v && typeof v === "object" ? `{${Object.keys(v).sort(ordered).map((k) => `${JSON.stringify(k)}:${walk(v[k])}`).join(",")}}` : JSON.stringify(v));
  return walk(value).replace(/[^\x00-\x7e]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

export async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// The sha256 of a terms 3 document as it stands (published files and proposals are already in canonical order).
export const digest = (doc) => sha256Hex(canonicalJson(doc));
// The ten questions a document answers, from the lines it carries.
export const questions = (doc) => FIELDS.map(([field, question]) => ({ field, question, answer: doc?.[field]?.says || "" }));
export const missing = (doc) => FIELDS.map(([f]) => f).filter((f) => !doc || typeof doc[f] !== "object" || !doc[f] || typeof doc[f].says !== "string");

// The comment that funds an order on a document.
export function comment(doc) {
  let line = `/knos fund ${doc.price.amount.replace(/\.00$/, "")} checks: ${doc.checks.deciding.map((c) => c.name).join(", ") || "none"}`;
  if (doc.changes.paths.length) line += ` paths: ${doc.changes.paths.join(", ")}`;
  if (doc.window.holdback_percent) line += ` holdback ${doc.window.holdback_percent} warranty ${doc.window.warranty_days}`;
  if (doc.evaluators.quorum > 1) line += ` quorum ${doc.evaluators.quorum}`;
  if (doc.dispute.arbiter) line += ` arbiter @${doc.dispute.arbiter}`;
  return `${line} days ${doc.deadline.days}`;
}

// The 600-byte terms an order on this document is funded on: what must fit.
const orderTerms = (doc, hash) => canonicalJson({ accept: doc.checks.accept, checks: doc.checks.deciding.map((c) => ({ app: c.app, name: c.name })),
  contract: hash, deny: uniq([...DENY, ...doc.changes.protected]), mode: doc.checks.mode, paths: doc.changes.paths, reserve: 7, v: 1 });

function finish(doc) {
  const out = { standard: STANDARD, v: 3, name: doc.name, version: doc.version };
  for (const [field] of FIELDS) out[field] = { ...doc[field], says: say(field, doc[field]) };
  return out;
}

const stateOf = (run) => (run.status !== "completed" ? "pending" : run.conclusion === "success" ? "passed" : ["skipped", "neutral"].includes(run.conclusion) ? "skipped" : "failed");
const RANK = { failed: 0, pending: 1, passed: 2, skipped: 3 };
const together = (states) => states.reduce((a, b) => (RANK[b] < RANK[a] ? b : a));

// (the checks that passed on every merge that could be read, the ones that did not and why): knos.propose_terms.passing.
export function passing(merges) {
  const read = merges.filter((m) => m.runs !== null), seen = new Map();
  for (const m of read) {
    for (const run of m.runs) {
      if (!run || typeof run.name !== "string" || KNOS_JOBS.test(run.name)) continue;
      const id = run.app?.id, app = Number.isInteger(id) && id > 0 ? id : ANY, key = JSON.stringify([run.name, app]);
      if (!seen.has(key)) seen.set(key, { name: run.name, app, by: new Map() });
      const by = seen.get(key).by;
      by.set(m.number, [...(by.get(m.number) || []), stateOf(run)]);
    }
  }
  const keep = [], dropped = [];
  for (const { name, app, by } of [...seen.values()].sort((a, b) => ordered(a.name, b.name) || a.app - b.app)) {
    const bad = [...by.keys()].sort((a, b) => a - b).filter((n) => together(by.get(n)) !== "passed");
    if (by.size === read.length && !bad.length) keep.push({ name, app });
    else if (bad.length) dropped.push(`\`${name}\` did not pass on #${bad[0]}${bad.length > 1 ? ` and ${bad.length - 1} more` : ""}`);
    else dropped.push(`\`${name}\` ran on ${by.size} of ${read.length} merges`);
  }
  return [keep, dropped];
}

// Who a CODEOWNERS file names for everything: the owners of its last `*` line.
export function owners(text) {
  let found = [];
  for (const line of text.split(/\r?\n/)) {
    const parts = line.split("#")[0].trim().split(/\s+/).filter(Boolean);
    if (parts[0] === "*") found = parts.slice(1).filter((p) => OWNER.test(p));
  }
  return uniq(found);
}

const publicGet = async (path) => {
  const r = await fetch(API + path, { headers: { Accept: "application/vnd.github+json" } });
  if (r.status === 404) return null;
  if (r.status === 403 || r.status === 429) throw new Refused("GitHub allows 60 answers an hour without signing in. Try again later.");
  if (!r.ok) throw new Refused(`GitHub did not answer (${r.status}).`);
  return r.json();
};

export async function proposeTerms(repoGiven, env = {}) {
  const get = env.get || publicGet, now = env.now ?? Date.now() / 1000, template = "bug-fix";
  let repo = String(repoGiven).trim().replace(/^https:\/\/github\.com\//, "").replace(/^\/+|\/+$/g, "");
  if (!REPO.test(repo)) throw new Refused("Name the repository as owner/name, like octocat/hello-world.");
  const info = await get(`repos/${repo}`);
  if (!info || typeof info !== "object" || !info.full_name) throw new Refused(`${repo} was not found. Only a public repository can be read without signing in.`);
  repo = info.full_name;
  const branch = info.default_branch || "main", owner = repo.split("/")[0];
  if (!NAMED.test(repo)) throw new Refused(`${repo} has a name too long for a terms file to carry.`);
  const pulls = await get(`repos/${repo}/pulls?state=closed&base=${branch}&sort=updated&direction=desc&per_page=100`);
  const merged = (Array.isArray(pulls) ? pulls : []).filter((p) => p && p.merged_at).sort((a, b) => ordered(b.merged_at, a.merged_at)).slice(0, MERGES);
  if (!merged.length) throw new Refused(`${repo} has no merged pull request among its last 100 closed ones, so nothing says which checks decide there. Nothing is proposed.`);
  const last = merged[0].merged_at, age = Math.floor((now - Date.parse(`${last.slice(0, 19)}Z`) / 1000) / 86400);
  if (age > FRESH_DAYS) {
    throw new Refused(`${repo} last merged a pull request on ${last.slice(0, 10)}, ${age} days ago. Nothing is proposed for a repository `
      + `with no merge in the last ${FRESH_DAYS} days: its record is too old to say which checks decide today.`);
  }
  const merges = [];
  for (const p of merged) {
    const got = await get(`repos/${repo}/commits/${p.head?.sha}/check-runs?per_page=100`);
    merges.push({ number: p.number, runs: got && Array.isArray(got.check_runs) ? got.check_runs : null });
  }
  const read = merges.filter((m) => m.runs !== null);
  const [deciding, dropped] = passing(merges);
  const root = await get(`repos/${repo}/contents/?ref=${branch}`);
  const dirs = (Array.isArray(root) ? root : []).filter((e) => e && e.type === "dir" && typeof e.name === "string").map((e) => e.name).sort(ordered);
  const tests = dirs.filter((d) => TEST_DIRS.includes(d.toLowerCase()));
  const listed = await get(`repos/${repo}/contents/.github/workflows?ref=${branch}`);
  const flows = (Array.isArray(listed) ? listed : []).map((e) => String(e?.name || "")).filter((n) => /\.ya?ml$/.test(n)).sort(ordered);
  let who = [], ownersFile = "";
  for (const path of CODEOWNERS) {
    const got = await get(`repos/${repo}/contents/${path}?ref=${branch}`);
    if (got && typeof got.content === "string") {
      try { who = owners(new TextDecoder().decode(Uint8Array.from(atob(got.content.replace(/\s/g, "")), (ch) => ch.charCodeAt(0)))); } catch { who = []; }
      ownersFile = path;
      break;
    }
  }
  const src = Object.fromEntries(FIELDS.map(([f]) => [f, [`Template default (\`${template}\`).`]]));
  src.deliverable = [`Template default (\`${template}\`): one deliverable for each issue of ${repo}.`];
  src.evidence = ["Template default: GitHub signs for a run of the pinned Knos workflows, and nothing else counts."];
  const protectedPaths = tests.map((d) => `${d}/**`);
  src.checks = read.length ? deciding.map((c) => `\`${c.name}\` passed on every one of the last ${read.length} merged pull requests (#${read[read.length - 1].number} to #${read[0].number}).`) : [];
  if (!deciding.length) {
    src.checks.push(read.length ? `No check passed on every one of the last ${read.length} merged pull requests, so a maintainer's merge decides alone. Name a check you trust.`
      : "The check runs of the recent merges could not be read, so no check is named. Name one you trust.");
  }
  src.checks.push(...dropped.slice(0, 8).map((d) => `Left out: ${d}.`), ...(dropped.length > 8 ? [`Left out: ${dropped.length - 8} more.`] : []));
  src.checks.push(flows.length ? `Workflows read: ${flows.join(", ")}.` : "No workflow file was found in .github/workflows.");
  const paths = ["src/**", "tests/**"].filter((g) => dirs.includes(g.slice(0, -3)) && !protectedPaths.includes(g));
  src.changes = tests.length ? tests.map((d) => `\`${d}/\` is a test directory of ${repo}: protected, so the work cannot pass by changing its own tests. Remove the line to let a contributor add tests.`)
    : [`No test directory was found at the top of ${repo}; nothing beyond the default is protected.`];
  src.changes.push("`.github/**` and `.knos/**` are protected in every order: they hold the checks and the terms.");
  src.changes.push(paths.length ? `Template default, kept where ${repo} has the directory: ${paths.join(", ")}.` : "Any other file may change: the template's directories are not all in this repository.");
  src.policy = [who.length ? `\`${ownersFile}\` names ${who.join(", ")} for every file.`
    : ownersFile ? `\`${ownersFile}\` names nobody for every file, so the owner, @${owner}, is proposed.` : `${repo} has no CODEOWNERS file, so the owner, @${owner}, is proposed.`];
  src.dispute = ["Template default: no arbiter is named. Name one neither side controls, or a rejection can only be undone by agreement."];
  src.evaluators = [`Template default: the order's own repository, ${repo}, judges. Add a second owner and \`quorum 2\` if the supplier does not trust it.`];
  const doc = {
    name: repo.toLowerCase(), version: 1,
    deliverable: { kind: "pull-request", one_per: "issue" },
    evidence: { sources: [{ issuer: GITHUB, workflow: ATTEST }, { issuer: GITHUB, workflow: PROVE }] },
    checks: { mode: "merge", deciding, accept: "",
      authority: `${flows.length ? `the ${flows.length} workflow file${flows.length === 1 ? "" : "s"} in .github/workflows of ${repo}` : `the checks GitHub records for ${repo}`} at the commit the order is funded on` },
    window: { warranty_days: 0, holdback_percent: 0 },
    changes: { paths, protected: uniq([...DENY, ...protectedPaths]), may_add: [] },
    dispute: { who: "supplier", evaluator: "arbiter", within_days: 7, money: "order", no_answer: "refund-at-deadline" },
    evaluators: { quorum: 1, list: [{ name: "own", issuer: GITHUB, repository: repo, workflow: PROVE, owner }] },
    price: { amount: "50.00", currency: "test USDC" },
    deadline: { days: 14, late: "refused" },
    policy: { may_change: who.length ? who : [`@${owner}`], how: "new-version" },
  };
  let terms = finish(doc), hash = await digest(terms);
  while (orderTerms(terms, hash).length > MAX_BYTES && doc.checks.deciding.length) {     // an order's terms hold 600 bytes
    const gone = doc.checks.deciding.pop();
    src.checks = [...src.checks.filter((s) => !s.startsWith(`\`${gone.name}\` passed`)), `Left out: \`${gone.name}\` passed every time, and an order's terms have no room for it (600 bytes).`];
    terms = finish(doc); hash = await digest(terms);
  }
  return { repo, terms, hash, from: src, last_merge: last, merges: merged.length, comment: comment(terms), file: FILE };
}
