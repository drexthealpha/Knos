/**
 * The other half of the trade: create one job against the knos offering,
 * fund it, and print what came back.
 *
 * This exists to prove the ACP path executes end to end. It is not part of
 * the product: knos itself never buys anything, and nothing in src/ imports
 * this file.
 *
 * Settings live outside the repo, next to the provider's, in
 * ~/.knos-keys/acp-buyer.json. No key is ever read into this file's source.
 *
 *   npm run buy -- "what did we decide about redis"
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  AcpAgent,
  AssetToken,
  PrivyAlchemyEvmProviderAdapter,
} from "@virtuals-protocol/acp-node-v2";
import type { JobRoomEntry, JobSession } from "@virtuals-protocol/acp-node-v2";
import { base } from "@account-kit/infra";
import type { Address } from "viem";

/** The knos provider, from its public agent page. */
const PROVIDER: Address = "0xd535a8828ffd79c12622313cb55e37d86302e0de";
const OFFERING = "answer_a_question_from_my_memory";
const PRICE_USDC = 0.01;

type Settings = {
  agentId: string;
  walletAddress: Address;
  walletId: string;
  signerPrivateKey: string;
  builderCode?: string;
};

function settings(): Settings {
  const path =
    process.env.KNOS_ACP_BUYER_SETTINGS ??
    resolve(
      process.env.USERPROFILE ?? process.env.HOME ?? ".",
      ".knos-keys",
      "acp-buyer.json",
    );
  let parsed: Settings;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8")) as Settings;
  } catch {
    throw new Error(`No buyer settings at ${path}.`);
  }
  const missing = (["walletId", "signerPrivateKey", "walletAddress"] as const)
    .filter((key) => !parsed[key]);
  if (missing.length > 0) {
    throw new Error(`${missing.join(" and ")} missing from ${path}.`);
  }
  return parsed;
}

async function main(): Promise<void> {
  const question = process.argv.slice(2).join(" ").trim();
  if (!question) throw new Error('Ask something: npm run buy -- "your question"');

  const config = settings();
  const buyer = await AcpAgent.create({
    evmProvider: await PrivyAlchemyEvmProviderAdapter.create({
      walletAddress: config.walletAddress,
      walletId: config.walletId,
      signerPrivateKey: config.signerPrivateKey,
      chains: [base],
      builderCode: config.builderCode,
    }),
  });

  let funded = false;

  buyer.on("entry", async (session: JobSession, entry: JobRoomEntry) => {
    if (entry.kind === "message") {
      if (entry.contentType === "deliverable") {
        console.log("--- the answer knos sold ---");
        console.log(entry.content);
        console.log("----------------------------");
      }
      return;
    }

    // kind === "system": every lifecycle event carries entry.event.
    console.log(`event: ${entry.event.type}`);

    if (entry.event.type === "budget.set" && !funded) {
      funded = true;
      console.log(`funding ${PRICE_USDC} USDC`);
      await session.fund(AssetToken.usdc(PRICE_USDC, session.chainId));
      return;
    }
    if (entry.event.type === "job.submitted") {
      console.log(`deliverable hash ${entry.event.deliverableHash}`);
    }
    if (entry.event.type === "job.completed") {
      console.log("job completed - funds released to the provider");
      process.exit(0);
    }
    if (entry.event.type === "job.rejected" || entry.event.type === "job.expired") {
      console.log(`job ${entry.event.type} - buyer refunded`);
      process.exit(1);
    }
  });

  await buyer.start(async () => {
    console.log(`asking knos: ${question}`);
    // No evaluatorAddress: a successful submit auto-completes and releases.
    const jobId = await buyer.createJobByOfferingName(
      base.id,
      OFFERING,
      PROVIDER,
      { question },
    );
    console.log(`job ${jobId} created on chain ${base.id}`);
  });
}

main().catch((why) => {
  console.error(String(why instanceof Error ? why.message : why));
  process.exit(1);
});
