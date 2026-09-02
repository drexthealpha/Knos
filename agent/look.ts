import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { AcpAgent, PrivyAlchemyEvmProviderAdapter } from "@virtuals-protocol/acp-node-v2";
import { base } from "@account-kit/infra";
import type { Address } from "viem";

const cfg = JSON.parse(readFileSync(resolve(process.env.USERPROFILE ?? process.env.HOME ?? ".", ".knos-keys", "acp-buyer.json"), "utf8"));
const buyer = await AcpAgent.create({
  evmProvider: await PrivyAlchemyEvmProviderAdapter.create({
    walletAddress: cfg.walletAddress as Address,
    walletId: cfg.walletId,
    signerPrivateKey: cfg.signerPrivateKey,
    chains: [base],
  }),
});
// Direct lookup by wallet: the marketplace keyword search is fuzzy and does
// not reliably return a given agent, which makes it useless as a check.
const PROVIDER = "0xd535a8828ffd79c12622313cb55e37d86302e0de";
const api = (buyer as any).api;
const a = await api.getAgentByWalletAddress(PROVIDER);
if (!a) {
  console.log(`no agent at ${PROVIDER}`);
} else {
  console.log(`AGENT ${a.name}  ${a.walletAddress}`);
  const offs = a.offerings ?? [];
  console.log(offs.length === 0 ? "  offerings: NONE" : `  offerings: ${offs.length}`);
  for (const o of offs) {
    console.log(`   - "${o.name}"`);
    console.log(`     ${JSON.stringify(o).slice(0, 400)}`);
  }
}
process.exit(0);
