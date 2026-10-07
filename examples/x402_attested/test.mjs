// node --test examples/x402_attested/test.mjs
// The x402 "knos-order" flow end to end on one machine: an HTTP server and a client, the chain replayed from fixtures.json
// (what the test build of knos_pay did in LiteSVM). The messages exchanged are the ones docs/X402.md prints, exactly.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import test from "node:test";

import { decode, encode, fundOrderWalletIx, orderAddress, requirement, status } from "./attested.mjs";
import { FIXTURES as fx, replay } from "./chain.mjs";
import { fetchAttested } from "./client.mjs";
import { server } from "./server.mjs";

const OFFER = {
  url: "https://seller.example/work/77", description: "Fix issue 77 of repository 987654321: delivered as a pull request, paid when it is merged with the funded check green",
  network: "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", program: fx.program, mint: fx.mint, amount: fx.amount, workSeconds: fx.work_s,
  repoId: fx.repo_id, issue: fx.issue, seq: fx.seq, mode: fx.mode, terms: fx.terms, wfRepo: fx.wf_repo, wfSha: fx.wf_sha,
  seller: { githubId: fx.seller.github_id, wallet: fx.seller.wallet },
  feeVersion: fx.fee_version,      // the build the fixture was recorded on: the 402 names the fee that build takes
};
const DELIVERY = { delivered: "https://github.com/octo/widgets/pull/12", head: fx.head, note: "paid when the order's pinned workflow attests the merge" };
const LIMITS = { maxAmount: 50_000_000, mints: [fx.mint] };

/** A server on a free local port, a chain, and the buyer's wallet. `url` is where the client really connects. */
async function world() {
  const chain = replay();
  const srv = server(OFFER, chain, async () => DELIVERY);
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  const url = `http://127.0.0.1:${srv.address().port}/work/77`;
  const sent = [];
  const wallet = { address: fx.buyer, token: fx.buyer_token, send: async (ix) => { sent.push(ix); return chain.send(ix, fx.buyer); } };
  return { chain, srv, url, wallet, sent, base: url.replace("/work/77", ""), close: () => new Promise((r) => srv.close(r)) };
}
/** The messages as docs/X402.md prints them, which must also be the committed messages.json. */
const docs = () => {
  const text = readFileSync(new URL("../../docs/X402.md", import.meta.url), "utf8");
  const out = {};
  for (const m of text.matchAll(/<!-- message: (\w+) -->\s*```json\n([\s\S]*?)\n```/g)) out[m[1]] = JSON.parse(m[2]);
  assert.deepEqual(out, JSON.parse(readFileSync(new URL("./messages.json", import.meta.url), "utf8")));
  return out;
};

test("the client funds the order the 402 names, is served, and the seller is paid when the acceptance lands", async () => {
  const w = await world();
  try {
    const got = await fetchAttested(w.url, w.wallet, LIMITS);
    assert.equal(got.status, 200);
    assert.deepEqual(got.body, DELIVERY);
    assert.equal(got.order, fx.order.address);
    // one transaction was signed: knos_pay's FundOrderWallet, the bytes LiteSVM accepted from the Python client
    assert.equal(w.sent.length, 1);
    assert.equal(Buffer.from(w.sent[0].data).toString("hex"), fx.fund.data);
    // the 402 named this payer's order, the fee on top, and the terms whose hash the order stores
    const req = got.messages.paymentRequired.accepts[0];
    assert.deepEqual([req.scheme, req.amount, req.asset, req.payTo, req.extra.order, req.extra.fee, req.extra.termsHash],
                     ["knos-order", String(fx.amount), fx.mint, fx.seller.wallet, fx.order.address, String(fx.fee), fx.terms_hash]);
    // delivered against escrow: the settlement says the money is held, not paid
    assert.deepEqual(got.settlement.extensions["knos-order"].info, { order: fx.order.address, state: "escrowed", deadline: fx.order.deadline });
    assert.equal(got.settlement.payer, fx.buyer);
    const at = async () => (await fetch(`${w.base}/orders/${fx.order.address}`)).json();
    assert.deepEqual(await at(), { order: fx.order.address, state: "escrowed", deadline: fx.order.deadline });
    // GitHub signs that the pull request was merged under the order's terms; PayOrder pays the seller the amount whole
    w.chain.accept();
    assert.deepEqual(await at(), { order: fx.order.address, state: "paid",
                                   payments: [{ payee: String(fx.seller.github_id), amount: String(fx.amount), to: fx.seller.wallet, pr: String(fx.pr) }] });
    assert.equal(fx.paid.received, fx.amount);
    // the exact messages are the ones the specification prints
    const d = docs();
    assert.deepEqual(got.messages.paymentRequired, d.paymentRequired);
    assert.deepEqual(got.messages.paymentPayload, d.paymentPayload);
    assert.deepEqual(got.messages.settlementResponse, d.settlementResponse);
    assert.deepEqual(await at(), d.statusPaid);
  } finally { await w.close(); }
});

