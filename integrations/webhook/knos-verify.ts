// Check a Knos acceptance receipt offline. One file, no dependency: copy it into a backend (Node 20 or later, Deno,
// Bun, a Worker: anything with WebCrypto as `crypto.subtle`).
//
//     import { verify } from "./knos-verify.ts";
//     const got = await verify({ token, receipt, terms }, jwks, { repository_id: 987654321 });
//     if (got.ok) { /* got.facts: order, commit, pull_request, repository_id, terms_hash, mode, payees, workflow */ }
//
// It is knos_verify.py beside this file, step for step and sentence for sentence (read that file's header for what
// is checked and what is not); fixtures.json holds the cases both answer the same way. `terms`, when given, is the
// exact text that was hashed at funding (terms.json of a Knos evidence bundle). This function opens no connection.

export const GITHUB = "https://token.actions.githubusercontent.com";
export const WORKFLOW = "drexthealpha/Knos/.github/workflows/";
export const MODES = ["merge", "tests"] as const;
export const LIMITS = [
  "The wallets paid and the amounts are the receipt's word: no signed token carries them.",
  "The key is the one the caller gave; it was not compared with the key account on chain.",
  "The named checks were not evaluated again, and the token's expiry was not held against it: a receipt records a past payment.",
];
const CLAIMS = ["actor_id", "event_name", "exp", "iat", "job_workflow_ref", "job_workflow_sha", "repository_id", "repository_owner_id",
  "run_attempt", "run_id", "runner_environment"];
const AUD = /^knos3:pay:([1-9A-HJ-NP-Za-km-z]{32,44}):([0-9a-f]{40}):([0-9a-f]{64}):([01]):([1-9][0-9]{0,9}):([0-9.,\-A-Za-z]+)$/;
const PAYEE = /^([1-9][0-9]{0,18})\.([0-9]{1,5})\.([\-1-9A-HJ-NP-Za-km-z]{1,44})$/;

export interface Payee { github_id: number; bps: number }
export interface Facts {
  order?: string; commit?: string; terms_hash?: string; mode?: string; pull_request?: number; payees?: Payee[];
  repository_id?: string; workflow?: string; workflow_sha?: string; iat?: unknown; exp?: unknown;
}
export interface Answer { ok: boolean; refused: string; why: string; checked: string[]; facts: Facts; limits: string[] }
export type Evidence = string | { token: string; receipt?: unknown; terms?: string | Uint8Array };
export type Expect = Partial<Record<"workflow" | "repository_id" | "order" | "commit" | "pull_request" | "terms_hash" | "mode" | "payee", string | number>>;
type Json = Record<string, any>;

class No extends Error {
  code: string;
  constructor(code: string, why: string) { super(why); this.code = code; }
}

function unb64(text: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]*$/.test(text)) throw new SyntaxError("not base64url");
  const bin = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

const utf8 = (bytes: Uint8Array): string => new TextDecoder("utf-8", { fatal: true }).decode(bytes);

