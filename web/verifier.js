// The verifier, for someone who builds on it: `renderVerifier(el, env)`.
//
// One sentence, then the page itself: the table of issuers (docs/VERIFIER.md and examples/issuers/issuers.json; tests/test_issuers.py
// holds this file to it), each with the algorithms it signs with and, for each algorithm, "accepted today" or "not yet". Below it the
// three calls as blocks to copy, and a tool that decodes a pasted JWT IN THE PAGE and says what the verifier would read of it.
// "Accepted" is about the format (RS256 under a 2048- or 4096-bit key): no row says a live token of that issuer was verified.
//
// The tool sends nothing: this file makes no request of any kind, and keeps nothing. It also verifies nothing. A signature can only be
// checked against the issuer's published key, and this page fetches no key set (the site asks no host but GitHub's API and Solana
// devnet), so every answer says "Decoded, not verified": what is shown is what the token SAYS, and whether the program could take a
// token of that kind. What the program takes is in programs-v2/knos_oidc/src/lib.rs: alg RS256, a signature of 256 or 512 bytes (a
// 2048- or 4096-bit key), at most MAX_JWT bytes, `iss` a string, `exp` a number at most a day ahead. What a program can then gate on
// is what crates/knos-oidc-interface reads: a top-level string, or a whole number of at most 18 digits.
export const PROGRAM = "FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W";      // knos-oidc, second deployment, devnet
export const CHECKED = "2026-10-05";            // the day the table's claims and key sizes were read
export const MAX_JWT = 8192, AHEAD = 86_400, LATE = 3600, KEY_BITS = [2048, 4096];
export const SENTENCE = "Verify any RS256 workload identity on Solana; read it from any program.";
const REPO = "https://github.com/drexthealpha/Knos/blob/main";

// name, where its claims were read, what it signs with, whether knos-oidc verifies it, the claims worth gating on, the claims the
// reader does not read, and how its `iss` looks (to name the issuer of a pasted token). `not`: the algorithms the issuer can also
// sign with that the verifier does not take yet (every issuer here can sign RS256, which it takes).
export const ISSUERS = [
  { id: "github", name: "GitHub Actions", source: "https://docs.github.com/en/actions/reference/security/oidc", signs: "RS256, 2048-bit", verified: "yes",
    gate: ["repository_id", "repository_owner_id", "job_workflow_ref", "job_workflow_sha", "ref", "sha", "event_name", "runner_environment", "aud"], unread: [],
    iss: /^https:\/\/token\.actions\.githubusercontent\.com$/ },
  { id: "gitlab", name: "GitLab CI (gitlab.com)", source: "https://docs.gitlab.com/ci/secrets/id_token_authentication/", signs: "RS256, 2048- and 4096-bit", verified: "yes",
    gate: ["project_id", "namespace_id", "ref_path", "ref_protected", "ci_config_ref_uri", "ci_config_sha", "sha", "runner_environment", "aud"], unread: ["groups_direct"],
    iss: /^https:\/\/gitlab\.com$/ },
  { id: "google", name: "Google Cloud (service account and workload ID tokens)", source: "https://docs.cloud.google.com/docs/authentication/get-id-token", signs: "RS256, 2048-bit",
    verified: "yes", gate: ["sub", "email", "azp", "aud"], unread: ["email_verified"], iss: /^https:\/\/accounts\.google\.com$/ },
  { id: "entra", name: "Microsoft Entra ID (app and managed identity tokens)", source: "https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference",
    signs: "RS256, 2048-bit", verified: "yes", gate: ["tid", "oid", "azp", "aud"], unread: ["roles"],
    iss: /^https:\/\/(login\.microsoftonline\.com\/[0-9a-f-]{36}\/v2\.0|sts\.windows\.net\/[0-9a-f-]{36}\/)$/ },
  { id: "aws", name: "AWS (IAM outbound identity federation)", source: "https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_outbound_token_claims.html",
    signs: "ES384, or RS256 on request", verified: "in part", part: "Ask for RS256.", not: ["ES384"], gate: ["sub", "aud"], unread: ["https://sts.amazonaws.com/"],
    iss: /^https:\/\/[a-z0-9-]+\.tokens\.sts\.global\.api\.aws$/ },
  { id: "kubernetes", name: "Kubernetes service account tokens (EKS, GKE, self-managed)", source: "https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/",
    signs: "RS256 or ECDSA, per cluster", verified: "in part", part: "Gate on sub only.", not: ["ES256", "ES384", "ES512"], gate: ["sub"], unread: ["aud", "kubernetes.io"],
    iss: /^https:\/\/oidc\.eks\.[a-z0-9-]+\.amazonaws\.com\/id\/[A-Za-z0-9]+$/, has: "kubernetes.io" },
  { id: "buildkite", name: "Buildkite", source: "https://buildkite.com/docs/agent/cli/reference/oidc", signs: "RS256, 2048-bit", verified: "yes",
    gate: ["organization_id", "pipeline_id", "build_branch", "build_commit", "step_key", "runner_environment", "aud"], unread: [], iss: /^https:\/\/agent\.buildkite\.com$/ },
  { id: "circleci", name: "CircleCI", source: "https://circleci.com/docs/guides/permissions-authentication/openid-connect-tokens/", signs: "RS256, 2048-bit", verified: "yes",
    gate: ["oidc.circleci.com/project-id", "oidc.circleci.com/vcs-origin", "oidc.circleci.com/vcs-ref", "aud"], unread: ["oidc.circleci.com/context-ids", "oidc.circleci.com/ssh-rerun"],
    iss: /^https:\/\/oidc\.circleci\.com\/org\/[0-9a-f-]{36}$/ },
  { id: "okta", name: "Okta", source: "https://developer.okta.com/docs/api/openapi/okta-oauth/guides/overview/", signs: "RS256, 2048-bit", verified: "yes",
    gate: ["cid", "sub", "aud"], unread: ["scp"], iss: /^https:\/\/[a-z0-9.-]+\.okta(preview)?\.com(\/oauth2\/[A-Za-z0-9]+)?$/ },
  { id: "auth0", name: "Auth0", source: "https://auth0.com/docs/secure/tokens/access-tokens/access-token-profiles", signs: "RS256, 2048-bit", verified: "yes",
    gate: ["sub", "azp", "aud"], unread: [], iss: /^https:\/\/[a-z0-9.-]+\.auth0\.com\/$/ },
  { id: "vercel", name: "Vercel (deployment OIDC tokens)", source: "https://vercel.com/docs/oidc/reference", signs: "RS256, 2048-bit", verified: "yes",
    gate: ["owner_id", "project_id", "environment", "sub", "aud"], unread: [], iss: /^https:\/\/oidc\.vercel\.com(\/[A-Za-z0-9_-]+)?$/ },
];