test("an order nobody accepted returns everything to the client after its deadline", async () => {
  const w = await world();
  try {
    const got = await fetchAttested(w.url, w.wallet, LIMITS);
    assert.equal(got.status, 200);
    w.chain.expire();
    const s = await status(w.chain, fx.program, got.order);
    assert.deepEqual(s, { order: fx.order.address, state: "refunded", amount: String(fx.amount + fx.fee) });
    assert.deepEqual(s, docs().statusRefunded);
  } finally { await w.close(); }
});

test("the server delivers nothing without the funded order, and one order pays for one delivery", async () => {
  const w = await world();
  try {
    const ask = (proof) => fetch(w.url, { headers: proof ? { "PAYMENT-SIGNATURE": proof } : {} });
    const plain = await ask(null);
    assert.equal(plain.status, 402);
    const required = decode(plain.headers.get("PAYMENT-REQUIRED"));
    assert.deepEqual(required, await plain.json());                       // the header and the body say the same
    assert.equal(required.accepts[0].extra.order, null);                  // no payer named: the client derives the order
    assert.equal(required.error, "PAYMENT-SIGNATURE header is required");
    const req = await requirement(OFFER, fx.buyer);
    const proof = (order) => encode({ x402Version: 2, resource: required.resource, accepted: req, payload: { order, transaction: "" }, extensions: {} });
    // a proof that names an order nobody funded, an account that is not an order, a proof that is not JSON
    let r = await ask(proof(fx.order.address));
    assert.equal(r.status, 402);
    assert.match((await r.json()).error, /there is no order at .*: fund it first/);
    assert.equal((await ask("not base64 json")).status, 402);
    assert.equal((await ask(encode({ x402Version: 2, accepted: req, payload: {} }))).status, 402);
    // funded: served once; the same order again is refused; a changed requirement is refused
    await w.wallet.send(await fundOrderWalletIx(req, fx.buyer, fx.buyer_token));
    const cheaper = encode({ x402Version: 2, accepted: { ...req, amount: "1" }, payload: { order: fx.order.address }, extensions: {} });
    r = await ask(cheaper);
    assert.equal(r.status, 402);
    assert.match((await r.json()).error, /not the one this server offers/);
    assert.equal((await ask(proof(fx.order.address))).status, 200);
    r = await ask(proof(fx.order.address));
    assert.equal(r.status, 402);
    assert.match((await r.json()).error, /already paid for one delivery/);
    // an order of another payer is another address: this one's proof cannot be passed off as theirs
    assert.notEqual(await orderAddress(fx.program, fx.repo_id, fx.issue, fx.seller.wallet, fx.seq), fx.order.address);
  } finally { await w.close(); }
});