async function sha256(data: Uint8Array): Promise<string> {
  const got = new Uint8Array(await crypto.subtle.digest("SHA-256", data as BufferSource));
  return Array.from(got, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** {kid: key} of every RS256 key with exponent 65537 and at least 2048 bits in a JWKS, a list of keys or one key. */
function keys(jwks: unknown): Map<string, Json> {
  const doc: any = typeof jwks === "string" ? JSON.parse(jwks) : jwks;
  const rows: any[] = doc && !Array.isArray(doc) && "keys" in doc ? doc.keys : Array.isArray(doc) ? doc : [doc];
  const out = new Map<string, Json>();
  for (const k of rows || []) {
    if (!k || typeof k !== "object" || k.e !== "AQAB" || (k.kty ?? "RSA") !== "RSA" || (k.alg ?? "RS256") !== "RS256") continue;
    let n: Uint8Array;
    try { n = unb64(String(k.n ?? "")); } catch { continue; }
    let lead = 0;
    while (lead < n.length && n[lead] === 0) lead++;
    const bits = n.length === lead ? 0 : (n.length - lead) * 8 - Math.clz32(n[lead]) + 24;
    if (bits >= 2048 && typeof k.kid === "string") out.set(k.kid, { kty: "RSA", n: k.n, e: "AQAB", alg: "RS256", ext: true });
  }
  return out;
}

/** The claims of `token` when it carries the RS256 signature of the key its header names; else refused. */
async function signed(token: string, known: Map<string, Json>): Promise<Json> {
  const parts = token.split(".");
  let head: Json, claims: Json, sig: Uint8Array;
  try {
    head = JSON.parse(utf8(unb64(parts[0])));
    claims = JSON.parse(utf8(unb64(parts[1])));
    sig = unb64(parts[2]);
    if (parts.length !== 3 || !head || !claims || typeof head !== "object" || typeof claims !== "object" || Array.isArray(head) || Array.isArray(claims)) throw new SyntaxError("shape");
  } catch {
    throw new No("token", "This is not a signed token (three base64url parts, the first two JSON).");
  }
  if (head.alg !== "RS256") throw new No("token", "The token is not signed with RS256, the only algorithm a Knos receipt uses.");
  const jwk = known.get(String(head.kid));
  if (!jwk) throw new No("token", "No key with the token's kid is among the keys given. Give the issuer's keys of the day the token was signed.");
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, sig as BufferSource, new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
  if (!ok) throw new No("token", "The token's signature is not the one of the key with its kid: the token or the key was changed.");
  return claims;
}

/** The token's claims as a receipt writes them: times as numbers, everything else as text. */
function told(claims: Json): Json {
  const out: Json = {};
  for (const key of CLAIMS) {
    if (!(key in claims)) continue;
    const v = claims[key];
    out[key] = key === "iat" || key === "exp" ? Number(v) : String(v);
  }
  return out;
}

function audience(claims: Json): Facts {
  const m = AUD.exec(String(claims.aud ?? ""));
  const payees = m ? m[6].split(",").map((p) => PAYEE.exec(p)) : [null];
  if (!m || !payees.every(Boolean)) {
    throw new No("audience", "The token was not signed for a Knos payment (its audience is not knos3:pay:order:commit:terms:mode:pull:payees).");
  }
  return { order: m[1], commit: m[2], terms_hash: m[3], mode: MODES[Number(m[4])], pull_request: Number(m[5]),
    payees: payees.map((p) => ({ github_id: Number(p![1]), bps: Number(p![2]) })) };
}

/** JSON with its keys in order, so two values are the same exactly when their texts are. */
function same(a: unknown, b: unknown): boolean {
  const flat = (v: any): any => Array.isArray(v) ? v.map(flat)
    : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, flat(v[k])])) : v;
  return JSON.stringify(flat(a)) === JSON.stringify(flat(b));
}

async function receiptHolds(r: any, token: string, claims: Json, facts: Facts): Promise<void> {
  let named: Json = {}, repo: unknown, digest: unknown, said: unknown, issuer: unknown, shaped = false;
  try {
    const a = r.issuer_authenticated, o = r.evaluator_observed, p = r.policy;
    shaped = r.type === "knos.acceptance-receipt" && (r.version === 2 || r.version === 3) && o.verdict === "accepted";
    named = { order: r.order, commit: o.artifact.commit, terms_hash: p.terms_hash, mode: p.mode, pull_request: o.artifact.pull_request,
      payees: r.payees.map((e: any) => ({ github_id: e.github_id, bps: e.bps })) };
    [repo, digest, said, issuer] = [r.repository.id, a.token_sha256, a.claims, a.issuer];
    if (digest === undefined || said === undefined || repo === undefined) shaped = false;
  } catch {
    shaped = false;
  }
  if (!shaped) throw new No("receipt", "This is not an acceptance receipt of version 2 or 3 with an accepted verdict (docs/RECEIPT.md).");
  if ((await sha256(unb64(token.slice(token.lastIndexOf(".") + 1)))) !== digest) {
    throw new No("receipt", "The receipt names another token than the one given (token_sha256 differs).");
  }
  if (!same(said, told(claims)) || issuer !== claims.iss || String(repo) !== String(claims.repository_id)) {
    throw new No("receipt", "The claims, the issuer or the repository in the receipt are not the ones the token carries.");
  }
  const mine: Json = facts;
  if (!same(named, Object.fromEntries(Object.keys(named).map((k) => [k, mine[k]])))) {
    throw new No("receipt", "The order, commit, terms, pull request or payees in the receipt are not the ones the token was signed for.");
  }
}

