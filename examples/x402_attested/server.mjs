// The resource server of the example: it sells one piece of work (the fix of an issue) under the "knos-order" scheme.
// It answers 402 with the order to fund, checks the funded order on chain, delivers, and reports where the order stands.
import { appendFileSync, existsSync, readFileSync } from "node:fs";
import http from "node:http";

import { decode, encode, escrowed, payerSigned, paymentRequired, requirement, status, verify } from "./attested.mjs";

/**
 * `offer`: what is sold and under which order. `chain`: { account, now, logs }. `deliver(order)`: the resource's body.
 * `deliveredFile`: where the orders already served are kept, one per line, so a restart never serves one twice.
 */
export function server(offer, chain, deliver, { deliveredFile } = {}) {
  if (!deliveredFile) throw new Error("server(): deliveredFile is required: the file of orders already served, kept across restarts");
  // an order pays for one delivery: read back from the file at start, appended on every delivery
  const delivered = new Set(existsSync(deliveredFile) ? readFileSync(deliveredFile, "utf8").split("\n").filter(Boolean) : []);
  const path = new URL(offer.url).pathname;
  return http.createServer(async (req, res) => {
    const send = (code, body, headers = {}) => { res.writeHead(code, { "content-type": "application/json", ...headers }); res.end(JSON.stringify(body)); };
    try {
      const url = new URL(req.url, "http://local");
      if (url.pathname.startsWith("/orders/")) return send(200, await status(chain, offer.program, url.pathname.slice(8)));
      if (url.pathname !== path) return send(404, { error: "no such resource" });
      const refuse = async (error, payer = null) => { const body = await paymentRequired(offer, payer, error); send(402, body, { "PAYMENT-REQUIRED": encode(body) }); };
      const proof = req.headers["payment-signature"];
      if (!proof) return refuse("PAYMENT-SIGNATURE header is required", req.headers["attested-payer"] ?? null);
      let p;
      try { p = decode(proof); } catch { return refuse("the PAYMENT-SIGNATURE header is not base64 JSON"); }
      // the order must be the one this resource is sold for; its payer is whoever funded it
      const base = await requirement(offer);
      const v = await verify(chain, base, p?.payload, offer.marginSeconds ?? 3600);
      if (!v.ok) return refuse(v.reason);
      // and the client accepted OUR requirement (as offered to that payer, or to nobody in particular): nothing in it is the client's to change
      const want = await requirement(offer, v.payer);
      if (p.x402Version !== 2 || ![JSON.stringify(want), JSON.stringify(base)].includes(JSON.stringify(p.accepted))) {
        return refuse("the accepted requirement is not the one this server offers", v.payer);
      }
      // a funded order is public on chain: only the wallet that funded it is served, by its signature of this resource and order
      if (!payerSigned(v.payer, offer.url, p.payload.order, p.payload.payerSignature)) {
        return refuse("the payer's signature of this order is missing or is not the payer's: sign `knos-order x402 payer <resource> <order>` with the wallet that funded it", v.payer);
      }
      if (delivered.has(p.payload.order)) return refuse("this order already paid for one delivery: fund another (a new seq)");
      delivered.add(p.payload.order);
      appendFileSync(deliveredFile, p.payload.order + "\n");
      return send(200, await deliver(p.payload.order), { "PAYMENT-RESPONSE": encode(escrowed(want, p.payload, v)) });
    } catch (e) {
      return send(500, { error: String(e.message ?? e) });
    }
  });
}
