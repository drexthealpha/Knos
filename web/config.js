// What the page reads from outside its own code. Everything here is data: change a line, nothing else moves.
//
// video: the recording at the top of the first screen, a release asset of this repository. `null` until a release
//   has one: the page then shows no video at all. The Pages build (scripts/build_site.sh) writes it from
//   KNOS_VIDEO_URL and, optionally, KNOS_VIDEO_POSTER; a file that cannot be loaded hides the video again.
// examples: what the three buttons under the first form put in it. Each input is a real one, and the checks in
//   tests/web/site.mjs say where it comes from: the two pull requests are in docs/agent_pr_ci.json, the transaction
//   is in tests/web/recorded/devnet_first_deployment.json.
export const CONFIG = {
  video: null,
  examples: [
    { id: "true", label: "A claim that is true", input: "https://github.com/usestrix/strix/pull/753",
      says: "an agent's pull request says its tests still pass, and GitHub's own checks agree" },
    { id: "false", label: "A claim that is false", input: "https://github.com/BerriAI/litellm/pull/34321",
      says: "a pull request ticks \"passes all CI\", and a check of its latest commit failed" },
    { id: "paid", label: "A task that was paid", input: "4PovnMjDMYj3DinBmX7S1vqN4KHVLxDd1tmoK5nrBNquiAidDxcrM78kMwezdziTxh4RroLp28ZVRFPoBh2zcDxt",
      says: "the transaction on Solana devnet that paid a task. Knos's own account paid itself there: a demonstration in test USDC" },
  ],
};
