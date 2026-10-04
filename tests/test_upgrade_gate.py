"""examples/upgrade_gate (LiteSVM, beside the test build of the second knos-oidc, with the test keys): a record
["build", program, executable hash] is written only on a token GitHub signed for Knos's own program.yml, at a commit of
main or of a release tag, with audience gate:<program>:<hash hex>. Everything else is refused, a record is written
once, and what `knos status` says about a pending upgrade's buffer follows from the record."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.pubkey import Pubkey  # noqa: E402

from _pay2 import FIX, Chain  # noqa: E402

from knos.settle.v2 import gate, oidc, pay  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ELF = b"\x7fELF" + hashlib.sha256(b"a build").digest() * 40      # stands for a program's bytes
HASH = gate.executable_hash(ELF)
COMMIT = "9" * 40
PROGRAM = pay.PAY_ID


class Gate(Chain):
    def __init__(self):
        super().__init__()
        self.svm.add_program_from_file(gate.GATE_ID, str(FIX / "upgrade_gate_v2_real.so"))

    def token(self, program: Pubkey = PROGRAM, executable: bytes = HASH, aud: str | None = None, **over) -> Pubkey:
        """What program.yml asks GitHub to sign after it built `program` at COMMIT."""
        self.warp(1)
        claims = {"file": "program.yml", "wf_repo": "drexthealpha/Knos", "wf_sha": COMMIT, "sha": COMMIT, "repository_id": gate.KNOS_REPO_ID,
                  "repository": "drexthealpha/Knos", "ref": "refs/heads/main", "event_name": "push", "run_id": 4242, **over}
        return self.gh(aud or gate.audience(program, executable), **claims)

    def record(self, tok: Pubkey, program: Pubkey = PROGRAM, executable: bytes = HASH, key: Pubkey | None = None) -> bool:
        return self.send([gate.record_ix(self.payer.pubkey(), tok, key or self.key, program, executable)], tag="record")

    def code(self) -> int | None:
        m = re.search(r"Custom\((\d+)\)", self.err or "")
        return int(m.group(1)) if m else None

    def account(self, address: str):
        """(owner, data) or None, as knos.mainnet_check's fetch gives an account."""
        a = self.svm.get_account(Pubkey.from_string(address))
        return (str(a.owner), bytes(a.data)) if a is not None and a.lamports > 0 else None


def test_a_build_is_recorded_only_on_githubs_word_and_once():
    c = Gate()
    tok = c.token()
    assert c.record(tok), c.err
    r = gate.read_record(c.data(gate.record_pda(PROGRAM, HASH)))
    assert r is not None and (r.program, r.executable, r.sha, r.run_id, r.time) == (PROGRAM, HASH, COMMIT, 4242, c.now())
    assert c.said("gate: build") == [f"gate: build program={PROGRAM} hash={HASH.hex()} commit={COMMIT} run=4242"]
    # written once: a later commit that builds the same bytes does not replace the first
    later = c.token(sha="8" * 40, wf_sha="8" * 40)
    assert not c.record(later) and gate.read_record(c.data(gate.record_pda(PROGRAM, HASH))).sha == COMMIT
    # the token says which program and which bytes: a relayer cannot record another pair with it
    other = hashlib.sha256(b"other").digest()
    assert not c.record(tok, executable=other) and not c.record(tok, program=oidc.OIDC_ID)
    assert c.data(gate.record_pda(PROGRAM, other)) is None
    # a release tag counts as main does
    assert c.record(c.token(executable=other, ref="refs/tags/v0.3.13"), executable=other), c.err


def test_nothing_but_knos_program_yml_at_the_commit_it_built_writes_a_record():
    c = Gate()
    n = iter(range(1, 100))
    fresh = lambda: hashlib.sha256(bytes([next(n)])).digest()  # noqa: E731
    for other in ({"repository_id": gate.KNOS_REPO_ID + 1}, {"file": "ci.yml"}, {"wf_repo": "mallory/Knos"}, {"runner_environment": "self-hosted"},
                  {"ref": "refs/heads/feature"}, {"ref": "refs/pull/7/merge"}, {"ref": "refs/tags/x"},
                  {"wf_sha": "8" * 40},                 # the workflow file of another commit than the one built
                  {"sha": "9" * 39 + "G"}):
        h = fresh()
        assert not c.record(c.token(executable=h, **other), executable=h) and c.code() == 1, other
    for aud in (f"gate:{PROGRAM}", f"gate:{PROGRAM}:{HASH.hex()}:x", f"knos3:{PROGRAM}:{HASH.hex()}", f"gate:{PROGRAM}:{HASH.hex().upper()}",
                f"gate:{PROGRAM}:{HASH.hex()[:62]}", f"gate:knos_pay:{HASH.hex()}"):
        assert not c.record(c.token(aud=aud)) and c.code() == 2, aud
    # a wrong key account; a revoked key: no record from a token it verified
    good = c.token()
    assert not c.record(good, key=gate.record_pda(PROGRAM, HASH)) and c.code() == 68
    assert c.revoke(oidc.GITHUB, c.github), c.err
    assert not c.record(good) and c.code() == 78
    assert c.data(gate.record_pda(PROGRAM, HASH)) is None


def test_knos_status_says_whether_a_pending_buffer_is_recorded():
    from solders.account import Account
    c = Gate()
    buffer, vault = Pubkey.from_bytes(hashlib.sha256(b"buffer").digest()), Pubkey.from_bytes(hashlib.sha256(b"vault").digest())
    loader = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")
    # a buffer as the loader lays it out; the cluster pads nothing, a programdata account may: trailing zeros do not count
    c.svm.set_account(buffer, Account(lamports=10 ** 9, data=(1).to_bytes(4, "little") + b"\x01" + bytes(vault) + ELF + bytes(64), owner=loader, executable=False))
    said = gate.words(c.account, str(PROGRAM), str(buffer))
    assert "NOT recorded by upgrade_gate" in said and HASH.hex() in said and "Do not approve it" in said
    assert c.record(c.token()), c.err
    said = gate.words(c.account, str(PROGRAM), str(buffer))
    assert said == (f"; the buffer's build {HASH.hex()} is recorded by upgrade_gate: GitHub's runner built it from commit {COMMIT} "
                    f"(run 4242, record {gate.record_pda(PROGRAM, HASH)})")
    # the record is of one program: the same bytes proposed for another program are not vouched for
    assert "NOT recorded" in gate.words(c.account, str(oidc.OIDC_ID), str(buffer))
    assert "could not be read" in gate.words(c.account, str(PROGRAM), str(vault)) and "could not be read" in gate.words(c.account, None, None)


def test_the_example_the_client_and_the_governance_script_name_one_program_and_one_layout():
    lib = (ROOT / "examples" / "upgrade_gate" / "src" / "lib.rs").read_text(encoding="utf-8")
    mjs = (ROOT / "scripts" / "governance.mjs").read_text(encoding="utf-8")
    assert f'declare_id!("{gate.GATE_ID}")' in lib and f'new PublicKey("{gate.GATE_ID}")' in mjs
    assert f"pub const KNOS_REPO_ID: u64 = {gate.KNOS_REPO_ID:_};" in lib and f'b"{gate.WORKFLOW}@"' in lib
    assert f"pub const RECORD_LEN: usize = {gate.RECORD_LEN};" in lib
    assert gate.KNOS_REPO_ID in json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))["attest_repo_ids"]
