// Which version of knos_pay is on devnet, read from the program itself: instruction 12 (Version) logs `knos2:version 1`
// in 2.1 and is refused by 2.0 as invalid instruction data. Simulated, never sent. The fee payer of a simulation must
// be an account that exists (nothing is signed, nothing is charged): the fee owner's, a public address. The blockhash is
// the zero one: simulating with replaceRecentBlockhash makes devnet put its own, so no blockhash has to be asked for first.
// Returns 1 (2.1 is live), 0 (2.0: the instruction is refused) or null (not told: devnet could not be asked, or it
// answered with something else).
export async function programVersion(knos, rpc, program, payer = knos.FEE_OWNER) {
  const tx = knos.serializeTx([{ program, data: Uint8Array.of(12), accounts: [] }], payer, knos.SYSTEM);
  const sim = (await knos.rpc(rpc, "simulateTransaction", [btoa(String.fromCharCode(...tx)), { encoding: "base64", sigVerify: false, replaceRecentBlockhash: true, commitment: "confirmed" }])).value;
  const said = (sim.logs || []).find((l) => /Program log: knos2:version \d+$/.test(l));
  if (said) return Number(said.split(" ").at(-1));
  return JSON.stringify(sim.err ?? null).includes("InvalidInstructionData") ? 0 : null;
}
