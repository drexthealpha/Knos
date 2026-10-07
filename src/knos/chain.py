"""Solana, as much of it as Knos needs: a JSON-RPC client on the standard library, `solders` for signing, and the
`Ledger` the relays talk to (knos.settle.relay for the first deployment, knos.settle.v2.relay for the second; the tests
hand them LiteSVM behind the same methods).

    KNOS_CLUSTER   devnet (default) or localnet. Mainnet is refused: the programs are not deployed there.
    KNOS_RPC       a custom RPC endpoint for that cluster
    KNOS_RELAY_KEY the key that pays the transaction fees (a JSON array of 64 bytes, or base58); default
                   ~/.knos/relay-key.json, created on first use. It holds no one's money and decides nothing.
    KNOS_WALLET_KEY a wallet for the commands that move its own money (`knos balance`, `knos fund-wallet`), in the same forms

A relay waits on round trips, so the Ledger keeps them few: `accounts` reads many accounts in one request, `send_all`
signs transactions that do not depend on each other over one blockhash, sends them side by side and waits for all of
them at once, `now` is one read of the clock the programs see, and a v1 transaction (`v1=True`: 4,096 bytes where a
legacy one holds 1,232) carries in one round what took three. `simulate` asks what a transaction would do, for no fee. The public endpoints count requests per address
(devnet: 100 in 10 seconds, 40 of them for one method; solana.com/docs/references/clusters): a 429 is waited out here,
never passed on as a failure.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from solders.compute_budget import ID as COMPUTE_BUDGET
from solders.compute_budget import set_compute_unit_limit
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message, MessageV1, TransactionConfig
from solders.pubkey import Pubkey
from solders.transaction import Transaction, VersionedTransaction

CLUSTERS = {"devnet": "https://api.devnet.solana.com", "localnet": "http://127.0.0.1:8899"}
MAX_COMPUTE_UNITS = 1_400_000   # the most one transaction may use
MAX_TX_BYTES = 1232             # the most one transaction may weigh, its signatures included
MAX_V1_BYTES = 4096             # and a v1 transaction (SIMD-0385), which carries its limits in the message, not in instructions
V1_LOADED = 64 * 1024 * 1024    # the account data a v1 transaction may load: unset means none, so it is always set (the legacy default)
# A cluster reads a v1 transaction's compute-unit limit from the message and runs a compute budget instruction in it as
# any other instruction, to no effect (devnet, Agave 4.4.0, by simulation, 3 Oct 2026). LiteSVM as solders 0.29.0 ships
# it runs v1 transactions but reads the limit from that instruction only (200,000 units an instruction without one):
# the tests turn this on, and the instruction then goes in beside the message's own limit.
V1_BUDGET_IX = False
CLOCK = Pubkey.from_string("SysvarC1ock11111111111111111111111111111111")
SIDE_BY_SIDE = 8                # requests `send_all` has in flight at once
LOG = "Program log: "            # what the runtime puts before a line a program logged
TERMS = "knos2:terms "          # what knos-pay logs before a job's terms JSON, in the transaction that funds it
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INVOKE, _DONE = re.compile(r"Program (\w{32,44}) invoke \[(\d+)\]$"), re.compile(r"Program \w{32,44} (?:success$|failed: )")


class Refused(Exception):
    pass


class RpcError(ValueError):
    def __init__(self, message: str, data: Any = None):
        logs = (data or {}).get("logs") if isinstance(data, dict) else None
        super().__init__(message + (" | " + " | ".join(logs[-4:]) if logs else ""))   # a failing program's own words
        self.data = data


def call(url: str, method: str, params: list, timeout: float = 10.0) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "knos"})
    got: dict = {}
    for wait_s in (1, 2, 4, 8, None):     # public endpoints rate-limit (429): back off rather than fail
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the configured cluster endpoint
                got = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or wait_s is None:
                raise
            asked = str(e.headers.get("Retry-After", "") if e.headers else "")    # the endpoint's own figure, when it gives one
            time.sleep(min(float(asked), 30.0) if asked.isdigit() else wait_s)
    if "error" in got:
        err = got["error"]
        raise RpcError(str(err.get("message", err)), err.get("data"))
    return got.get("result")


def b58(raw: bytes) -> str:
    n, out = int.from_bytes(raw, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def said(logs, program: Pubkey | None = None) -> list[str]:
    """The lines programs logged in one transaction, without the "Program log: " the runtime puts before them; with
    `program`, only what that program itself logged. A program can log any text, so who is speaking is read from the
    runtime's own lines ("Program <id> invoke [depth]", "... success", "... failed: ..."), which no program can write."""
    out: list[str] = []
    stack: list[str] = []
    for line in logs:
        called = _INVOKE.match(line)
        if called:
            stack[int(called.group(2)) - 1:] = [called.group(1)]
        elif _DONE.match(line):
            del stack[-1:]
        elif line.startswith(LOG) and (program is None or stack[-1:] == [str(program)]):
            out.append(line[len(LOG):])
    return out


