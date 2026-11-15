// The JavaScript client (sdk/settle), as an implementation the conformance kit can run:
//
//     python conformance/run.py --impl "node conformance/impl/knos_js.mjs"
//
// SDK: operations answered by a function sdk/settle exports. ADAPTER: operations sdk/settle has no function for, done
// here from the description in docs/reference/CONFORMANCE.md with nothing of the SDK's but its sha256; they show that the
// description is enough to write a second implementation from, and they are not a claim about the SDK. Everything
// else is answered `unsupported`: the SDK does not check receipts (so it says no verdict of one) and does not write a
// statement's text.
//
// Whole numbers above 2^53 are read from the input's own text as BigInt (Node 22's JSON.parse hands the reviver the
// source text), so no digit is lost on the way in.
import { sha256, hex, v2, meter, rotateAudience, gateAudience, Refused } from "../../sdk/settle/index.js";

const enc = new TextEncoder();
const big = (key, value, context) => (typeof value === "number" && context && Number.isInteger(value) && !Number.isSafeInteger(value) ? BigInt(context.source) : value);
const sortKeys = (value) => {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((name) => [name, sortKeys(value[name])]));
  return value;
};
const hashHex = async (text) => hex(await sha256(enc.encode(text)));
class Refuse extends Error {}


const PREFIX = { deliverable: "dlv", evaluation: "evl", invoice_line: "inv", settlement: "stl" };
const VERDICTS = ["accepted", "rejected", "insufficient_evidence", "disputed"];
const OLD_VERDICTS = { passed: "accepted", clean: "accepted", failed: "rejected", refused: "rejected", unverified: "insufficient_evidence", pending: "insufficient_evidence",
  none: "insufficient_evidence" };
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
// prefix, "_" and 24 hex characters of sha256("knos.id.v1" 0x00 kind 0x00, then each part: its length as u32 big-endian and its UTF-8 bytes)
const idOf = async (kind, ...parts) => {
  const chunks = [enc.encode(`knos.id.v1\0${kind}\0`)];
  for (const part of parts) {
    const bytes = enc.encode(String(part)), size = new Uint8Array(4);
    new DataView(size.buffer).setUint32(0, bytes.length);
    chunks.push(size, bytes);
  }
  const all = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
  let at = 0;
  for (const c of chunks) { all.set(c, at); at += c.length; }
  return `${PREFIX[kind]}_${hex(await sha256(all)).slice(0, 24)}`;
};
const kindOf = (id) => { const m = /^([a-z]{3})_[0-9a-f]{24}$/.exec(String(id)); return (m && Object.keys(PREFIX).find((k) => PREFIX[k] === m[1])) || null; };

// -- ledger format 2 ---------------------------------------------------------------------------------------------------
const FIELDS = ["deliverable_id", "evaluation_id", "invoice_line_id", "settlement_id", "verdict", "amount", "currency", "buyer", "seller", "order", "milestone",
  "policy", "artifact", "evidence", "evaluator", "run", "month", "seq"];
const unhex = (text) => Uint8Array.from(text.match(/../g) || [], (h) => parseInt(h, 16));
const join = (chunks) => {
  const all = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
  let at = 0;
  for (const c of chunks) { all.set(c, at); at += c.length; }
  return all;
};
const u32 = (n) => { const out = new Uint8Array(4); new DataView(out.buffer).setUint32(0, n); return out; };
const tagged = async (tag, ...parts) => sha256(join([enc.encode(`${tag}\0`), ...parts]));
const whole = (text, most) => /^(0|[1-9][0-9]{0,19})$/.test(text) && BigInt(text) < most;
// 'knos.event' 0x00, 0x02, 0x12, then each of the eighteen texts as its length (u32 big-endian) and its UTF-8 bytes; refused when it is not one event
const eventBytes = async (e) => {
  if (!e || typeof e !== "object" || Object.keys(e).length !== FIELDS.length || !FIELDS.every((k) => typeof e[k] === "string")) throw new Refuse();
  if (!VERDICTS.includes(e.verdict) || !["amount", "buyer", "seller", "seq"].every((k) => whole(e[k], 1n << 64n)) || !whole(e.milestone, 1n << 32n)) throw new Refuse();
  if (!/^[0-9]{6}$/.test(e.month) || !/^[0-9a-f]{64}$/.test(e.order) || !/^[0-9a-f]{64}$/.test(e.policy) || !/^[0-9a-f]{40}$/.test(e.artifact)
    || !/^([0-9a-f]{64})?$/.test(e.evidence)) throw new Refuse();
  const dlv = await idOf("deliverable", e.order, e.milestone);
  if (e.deliverable_id !== dlv || e.evaluation_id !== await idOf("evaluation", dlv, e.artifact, e.policy, e.evaluator, e.run)) throw new Refuse();
  if ((e.invoice_line_id && kindOf(e.invoice_line_id) !== "invoice_line") || (e.settlement_id && kindOf(e.settlement_id) !== "settlement")) throw new Refuse();
  const chunks = [enc.encode("knos.event\0"), Uint8Array.of(2, FIELDS.length)];
  for (const k of FIELDS) { const raw = enc.encode(e[k]); chunks.push(u32(raw.length), raw); }
  return join(chunks);
};
const leaf2 = async (e) => tagged("knos.leaf.2", await eventBytes(e));
const top2 = async (hashes) => {
  if (hashes.length === 1) return hashes[0];
  let k = 1;
  while (k * 2 < hashes.length) k *= 2;
  return tagged("knos.node.2", await top2(hashes.slice(0, k)), await top2(hashes.slice(k)));
};
const seal2 = (size, top) => tagged("knos.root.2", u32(size), top);

