// The task both agents and the evaluator agree on, with no model anywhere: sort a list of words and drop the
// duplicates. `work` is what an honest seller does, `judge` is the whole of the evaluator's decision.
import { createHash } from "node:crypto";

export const KIND = "sort-unique";
export const DEVNET_RPC = "https://api.devnet.solana.com";
export const DEVNET_USDC = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";      // Circle's devnet mint: test USDC
export const digest = (result) => createHash("sha256").update(JSON.stringify(result)).digest("hex");
export const work = (input) => [...new Set(input)].sort();
/** A seller that ships something that looks finished and is not: the duplicates are still there. */
export const wrongWork = (input) => [...input].sort();

/** { accepted, reason, digest }: accepted only when the delivery is, exactly, the work the task asked for. */
export function judge(task, delivery) {
  if (!delivery || !Array.isArray(delivery.result)) return { accepted: false, reason: "the delivery carries no result", digest: null };
  const got = digest(delivery.result), want = digest(work(task.input));
  if (delivery.task !== task.id) return { accepted: false, reason: `the delivery is for task ${delivery.task}, not ${task.id}`, digest: got };
  if (got !== want) return { accepted: false, reason: "the result is not the sorted list without duplicates", digest: got };
  return { accepted: true, reason: "the result is the sorted list without duplicates", digest: got };
}
