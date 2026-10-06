"""scripts/exercise_public.py: the rounds that move a capability from "rehearsed on staging" to "exercised at the public
program ids", run here on the local simulator with the test builds and fixture tokens, end to end: the run, what it
keeps, a step that waits for a workflow run and is picked up later, `record` into a copy of the repository (the
manifest, the documents, the demo's data, the provenance page), `status` and `propose-oidc` with a fake cluster."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("exercise_public", ROOT / "scripts" / "exercise_public.py")
ex = importlib.util.module_from_spec(spec)
sys.modules["exercise_public"] = ex
spec.loader.exec_module(ex)

from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import gate  # noqa: E402

ELF = {n: bytes([i + 1]) * 64 + n.encode() for i, n in enumerate(ex.PROGRAMS)}      # stand-ins for the four builds
HASH = {n: gate.executable_hash(e).hex() for n, e in ELF.items()}
SLOT = 412_000_000
IDS = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))


def cluster(runs: dict[str, bytes]):
    """`account(address)` of a cluster where each program's data account holds these bytes, deployed in SLOT + its place."""
    held = {}
    for i, n in enumerate(ex.PROGRAMS):
        if n in runs:
            head = (3).to_bytes(4, "little") + (SLOT + i).to_bytes(8, "little") + b"\x01" + bytes(32)
            held[str(mc.programdata_address(IDS[n]))] = ("BPFLoaderUpgradeab1e11111111111111111111111", head + runs[n] + bytes(40))
    return lambda address: held.get(address)