export const CALLS = [
  { title: "Register an issuer's key by its URL.", lang: "js", code: `import { verifier } from "./settle.js";
const oidc = verifier("${PROGRAM}");
const url = "https://accounts.google.com";      // the issuer's iss
// public: GitHub signed that the rotate workflow found n there
await oidc.registerIssuerKeyIx(payer, url, n, attest, attestKey);
// private: your wallet's word, usable now
await oidc.registerPrivateKeyIx(wallet, url, n);
await oidc.keyParamsIx(payer, url, n);` },
  { title: "Verify a token: write it, then two steps.", lang: "js", code: `import { tokenId, stepPlan } from "./settle.js";
const tid = await tokenId(jwt);
const writes = await oidc.writeIxs(payer, tid, jwt);
const key = await oidc.keyPda(url, n);
const steps = await Promise.all(stepPlan(2048).map((squarings) => oidc.stepIx(payer, tid, key, squarings)));
const account = await oidc.tokenPda(payer, tid);      // verified after the last step` },
  { title: "Read the verified token from your program.", lang: "rust", code: `// knos-oidc-interface: no dependency, no CPI
let tok = Token::read(&token.owner.to_bytes(), &token.try_borrow_data()?, now)?;
tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now)?;
let google = tok.issuer() == ISSUER_OTHER
    && tok.issuer_hash() == Some(&hash(b"https://accounts.google.com").to_bytes());
let ok = google && tok.claim("sub").is_some_and(|v| v.is(SERVICE_ACCOUNT))
    && tok.audience().is_some_and(|a| a.starts_with("my-app:"));` },
];

const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---- decoding, with no browser needed ---------------------------------------------------------------------------------------------
function unb64url(s) {
  if (!/^[A-Za-z0-9_-]*$/.test(s) || s.length % 4 === 1) return null;
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}
function objectOf(part) {
  const bytes = unb64url(part);
  if (!bytes) return null;
  try {
    const v = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    return v && typeof v === "object" && !Array.isArray(v) ? v : null;
  } catch { return null; }
}

/** Whether a program can gate on a claim's value, as crates/knos-oidc-interface reads it: { read, why }. */
export function readable(value) {
  if (typeof value === "string") return /[\u0000-\u001f]/.test(value) ? { read: false, why: "text with a control character" } : { read: true, why: "text" };
  if (typeof value === "number") return Number.isInteger(value) && value >= 0 && value < 1e18 ? { read: true, why: "whole number" } : { read: false, why: "not a whole number" };
  if (typeof value === "boolean") return { read: false, why: "true or false" };
  if (Array.isArray(value)) return { read: false, why: "a list" };
  return value === null ? { read: false, why: "null" } : { read: false, why: "nested" };
}

/** The issuer of the table a token's `iss` (or its shape) names, or null. */
export function issuerOf(claims) {
  const iss = typeof claims?.iss === "string" ? claims.iss : "";
  return ISSUERS.find((i) => i.iss.test(iss)) || ISSUERS.find((i) => i.has && claims && Object.hasOwn(claims, i.has)) || null;
}

/** What a pasted token says and whether knos-oidc could take one like it. Nothing here checks a signature.
 *  { ok: false, error } for text that is not a JWT; else { ok: true, header, claims, alg, algOk, bits, bitsOk, bytes, sizeOk, issuer,
 *  exp: { state: "ok" | "missing" | "ahead" | "late" }, rows: [{ name, value, read, why, known }], lines: [{ ok, text }], takes }. */
