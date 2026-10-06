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
