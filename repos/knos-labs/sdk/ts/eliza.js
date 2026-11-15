// An ElizaOS plugin: agents claim a unit before working on it, and share Knos/Sibyl memory.
// Action shape per docs.elizaos.ai (core-concepts/plugins/actions): name, similes, description, validate, handler,
// examples. Register with: plugins: [knosPlugin({ workspace: "/path/to/repo" })]
import { Knos } from "./index.js";

export function knosPlugin({ workspace, agent } = {}) {
  let k;
  const client = async (runtime) =>
    (k ??= await Knos.connect({ agent: agent || runtime?.character?.name || "eliza", workspace }));

  const claim = {
    name: "KNOS_CLAIM",
    similes: ["CLAIM_TASK", "TAKE_TASK"],
    description: "Claim a unit of work (task:..., file path, market:...) so no other agent does it at the same time.",
    validate: async (_runtime, message) => /\b(task|market|wallet|file):\S+/.test(message?.content?.text || ""),
    handler: async (runtime, message, _state, _options, callback) => {
      const unit = (message.content.text.match(/\b(?:task|market|wallet|file):\S+/) || [])[0];
      const k = await client(runtime);
      const ok = await k.claim(unit);
      const text = ok ? `Claimed ${unit}.` : `${unit} is held by ${k.holder}; taking other work.`;
      await callback?.({ text });
      return { success: ok, text };
    },
    examples: [[{ name: "{{user}}", content: { text: "work on task:invoice-4411" } },
                { name: "{{agent}}", content: { text: "Claimed task:invoice-4411.", actions: ["KNOS_CLAIM"] } }]],
  };

  const recall = {
    name: "KNOS_RECALL",
    similes: ["SHARED_MEMORY"],
    description: "Look up what any agent on this workspace recorded, with sources.",
    validate: async () => true,
    handler: async (runtime, message, _state, _options, callback) => {
      const text = await (await client(runtime)).recall(message.content.text);
      await callback?.({ text });
      return { success: true, text };
    },
    examples: [],
  };

  return { name: "knos", description: "Claims and shared memory across agents (Knos)", actions: [claim, recall] };
}
