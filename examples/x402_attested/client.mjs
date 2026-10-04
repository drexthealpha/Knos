// The client of the example: it asks for the resource, reads the 402, checks the order it is asked to fund against
// what it is willing to pay, funds it, and asks again with the order's address as its payment proof.
import { KNOS_PAY, SCHEME, decode, encode, fundOrderWalletIx, orderAddress, orderFee, termsHash } from "./attested.mjs";

/**
 * `wallet`: { address, token, send(ix) -> signature } (send signs and submits). `limits`: { maxAmount, programs, mints }.
 * Returns { status, body, settlement, order, messages } where messages are the exact JSON objects exchanged.
 */
export async function fetchAttested(url, wallet, limits, fetcher = fetch) {
  const first = await fetcher(url, { headers: { "Attested-Payer": wallet.address } });
  if (first.status !== 402) return { status: first.status, body: await first.json(), messages: {} };
  const required = decode(first.headers.get("PAYMENT-REQUIRED"));
  const req = required.accepts.find((a) => a.scheme === SCHEME);
  if (!req) throw new Error(`the server offers no ${SCHEME} payment`);
  const x = req.extra;
  // never trust the server's arithmetic: the order is ours to derive, the terms ours to hash, the price ours to cap
  if (!(limits.programs ?? [KNOS_PAY]).includes(x.program)) throw new Error(`refusing to fund an order of ${x.program}: not a program this client knows`);
  if (!limits.mints.includes(req.asset)) throw new Error(`refusing to pay in mint ${req.asset}`);
  if (BigInt(req.amount) > BigInt(limits.maxAmount)) throw new Error(`the price ${req.amount} is over this client's limit ${limits.maxAmount}`);
  if (x.termsHash !== await termsHash(x.terms)) throw new Error("the terms hash is not the hash of the terms");
  if (x.fee !== String(orderFee(req.amount))) throw new Error("the fee is not knos_pay's fee for this amount");
  const order = await orderAddress(x.program, x.repoId, x.issue, wallet.address, x.seq);
  if (x.order !== null && x.order !== order) throw new Error("the order the server names is not the one this wallet's funding creates");
  const transaction = await wallet.send(await fundOrderWalletIx(req, wallet.address, wallet.token));
  const payment = { x402Version: 2, resource: required.resource, accepted: req, payload: { order, transaction }, extensions: {} };
  const second = await fetcher(url, { headers: { "PAYMENT-SIGNATURE": encode(payment) } });
  const header = second.headers.get("PAYMENT-RESPONSE");
  return { status: second.status, body: await second.json(), settlement: header ? decode(header) : null, order,
           messages: { paymentRequired: required, paymentPayload: payment, settlementResponse: header ? decode(header) : null } };
}