export function decode(text, nowS = Math.floor(Date.now() / 1000)) {
  const jwt = String(text ?? "").trim().replace(/^Bearer\s+/i, "");
  if (!jwt) return { ok: false, error: "" };
  const parts = jwt.split(".");
  if (parts.length !== 3) return { ok: false, error: "Paste a signed JWT: three parts, two dots." };
  const header = objectOf(parts[0]), claims = objectOf(parts[1]), sig = unb64url(parts[2]);
  if (!header || !claims || !sig) return { ok: false, error: "Paste a signed JWT: this one does not decode." };
  const alg = typeof header.alg === "string" ? header.alg : "none", algOk = alg === "RS256";
  const bits = sig.length * 8, bitsOk = KEY_BITS.includes(bits), bytes = new TextEncoder().encode(jwt).length, sizeOk = bytes <= MAX_JWT;
  const issuer = issuerOf(claims), issOk = typeof claims.iss === "string" && /^https:\/\/.+/.test(claims.iss) && claims.iss.length <= 200;
  const expOk = readable(claims.exp).read && typeof claims.exp === "number";
  const exp = { state: !expOk ? "missing" : claims.exp > nowS + AHEAD ? "ahead" : nowS >= claims.exp + LATE ? "late" : "ok" };
  const gate = new Set(issuer ? issuer.gate : []);
  const rows = Object.entries(claims).map(([name, value]) => ({ name, value: typeof value === "string" ? value : JSON.stringify(value), ...readable(value), known: gate.has(name) }));
  const lines = [{ ok: algOk, text: algOk ? "Signed RS256: the verifier takes it." : `Signed ${alg}: the verifier does not take it.` }];
  if (algOk) lines.push({ ok: bitsOk, text: bitsOk ? `Signed by a ${bits}-bit key: the verifier takes it.` : `Signed by a ${bits}-bit key: the verifier takes 2048 or 4096.` });
  if (!sizeOk) lines.push({ ok: false, text: `Holds ${bytes.toLocaleString("en-US")} bytes: the verifier takes 8,192.` });
  lines.push(!issOk ? { ok: false, text: "Names no https issuer: the verifier refuses it." }
    : issuer ? { ok: true, text: `Names ${issuer.name} as its issuer.` } : { ok: true, text: "Names an issuer the table lacks: register its key." });
  lines.push({ missing: { ok: false, text: "Carries no numeric exp: the verifier refuses it." }, ahead: { ok: false, text: "Expires over a day ahead: the verifier refuses it." },
    late: { ok: false, text: "Expired over an hour ago: a program refuses it." }, ok: { ok: true, text: "Expires in time: a program can still read it." } }[exp.state]);
  return { ok: true, header, claims, alg, algOk, bits, bitsOk, bytes, sizeOk, issuer, exp, rows, lines,
    takes: algOk && bitsOk && sizeOk && issOk && exp.state !== "missing" && exp.state !== "ahead" };
}

/** A token to try the tool with: Buildkite's documented claims, and 256 bytes that are not a signature. */
export function sample(nowS = Math.floor(Date.now() / 1000)) {
  const b64 = (s) => btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const claims = { iss: "https://agent.buildkite.com", sub: "organization:acme-inc:pipeline:super-duper-app:ref:refs/heads/main:commit:9f3182061f1e2cca4702c368cbc039b7dc9d4485:step:build",
    aud: "my-app:release:v1.2.0", iat: nowS, nbf: nowS, exp: nowS + 300, organization_id: "0184990a-477b-4fa8-9968-496074483cec", pipeline_id: "0184990a-4782-42b5-afc1-16715b10b1b0",
    build_number: 1, build_branch: "main", build_commit: "9f3182061f1e2cca4702c368cbc039b7dc9d4485", step_key: "build_step", runner_environment: "self-hosted" };
  return `${b64(JSON.stringify({ alg: "RS256", typ: "JWT", kid: "sample" }))}.${b64(JSON.stringify(claims))}.${b64("\u0000".repeat(256))}`;
}

// ---- a receipt in five parts ------------------------------------------------------------------------------------------------------
// knos.receipt.parts, in the page: Identity, Execution, Acceptance, Consequence, Assurance, each one line and what stands behind it.
// tests/data/receipt_parts.json holds receipts and the Python's answer; tests/web/verifier.mjs holds this to it, word for word. The
// page does not check the receipt's rules or any signature (`knos receipt explain FILE` does the first, a bundle the second): it READS.
export const FIVE = ["identity", "execution", "acceptance", "consequence", "assurance"];
const TITLES = { identity: "Identity", execution: "Execution", acceptance: "Acceptance", consequence: "Consequence", assurance: "Assurance" };
const ASKS = { identity: "Who produced the evidence?", execution: "Which evaluator ran, on which inputs?", acceptance: "Which agreed test passed?",
  consequence: "What became payable, and to whom?", assurance: "What stayed trusted or outside the evaluation?" };
