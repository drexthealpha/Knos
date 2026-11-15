"""The Tempo escrow (contracts/KnosEscrow.sol) from Python: deploy, post, claim, deliver, accept, verify_release, reject,
release, refund.

Plain JSON-RPC and signed legacy transactions (eth_account), so the same code runs on Tempo Moderato, Tempo mainnet
(locked until the audit, capped at $500 per job in the contract itself), and a local anvil for tests and the bench.
On Tempo a job id is the sha256 of its brief, so the brief on any relay is checked against the id itself.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ARTIFACT = Path(__file__).with_name("KnosEscrow.json")
TEST_TOKEN = Path(__file__).with_name("TestToken.json")
MODERATO = "https://rpc.moderato.tempo.xyz"
PATH_USD = "0x20C0000000000000000000000000000000000000"
STATES = {0: "none", 1: "open", 2: "claimed", 3: "delivered", 4: "released", 5: "refunded"}
MIN_JOB_UNITS = 1_000_000     # 1 USDC (pathUSD has 6 decimals)
MIN_FEE_UNITS = 50_000        # fee = max(2.5%, 0.05)


class TempoError(Exception):
    pass


def _sel(sig: str) -> bytes:
    from eth_utils import keccak
    return keccak(text=sig)[:4]


@dataclass
class TempoJob:
    id: bytes
    buyer: str
    worker: str | None
    amount: int
    deadline: int
    state: str
    result: bytes | None
    verifier: str | None = None    # may release on proof (0.3.4 contracts); None = none, or a pre-0.3.4 contract
    proof: bytes | None = None


class Chain:
    def __init__(self, url: str, timeout: float = 30.0):
        self.url, self.timeout, self._id = url, timeout, 0
        self._chain_id = None
        self._gas_price = None

    def rpc(self, method: str, params: list):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode()
        for attempt in range(5):   # Moderato's public RPC sometimes answers with an empty body
            try:
                req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json",
                                                                         "User-Agent": "knos"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - configured RPC
                    got = json.loads(r.read())
                break
            except (OSError, ValueError):
                if attempt == 4:
                    raise
                time.sleep(0.3 * (attempt + 1))
        if "error" in got:
            raise TempoError(got["error"].get("message", str(got["error"])))
        return got["result"]

    @property
    def chain_id(self) -> int:
        if self._chain_id is None:
            self._chain_id = int(self.rpc("eth_chainId", []), 16)
        return self._chain_id

    def call(self, to: str, sig: str, types: list, args: list) -> bytes:
        from eth_abi import encode
        data = "0x" + (_sel(sig) + encode(types, args)).hex()
        return bytes.fromhex(self.rpc("eth_call", [{"to": to, "data": data}, "latest"])[2:])

    def send(self, key, to: str | None, data: bytes, gas: int | None = None) -> dict:
        from eth_account import Account
        from eth_utils import to_checksum_address
        if self._gas_price is None:
            self._gas_price = int(self.rpc("eth_gasPrice", []), 16)
        nonce = int(self.rpc("eth_getTransactionCount", [key.address, "pending"]), 16)
        if gas is None:   # Tempo prices new state far above Ethereum, so estimate rather than assume
            q = {"from": key.address, "data": "0x" + data.hex()}
            if to:
                q["to"] = to
            gas = min(int(self.rpc("eth_estimateGas", [q]), 16) * 13 // 10, 30_000_000)   # the per-tx gas cap
        tx = {"to": to_checksum_address(to) if to else b"", "data": data, "value": 0, "gas": gas, "gasPrice": self._gas_price, "nonce": nonce,
              "chainId": self.chain_id}
        raw = Account.sign_transaction(tx, key.key).raw_transaction
        h = self.rpc("eth_sendRawTransaction", ["0x" + raw.hex()])
        end = time.monotonic() + 60
        while time.monotonic() < end:
            rec = self.rpc("eth_getTransactionReceipt", [h])
            if rec:
                if int(rec["status"], 16) != 1:
                    raise TempoError(f"reverted: {h}")
                return rec
            time.sleep(0.1)
        raise TempoError(f"{h} not mined within 60 s")

    def deploy(self, key, artifact: Path, types: list, args: list) -> str:
        from eth_abi import encode
        art = json.loads(artifact.read_text(encoding="utf-8"))
        code = bytes.fromhex(art["bytecode"].removeprefix("0x")) + encode(types, args)
        from eth_utils import to_checksum_address
        return to_checksum_address(self.send(key, None, code)["contractAddress"])

    def balance(self, token: str, who: str) -> int:
        from eth_abi import decode
        return decode(["uint256"], self.call(token, "balanceOf(address)", ["address"], [who]))[0]

    def now(self) -> int:
        return int(self.rpc("eth_getBlockByNumber", ["latest", False])["timestamp"], 16)


class Escrow:
    def __init__(self, chain: Chain, address: str, token: str):
        self.chain, self.address, self.token = chain, address, token

    @classmethod
    def deploy(cls, chain: Chain, key, token: str, fee_to: str, fee_bps: int = 250, review_s: int = 86_400,
               guardian: str | None = None, cap_units: int = 0, min_fee_units: int = MIN_FEE_UNITS,
               min_job_units: int = MIN_JOB_UNITS) -> "Escrow":
        addr = chain.deploy(key, ARTIFACT, ["address", "address", "uint16", "uint128", "uint128", "uint64", "address",
                                            "uint128"],
                            [token, fee_to, fee_bps, min_fee_units, min_job_units, review_s, guardian or key.address,
                             cap_units])
        return cls(chain, addr, token)

    def _tx(self, key, sig: str, types: list, args: list) -> dict:
        from eth_abi import encode
        return self.chain.send(key, self.address, _sel(sig) + encode(types, args))

    def post(self, buyer, job_id: bytes, amount: int, work_s: int, verifier: str | None = None) -> dict:
        """Approve, then post. `verifier` (an address; default none) may release the delivered work on proof."""
        from eth_abi import encode
        self.chain.send(buyer, self.token, _sel("approve(address,uint256)") + encode(["address", "uint256"],
                                                                                     [self.address, amount]))
        if verifier:
            return self._tx(buyer, "postWithVerifier(bytes32,uint128,uint64,address)",
                            ["bytes32", "uint128", "uint64", "address"], [job_id, amount, work_s, verifier])
        return self._tx(buyer, "post(bytes32,uint128,uint64)", ["bytes32", "uint128", "uint64"],
                        [job_id, amount, work_s])

    def verify_release(self, verifier, job_id: bytes, result_hash: bytes, proof_root: bytes) -> dict:
        """Paid on proof: the job's verifier releases it, naming the exact result hash the worker committed (the
        contract refuses any other: "verifier releases unproven work") and recording `proof_root`."""
        return self._tx(verifier, "verifyRelease(bytes32,bytes32,bytes32)", ["bytes32", "bytes32", "bytes32"],
                        [job_id, result_hash, proof_root])

    def set_paused(self, guardian, on: bool) -> dict:
        return self._tx(guardian, "setPaused(bool)", ["bool"], [on])

    def lower_cap(self, guardian, cap_units: int) -> dict:
        return self._tx(guardian, "lowerCap(uint128)", ["uint128"], [cap_units])

    def fee(self, amount: int) -> int:
        from eth_abi import decode
        return decode(["uint256"], self.chain.call(self.address, "fee(uint256)", ["uint256"], [amount]))[0]

    def claim(self, worker, job_id: bytes) -> dict:
        return self._tx(worker, "claim(bytes32)", ["bytes32"], [job_id])

    def deliver(self, worker, job_id: bytes, result: bytes) -> dict:
        return self._tx(worker, "deliver(bytes32,bytes32)", ["bytes32", "bytes32"], [job_id, result])

    def accept(self, buyer, job_id: bytes) -> dict:
        return self._tx(buyer, "accept(bytes32)", ["bytes32"], [job_id])

    def reject(self, buyer, job_id: bytes) -> dict:
        return self._tx(buyer, "reject(bytes32)", ["bytes32"], [job_id])

    def release(self, anyone, job_id: bytes) -> dict:
        return self._tx(anyone, "release(bytes32)", ["bytes32"], [job_id])

    def refund(self, buyer, job_id: bytes) -> dict:
        return self._tx(buyer, "refund(bytes32)", ["bytes32"], [job_id])

    def job(self, job_id: bytes) -> TempoJob:
        """A job, from a 0.3.4 contract (8 fields) or a pre-0.3.4 one (6 fields: no verifier, no proof)."""
        from eth_abi import decode
        raw = self.chain.call(self.address, "jobs(bytes32)", ["bytes32"], [job_id])
        types = ["address", "address", "uint128", "uint64", "uint8", "bytes32"]
        verifier, proof = None, None
        if len(raw) >= 8 * 32:
            b, w, amount, deadline, state, result, v, p = decode(types + ["address", "bytes32"], raw)
            verifier, proof = (None if int(v, 16) == 0 else v), (None if p == bytes(32) else p)
        else:
            b, w, amount, deadline, state, result = decode(types, raw)
        zero = "0x" + "0" * 40
        return TempoJob(job_id, b, None if w == zero else w, amount, deadline, STATES[state],
                        None if result == bytes(32) else result, verifier, proof)


ESCROW_MODERATO = "0x8B913C5946a4C1CD95089D7a563dB864d46b694E"   # 0.3.6: + ERC-8183 jobs; fee max(2.5%, 0.05 USDC)
DEPLOY_BLOCK_MODERATO = 37_733_653          # at or before the deployment (a log-scan start)


def _posted_topic() -> str:
    from eth_utils import keccak
    return "0x" + keccak(text="Posted(bytes32,address,uint256)").hex()


class TempoVenue:
    """Knos jobs on the Tempo escrow, for the reference worker: open jobs from the contract's Posted logs, briefs from
    the relay (a Tempo job id is the sha256 of its brief, so the relay cannot swap it), claim and deliver on chain.
    The deliverable is sealed to the brief's `seal_to` key (the web app's passkey buyers set one); a brief without
    one is skipped, since an EVM address is not an encryption key."""

    def __init__(self, escrow: Escrow, relay, key, from_block: int = DEPLOY_BLOCK_MODERATO):
        self.escrow, self.relay, self.key, self.from_block = escrow, relay, key, from_block

    @classmethod
    def moderato(cls, relay, key) -> "TempoVenue":
        return cls(Escrow(Chain(MODERATO), ESCROW_MODERATO, PATH_USD), relay, key)

    def open(self) -> list[tuple[TempoJob, object]]:
        from .market import Brief
        logs = self.escrow.chain.rpc("eth_getLogs", [{"address": self.escrow.address, "fromBlock": hex(self.from_block),
                                                      "toBlock": "latest", "topics": [_posted_topic()]}]) or []
        now = self.escrow.chain.now()
        out = []
        for log in logs:
            jid = bytes.fromhex(log["topics"][1][2:])
            j = self.escrow.job(jid)
            if j.state != "open" or j.deadline < now:
                continue
            try:
                brief = Brief.decode(self.relay.get_brief(jid.hex()))
            except Exception:  # noqa: BLE001 - a brief this relay does not hold, or does not verify, is skipped
                continue
            if brief.seal_to:
                out.append((j, brief))
        return sorted(out, key=lambda x: x[0].deadline)

    def claim(self, j: TempoJob) -> bool:
        try:
            self.escrow.claim(self.key, j.id)
            return True
        except TempoError:
            return False

    def deliver(self, j: TempoJob, text: str, seal_to: str) -> str:
        from .market import seal_for
        sealed = seal_for(None, text.encode(), seal_to)
        h = self.relay.put_delivery(sealed)
        self.escrow.deliver(self.key, j.id, bytes.fromhex(h))
        return h