def tree(tmp_path: Path) -> Path:
    """A copy of the repository whose feed names the stand-in builds for proposals 3 to 6."""
    root = tmp_path / "repo"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", "target", ".venv", ".knos-keys", "*.so"))
    feed = json.loads((root / "web" / "upgrades.json").read_text(encoding="utf-8"))
    for e in feed["entries"]:
        if e["index"] == ex.PROPOSALS.get(e["program"]):
            e["build_hash"] = HASH[e["program"]]
    (root / "web" / "upgrades.json").write_text(json.dumps(feed, indent=1) + "\n", encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def ran():
    """One simulated run of every round: (the evidence, what it said)."""
    said: list[str] = []
    w = ex.Simulated()
    try:
        programs = {n: {"id": IDS[n], "hash": HASH[n], "slot": SLOT + i, "build": ex.NEW[n], "proposal": ex.PROPOSALS[n], "is": "new"} for i, n in enumerate(ex.PROGRAMS)}
        ev = ex.run(w, ex.new_evidence(w, programs), say=said.append)
        first = json.loads(json.dumps(ev))
        again: list[str] = []
        ex.run(w, ev, say=again.append)           # a second run sends nothing
    finally:
        w.close()
    return first, ev, said, again


def test_every_round_runs_on_the_simulator_and_keeps_its_transactions_and_what_it_checked(ran):
    ev, _after, said, _again = ran
    assert ev["mode"] == "simulated" and json.loads(json.dumps(ev)) == ev
    done = {c for c, e in ev["exercises"].items() if e["status"] == "exercised"}
    assert done == {"fund_from_wallet", "top_up", "refund", "work_orders", "order_pay", "single_use_tokens", "verify_github", "order_quorum", "neutral_attest",
                    "order_challenge", "warranty_revert", "order_auto_accept", "tests_mode", "meter_batch", "meter_seller_claim"}
    for cap in done:
        e = ev["exercises"][cap]
        assert ex._SIG.fullmatch(e["signature"]) and e["asserted"] and e["program"] in ex.PROGRAMS and cap in ex.ROUNDS[e["round"]][2], cap
    assert not [line for line in said if "FAILED" in line], said
    sigs = [t["signature"] for st in ev["rounds"].values() for t in st.get("transactions", [])]
    assert len(sigs) == len(set(sigs)) == 23


def test_the_refusals_are_evidence_and_the_single_use_error_is_the_one_the_source_names(ran):
    ev = ran[0]
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    number = int(re.search(r"pub const E_REPLAY: u32 = (\d+);", lib)[1])
    assert ex.single_use() == (number, "a token works once") and number == 91
    order = ev["rounds"]["order"]
    # the fund token's second use, while the order's address is free: the single-use rule, and no second order
    assert order["replay"]["error"] == number and order["replay"]["means"] == "a token works once"
    # the first proof against a second funding of the same address: refused, nothing paid twice
    assert order["double"]["error"] == number and order["double"]["signature"] != order["replay"]["signature"]
    # a duplicate settlement: the relay answers with the first payment and sends nothing
    assert order["duplicate"] == {"answer": "already", "names": order["paid"]["signature"]}
    # the expired order went back whole, fee included
    assert order["refund"]["amount"] == order["fund2"]["amount"] + order["fund2"]["fee"]
    refusals = ev["exercises"]["single_use_tokens"]["refusals"]
    assert [r["error"] for r in refusals] == [number, number] and all(ex._SIG.fullmatch(r["signature"]) for r in refusals)
    # one judge out of two moved nothing; the second paid four fifths; the revert returned the holdback and its fee
    q = ev["rounds"]["quorum"]
    assert (q["two"]["paid"], q["two"]["held_back"]) == (4_000_000, 1_000_000) and q["revert"]["amount"] > q["two"]["held_back"]
    assert "one of two, nothing is paid" in q["transactions"][1]["what"]
    # the NaN claim: refused by the verifier with its not-JSON error, after a control that differs in that one value was verified
    s = ev["rounds"]["strict"]
    assert s["refused"]["error"] == 61 and len(s["transactions"]) == 2 and "refused" not in s["transactions"][0]
    assert ev["exercises"]["oidc_strict_json"]["status"] == "refused as it should be"       # a refusal alone moves no stage


def test_a_second_run_sends_nothing_and_what_has_no_round_says_why(ran):
    first, after, _said, again = ran
    assert {k: v for k, v in after.items() if k != "finished"} == {k: v for k, v in first.items() if k != "finished"}
    assert sum("done before" in line for line in again) >= 5 and not [line for line in again if line.startswith("  ok ")]
    assert first["exercises"]["passkey_funder"]["status"].startswith("needs run: the site's Buy page")
    assert first["exercises"]["gitlab_pay"]["status"].startswith("needs run: a pipeline on gitlab.com")
    assert first["exercises"]["fee_tiers"]["status"].startswith("no round: the second tier starts above 1,000.00")
    plan = ex.exercisable()
    assert set(c for _f, _p, caps in ex.ROUNDS.values() for c in caps) <= set(plan) and not set(plan) & ex.NOT_ON_CHAIN


def test_a_step_that_needs_a_workflow_run_is_written_down_and_picked_up_by_the_next_run():
    said: list[str] = []
    w = ex.Simulated()
    try:
        programs = {n: {"id": IDS[n], "hash": HASH[n], "slot": SLOT, "build": ex.NEW[n], "proposal": ex.PROPOSALS[n], "is": "new" if n != "knos_meter" else "old"}
                    for n in ex.PROGRAMS}
        real = w.find
        w.find = lambda kind, pick, forge, taken: None if kind == "revert" else real(kind, pick, forge, taken)       # the revert's run has not happened yet
        ev = ex.run(w, ex.new_evidence(w, programs), only="quorum", say=said.append)
        assert ev["exercises"]["order_quorum"]["status"] == "exercised" and ev["exercises"]["order_challenge"] == {"status": "needs run: attest.yml", "round": "quorum"}
        assert any(line.startswith("  NEEDS A RUN of attest.yml: ") and "-f kind=revert" in line for line in said)
        sent = len(ev["rounds"]["quorum"]["transactions"])
        w.find = real
        ex.run(w, ev, only="quorum", say=said.append)
        assert ev["exercises"]["order_challenge"]["status"] == ev["exercises"]["warranty_revert"]["status"] == "exercised"
        assert len(ev["rounds"]["quorum"]["transactions"]) == sent + 1          # the one step that was left, and no other again
        # a round whose program has not been upgraded is skipped, with the reason, and nothing of it is sent
        ex.run(w, ev, only="meter", say=said.append)
        assert ev["exercises"]["meter_batch"]["status"] == "skipped: knos_meter does not run its upgraded build at the public id"
        assert "transactions" not in ev["rounds"]["meter"]
    finally:
        w.close()


def test_status_says_which_build_each_public_id_runs_and_exits_0_3_or_1(tmp_path):
    root = tree(tmp_path)
    old = json.loads((root / "docs" / "provenance.json").read_text(encoding="utf-8"))["programs"]
    said: list[str] = []
    assert ex.status("rpc", said.append, cluster(ELF), root) == 0
    assert said[0] == (f"knos_oidc {IDS['knos_oidc']}: runs knos_oidc 2.1, the build of proposal 3; hash {HASH['knos_oidc']}; last deployed in slot {SLOT}")
    assert "knos_passkey 1.1, the build of proposal 6" in said[3] and f"slot {SLOT + 3}" in said[3] and "run the exercises" in said[4]
    # the hash is the page's: the program data without its header and its trailing zeros
    assert ex.read_programs(cluster(ELF), root)["knos_pay"]["hash"] == HASH["knos_pay"] == mc.elf_hash(ELF["knos_pay"])
    # an upgrade that has not executed: the build read before it, by the hash docs/provenance.json holds; nothing waits
    account = cluster(ELF)
    before = dict(ELF)

    def with_old(address):
        if address == str(mc.programdata_address(IDS["knos_meter"])):
            return ("loader", b"\x03" + bytes(44) + b"x")
        return account(address)
    rows = ex.read_programs(with_old, root)
    assert rows["knos_meter"]["is"] == "unknown" and ex.status_code(rows) == 1          # bytes nobody recorded: unexpected
    rows["knos_meter"].update(**{"is": "old"}, hash=old["knos_meter"]["on_chain_hash"])
    assert ex.status_code(rows) == 3
    seen = json.loads((root / "docs" / "provenance.json").read_text(encoding="utf-8"))
    seen["programs"]["knos_meter"]["on_chain_hash"] = gate.executable_hash(b"old meter").hex()
    (root / "docs" / "provenance.json").write_text(json.dumps(seen), encoding="utf-8")
    said.clear()
    assert ex.status("rpc", said.append, cluster({**before, "knos_meter": b"old meter"}), root) == 3
    assert "knos_meter 1.0: proposal 5 has not executed" in said[2] and "skip the exercises and ship the rest" in said[4]
    # a program that is not there, and a cluster that does not answer: 1
    assert ex.status("rpc", said.append, cluster({n: e for n, e in ELF.items() if n != "knos_pay"}), root) == 1

    def down(address):
        raise OSError("no route")
    assert ex.status("rpc", said.append, down, root) == 1 and "could not be read" in said[-1]


def test_record_writes_the_manifest_the_documents_and_the_demo_only_for_programs_whose_hash_matches(ran, tmp_path):
    ev = copy.deepcopy(ran[0])
    # simulated evidence is never written into the repository itself
    said: list[str] = []
    manifest = (ROOT / "docs" / "capabilities.json").read_bytes()
    assert ex.record(ev, ROOT, said.append) == 1 and said == ["refused: this evidence is from the simulator. Only a run at the public program ids is written into the repository."]
    assert (ROOT / "docs" / "capabilities.json").read_bytes() == manifest
    root = tree(tmp_path)
    ev["programs"] = ex.read_programs(cluster({**ELF, "knos_passkey": b"some other bytes"}), root)
    assert [r["is"] for r in ev["programs"].values()] == ["new", "new", "new", "unknown"]

    def feed(at: Path) -> None:        # what scripts/upgrade_feed.py would write once the multisig marks all four executed
        doc = json.loads((at / "web" / "upgrades.json").read_text(encoding="utf-8"))
        for e in doc["entries"]:
            if e["index"] in (3, 4, 5, 6):
                e.update(status="executed", squads_status="Executed")
        (at / "web" / "upgrades.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    said.clear()
    assert ex.record(ev, root, said.append, feed) == 1          # 1: the feed and the chain disagree about knos_passkey, and it says so
    assert any("the feed says proposal 6 executed, and knos_passkey did not run its build" in line for line in said), said
    data = json.loads((root / "docs" / "capabilities.json").read_text(encoding="utf-8"))
    assert {n: p["on_chain"] for n, p in data["programs"].items()} == {"knos_oidc": "2.1", "knos_pay": "2.1", "knos_meter": "1.1", "knos_passkey": "1.0", "upgrade_gate": "1.0"}
    by = {c["id"]: c for c in data["capabilities"]}
    moved = {c for c, e in ev["exercises"].items() if e["status"] == "exercised"}
    assert {c["id"] for c in data["capabilities"] if c["stage"] == "exercised"} == moved
    for cid in moved:
        got = by[cid]["evidence"]
        assert got["exercised"]["signature"] == ev["exercises"][cid]["signature"] and got["exercised"]["ids"] == "public" and got["exercised"]["asserted"], cid
        assert got["deployed"]["id"] == IDS[got["deployed"]["program"]] and "not on the public program ids" not in by[cid].get("note", ""), cid
        assert not by[cid].get("note", "").startswith(("Rehearsed on", "Runs at the public id")), cid
    assert by["work_orders"]["evidence"]["deployed"]["version"] == "2.1" and by["refund"]["evidence"]["deployed"]["version"] == "2.0"
    assert by["single_use_tokens"]["evidence"]["exercised"]["refusals"][0]["error"] == 91
    assert by["oidc_strict_json"]["stage"] == "tested" and by["passkey_funder"]["stage"] == "tested"
    sys.path.insert(0, str(ROOT / "scripts"))
    import capabilities as cap
    assert cap.problems(data, root) == [] and cap.render(root, check=True) == []
    # the feed: three proposals executed, the fourth as it was; the provenance record: the slot each build went live
    feed_now = {e["index"]: e["status"] for e in json.loads((root / "web" / "upgrades.json").read_text(encoding="utf-8"))["entries"]}
    assert [feed_now[i] for i in (3, 4, 5, 6)] == ["executed", "executed", "executed", "pending"]
    seen = json.loads((root / "docs" / "provenance.json").read_text(encoding="utf-8"))["programs"]
    assert [seen[n].get("live_slot") for n in ex.PROGRAMS] == [SLOT, SLOT + 1, SLOT + 2, None] and seen["knos_pay"]["on_chain_hash"] == HASH["knos_pay"]
    page = (root / "docs" / "PROVENANCE.md").read_text(encoding="utf-8")
    row = next(line for line in page.splitlines() if line.startswith("| `") and IDS["knos_pay"] in line)
    assert f"| 4 | {SLOT + 1} |" in row and ev["exercises"]["work_orders"]["signature"] in row and "(`order_pay`)" in row
    assert "not live yet | none: the public id does not run this build yet" in next(line for line in page.splitlines() if line.startswith("| `") and IDS["knos_passkey"] in line)
    # the document: one section with every transaction; the demo: the PUBLIC round, each step its own transaction
    text = (root / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8")
    section = text[text.index(ex.BEGIN):text.index(ex.END)]
    assert text.index(ex.BEGIN) < text.index("## The 0.3.14 rehearsal on devnet") and "refused, error 91: a token works once" in section
    assert all(t["signature"] in section for st in ev["rounds"].values() for t in st.get("transactions", []))
    demo = json.loads((root / "web" / "demo_data.json").read_text(encoding="utf-8"))
    order, meter_round = ev["rounds"]["order"], ev["rounds"]["meter"]
    assert demo["ids"] == "public" and demo["fund"] == {"comment": "/knos fund 5", "tx": order["fund1"]["signature"], "order": order["fund1"]["order"],
                                                        "amount": "5.00", "fee": "0.40"}
    assert demo["paid"]["tx"] == order["paid"]["signature"] and demo["paid"]["amount"] == "5.00" and demo["paid"]["seconds"] > 0
    assert demo["replay"] == {"tx": order["replay"]["signature"], "error": 91, "means": "a token works once", "single_use_error": 91, "single_use": "a token works once"}
    assert demo["count"] == {"buyer": 6, "seller": 7, "apart": 1, "buyer_tx": [meter_round["batch0"]["signature"], meter_round["batch1"]["signature"]],
                             "seller_tx": [meter_round["claim0"]["signature"], meter_round["claim1"]["signature"]]}
    # recording the same evidence again changes nothing
    files = ("docs/capabilities.json", "docs/CAPABILITIES.md", "web/demo_data.json", "docs/PROVENANCE.md", "docs/provenance.json", "README.md")
    before = {f: (root / f).read_bytes() for f in files}
    assert not [f for f, data in before.items() if b"\r" in data]     # written as the repository keeps them (.gitattributes eol=lf), on Windows too
    ex.record(ev, root, lambda line: None)
    assert {f: (root / f).read_bytes() for f in files} == before


def test_propose_oidc_proposes_knos_oidc_alone_and_only_a_build_the_gate_recorded(tmp_path, monkeypatch):
    import upgrade_feed
    root, keys, so = tree(tmp_path), tmp_path / "keys", tmp_path / "so"
    keys.mkdir()
    so.mkdir()
    strict = b"knos_oidc with strict json"
    for n in ex.PROGRAMS:
        (so / f"{n}.so").write_bytes(strict if n == "knos_oidc" else ELF[n])
    calls: list[tuple[list[str], dict]] = []

    def deploy(argv, env):
        calls.append((argv, env))
        (keys / "upgrade-schedule.json").write_text(json.dumps({"proposals": [{"program": "knos_oidc", "index": 7, "hash": "h7", "buffer": "Buf7",
                                                                               "executable_from": 1_791_500_000}]}), encoding="utf-8")
        return 0
    record = type("R", (), {"sha": "ab" * 20, "run_id": 37_300_000_001})()
    monkeypatch.setattr(upgrade_feed, "gate_record", lambda account, program, build: record if build == gate.executable_hash(strict).hex() else None)
    said: list[str] = []
    # before the four proposals have executed: refused, exit 3, nothing called
    meter_old = json.loads((root / "docs" / "provenance.json").read_text(encoding="utf-8"))
    meter_old["programs"]["knos_meter"]["on_chain_hash"] = gate.executable_hash(b"old meter").hex()
    (root / "docs" / "provenance.json").write_text(json.dumps(meter_old), encoding="utf-8")
    assert ex.propose_oidc("rpc", keys, so, said.append, cluster({**ELF, "knos_meter": b"old meter"}), deploy, root) == 3 and not calls
    assert "proposals 3 to 6 have not all executed" in said[-1]
    # another program's bytes differ from what is live: refused, nothing called
    (so / "knos_pay.so").write_bytes(b"a rebuild of knos_pay")
    assert ex.propose_oidc("rpc", keys, so, said.append, cluster(ELF), deploy, root) == 1 and not calls
    assert said[-1].startswith("refused: the build of knos_pay in ") and "this release changes knos_oidc alone" in said[-1]
    (so / "knos_pay.so").write_bytes(ELF["knos_pay"])
    # a build the gate has no record of
    (so / "knos_oidc.so").write_bytes(b"not a verified build")
    assert ex.propose_oidc("rpc", keys, so, said.append, cluster(ELF), deploy, root) == 1 and not calls and "holds no record of the build" in said[-1]
    (so / "knos_oidc.so").write_bytes(strict)
    assert ex.propose_oidc("rpc", keys, so, said.append, cluster(ELF), deploy, root) == 0
    (argv, env), = calls
    assert argv[0] == "bash" and argv[1].endswith("scripts/deploy_v2.sh") and argv[2:] == ["--propose"]
    assert (env["KNOS_CHANGES"], env["KNOS_SO_DIR"], env["KNOS_KEYS"], env["KNOS_RPC"]) == ("knos_oidc", str(so), str(keys), "rpc")
    assert said[-1] == "proposal 7 for knos_oidc (build h7, buffer Buf7): can be executed from 2026-10-08 22:53 UTC; scripts/schedule_upgrade.sh arranges it"
    named = json.loads((root / "docs" / "provenance.json").read_text(encoding="utf-8"))["next"]["knos_oidc"]
    assert named == {"version": "2.2", "build_hash": gate.executable_hash(strict).hex(), "source_commit": "ab" * 20, "gate_run": 37_300_000_001}
    # once that build is live, status knows it by the name docs/provenance.json gave it, and there is nothing left to propose
    assert ex.read_programs(cluster({**ELF, "knos_oidc": strict}), root)["knos_oidc"]["is"] == "next"
    assert ex.propose_oidc("rpc", keys, so, said.append, cluster({**ELF, "knos_oidc": strict}), deploy, root) == 1 and "there is nothing to propose" in said[-1]