const VERDICT_WORDS = { accepted: "accepted", rejected: "rejected", insufficient_evidence: "insufficient evidence", disputed: "disputed" };
const LEVEL_WORDS = { reported: "a workflow reported the result", rerun: "an evaluator outside the supplier's control ran the pinned suite again",
  agreed: "two evaluators with different owners each ran the suite and agree", attested: "an attestation of the execution itself stands behind the result" };
const T_ISSUER = "The issuer, for which workflow ran, in which repository and run. It did not sign what the run read, ran or concluded.";
const T_POLICY = "Whoever wrote the terms: the level says how the result was checked, not that the terms asked for the right thing.";
const TRUSTED = {
  reported: [T_ISSUER, "The run that reported the result, and whoever controls its repository, its workflow and its runner: the result is that run's word.",
    "The supplier, as far as the suite ran where the supplier's change could reach it.", T_POLICY],
  rerun: [T_ISSUER, "The one evaluator that ran the suite again, its operator and its runner: nobody else repeated it.", T_POLICY],
  agreed: [T_ISSUER, "That the evaluators which agree are not one party behind accounts nobody declared related: ids and declarations are all that is compared.",
    "The runners the evaluators ran on.", T_POLICY],
};
const T_UNSIGNED = "Whoever keeps the run's own record: no issuer signed it, so not even which workflow ran is authenticated.";
const O = {
  workflow: "The workflow file decides what it reads: the issuer signed which workflow ran, not what it read, ran or concluded.",
  unsigned: "No issuer signed anything: the evidence is the run's own record, and whoever keeps it could have written another.",
  reported: "Nobody outside the supplier's reach ran the checks again: the result is one run's word.",
  merge: "No test decided: the terms name no check, the merge alone was the acceptance, and whoever may merge can accept.",
  mergeToo: "A merge was required beside the named checks: whoever may merge decides when, and whether.",
  seller: (id, kind) => `The evaluator's account is the payee's: account ${id} owns or started the ${kind} run, and is paid by it.`,
  buyer: (id, kind) => `The evaluator's account is the buyer's: account ${id} owns or started the ${kind} run, and funded the order.`,
  ownRepo: "The order's own repository judged: the buyer chose it, and its administrators can accept.",
  oneParty: (why) => `The evaluators are one party: ${why}`,
  terms: "Whether the terms asked for the right thing is outside the evaluation: a passing weak test is a weak acceptance.",
  disputed: "The verdict is contested and not resolved: which side is right is outside this receipt.",
};
const short = (t, keep = 12) => (t.length <= keep ? t : `${t.slice(0, keep)}…`);
function money(units, decimals) {
  const u = BigInt(units), base = 10n ** BigInt(decimals);
  return decimals ? `${u / base}.${String(u % base).padStart(decimals, "0")}` : String(u);
}
function amount(units, decimals) {
  const [whole, part = ""] = money(units, decimals).split(".");
  return `${whole}.${part.replace(/0+$/, "").padEnd(2, "0")}`;
}
function reranSays(x) {
  if (!x) return "";
  const env = x.environment || {};
  const where = [["knos", "knos"], ["runner_os", "on"], ["imageos", "image"], ["imageversion", "version"]].filter(([k]) => env[k]).map(([k, name]) => `${name} ${env[k]}`).join(", ");
  if (!x.reexecuted) return ` By its own run's word, it did not run the acceptance suite: it read the record of the order's repository${where ? ` (${where})` : ""}.`;
  return ` By its own run's word, it ran the acceptance suite itself (${x.assurance}${x.image_digest ? `, image ${x.image_digest}` : ""}${where ? `; ${where}` : ""}).`;
}
/** The level of a version 4 receipt, from its evidence (knos.receipt.assurance_of with nothing declared related). */
function assuranceOf(r) {
  const o = r.evaluator_observed, sellers = new Set(r.payees.map((p) => p.github_id));
  const party = (e) => [e.owner_id, e.actor_id];
  const ran = o.evaluators.filter((e) => e.kind !== "repository" && e.independent_of_seller && !party(e).some((i) => sellers.has(i)) && e.reexecution?.reexecuted === true);
  const was = r.disputed ? r.disputed.contests.verdict : o.verdict;
  const both = was === "accepted" && ran.some((a, n) => ran.slice(n + 1).some((b) => !party(a).some((i) => party(b).includes(i))));
  const level = both ? "agreed" : ran.length ? "rerun" : "reported";
  return { level, trusted: r.issuer_authenticated !== null ? [...TRUSTED[level]] : [T_UNSIGNED, ...TRUSTED[level].slice(1)], declared_related: [] };
}
const SHAPE = ["evaluator_observed", "policy", "amounts", "payees", "evidence_source", "ids", "limitations", "order", "cluster"];

/** A pasted receipt of version 4 or 5 in five parts: { ok: false, error } or { ok: true, version, verdict, authorises_payment, weak,
 *  parts: [{ id, title, asks, line, facts, more }] }, the shape of knos.receipt.parts (its `receipt` digest apart). */