def message(ixs, payer: Pubkey, blockhash: Hash | None = None) -> Message:
    """The message `Ledger.send` signs: these instructions, behind a compute-unit limit when they bring none (a cluster
    gives an instruction 200,000 compute units unless asked; GitHub's RSA signature takes more)."""
    ixs = list(ixs)
    if not any(ix.program_id == COMPUTE_BUDGET for ix in ixs):
        ixs.insert(0, set_compute_unit_limit(MAX_COMPUTE_UNITS))
    return Message.new_with_blockhash(ixs, payer, blockhash or Hash.default())


def message_v1(ixs, payer: Pubkey, blockhash: Hash | None = None) -> MessageV1:
    """The same instructions as a v1 message: up to MAX_V1_BYTES, no lookup tables, and the compute-unit limit in the
    message itself (the limit an instruction among `ixs` asks for, else the most a transaction may use). A compute
    budget instruction does nothing in a v1 transaction, so those are left out (see V1_BUDGET_IX)."""
    units, rest = MAX_COMPUTE_UNITS, []
    for ix in ixs:
        if ix.program_id != COMPUTE_BUDGET:
            rest.append(ix)
        elif bytes(ix.data)[:1] == b"\x02":
            units = int.from_bytes(bytes(ix.data)[1:5], "little")
    config = TransactionConfig(compute_unit_limit=units, loaded_accounts_data_size_limit=V1_LOADED)
    return MessageV1.try_compile(payer, ([set_compute_unit_limit(units)] if V1_BUDGET_IX else []) + rest, blockhash or Hash.default(), config)


def tx_size(ixs, payer: Pubkey, v1: bool = False) -> int:
    """The bytes these instructions weigh as one transaction of `Ledger.send`'s, signed. A cluster takes MAX_TX_BYTES,
    and MAX_V1_BYTES of a v1 transaction (`v1`)."""
    if v1:
        m1 = message_v1(ixs, payer)
        return 1 + 64 * m1.header.num_required_signatures + len(bytes(m1))      # the version byte (0x81), the message, the signatures
    m = message(ixs, payer)
    return 1 + 64 * m.header.num_required_signatures + len(bytes(m))


def sign(ixs, payer: Keypair, signers, blockhash: Hash, v1: bool = False) -> Transaction | VersionedTransaction:
    """One transaction: `message` over `blockhash` (`message_v1` with `v1`), signed by the fee payer and whoever else
    must sign."""
    everyone = {bytes(k.pubkey()): k for k in [payer, *(signers or [])]}
    if v1:
        m1 = message_v1(ixs, payer.pubkey(), blockhash)
        return VersionedTransaction(m1, [everyone[bytes(k)] for k in m1.account_keys[:m1.header.num_required_signatures]])
    return Transaction(list(everyone.values()), message(ixs, payer.pubkey(), blockhash), blockhash)


def v1_refused(why: BaseException) -> bool:
    """Whether a failure says the cluster does not take v1 transactions at all (an endpoint or a validator older than
    SIMD-0385), which is no verdict on what the transaction asked for: the same instructions go out as legacy ones."""
    text = str(why).lower()
    return any(mark in text for mark in ("unsupported transaction version", "transaction version", "failed to deserialize", "invalid transaction version",
                                         "unsupportedversion"))


