#!/usr/bin/env node
// npx knos@latest [paper link] [test USDC]: one real proof on NEAR testnet (POST https://knos.onrender.com/api/near/claim/flow);
// prints the claim, the locked test's sha256, the verdict and the receipt's NEAR transactions. No dependencies.
const [url = "https://doi.org/10.46298/dmtcs.3545", amount = "3"] = process.argv.slice(2);
if (url === "-h" || url === "--help") { console.log("npx knos@latest [paper link] [test USDC]"); process.exit(0); }
console.log(`Proving the claim of ${url} on NEAR testnet with ${amount} test USDC (about 25 s)...`);
let d;
try {
  const r = await fetch("https://knos.onrender.com/api/near/claim/flow", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, amount: Number(amount) }), signal: AbortSignal.timeout(300000) });
  d = await r.json();
} catch (e) {
  console.log(`Not proved: the service did not answer (${e.message}). Where to fix it: try again in a minute; https://drexthealpha.github.io/Knos/status/ says if it is up.`);
  process.exit(1);
}
const v = d.verdict || {};
if (!d.ok || !d.verdict) {
  console.log(`Not proved: ${d.why || d.next || d.why_not_settled || "no answer"}. Where to fix it: paste a paper Knos has a claim for, listed at https://drexthealpha.github.io/Knos/claims/`);
  process.exit(1);
}
console.log(`Claim: ${d.claim}`);
console.log(`Locked test sha256: ${d.test_sha256 || "not returned"}`);
console.log(`Verdict: ${v.holds ? "holds" : "does not hold"}${d.reused ? " (the last verified proof, reused)" : ""}, job ${d.job}`);
if (v.agent_a) console.log(`Agent A: ${v.agent_a}`);
if (v.ai_reviewer) console.log(`Reviewer: ${v.ai_reviewer}`);
const rc = d.receipt || {};
if (rc.buyer_usd != null) {
  console.log(`Receipt: ${rc.buyer_usd} test USDC behind the proof, ${rc.agent_usd} to the agent, ${rc.knos_usd} to Knos`);
  for (const k of ["fee_url", "agent_pay_url", "job_pay_url"]) if (rc[k]) console.log(`  NEAR: ${rc[k]}`);
} else if (d.why_not_settled) console.log(`Not paid: ${d.why_not_settled}`);