test("the client refuses an order it did not agree to before it signs anything", async () => {
  const w = await world();
  try {
    const tampered = (change) => async (url, init) => {
      const res = await fetch(url, init);
      if (res.status !== 402) return res;
      const body = await res.json();
      change(body.accepts[0]);
      return new Response(JSON.stringify(body), { status: 402, headers: { "PAYMENT-REQUIRED": encode(body) } });
    };
    for (const [change, why] of [[(a) => { a.amount = "60000000"; }, /over this client's limit/],
                                 [(a) => { a.extra.terms = a.extra.terms.replace("test", "none"); }, /terms hash is not the hash of the terms/],
                                 [(a) => { a.extra.program = fx.mint; }, /not a program this client knows/],
                                 [(a) => { a.asset = fx.buyer; }, /refusing to pay in mint/],
                                 [(a) => { a.extra.fee = "1"; }, /fee is not knos_pay's fee/],
                                 [(a) => { a.extra.order = fx.order.ov; }, /not the one this wallet's funding creates/]]) {
      await assert.rejects(fetchAttested(w.url, w.wallet, LIMITS, tampered(change)), why);
    }
    assert.equal(w.sent.length, 0);
  } finally { await w.close(); }
});

if (process.argv.includes("--write")) {       // messages.json: the JSON blocks of docs/X402.md
  const w = await world();
  const got = await fetchAttested(w.url, w.wallet, LIMITS);
  w.chain.accept();
  const paid = await status(w.chain, fx.program, got.order);
  const w2 = await world();
  const got2 = await fetchAttested(w2.url, w2.wallet, LIMITS);
  w2.chain.expire();
  writeFileSync(new URL("./messages.json", import.meta.url),
                JSON.stringify({ ...got.messages, statusPaid: paid, statusRefunded: await status(w2.chain, fx.program, got2.order) }, null, 1) + "\n");
  await w.close(); await w2.close();
}

test("the fee the 402 names follows the build that is live", async () => {
  const { orderFee, feesFor, requirement } = await import("./attested.mjs");
  // knos_pay 2.2 (Version answers 2): 0.30%, at least 0.05. Before it: the 0.3.14 tiers, at least 0.40.
  assert.deepEqual([5_000_000, 20_000_000, 100_000_000, 5_000_000_000].map((a) => String(orderFee(a, 2))), ["50000", "60000", "300000", "15000000"]);
  assert.deepEqual([5_000_000, 20_000_000, 100_000_000, 5_000_000_000].map((a) => String(orderFee(a, 1))), ["400000", "500000", "2500000", "65000000"]);
  assert.equal(String(orderFee(20_000_000)), "60000");                     // nobody asked: the rule of this tree's build
  assert.deepEqual(feesFor(20_000_000), ["60000", "500000"]);
  const at = async (feeVersion) => (await requirement({ ...OFFER, feeVersion })).extra.fee;
  assert.deepEqual([await at(1), await at(2), await at(undefined)], ["500000", "60000", "60000"]);
  // a client that asked the program holds the server to that build's fee; one that did not accepts either rule's and nothing else
  const refusing = async (fee, limits) => {
    const chain = replay(), srv = server({ ...OFFER }, chain, async () => DELIVERY);
    await new Promise((r) => srv.listen(0, "127.0.0.1", r));
    const url = `http://127.0.0.1:${srv.address().port}/work/77`;
    const tampered = async (u, init) => {
      const res = await fetch(u, init);
      if (res.status !== 402) return res;
      const body = JSON.parse(Buffer.from(res.headers.get("PAYMENT-REQUIRED"), "base64").toString("utf8"));
      body.accepts[0].extra.fee = fee;
      return new Response(JSON.stringify(body), { status: 402, headers: { "PAYMENT-REQUIRED": Buffer.from(JSON.stringify(body)).toString("base64") } });
    };
    const wallet = { address: fx.buyer, token: fx.buyer_token, send: async () => { throw new Error("funded"); } };
    try { await fetchAttested(url, wallet, limits, tampered); return "served"; } catch (e) { return /fee is not knos_pay's fee/.test(e.message) ? "refused" : e.message; }
    finally { await new Promise((r) => srv.close(r)); }
  };
  assert.deepEqual([await refusing("60000", { ...LIMITS, feeVersion: 1 }), await refusing("500000", { ...LIMITS, feeVersion: 2 }), await refusing("500000", { ...LIMITS, feeVersion: 1 }),
    await refusing("60000", LIMITS), await refusing("500000", LIMITS), await refusing("70000", LIMITS)], ["refused", "refused", "funded", "funded", "funded", "refused"]);
});