export function receiptParts(r) {
  if (!r || typeof r !== "object" || Array.isArray(r) || r.type !== "knos.acceptance-receipt") return { ok: false, error: "Paste an acceptance receipt: this is another file." };
  if (r.version !== 4 && r.version !== 5) return { ok: false, error: `Read version 4 or 5: this is version ${Number(r.version) || "unknown"}.` };
  if (SHAPE.some((k) => r[k] === undefined || r[k] === null) || (r.version === 5 && !r.assurance)) return { ok: false, error: "Paste the whole receipt: a part is missing." };
  try { return { ok: true, ...partsOf(r) }; } catch { return { ok: false, error: "Paste the whole receipt: a part does not read." }; }
}
function partsOf(r) {
  const o = r.evaluator_observed, a = r.issuer_authenticated, p = r.policy, m = r.amounts, src = r.evidence_source, got = r.ids, d = r.disputed;
  const assured = r.version === 5 ? r.assurance : assuranceOf(r), level = assured.level, verdict = o.verdict;
  let ident, one, more1;
  if (a !== null) {
    const gl = a.provider === "gitlab", cl = a.claims, host = { github: "GitHub", gitlab: "GitLab" }[a.provider];
    ident = { signed: true, issuer: a.issuer, provider: a.provider, repository: cl[gl ? "project_id" : "repository_id"], repository_name: r.repository?.full_name ?? null,
      workflow: cl[gl ? "ci_config_ref_uri" : "job_workflow_ref"], workflow_sha: cl[gl ? "ci_config_sha" : "job_workflow_sha"], run: cl[gl ? "pipeline_id" : "run_id"],
      attempt: gl ? null : cl.run_attempt, started_by: cl[gl ? "user_id" : "actor_id"], runner: cl.runner_environment, token_sha256: a.token_sha256, verified_in: a.verified.transaction };
    one = `${host} signed: workflow ${ident.workflow} ran in repository ${ident.repository}, run ${ident.run}.`;
    more1 = [`Issuer ${a.issuer}; token sha256 ${a.token_sha256}.`, `Workflow file at commit ${ident.workflow_sha}; run started by account ${ident.started_by} on a ${ident.runner} runner.`,
      `The signature was verified on chain in transaction ${ident.verified_in}.`];
  } else {
    ident = { signed: false, issuer: null, provider: null, repository: null, repository_name: null, workflow: null, workflow_sha: null, run: null, attempt: null, started_by: null,
      runner: null, token_sha256: null, verified_in: null, record_sha256: src.reference };
    one = "Nobody signed: the evidence is the run's own record.";
    more1 = [src.reference ? `The run's record has sha256 ${src.reference}.` : "No copy of the run's record is named."];
  }
  const reran = o.evaluators.filter((e) => e.reexecution?.reexecuted === true);
  const images = [...new Set(reran.map((e) => e.reexecution.image_digest).filter(Boolean))].sort();
  const checks = () => o.checks.map((c) => ({ ...c }));
  const execu = { evaluator: o.judge.kind, evaluator_version: o.judge.version, commit: o.artifact.commit, pull_request: o.artifact.pull_request, checks: checks(),
    evaluators: o.evaluators.map((e) => ({ kind: e.kind, repository_id: e.repository_id, owner_id: e.owner_id, actor_id: e.actor_id, runner: e.runner, reexecuted: e.reexecution?.reexecuted ?? null })),
    images, evaluation: got.evaluation };
  const two = `Evaluator ${o.judge.kind}, workflow ${short(o.judge.version)}, read commit ${short(o.artifact.commit)} of pull request ${o.artifact.pull_request}; `
    + (o.evaluators.length ? `${reran.length} of ${o.evaluators.length} ran the suite again.` : "who controls it is not recorded.");
  const more2 = [`Inputs by hash: commit ${o.artifact.commit}; workflow ${o.judge.version}; terms ${p.terms_hash}${images.length ? `; image ${images.join(", ")}.` : "."}`,
    ...o.evaluators.map((e) => `${e.kind}: repository ${e.repository_id}, owner account ${e.owner_id}, started by account ${e.actor_id};${reranSays(e.reexecution) || " how it reached its verdict is not recorded."}`),
    `Evaluation ${got.evaluation}.`];
  const names = o.checks.map((c) => `${c.name}: ${c.conclusion}`).join(", ");
  const test = (p.mode === "tests" ? "the acceptance suite the terms pin" : "a merge") + (names ? `, and the named checks (${names})` : "");
  const accept = { verdict, predicate: { mode: p.mode, checks: checks() }, terms_hash: p.terms_hash, policy_version: p.version, allowed_paths: p.allowed_paths, denied_paths: p.denied_paths,
    contested: d ? { by: d.by.role, was: d.contests.verdict } : null };
  const said = { accepted: `Accepted: ${test} passed`, rejected: `Rejected: ${test} did not pass`, insufficient_evidence: `Not decided: ${test} could not be read`, disputed: `Disputed: ${test} is contested` }[verdict];
  const three = `${said}, under terms ${short(p.terms_hash)}.`;
  const more3 = [`Terms hash ${p.terms_hash}, fixed when the order was funded; policy version ${p.version !== null ? p.version : "not public"}.`,
    ...(d ? [`Contested by the ${d.by.role}: ${d.reason} The verdict before was ${VERDICT_WORDS[d.contests.verdict]}.`] : []),
    ...(p.allowed_paths === null ? [] : [`Paths allowed: ${p.allowed_paths.join(", ") || "any"}; protected: ${(p.denied_paths || []).join(", ") || "none"}.`])];
  const paid = r.transaction !== null, cash = r.cluster === "devnet" ? "test money on devnet" : `mint ${m.mint}`;
  const conseq = { payable: paid && (verdict === "accepted" || verdict === "disputed") ? m.paid : "0", paid: m.paid, of: m.of, fee: m.fee, tip: m.tip, decimals: m.decimals, mint: m.mint, order: r.order,
    payees: r.payees.map((x) => ({ ...x })), transaction: paid ? r.transaction.signature : null, deliverable: got.deliverable, settlement: got.settlement, invoice_line: got.invoice_line };
  const to = r.payees.map((x) => (x.github_id ? `account ${x.github_id}` : `wallet ${short(x.to)}`)).join(", ") || "nobody named";
  const four = paid ? `${amount(m.paid, m.decimals)} of ${amount(m.of, m.decimals)} paid to ${to} (${cash}), order ${short(r.order)}.`
    : `Nothing became payable: order ${short(r.order)} holds ${amount(m.of, m.decimals)} (${cash}).`;
  const more4 = [`Order ${r.order}; deliverable ${got.deliverable}.`,
    ...(paid ? [`Paying transaction ${r.transaction.signature}; fee ${amount(m.fee, m.decimals)}, tip ${amount(m.tip, m.decimals)}, on top of the amount.`] : ["No payment is recorded: this receipt authorises none."]),
    ...(paid ? r.payees.map((x) => `${amount(x.amount, m.decimals)} to ${x.to}${x.github_id ? ` (account ${x.github_id}, ${Number((x.bps / 100).toPrecision(6))}%).` : "."}`) : []),
    ...(paid && d ? ["A payment recorded before the dispute stays recorded: the money moved."] : [])];
  // what stayed trusted or outside: the sentences that make it weak, then the ones every receipt carries (knos.receipt.outside_of)
  const c = r.commercial_authorisation || {}, sellers = new Set(r.payees.map((x) => x.github_id));
  const buyers = new Set([c.funder?.github_id, c.source?.owner_id].filter(Boolean));
  const weak = [...(a === null ? [O.unsigned] : []), ...(level === "reported" ? [O.reported] : []), ...(p.mode === "merge" && !o.checks.length ? [O.merge] : [])];
  for (const e of o.evaluators) {
    const ids = [...new Set([e.owner_id, e.actor_id])];
    weak.push(...ids.filter((i) => sellers.has(i)).map((i) => O.seller(i, e.kind)));
    if (e.kind !== "repository") weak.push(...ids.filter((i) => buyers.has(i)).map((i) => O.buyer(i, e.kind)));
  }
  if (o.same_controller) weak.push(O.oneParty(o.independence));
  const always = [...(d ? [O.disputed] : []), ...(a !== null ? [O.workflow] : []), ...(p.mode === "merge" && o.checks.length ? [O.mergeToo] : []),
    ...(o.evaluators.some((e) => e.kind === "repository") ? [O.ownRepo] : []), O.terms];
  const assure = { level, level_says: LEVEL_WORDS[level], weak: weak.length > 0, weak_because: weak, outside: [...weak, ...always], trusted: [...assured.trusted],
    declared_related: assured.declared_related, limitations: [...r.limitations] };
  const five = weak.length ? `WEAK (${level}): ${weak[0]}${weak.length > 1 ? ` And ${weak.length - 1} more.` : ""}` : `${level[0].toUpperCase()}${level.slice(1)}: ${LEVEL_WORDS[level]}. ${always[0]}`;
  const more5 = [...weak.map((s) => `Weak because: ${s}`), ...always.map((s) => `Outside the evaluation: ${s}`), ...assured.trusted.map((s) => `Still trusted: ${s}`), ...r.limitations.map((s) => `Not shown: ${s}`)];
  const lines = [one, two, three, four, five], facts = [ident, execu, accept, conseq, assure], more = [more1, more2, more3, more4, more5];
  return { kind: "knos-receipt-parts", v: 1, receipt: null, version: r.version, verdict, authorises_payment: verdict === "accepted", weak: weak.length > 0,
    parts: FIVE.map((id, n) => ({ id, title: TITLES[id], asks: ASKS[id], line: lines[n], facts: facts[n], more: more[n] })) };
}