def wait_all(url: str, signatures: list[str], within: float = 60.0, commitment: str = "confirmed") -> list[dict]:
    """Wait until every signature reaches `commitment`, asking about all of them in one request each time. RpcError
    if one failed on chain (once all have an answer), TimeoutError if one never landed."""
    end = time.monotonic() + within
    good = ("finalized",) if commitment == "finalized" else ("confirmed", "finalized")
    got: dict[str, dict] = {}
    while True:
        waiting = [s for s in dict.fromkeys(signatures) if s not in got]
        if waiting:
            for sig, status in zip(waiting, call(url, "getSignatureStatuses", [waiting])["value"]):
                if status and status.get("confirmationStatus") in good:
                    got[sig] = status
        if len(got) == len(set(signatures)):
            break
        if time.monotonic() >= end:
            lost = next(s for s in signatures if s not in got)
            raise TimeoutError(f"{lost} not confirmed within {within:.0f}s")
        time.sleep(0.4)
    failed = next((got[s] for s in signatures if got[s].get("err")), None)
    if failed is not None:
        raise RpcError(f"transaction failed: {failed['err']}", failed)
    return [got[s] for s in signatures]


def wait(url: str, signature: str, within: float = 60.0, commitment: str = "confirmed") -> dict:
    """Wait until `signature` reaches `commitment`; RpcError if it failed on chain, TimeoutError if it never landed."""
    return wait_all(url, [signature], within, commitment)[0]


