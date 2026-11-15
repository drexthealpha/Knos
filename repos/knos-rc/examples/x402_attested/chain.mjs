// The chain of the example, replayed from fixtures.json: what the test build of knos_pay did in LiteSVM
// (scripts/x402_fixture.py). It does not run the program. It accepts exactly the funding instruction LiteSVM accepted
// (the same bytes and accounts) and then holds the Order account that instruction created; `accept` and `expire` apply
// the recorded payment or the recorded refund.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { b58, hex } from "../../sdk/settle/index.js";

export const FIXTURES = JSON.parse(readFileSync(new URL("./fixtures.json", import.meta.url), "utf8"));

export function replay(fx = FIXTURES) {
  const accounts = new Map(), said = [];
  let now = fx.fund.at;
  return {
    now: () => now,
    account: async (address) => accounts.get(address) ?? null,
    logs: async () => said.slice(),
    /** Sends one instruction signed by `signer`. Returns the transaction's signature; throws what a cluster would refuse. */
    async send(ix, signer) {
      const metas = ix.accounts.map((a) => [a.pubkey, a.signer, a.writable]);
      const same = ix.program === fx.program && hex(ix.data) === fx.fund.data && JSON.stringify(metas) === JSON.stringify(fx.fund.accounts);
      if (!same || signer !== fx.buyer) throw new Error("the replayed chain knows one transaction: the buyer's FundOrderWallet, byte for byte");
      if (accounts.has(fx.order.address)) throw new Error("custom program error: 0x65");      // 101: the order exists already
      accounts.set(fx.order.address, { owner: fx.program, data: Uint8Array.from(Buffer.from(fx.order.data, "hex")) });
      said.push(...fx.fund.logs);
      return b58(createHash("sha512").update(ix.data).digest());
    },
    /** The acceptance lands: a judge's GitHub-signed token paid the order (PayOrder). The order's account is closed. */
    accept() { now = fx.paid.at; accounts.delete(fx.order.address); said.push(...fx.paid.logs); },
    /** Nobody delivered: after the deadline anyone sends RefundOrder, and everything returns to the buyer. */
    expire() { now = fx.refunded.at; accounts.delete(fx.order.address); said.push(...fx.refunded.logs); },
  };
}