/** The five rows: each one line, and a fold that holds what stands behind it. */
export function partsHtml(got, esc = escHtml) {
  if (!got.ok) return got.error ? `<p class="status bad" data-parts="unread">${esc(got.error)}</p>` : "";
  const row = (p) => `<details class="k-more" data-part="${p.id}"${p.id === "assurance" && got.weak ? ' data-weak="yes"' : ""}>
    <summary style="display:flex;flex-wrap:wrap;overflow-wrap:anywhere;min-width:0"><strong>${esc(p.title)}</strong> <span style="min-width:0;overflow-wrap:anywhere">${esc(p.line)}</span></summary>
    <p class="fine">${esc(p.asks)}</p><ul class="plain">${p.more.map((s) => `<li style="overflow-wrap:anywhere">${esc(s)}</li>`).join("")}</ul></details>`;
  return `<p class="status ${got.weak ? "bad" : "ok"}" data-parts="${got.weak ? "weak" : "read"}"><strong>${got.weak ? "Read: a weak acceptance." : "Read, not verified."}</strong> Verdict: ${esc(VERDICT_WORDS[got.verdict])}.</p>
    <div id="vf-parts" data-not-prose>${got.parts.map(row).join("")}</div>`;
}

// ---- the page ---------------------------------------------------------------------------------------------------------------------
const names = (list, esc) => list.map((n) => `<code>${esc(n)}</code>`).join(" ");