const SDK = {
  "terms.hash": async (i) => ({ json: new TextDecoder().decode(v2.termsJson(i.terms)), sha256: hex(await v2.termsHash(v2.termsJson(i.terms))) }),
  "terms.canonical": async (i) => { const raw = v2.canonicalTerms(i.terms); return { json: new TextDecoder().decode(raw), sha256: hex(await v2.termsHash(raw)) }; },
  "ledger.eval_id": async (i) => hex(await meter.evalKey(i.order, i.artifact, i.policy, i.milestone)),
  "ledger.batch_root": async (i) => hex(await meter.merkleRoot(i.ids)),
  "ledger.batch_root_any": async (i) => hex(await meter.batchRoot(i.ids, i.corrections)),
  "ledger.check_proof": (i) => meter.checkProof(i.id, i.index, i.size, i.path, i.root, i.correction),
  "ledger.chain_hash": async (i) => hex(await meter.chainHash(i.before, i.root, i.seq, i.count, i.accepted, i.value)),
  "audience.knos2_fund": (i) => v2.fundAudience(i.issue, i.amount, i.mode, i.terms, i.balance, i.work_s),
  "audience.knos2_pay": (i) => v2.payAudience(i.repo_id, i.issue, i.payee_id, i.head_sha, i.terms, i.mode, i.address),
  "audience.knos2_bind": (i) => v2.bindAudience(i.address),
  "audience.knos3_fund": (i) => v2.orderFundAudience(i.issue, i.amount, i.mode, i.terms, i.balance, i.work_s, i.seq, Uint8Array.from(i.options.match(/../g), (h) => parseInt(h, 16))),
  "audience.knos3_pay": (i) => v2.orderPayAudience(i.order, i.head_sha, i.terms, i.mode, i.pr, i.payees),
  "audience.knos3_auto": (i) => v2.autoAudience(i.order, i.head_sha, i.terms, i.pr, i.payee_id, i.address),
  "audience.knos3_rule": (i) => v2.ruleAudience(i.order, i.payees),
  "audience.knos3_bind": (i) => v2.orgBindAudience(i.address),
  "audience.knos3_take": (i) => v2.takeAudience(i.order, i.taker_id, i.days),
  "audience.knos3_cancel": (i) => v2.cancelAudience(i.order),
  "audience.knos3_revert": (i) => v2.revertAudience(i.order, i.head_sha),
  "audience.knosm_eval": (i) => meter.evalAudience(i.buyer_id, i.seller_id, i.order, i.artifact, i.policy, i.milestone, i.accepted, i.rate),
  "audience.knosm_batch": (i) => meter.batchAudience(i.buyer_id, i.seller_id, i.month, i.seq, i.count, i.accepted, i.value, i.root, i.kind),
  "audience.parse_knosm_batch": (i) => {
    const b = meter.parseBatch(i.audience);
    return { kind: b.claim ? "claim" : "batch", buyer_id: b.buyerId, seller_id: b.sellerId, month: b.month, seq: b.seq, count: b.count, accepted: b.accepted, value: b.value, root: b.root };
  },
  "audience.gate": (i) => gateAudience(i.program, i.executable),
  "audience.knos_oidc_key": (i) => rotateAudience(i.issuer, BigInt("0x" + i.modulus)),
};

