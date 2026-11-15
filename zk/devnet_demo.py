"""The knos_zk demo on devnet: the fixture proof verifies, tampered ones are refused ON CHAIN (sent past preflight so
the refusal has a public signature), the verdict is recorded, and a payout's check reads it back.

  KNOS_ZK_PAYER=<devnet keypair file> PYTHONPATH=src python zk/devnet_demo.py [program id] [out.json]

Writes the signatures and compute units to out.json (default zk/fixtures/score64/devnet.json; public data only). The
committed devnet.json was read back from the chain by zk/devnet_read.py, in the same shape.
SYNTHETIC data: the hidden set is the made-up sample of zk/score_circuit.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from knos import chain
from knos.zk import client, groth16

URL = os.environ.get("KNOS_ZK_RPC", "https://api.devnet.solana.com")
HERE = Path(__file__).resolve().parent


def main() -> None:
    program = Pubkey.from_string(sys.argv[1] if len(sys.argv) > 1 else client.DEVNET_PROGRAM_ID)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "fixtures" / "score64" / "devnet.json"
    payer = Keypair.from_json(Path(os.environ["KNOS_ZK_PAYER"]).read_text())
    vk, proof, inputs = groth16.load_dir(HERE / "fixtures" / "score64")
    assert groth16.verify(vk, proof, inputs)

    runs = {}
    runs["verify"] = client.send(URL, payer, [client.verify_ix(program, proof, inputs)])
    bad_c = bytearray(proof.c)
    bad_c[63] ^= 1
    tampered = groth16.Proof(proof.a, proof.b, bytes(bad_c))
    # a flipped bit of C can leave the curve; the program refuses either way. A lower-bar claim is a valid curve
    # point set with a false statement: the pairing itself says no.
    runs["tampered_threshold"] = client.send(
        URL, payer, [client.verify_ix(program, proof, [inputs[0], inputs[1], inputs[2] - 1])], skip_preflight=True)
    runs["tampered_proof_c"] = client.send(URL, payer, [client.verify_ix(program, tampered, inputs)], skip_preflight=True)
    verdict, _ = client.verdict_address(program, inputs)
    have = chain.call(URL, "getAccountInfo", [str(verdict), {"encoding": "base64", "commitment": "confirmed"}])["value"]
    if have is None:
        runs["verify_and_record"] = client.send(URL, payer, [client.record_ix(program, payer.pubkey(), proof, inputs)])
        have = chain.call(URL, "getAccountInfo", [str(verdict), {"encoding": "base64", "commitment": "confirmed"}])["value"]
    import base64

    data = base64.b64decode(have["data"][0])
    ok, why = client.payable(have["owner"], data, program, spec_hash=inputs[0], bar=48, pred_hash=inputs[1])

    def slim(r: dict) -> dict:
        return {"signature": r["signature"], "compute_units": r["compute_units"], "err": r["err"], "slot": r["slot"],
                "program_log": [ln for ln in r["logs"] if "knos_zk" in ln or "consumed" in ln or "failed" in ln]}

    doc = {
        "SYNTHETIC": "the hidden set is the made-up sample of zk/score_circuit; devnet only; TOY verifying key",
        "cluster": "devnet" if "devnet" in URL else "localnet (solana-test-validator)",
        "program_id": str(program),
        "verdict_account": str(verdict),
        "payable": ok, "payable_reasons": why,
        "runs": {k: slim(v) for k, v in runs.items()},
    }
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    main()