async function termsHold(raw: string | Uint8Array, facts: Facts, receipt: any): Promise<void> {
  const data = typeof raw === "string" ? new TextEncoder().encode(raw) : raw;
  if ((await sha256(data)) !== facts.terms_hash) {
    throw new No("terms", "These are not the terms hashed at funding (their sha256 is not the terms hash the token names).");
  }
  let ok = false;
  try {
    const t = JSON.parse(utf8(data));
    const p = receipt?.policy;
    ok = t.mode === facts.mode && (receipt == null || same([t.paths, t.deny, t.v], [p.allowed_paths, p.denied_paths, p.version]));
  } catch {
    ok = false;
  }
  if (!ok) throw new No("terms", "The terms do not say what the token and the receipt's policy say (mode, allowed and denied paths, version).");
}

function expected(expect: Expect, facts: Facts): void {
  const mine: Json = facts;
  for (const [key, want] of Object.entries(expect)) {
    if (key === "workflow") continue;
    let ok: boolean;
    if (key === "payee") ok = (facts.payees ?? []).some((p) => String(p.github_id) === String(want));
    else if (["repository_id", "order", "commit", "pull_request", "terms_hash", "mode"].includes(key)) ok = String(mine[key]) === String(want);
    else throw new No("expect", `\`${key}\` is not a fact this function can hold a receipt to.`);
    if (!ok) throw new No("expect", `The receipt is for another ${key.replace(/_/g, " ")} than the one expected.`);
  }
}

/** The answer for `evidence` under the keys `jwks`. Never throws for evidence that is wrong: `ok` is false,
 *  `refused` is the step that failed and `why` says it in a sentence. */
export async function verify(evidence: Evidence, jwks: unknown, expect: Expect = {}): Promise<Answer> {
  const checked: string[] = [];
  let facts: Facts = {};
  const no = (refused: string, why: string): Answer => ({ ok: false, refused, why, checked, facts, limits: [...LIMITS] });
  try {
    let ev: any = evidence;
    if (typeof ev === "string") {
      const text = ev.trim();
      ev = text.startsWith("{") ? JSON.parse(text) : { token: text };
    }
    if (!ev || typeof ev !== "object" || typeof ev.token !== "string") {
      throw new No("token", "Give the token GitHub signed, or a mapping with `token` and optionally `receipt` and `terms`.");
    }
    const token: string = ev.token.trim();
    let receipt = ev.receipt ?? null;
    const terms = ev.terms ?? null;
    const claims = await signed(token, keys(jwks));
    checked.push("the token carries the RS256 signature of the key given for its kid");
    const workflow = String(expect.workflow ?? WORKFLOW);
    if (claims.iss !== GITHUB || !String(claims.job_workflow_ref ?? "").startsWith(workflow)) {
      throw new No("issuer", `The token is not GitHub's for a run of ${workflow}: another issuer or another workflow asked for it.`);
    }
    checked.push(`GitHub signed it for a run of ${claims.job_workflow_ref}`);
    facts = { ...audience(claims), repository_id: String(claims.repository_id ?? ""), workflow: claims.job_workflow_ref,
      workflow_sha: String(claims.job_workflow_sha ?? ""), iat: claims.iat, exp: claims.exp };
    checked.push("it names one order, commit, terms hash, pull request and its payees");
    if (receipt !== null) {
      if (typeof receipt === "string") receipt = JSON.parse(receipt);
      await receiptHolds(receipt, token, claims, facts);
      checked.push("the receipt names this token and says what the token says");
    }
    if (terms !== null) {
      await termsHold(terms, facts, receipt);
      checked.push("the terms are the ones hashed at funding");
    }
    expected(expect, facts);
    const named = Object.keys(expect).filter((k) => k !== "workflow").map((k) => k.replace(/_/g, " ")).sort();
    if (named.length) checked.push(`it is for the ${named.join(", ")} expected`);
  } catch (e) {
    if (e instanceof No) return no(e.code, e.message);
    if (e instanceof SyntaxError || e instanceof TypeError) return no("token", "The evidence could not be read as a token or as JSON.");
    throw e;
  }
  return { ok: true, refused: "", why: "", checked, facts, limits: [...LIMITS] };
}
