/**
 * knos as one discoverable service: answer a question from this machine's
 * memory.
 *
 * One offering. No evaluator, no accounts, no reputation.
 *
 * The offering is registered once through the Virtuals service registry, in
 * a browser; REGISTER.md next to this file has the exact values to enter.
 * This file is the other half: it listens for jobs against that offering,
 * asks knos, and submits what knos found.
 *
 * knos still has no model. What comes back is the passage and its source,
 * the same as `knos ask` prints, which is the whole product being sold.
 *
 * Nothing here runs on a schedule. It answers jobs a buyer created.
 */

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  AcpAgent,
  AssetToken,
  PrivyAlchemyEvmProviderAdapter,
} from "@virtuals-protocol/acp-node-v2";
import type { JobRoomEntry, JobSession } from "@virtuals-protocol/acp-node-v2";
import { base } from "@account-kit/infra";
import type { Address } from "viem";

const here = dirname(fileURLToPath(import.meta.url));

/**
 * One question costs this much. Small on purpose: probing should be cheap to
 * answer and not free to spam.
 */
const PRICE_USDC = 0.01;

type Settings = {
  agentId: string;
  walletAddress: Address;
  apiKey?: string;
  walletId: string;
  signerPrivateKey: string;
  builderCode?: string;
  knos: string;
};

/**
 * What the registry handed back after registration, kept outside the repo
 * with the keys rather than beside the code. The agent id and the wallet are
 * public and appear in the README; the signer never leaves this file.
 */
function settings(): Settings {
  const path =
    process.env.KNOS_ACP_SETTINGS ??
    resolve(
      process.env.USERPROFILE ?? process.env.HOME ?? here,
      ".knos-keys",
      "acp.json",
    );

  let parsed: Settings;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8")) as Settings;
  } catch {
    throw new Error(
      `No settings at ${path}. Register the agent first, then write that file. See REGISTER.md.`,
    );
  }

  // Name what is missing rather than failing somewhere inside the SDK. The
  // wallet the registry mints cannot sign on its own: the signer comes from
  // the agent's Signers tab and is a separate value from the API key.
  const missing = (["walletId", "signerPrivateKey"] as const).filter(
    (key) => !parsed[key],
  );
  if (missing.length > 0) {
    throw new Error(
      `Agent ${parsed.agentId ?? "?"} is registered, but ${missing.join(" and ")} ` +
        `${missing.length === 1 ? "is" : "are"} still empty in ${path}.\n` +
        `Both are on the agent's Signers tab: ` +
        `https://app.virtuals.io/acp/agents/${parsed.agentId ?? ""}\n` +
        `Add a signer, copy the key, and paste both values in.`,
    );
  }
  return parsed;
}

/** Ask knos, and hand back exactly what it said. */
function ask(knos: string, question: string): Promise<string> {
  return new Promise((done) => {
    const run = spawn(knos, ["ask", question], { windowsHide: true });
    let said = "";
    run.stdout.on("data", (chunk) => (said += chunk));
    run.on("close", () => done(said.trim() || NOTHING));
    run.on("error", () => done(NOTHING));
  });
}

/**
 * A paid job gets an answer either way. Finding out that knos knows nothing
 * about something is a real answer, and it is what was paid for.
 */
const NOTHING = "Nothing known about that.";

/** What each open job asked, until it is funded and can be answered. */
const asked = new Map<string, string>();

function questionIn(content: string): string {
  try {
    const parsed = JSON.parse(content);
    return String(parsed.question ?? parsed.query ?? "").trim();
  } catch {
    return content.trim();
  }
}

async function main(): Promise<void> {
  const config = settings();

  const seller = await AcpAgent.create({
    evmProvider: await PrivyAlchemyEvmProviderAdapter.create({
      walletAddress: config.walletAddress,
      walletId: config.walletId,
      signerPrivateKey: config.signerPrivateKey,
      chains: [base],
      builderCode: config.builderCode,
    }),
  });

  seller.on("entry", async (session: JobSession, entry: JobRoomEntry) => {
    // The buyer says what they want to know, and knos names its price.
    if (entry.kind === "message") {
      if (entry.contentType === "requirement" && session.status === "open") {
        asked.set(session.jobId, questionIn(entry.content));
        await session.setBudget(AssetToken.usdc(PRICE_USDC, session.chainId));
      }
      return;
    }

    if (entry.event.type === "job.funded") {
      const question = asked.get(session.jobId) ?? "";
      await session.submit(question ? await ask(config.knos, question) : NOTHING);
      asked.delete(session.jobId);
    }

    if (entry.event.type === "job.completed" || entry.event.type === "job.rejected") {
      asked.delete(session.jobId);
    }
  });

  await seller.start(() => {
    console.log(`knos is answering questions at ${PRICE_USDC} USDC each.`);
  });
}

main().catch((why) => {
  console.error(String(why instanceof Error ? why.message : why));
  process.exit(1);
});
