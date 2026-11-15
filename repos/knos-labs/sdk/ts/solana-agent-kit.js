// A Solana Agent Kit action: claim a unit before acting (e.g. market:SOL before trading it).
// Action shape per Solana Agent Kit: name, similes, description, examples, schema (zod), handler(agent, input).
import { z } from "zod";
import { Knos } from "./index.js";

export function knosClaimAction({ workspace, agent = "solana-agent" } = {}) {
  let k;
  return {
    name: "KNOS_CLAIM",
    similes: ["claim task", "claim market", "lock unit of work"],
    description: "Claim a unit (market:SOL, task:..., wallet:...) so no other agent acts on it at the same time.",
    examples: [[{ input: { unit: "market:SOL" }, output: { status: "success", claimed: true },
                  explanation: "Claim the SOL market before placing orders" }]],
    schema: z.object({ unit: z.string().min(3) }),
    handler: async (_agent, input) => {
      k ??= await Knos.connect({ agent, workspace });
      const claimed = await k.claim(input.unit);
      return { status: "success", claimed, holder: claimed ? null : k.holder };
    },
  };
}