/** What the table says of one issuer today: [{ alg, today }], RS256 first. */
export function today(issuer) {
  return [{ alg: "RS256", today: true }, ...(issuer.not || []).map((alg) => ({ alg, today: false }))];
}

function issuerTable(esc) {
  const accepted = (i) => `<span class="status ok">RS256: accepted today.</span>${i.not ? ` <span class="status bad">${esc(i.not.join(", "))}: not yet.</span>` : ""}${i.part ? ` ${esc(i.part)}` : ""}`;
  const row = (i) => `<tr data-issuer="${esc(i.id)}"><th scope="row"><a href="${esc(i.source)}" target="_blank" rel="noopener">${esc(i.name)}</a></th><td>${esc(i.signs)}</td>
    <td>${accepted(i)}</td><td>${names(i.gate, esc)}</td><td>${names(i.unread, esc)}</td>
    <td><a href="${REPO}/examples/issuers/${esc(i.id)}/README.md" target="_blank" rel="noopener">Open</a></td></tr>`;
  return `<div class="k-table"><table><caption>Read on ${CHECKED}, from each issuer's pages and keys. No live token.</caption>
    <thead><tr><th scope="col">Issuer</th><th scope="col">Signs with</th><th scope="col">Accepted today</th><th scope="col">Gate on</th><th scope="col">Not read</th><th scope="col">Example</th></tr></thead>
    <tbody>${ISSUERS.map(row).join("")}</tbody></table></div>`;
}

function result(d, esc) {
  if (!d.ok) return d.error ? `<p class="status bad">${esc(d.error)}</p>` : "";
  const short = (v) => (v.length > 96 ? `${v.slice(0, 96)}…` : v);
  const head = Object.entries(d.header).map(([k, v]) => `<code>${esc(k)}: ${esc(short(typeof v === "string" ? v : JSON.stringify(v)))}</code>`).join(" ");
  const claim = (r) => `<tr><th scope="row"><code>${esc(r.name)}</code></th><td><code>${esc(short(r.value))}</code></td>
    <td class="${r.read ? "status ok" : "status bad"}">${r.read ? (r.known ? "Yes: gate on it" : "Yes") : `No: ${esc(r.why)}`}</td></tr>`;
  return `<p class="status" id="vf-verdict"><strong>Decoded, not verified.</strong></p>
    <ul class="plain" id="vf-lines">${d.lines.map((l) => `<li class="k-step" data-state="${l.ok ? "done" : "bad"}">${esc(l.text)}</li>`).join("")}</ul>
    <div class="fine" id="vf-header">${head}</div>
    <div class="k-table"><table id="vf-claims"><thead><tr><th scope="col">Claim</th><th scope="col">Says</th><th scope="col">A program can gate on it</th></tr></thead>
    <tbody>${d.rows.map(claim).join("")}</tbody></table></div>`;
}

