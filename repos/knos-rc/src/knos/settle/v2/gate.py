"""Client of examples/upgrade_gate: the on-chain record that GitHub's runner built one executable from one commit.

A record ["build", program, hash] exists only if GitHub signed a token for a run of Knos's own program.yml, at a commit
of main or of a release tag, with audience gate:<program>:<hash hex>, and knos-oidc verified it. `hash` is the
executable hash (sha256 of the program's bytes without their trailing zeros: what `solana-verify get-executable-hash`
prints). scripts/governance.mjs refuses to propose an upgrade whose buffer has no record; `words` is the sentence
`knos status` adds to a pending upgrade.

How a record comes to be: program.yml's `gate` job, after the verified builds of a run on main or a release tag, hashes
each build and asks GitHub for a token with `audience`; it posts each as a `knos-gate:` comment on the "knos tokens"
issue of drexthealpha/Knos; the worker (knos.proof.ghrelay) finds it, and knos.settle.v2.relay has knos-oidc verify it
and sends `record_ix`. `scripts/deploy_v2.sh --propose` waits for the record before it proposes."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

GATE_ID = Pubkey.from_string("2DfVEuBMWvvh3kXZaQwk2SoszJsoV1PTiK1VGCkB55HW")
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
KNOS_REPO_ID = 1353152983
WORKFLOW = "drexthealpha/Knos/.github/workflows/program.yml"
RECORD_LEN = 136
BUFFER_HEADER = 37          # the upgradeable loader's Buffer: variant u32 (1), authority option (1 + 32), then the program


def executable_hash(program: bytes) -> bytes:
    """sha256 of the program's bytes without their trailing zeros."""
    return hashlib.sha256(bytes(program).rstrip(b"\x00")).digest()


def audience(program: Pubkey | str, executable: bytes) -> str:
    """What program.yml asks GitHub to sign for the build of `program` whose executable hash is `executable`."""
    return f"gate:{program}:{executable.hex()}"


def record_pda(program: Pubkey, executable: bytes, gate: Pubkey = GATE_ID) -> Pubkey:
    return Pubkey.find_program_address([b"build", bytes(program), executable], gate)[0]


@dataclass
class Record:
    run_id: int             # the GitHub Actions run that built it
    time: int               # when the record was written (the chain's clock)
    slot: int
    program: Pubkey
    executable: bytes       # the executable hash
    sha: str                # the commit GitHub built it from


def read_record(data: bytes | None) -> Record | None:
    if not data or len(data) != RECORD_LEN or data[0] != 1:
        return None
    return Record(run_id=int.from_bytes(data[8:16], "little"), time=int.from_bytes(data[16:24], "little", signed=True),
                  slot=int.from_bytes(data[24:32], "little"), program=Pubkey.from_bytes(data[32:64]), executable=bytes(data[64:96]),
                  sha=bytes(data[96:136]).decode("ascii", "replace"))


def record_ix(payer: Pubkey, token: Pubkey, key: Pubkey, program: Pubkey, executable: bytes, gate: Pubkey = GATE_ID) -> Instruction:
    """Anyone relays. `token`: the verified token account; `key`: the knos-oidc key account it names."""
    return Instruction(gate, b"", [AccountMeta(payer, True, True), AccountMeta(token, False, False), AccountMeta(key, False, False),
                                   AccountMeta(record_pda(program, executable, gate), False, True), AccountMeta(SYSTEM, False, False)])


def words(account, program: str | None, buffer: str | None, gate: Pubkey = GATE_ID) -> str:
    """What `knos status` says about the buffer of a pending upgrade. `account(address)` gives (owner, data) or None,
    as knos.mainnet_check's fetch does."""
    got = account(buffer) if program and buffer else None
    if not program or not got or len(got[1]) < BUFFER_HEADER or got[1][:4] != (1).to_bytes(4, "little"):
        return "; its buffer could not be read, so whether GitHub built it is not known"
    h = executable_hash(got[1][BUFFER_HEADER:])
    at = record_pda(Pubkey.from_string(program), h, gate)
    rec = account(str(at))
    r = read_record(rec[1]) if rec and str(rec[0]) == str(gate) else None
    if r is None or r.executable != h or str(r.program) != program:
        return (f"; the buffer's build {h.hex()} is NOT recorded by upgrade_gate ({at} does not exist): no GitHub run vouches for these bytes. "
                "Do not approve it until program.yml has recorded this hash, or the members have rebuilt it themselves")
    return f"; the buffer's build {h.hex()} is recorded by upgrade_gate: GitHub's runner built it from commit {r.sha} (run {r.run_id}, record {at})"
