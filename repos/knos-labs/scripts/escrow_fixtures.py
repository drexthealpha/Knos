"""Write sdk/escrow/fixtures.json: escrow instructions and a job account encoded by the Python builders (the
authority, src/knos/jobs/sol.py), so the npm package's tests (sdk/escrow/test.mjs) can check its encodings byte for
byte, offline.  Run: python scripts/escrow_fixtures.py
"""
import json
import struct
from pathlib import Path

from solders.pubkey import Pubkey

from knos.jobs import sol

OUT = Path(__file__).resolve().parents[1] / "sdk" / "escrow" / "fixtures.json"
PID = Pubkey.from_string(sol.DEVNET_PROGRAM)
NAMES = ["buyer", "worker", "verifier", "anyone", "buyer_token", "worker_token", "vault_token", "fee_token"]
K = {n: Pubkey(bytes([i + 1]) * 32) for i, n in enumerate(NAMES)}
B32 = {n: bytes([0xA0 + i]) * 31 + bytes([i]) for i, n in enumerate(["job_id", "brief", "result", "proof"])}
AMOUNT, WORK, REVIEW = 2_500_000, 3_600, 86_400

cases = [
    ("post", {"verifier": None}, sol.post(PID, K["buyer"], B32["job_id"], AMOUNT, WORK, REVIEW, B32["brief"],
                                          K["buyer_token"], K["vault_token"])),
    ("post", {"verifier": "verifier"}, sol.post(PID, K["buyer"], B32["job_id"], AMOUNT, WORK, REVIEW, B32["brief"],
                                                K["buyer_token"], K["vault_token"], verifier=K["verifier"])),
    ("claim", {}, sol.claim(PID, K["worker"], B32["job_id"], K["worker_token"], K["vault_token"])),
    ("deliver", {}, sol.deliver(PID, K["worker"], B32["job_id"], B32["result"], K["worker_token"], K["vault_token"])),
    ("accept", {}, sol.accept(PID, K["buyer"], B32["job_id"], K["vault_token"], K["worker_token"], K["fee_token"])),
    ("release", {}, sol.release(PID, K["anyone"], B32["job_id"], K["vault_token"], K["worker_token"], K["fee_token"],
                                K["buyer"])),
    ("verify_release", {}, sol.verify_release(PID, K["verifier"], B32["job_id"], B32["result"], B32["proof"],
                                              K["vault_token"], K["worker_token"], K["fee_token"], K["buyer"])),
    ("reject", {}, sol.reject(PID, K["buyer"], B32["job_id"], K["vault_token"], K["buyer_token"])),
    ("refund", {}, sol.refund(PID, K["buyer"], B32["job_id"], K["vault_token"], K["buyer_token"])),
    ("verify_reject", {}, sol.verify_reject(PID, K["verifier"], B32["job_id"], B32["proof"], K["vault_token"],
                                            K["buyer_token"], K["buyer"])),
    ("settle", {"signer": "anyone"}, sol.crank(PID, K["anyone"], B32["job_id"], K["vault_token"], K["worker_token"],
                                               K["fee_token"], K["buyer_token"], K["buyer"])),
    ("settle", {"signer": "buyer"}, sol.crank(PID, K["buyer"], B32["job_id"], K["vault_token"], K["worker_token"],
                                              K["fee_token"], K["buyer_token"], K["buyer"])),
]

# A 225-byte job account (delivered, with a verifier and a stake field), laid out as lib.rs Job::store.
job = (bytes([3]) + bytes(K["buyer"]) + bytes(K["worker"]) + struct.pack("<Qqq", AMOUNT, 1_900_000_000, REVIEW)
       + B32["brief"] + B32["result"] + bytes(K["verifier"]) + B32["proof"] + struct.pack("<Q", 250_000))
parsed = sol.parse_job(sol.job_pda(PID, B32["job_id"]), job)
assert len(job) == sol.JOB_LEN

fixture = {
    "program_id": str(PID),
    "keys": {n: str(k) for n, k in K.items()},
    "bytes32": {n: b.hex() for n, b in B32.items()},
    "numbers": {"amount": AMOUNT, "work": WORK, "review": REVIEW},
    "pdas": {"config2": str(sol.config_pda(PID)), "vault": str(sol.vault_authority(PID)),
             "job": str(sol.job_pda(PID, B32["job_id"]))},
    "instructions": [{"name": name, "options": opts, "data": ix.data.hex(),
                      "accounts": [{"pubkey": str(m.pubkey), "signer": m.is_signer, "writable": m.is_writable}
                                   for m in ix.accounts]} for name, opts, ix in cases],
    "job": {"hex": job.hex(), "state": parsed.state, "buyer": str(parsed.buyer), "worker": str(parsed.worker),
            "amount": parsed.amount, "deadline": parsed.deadline, "review": parsed.review,
            "brief": parsed.brief.hex(), "result": parsed.result.hex(), "verifier": str(parsed.verifier),
            "proof": parsed.proof.hex(), "stake": parsed.stake},
}
OUT.write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8")
print(f"wrote {OUT} ({len(cases)} instructions, job {len(job)} bytes)")