/** Fills `el` with the builders' page. `env`: { esc, ids } of web/app.js, both optional; `env.now()` (seconds) holds the clock in tests. */
export function renderVerifier(el, env = {}) {
  if (!el) return;
  const esc = env.esc || escHtml, program = env.ids?.knos_oidc || PROGRAM, now = env.now || (() => Math.floor(Date.now() / 1000));
  const calls = CALLS.map((c, n) => `<section class="k-card vf-call" data-tilt><p class="k-kicker">Call ${n + 1}</p><h3>${esc(c.title)}</h3>
    <pre><code data-lang="${c.lang}">${esc(c.code.replaceAll(PROGRAM, program))}</code></pre><button type="button" class="k-btn quiet" data-copy="call-${n}">Copy</button></section>`).join("");
  el.innerHTML = `<p class="k-kicker" id="vf-sentence">${esc(SENTENCE)}</p>
    <h2>Verify a signed workload identity</h2>
    <p id="vf-who">No outside program reads it yet.</p>
    <h3>Check which issuers it takes today.</h3>
    <p id="vf-count">${ISSUERS.length} issuers: ${ISSUERS.filter((i) => i.verified === "yes").length} accepted today, ${ISSUERS.filter((i) => i.verified !== "yes").length} in part.</p>
    ${issuerTable(esc)}
    <p class="fine" id="vf-notyet">Not yet: ES256, ES384, ES512, PS256, EdDSA.</p>
    <p>Find it on devnet: <code class="k-num" id="vf-program" data-copy style="white-space:normal;overflow-wrap:anywhere">${esc(program)}</code> <button type="button" class="k-btn quiet" data-copy="program">Copy</button></p>
    <div class="k-stage" id="vf-calls">${calls}</div>
    <p class="fine"><a href="${REPO}/docs/VERIFIER.md" target="_blank" rel="noopener">Read the one page.</a>
      <a href="${REPO}/examples/oidc_gate/template.rs" target="_blank" rel="noopener">Copy the 30-line program.</a></p>
    <section class="k-card" id="vf-tool"><p class="k-kicker">Try it</p>
      <h3><label for="vf-jwt">Paste a JWT; see what the verifier reads.</label></h3>
      <p class="fine">Keep it private: this page sends it nowhere.</p>
      <textarea id="vf-jwt" rows="5" spellcheck="false" autocomplete="off" autocapitalize="off" placeholder="eyJhbGciOiJSUzI1NiIs…"></textarea>
      <p><button type="button" class="k-btn quiet" id="vf-sample">Load a sample</button> <button type="button" class="k-btn quiet" id="vf-clear">Clear</button></p>
      <div id="vf-out" aria-live="polite"></div></section>
    <section class="k-card" id="vf-five"><p class="k-kicker">A receipt, in five parts</p>
      <h3><label for="vf-five-in">Paste a receipt; read its five parts.</label></h3>
      <p class="fine">Read here. Sent nowhere.</p>
      <textarea id="vf-five-in" rows="4" spellcheck="false" autocomplete="off" autocapitalize="off" placeholder='{"type": "knos.acceptance-receipt", "version": 5, …}'></textarea>
      <div id="vf-five-out" aria-live="polite"></div></section>
    ${env.badge ? `<section class="k-card" id="vf-badge"><p class="k-kicker">A receipt that checks</p>
      <h3><label for="vf-receipt">Paste a verified receipt; see its badge.</label></h3>
      <p class="fine">Hashed again here. Sent nowhere.</p>
      <textarea id="vf-receipt" rows="4" spellcheck="false" autocomplete="off" autocapitalize="off" placeholder='{"verified": {…}, "receipt": {…}}'></textarea>
      <div id="vf-badge-out" aria-live="polite"></div></section>` : ""}`;
  const box = el.querySelector("#vf-jwt"), out = el.querySelector("#vf-out");
  const show = () => { out.innerHTML = result(decode(box.value, now()), esc); };
  box.addEventListener("input", show);
  el.querySelector("#vf-sample").addEventListener("click", () => { box.value = sample(now()); show(); });
  el.querySelector("#vf-clear").addEventListener("click", () => { box.value = ""; show(); });
  // THE BADGE (web/badge.js renderVerified, which the page hands in as env.badge: this module imports nothing): drawn only for a receipt whose verdict is accepted and, when the receipt
  // itself is pasted with it, only if it hashes to the digest the badge names. What is pasted: { verified, receipt },
  // where `verified` is what knos.badge.verified(receipt) returned; or that object alone.
  // THE FIVE PARTS of a pasted receipt (version 4 or 5): what `knos receipt explain FILE` prints. A file that holds the receipt beside
  // something else ({ receipt }) is read too. An acceptance that stands on a weak test reads as weak, however valid its signature.
  const fiveIn = el.querySelector("#vf-five-in"), fiveOut = el.querySelector("#vf-five-out");
  fiveIn.addEventListener("input", () => {
    const typed = fiveIn.value.trim();
    if (!typed) { fiveOut.innerHTML = ""; return; }
    let doc;
    try { doc = JSON.parse(typed); } catch { fiveOut.innerHTML = `<p class="status bad" data-parts="unread">Not JSON. Paste the whole file.</p>`; return; }
    fiveOut.innerHTML = partsHtml(receiptParts(doc && !doc.type && doc.receipt ? doc.receipt : doc), esc);
  });
  const paper = el.querySelector("#vf-receipt"), badgeOut = el.querySelector("#vf-badge-out");
  if (paper) paper.addEventListener("input", async () => {
    const typed = paper.value.trim();
    if (!typed) { badgeOut.innerHTML = ""; return; }
    let doc;
    try { doc = JSON.parse(typed); } catch { badgeOut.innerHTML = `<p class="status bad" data-verified="unread">Not JSON. Paste the whole file.</p>`; return; }
    await env.badge(badgeOut, doc && doc.verified ? doc.verified : doc, (doc && doc.receipt) || null);
  });
  const text = (what) => (what === "program" ? program : CALLS[Number(what.slice(5))].code.replaceAll(PROGRAM, program));
  for (const b of el.querySelectorAll("button[data-copy]")) {          // the address itself is marked too, so that the site adds no second button to it
    b.addEventListener("click", async () => {
      let done = false;
      try { await navigator.clipboard.writeText(text(b.dataset.copy)); done = true; } catch { /* a browser that refuses the clipboard: the block is there to select */ }
      b.textContent = done ? "Copied" : "Select the text";
      b.dataset.state = done ? "done" : "bad";
    });
  }
}