@dataclass
class Ledger:
    """A cluster reached over JSON-RPC."""
    url: str
    commitment: str = "confirmed"
    takes_v1: bool = True       # v1 transactions (4,096 bytes) may be sent; a relay sets it False once the cluster has refused one

    # -- writing ---------------------------------------------------------------------------------------------------
    def _blockhash(self) -> Hash:
        return Hash.from_string(call(self.url, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])

    def _submit(self, tx: Transaction | VersionedTransaction) -> str:
        """Hand one signed transaction to the cluster, with preflight: a failing program returns its logs, and costs
        no fee."""
        raw = base64.b64encode(bytes(tx)).decode()
        return call(self.url, "sendTransaction", [raw, {"encoding": "base64", "preflightCommitment": "confirmed"}])

    def send(self, ixs, payer: Keypair, signers: list[Keypair] | None = None, v1: bool = False) -> str:
        """Sign, send (with preflight, so a failing program returns its logs) and wait for `commitment`. `v1`: as a
        v1 transaction, which holds MAX_V1_BYTES."""
        sig = self._submit(sign(ixs, payer, signers, self._blockhash(), v1))
        wait(self.url, sig, 60.0, self.commitment)
        return sig

    def simulate(self, ixs, payer: Keypair, signers: list[Keypair] | None = None, v1: bool = False) -> list[str]:
        """What the cluster would log for this transaction, without sending it: no fee, nothing changed. RpcError,
        with the programs' own words, when it would fail."""
        raw = base64.b64encode(bytes(sign(ixs, payer, signers, Hash.default(), v1))).decode()
        got = call(self.url, "simulateTransaction", [raw, {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True,
                                                           "commitment": self.commitment}])["value"]
        if got.get("err"):
            raise RpcError(f"transaction failed: {got['err']}", got)
        return list(got.get("logs") or [])

    def send_all(self, groups, payer: Keypair, signers: list[Keypair] | None = None, v1: bool = False) -> list[str]:
        """Several transactions that do not depend on each other (`groups`: the instructions of each): signed over one
        blockhash, sent without waiting between them, then waited for together, so the lot costs one round of
        confirmation where `send` in turn would cost one each. Returns their signatures in order. Raises what `send`
        would for the first that failed, once the others have landed or failed too (so the caller knows where the
        chain stands). No two groups may be the same instructions: they would be one transaction."""
        groups = [list(g) for g in groups]
        if len(groups) < 2:
            return [self.send(g, payer, signers, v1) for g in groups]
        blockhash = self._blockhash()
        txs = [sign(ixs, payer, signers, blockhash, v1) for ixs in groups]

        def submit(tx):
            try:
                return self._submit(tx)
            except Exception as why:  # noqa: BLE001 - kept, and raised below once the rest have been waited for
                return why
        with ThreadPoolExecutor(max_workers=min(len(txs), SIDE_BY_SIDE)) as pool:
            sent = list(pool.map(submit, txs))
        refused = next((s for s in sent if not isinstance(s, str)), None)
        try:
            wait_all(self.url, [s for s in sent if isinstance(s, str)], 60.0, self.commitment)
        except Exception:
            if refused is None:
                raise
        if refused is not None:
            raise refused
        return sent

    # -- reading ---------------------------------------------------------------------------------------------------
    def infos(self, addresses) -> list[tuple[Pubkey, bytes] | None]:
        """(owner, data) of each account, None for one that does not exist: one request per hundred addresses."""
        addresses, out = list(addresses), []
        for i in range(0, len(addresses), 100):
            got = call(self.url, "getMultipleAccounts", [[str(a) for a in addresses[i:i + 100]],
                                                         {"encoding": "base64", "commitment": self.commitment}])
            out += [(Pubkey.from_string(v["owner"]), base64.b64decode(v["data"][0])) if v else None for v in got["value"]]
        return out

    def account(self, address: Pubkey) -> bytes | None:
        got = call(self.url, "getAccountInfo", [str(address), {"encoding": "base64", "commitment": self.commitment}])
        return base64.b64decode(got["value"]["data"][0]) if got["value"] else None

    def accounts(self, addresses) -> list[bytes | None]:
        """The data of each account (None: it does not exist), in one request per hundred addresses."""
        return [i[1] if i else None for i in self.infos(addresses)]

    def owner(self, address: Pubkey) -> Pubkey | None:
        """The program that owns an account: for a mint, its token program."""
        got = self.infos([address])[0]
        return got[0] if got else None

    def program_accounts(self, program: Pubkey, size: int | None = None, memcmp: dict[int, bytes] | None = None) -> list[tuple[Pubkey, bytes]]:
        """(address, data) of every account of `program` whose bytes at each offset match, of this size when one is
        given."""
        filters: list[dict] = [{"dataSize": size}] if size is not None else []
        filters += [{"memcmp": {"offset": off, "bytes": b58(raw)}} for off, raw in (memcmp or {}).items()]
        got = call(self.url, "getProgramAccounts", [str(program), {"encoding": "base64", "commitment": self.commitment,
                                                                   "filters": filters}], timeout=30) or []
        return [(Pubkey.from_string(i["pubkey"]), base64.b64decode(i["account"]["data"][0])) for i in got]

    def recent(self, address: Pubkey, limit: int = 20) -> list[tuple[str, int | None]]:
        """(signature, unix time) of the successful transactions that touched `address`, newest first: at most `limit`
        of the cluster's rows (failed ones are among the rows and left out here)."""
        got = call(self.url, "getSignaturesForAddress", [str(address), {"limit": limit, "commitment": self.commitment}]) or []
        return [(g["signature"], g.get("blockTime")) for g in got if g.get("err") is None]

    def signatures(self, address: Pubkey, limit: int = 20) -> list[str]:
        return [sig for sig, _when in self.recent(address, limit)]

    def last_signature(self, address: Pubkey) -> str | None:
        """The most recent successful transaction that touched `address`."""
        return next(iter(self.signatures(address, 5)), None)

    def touched(self, address: Pubkey) -> int | None:
        """When a transaction last named `address` (unix time, failed or not); None when the cluster knows of none."""
        got = call(self.url, "getSignaturesForAddress", [str(address), {"limit": 1, "commitment": self.commitment}]) or []
        return got[0].get("blockTime") if got else None

    def _transaction(self, signature: str) -> dict:
        """One transaction as the cluster gives it (version 1 included); {} when the cluster no longer has it."""
        return call(self.url, "getTransaction", [signature, {"encoding": "json", "commitment": self.commitment,
                                                             "maxSupportedTransactionVersion": 1}], timeout=20) or {}

    def logs(self, signature: str) -> list[str]:
        """What the programs logged in one transaction, line by line; empty when the cluster no longer has it."""
        return list((self._transaction(signature).get("meta") or {}).get("logMessages") or [])

    def payer_of(self, signature: str) -> str | None:
        """The fee payer of one transaction (its first account); None when the cluster no longer has it."""
        keys = ((self._transaction(signature).get("transaction") or {}).get("message") or {}).get("accountKeys") or []
        return str(keys[0]) if keys else None

    def history(self, address: Pubkey, most: int = 500):
        """The successful transactions that touched `address`, newest first: a hundred of the cluster's rows a
        request (failed ones are among the rows and left out here), and at most `most` rows in all."""
        before, rows = None, 0
        while rows < most:
            opts = {"limit": 100, "commitment": self.commitment, **({"before": before} if before else {})}
            got = call(self.url, "getSignaturesForAddress", [str(address), opts]) or []
            yield from (g["signature"] for g in got if g.get("err") is None)
            if len(got) < 100:
                return
            before, rows = got[-1]["signature"], rows + len(got)

    def log_of(self, address: Pubkey, marker: str, check=None, by: Pubkey | None = None) -> str | None:
        """The log line that starts with `marker` in the transaction that made what is at `address`: the line as the
        program wrote it, marker included (a job's terms are logged as `knos2:terms <json>` when it is funded).
        The transactions that touched `address` are read newest first and the first such line is the answer: an
        address is used again (a job is refunded, and the issue funded anew), so the newest funding is the one that
        made what is there now. Anyone can name any address in a transaction of their own and log anything in it:
        `by` takes only what that program itself logged, and `check(line)` says which line is meant (`terms_of`
        takes only the terms whose hash the job stores). None when the last 500 transactions of the address hold no
        such line."""
        for sig in self.history(address):
            for line in said(self.logs(sig), by):
                if line.startswith(marker) and (check is None or check(line)):
                    return line
        return None

    def terms_of(self, job: Pubkey) -> bytes | None:
        """The terms JSON a job of the second deployment was funded with. knos-pay keeps only their sha256 in the
        job and logs the JSON itself in the funding transaction; this is `log_of` for that line as knos-pay wrote it,
        held to the hash the job stores. For a job that is gone: the terms of the last funding at its address. None
        when there are none."""
        from .settle.v2 import pay
        j = pay.read_job(self.account(job))
        line = self.log_of(job, TERMS, (lambda line: pay.terms_hash(line[len(TERMS):].encode()) == j.terms) if j else None, pay.PAY_ID)
        return line[len(TERMS):].encode() if line else None

    def now(self) -> int:
        """Unix time as the programs see it: the cluster's Clock account, never the local clock."""
        data = self.account(CLOCK)
        if data is None or len(data) < 40:
            raise RpcError("the cluster's clock could not be read")
        return int.from_bytes(data[32:40], "little", signed=True)