const ADAPTER = {
  // keys sorted, no white space, UTF-8 with nothing outside ASCII escaped
  "receipt.digest": (i) => hashHex(JSON.stringify(sortKeys(i.receipt))),
  // sha256(order || milestone as u32 little-endian)
  "ledger.deliverable_id": async (i) => {
    const order = Uint8Array.from(i.order.match(/../g), (h) => parseInt(h, 16)), out = new Uint8Array(36);
    out.set(order);
    new DataView(out.buffer).setUint32(32, i.milestone, true);
    return hex(await sha256(out));
  },
  // The four ids, the verdicts and the rule that bills a deliverable once, from the description in conformance/vectors/ids.v1.json.
  "ids.deliverable": (i) => idOf("deliverable", i.scope, i.key),
  "ids.evaluation": (i) => idOf("evaluation", i.deliverable, i.artifact, i.policy, i.evaluator, i.run),
  "ids.invoice_line": (i) => idOf("invoice_line", i.supplier, i.invoice, i.line),
  "ids.settlement": (i) => idOf("settlement", i.deliverable, i.method, i.reference),
  "ids.kind_of": (i) => kindOf(i.id),
  "ids.expect": (i) => { if (kindOf(i.id) !== i.kind) throw new Refuse(); return i.id; },
  "ids.order_scope": (i) => {
    if (/^[0-9a-f]{64}$/.test(i.order)) return i.order;
    if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(i.order)) throw new Refuse();
    let n = 0n;
    for (const c of i.order) n = n * 58n + BigInt(B58.indexOf(c));
    if (n >= 1n << 256n) throw new Refuse();
    return n.toString(16).padStart(64, "0");
  },
  "ids.verdict": (i) => {
    const word = i.word.trim().toLowerCase().replace(/[ -]/g, "_"), is = OLD_VERDICTS[word] || word;
    if (!VERDICTS.includes(is)) throw new Refuse();
    return is;
  },
  // the first accepted evaluation of each deliverable, by its place in the list
  "ids.billed_once": (i) => {
    const seen = new Set(), out = [];
    for (const [n, e] of i.evaluations.entries()) {
      if (kindOf(e.deliverable) !== "deliverable" || !VERDICTS.includes(e.verdict)) throw new Refuse();
      if (e.verdict === "accepted" && !seen.has(e.deliverable)) { seen.add(e.deliverable); out.push(n); }
    }
    return out;
  },
  // Ledger format 2, from the description in conformance/vectors/ledger.v2.json: the leaf is the hash of the whole event.
  "ledger2.event_bytes": async (i) => hex(await eventBytes(i.event)),
  "ledger2.leaf": async (i) => hex(await leaf2(i.event)),
  "ledger2.root": async (i) => {
    const byKey = new Map();
    for (const e of i.events) {
      const leaf = await leaf2(e), key = hex(await meter.evalKey(e.order, e.artifact, e.policy, Number(e.milestone)));
      if (byKey.has(key)) throw new Refuse();
      byKey.set(key, leaf);
    }
    const leaves = [...byKey.keys()].sort().map((k) => byKey.get(k));
    for (const k of [...new Set(i.corrections)].sort()) leaves.push(await tagged("knos.fix.2", unhex(k)));
    return hex(await seal2(leaves.length, leaves.length ? await top2(leaves) : new Uint8Array(0)));
  },
  "ledger2.check_proof": async (i) => {
    let r;
    try { r = await leaf2(i.event); } catch (e) { if (e instanceof Refuse) return false; throw e; }
    if (!(i.index >= 0 && i.index < i.size)) return false;
    let fn = i.index, sn = i.size - 1;
    for (const p of i.path.map(unhex)) {
      if (sn === 0) return false;
      if (fn % 2 === 1 || fn === sn) {
        r = await tagged("knos.node.2", p, r);
        while (fn % 2 === 0 && fn !== 0) { fn = Math.floor(fn / 2); sn = Math.floor(sn / 2); }
      } else r = await tagged("knos.node.2", r, p);
      fn = Math.floor(fn / 2); sn = Math.floor(sn / 2);
    }
    return sn === 0 && hex(await seal2(i.size, r)) === i.root;
  },
  // sha256 of the bytes above the first line that starts "sha256,"
  "statement.hash": async (i) => {
    const text = i.statement, at = text.indexOf("\nsha256,");
    if (!text.startsWith("knos meter statement,1\n") || at < 0) throw new Refuse();
    const computed = await hashHex(text.slice(0, at + 1)), stated = text.slice(at + 8).split("\n")[0];
    return { sha256: computed, stated, agrees: computed === stated };
  },
};

let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const lines = [];
for (const line of input.split("\n")) {
  if (!line.trim()) continue;
  const c = JSON.parse(line, big), fn = SDK[c.op] || ADAPTER[c.op];
  let answer;
  if (!fn) answer = { unsupported: true };
  else {
    try { answer = { output: await fn(c.input) }; } catch (e) { if (!(e instanceof Refuse || e instanceof Refused)) throw e; answer = { refused: true }; }
  }
  lines.push(JSON.stringify({ id: c.id, ...answer }));
}
process.stdout.write(lines.join("\n") + "\n");
