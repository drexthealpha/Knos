// The JavaScript client (sdk/settle), as an implementation the conformance kit can run:
//
//     python conformance/run.py --impl "node conformance/impl/knos_js.mjs"
//
// SDK: operations answered by a function sdk/settle exports. ADAPTER: operations sdk/settle has no function for, done
// here from the description in docs/CONFORMANCE.md with nothing of the SDK's but its sha256; they show that the
// description is enough to write a second implementation from, and they are not a claim about the SDK. Everything
// else is answered `unsupported`: the SDK does not check receipts and does not write a statement's text.
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