def ledger() -> Ledger:
    c = os.environ.get("KNOS_CLUSTER", "devnet")
    if c not in CLUSTERS:
        raise Refused(f"Knos runs on devnet (or a localnet) only; {c!r} is not available.")
    return Ledger(os.environ.get("KNOS_RPC") or CLUSTERS[c])


def _keypair(text: str) -> Keypair:
    text = text.strip()
    if text.startswith("["):
        return Keypair.from_bytes(bytes(json.loads(text)))
    return Keypair.from_base58_string(text)


def key() -> Keypair:
    """The fee payer: KNOS_RELAY_KEY (KNOS_MEMBER_KEY, its name before 0.3.10, still works), else a key file made on
    first use, readable by its owner only."""
    env = os.environ.get("KNOS_RELAY_KEY") or os.environ.get("KNOS_MEMBER_KEY")
    if env:
        return _keypair(env)
    from . import paths
    p = paths.home() / "relay-key.json"
    try:
        return _keypair(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    k = Keypair()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(list(bytes(k))))
    return k


def wallet(file: str | os.PathLike | None = None) -> Keypair:
    """A wallet that signs for its own money: the keypair file given (as `solana-keygen` writes it), else
    KNOS_WALLET_KEY. Refused, in words, when there is neither or it cannot be read."""
    try:
        if file:
            with open(file, encoding="utf-8") as f:
                return _keypair(f.read())
        if os.environ.get("KNOS_WALLET_KEY"):
            return _keypair(os.environ["KNOS_WALLET_KEY"])
    except (OSError, ValueError) as why:
        raise Refused(f"That is not a Solana keypair ({why}). It is a JSON array of 64 numbers, as `solana-keygen new` "
                      "writes it, or the key in base58.") from None
    raise Refused("This command signs with your wallet. Pass --keypair FILE (a Solana keypair file), or set KNOS_WALLET_KEY.")
