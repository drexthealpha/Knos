"""scripts/exercise_public.py: the rounds that move a capability from "rehearsed on staging" to "exercised at the public
program ids", run here on the local simulator with the test builds and fixture tokens, end to end: the run, what it
keeps, a step that waits for a workflow run and is picked up later, `record` into a copy of the repository (the
manifest, the documents, the demo's data, the provenance page), `status` and `propose` with a fake cluster, the rounds
0.3.18 adds, and the staging rehearsal of knos_pay's new build."""
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
ex.register_places()        # what the command does before anything else: the rounds of scripts/exercise_rounds/ are registered,
ex.load_rounds()            # and `gitlab` is then that folder's round (scripts/gitlab_round.py), not the built-in one

from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import gate  # noqa: E402

ELF = {n: bytes([i + 1]) * 64 + n.encode() for i, n in enumerate(ex.PROGRAMS)}      # stand-ins for the four builds
HASH = {n: gate.executable_hash(e).hex() for n, e in ELF.items()}
SLOT = 412_000_000
IDS = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
# The records as they stood before the round at the public ids (docs/capabilities.json, docs/provenance.json and
# web/upgrades.json of knos-rc 2f3418d4): what these tests start from. `record` has since written the round into the
# committed ones, and a round, a status or a proposal is tested on the state it is made for.
BEFORE = ROOT / "tests" / "fixtures" / "before_round"
BEFORE_FILES = ("docs/capabilities.json", "docs/provenance.json", "web/upgrades.json")


def run(*args, **kw):
    """ex.run against the manifest of before the round: what is below `exercised` there is what a round has to do."""
    return ex.run(*args, root=BEFORE, **kw)


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
    for f in BEFORE_FILES:
        shutil.copyfile(BEFORE / f, root / f)
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
        # "new" for a program whose test build is of the source that is live, "next" for one this tree changes
        programs = {n: {**ex.simulated_programs()[n], "hash": HASH[n], "slot": SLOT + i} for i, n in enumerate(ex.PROGRAMS)}
        ev = run(w, ex.new_evidence(w, programs), say=said.append)
        first = json.loads(json.dumps(ev))
        again: list[str] = []
        run(w, ev, say=again.append)           # a second run sends nothing
    finally:
        w.close()
    return first, ev, said, again


def test_every_round_runs_on_the_simulator_and_keeps_its_transactions_and_what_it_checked(ran):
    ev, _after, said, _again = ran
    assert ev["mode"] == "simulated" and json.loads(json.dumps(ev)) == ev
    done = {c for c, e in ev["exercises"].items() if e["status"] == "exercised"}
    assert done == {"fund_from_wallet", "top_up", "refund", "work_orders", "order_pay", "single_use_tokens", "verify_github", "order_quorum", "neutral_attest",
                    "order_challenge", "warranty_revert", "order_auto_accept", "tests_mode", "meter_batch", "meter_seller_claim",
                    "fee_tiers", "holdback_release", "outcome_not_code", "x402_knos_order"}
    for cap in done:
        e = ev["exercises"][cap]
        assert ex._SIG.fullmatch(e["signature"]) and e["asserted"] and e["program"] in ex.PROGRAMS and cap in ex.ROUNDS[e["round"]][2], cap
    assert not [line for line in said if "FAILED" in line], said
    sigs = [t["signature"] for st in ev["rounds"].values() for t in st.get("transactions", [])]
    assert len(sigs) == len(set(sigs)) == 23 + 2 + 3 + 3 + 2          # 0.3.17's rounds, then fees, holdback, issuer, x402


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
    assert first["exercises"]["passkey_funder"]["status"] == first["exercises"]["buyer_page"]["status"] == "needs run: the site's Buy page"
    # GitLab is a registered round since 0.3.20 (scripts/exercise_rounds/gitlab.py): the built-in rounds say nothing of it,
    # and what it does on the simulator and without credentials is held in tests/test_exercise_round_files.py and tests/test_gitlab_round.py
    assert "gitlab" not in ex.ROUNDS and "gitlab_pay" not in first["exercises"] and ex.EXT["gitlab"].caps == ("verify_gitlab", "gitlab_pay")
    assert first["exercises"]["verify_any_issuer"]["status"].startswith("cannot: no issuer other than GitHub and GitLab")
    assert first["exercises"]["supplier_appeal"]["status"] == "needs run: attest.yml" and first["exercises"]["supplier_preflight"]["status"] == "needs run: knos preflight"
    assert not [e for e in first["exercises"].values() if e["status"].startswith("failed")]
    plan = ex.exercisable(BEFORE)
    assert set(c for _f, _p, caps in ex.ROUNDS.values() for c in caps) <= set(plan) and not set(plan) & ex.NOT_ON_CHAIN


def test_a_step_that_needs_a_workflow_run_is_written_down_and_picked_up_by_the_next_run():
    said: list[str] = []
    w = ex.Simulated()
    try:
        programs = {n: {"id": IDS[n], "hash": HASH[n], "slot": SLOT, "build": ex.NEW[n], "proposal": ex.PROPOSALS[n], "is": "new" if n != "knos_meter" else "old"}
                    for n in ex.PROGRAMS}
        real = w.find
        w.find = lambda kind, pick, forge, taken: None if kind == "revert" else real(kind, pick, forge, taken)       # the revert's run has not happened yet
        ev = run(w, ex.new_evidence(w, programs), only="quorum", say=said.append)
        assert ev["exercises"]["order_quorum"]["status"] == "exercised" and ev["exercises"]["order_challenge"] == {"status": "needs run: attest.yml", "round": "quorum"}
        assert any(line.startswith("  NEEDS A RUN of attest.yml: ") and "-f kind=revert" in line for line in said)
        sent = len(ev["rounds"]["quorum"]["transactions"])
        w.find = real
        run(w, ev, only="quorum", say=said.append)
        assert ev["exercises"]["order_challenge"]["status"] == ev["exercises"]["warranty_revert"]["status"] == "exercised"
        assert len(ev["rounds"]["quorum"]["transactions"]) == sent + 1          # the one step that was left, and no other again
        # a round whose program has not been upgraded is skipped, with the reason, and nothing of it is sent
        run(w, ev, only="meter", say=said.append)
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
    assert by["oidc_strict_json"]["stage"] == "tested" and by["passkey_funder"]["stage"] == "tested" and by["supplier_appeal"]["stage"] == "tested"
    assert by["outcome_not_code"]["evidence"]["exercised"]["round"] == "issuer" and by["outcome_not_code"]["evidence"]["deployed"]["program"] == "knos_oidc"
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
                                                        "amount": "5.00", "fee": "0.05" if "knos_pay" in ex.changed_fixtures() else "0.40"}
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


def test_status_as_json_is_one_object_with_the_same_exit_code(tmp_path):
    root = tree(tmp_path)
    said: list[str] = []
    assert ex.status("rpc", said.append, cluster(ELF), root, as_json=True) == 0 and len(said) == 1
    doc = json.loads(said[0])
    assert doc["exit"] == 0 and doc["says"].startswith("all four run the upgraded builds") and list(doc["programs"]) == list(ex.PROGRAMS)
    assert doc["programs"]["knos_pay"] == {"id": IDS["knos_pay"], "hash": HASH["knos_pay"], "slot": SLOT + 1, "build": "2.1", "proposal": 4, "is": "new"}
    said.clear()
    assert ex.status("rpc", said.append, cluster({n: e for n, e in ELF.items() if n != "knos_pay"}), root, as_json=True) == 1 and json.loads(said[0])["exit"] == 1

    def down(address):
        raise OSError("no route")
    said.clear()
    assert ex.status("rpc", said.append, down, root, as_json=True) == 1 and json.loads(said[0]) == {"exit": 1, "says": "rpc could not be read (OSError: no route)", "programs": {}}


def test_the_fee_asserted_is_the_live_builds_rule_and_not_the_trees_client(ran):
    """The order above 1,000.00: the fee is read from the order's account, and held to the rule written out for the
    build the public id runs. The rule is not taken from knos.settle.v2.pay, which follows the tree's program."""
    ev = ran[0]
    fees = ev["rounds"]["fees"]
    changed = "knos_pay" in ex.changed_fixtures()
    assert ev["programs"]["knos_pay"]["is"] == ("next" if changed else "new")
    assert fees["fund"]["amount"] == 1_500_000_000 and fees["fund"]["fee"] == (4_500_000 if changed else 30_000_000)
    assert (ex.fee_tiers_21(1_500_000_000), ex.fee_tiers_21(5_000_000), ex.fee_tiers_21(100_000_000)) == (30_000_000, 400_000, 2_500_000)
    assert [ex.fee_flat(a * 1_000_000) for a in (5, 100, 1_000, 5_000, 100_000)] == [50_000, 300_000, 3_000_000, 15_000_000, 300_000_000]
    said = ev["exercises"]["fee_tiers"]["asserted"]
    assert "read from the order's account on chain" in said[0] and ("0.30%" if changed else "knos_pay 2.1: 2.5% of the first 1,000.00") in said[1]
    assert [t["what"] for t in fees["transactions"]][1] == "past its deadline the order goes back to the wallet, fee included"
    src = (ROOT / "scripts" / "exercise_public.py").read_text(encoding="utf-8")
    body = src[src.index("def round_fees"):src.index("def round_holdback")]
    assert "pay.order_fee" not in body and "pay.fee_of" not in body
    # a wallet that cannot carry such an order: said as what cannot be done, and nothing is sent
    w = ex.Simulated()
    try:
        w.tokens = lambda account: 0
        got = run(w, ex.new_evidence(w, ex.simulated_programs()), only="fees", say=lambda line: None)
        assert got["exercises"]["fee_tiers"]["status"].startswith("cannot: the funding wallet ") and "transactions" not in got["rounds"]["fees"]
    finally:
        w.close()


def test_a_holdback_needs_a_day_and_resume_finishes_it():
    said: list[str] = []
    w = ex.Simulated()
    try:
        warp = w.wait_until

        def a_cluster_waits(t, what):          # devnet's clock is not ours to move: what Public.wait_until does past two and a half minutes
            raise ex.Wait(t, what)
        w.wait_until = a_cluster_waits
        ev = run(w, ex.new_evidence(w, ex.simulated_programs()), only="holdback", say=said.append)
        st = ev["rounds"]["holdback"]
        until = st["paid"]["until"]
        assert ev["exercises"]["holdback_release"] == {"status": f"needs time: {ex.day(until)}: the end of the warranty, after which the holdback is released to the payee",
                                                       "round": "holdback"}
        assert st["needs_time"] == until and until - w.now() > 86_000 and (st["paid"]["paid"], st["paid"]["held_back"]) == (4_000_000, 1_000_000)
        assert len(st["transactions"]) == 2 and any("`--resume` after it finishes this round" in line for line in said)
        run(w, ev, only="holdback", say=said.append)                 # too early still: nothing more is sent
        assert len(st["transactions"]) == 2
        w.wait_until = warp
        run(w, ev, only="holdback", say=said.append)                 # a day later, `--resume`
        assert ev["exercises"]["holdback_release"]["status"] == "exercised" and "needs_time" not in st and len(st["transactions"]) == 3
        assert ev["exercises"]["holdback_release"]["signature"] == st["release"]["signature"] and "1.00 reached the payee's account" in ev["exercises"]["holdback_release"]["asserted"][1]
    finally:
        w.close()


def test_tokens_the_repositorys_own_run_carried_first_are_read_from_the_chain():
    """At the public ids the repository's own workflow carries every token it posts before a round reads it: a fund
    token's order may be paid already, a quorum's first judge recorded, a holdback's proof paid. The rounds then hold
    what the chain shows (the transaction that set the token's marker, the holdback's record) and send nothing twice."""
    said: list[str] = []
    w = ex.Simulated()
    try:
        real = w.find

        def carried_first(kind, pick, forge, taken):
            tok = real(kind, pick, forge, taken)
            if tok is not None and kind in ("fund", "pay"):
                assert w.submit(tok).get("ok"), "the repository's run carried its token"
            return tok
        w.find = carried_first
        ev = run(w, ex.new_evidence(w, ex.simulated_programs()), only="quorum", say=said.append)
        run(w, ev, only="holdback", say=said.append)
        assert not [line for line in said if "FAILED" in line], said
        q, h = ev["rounds"]["quorum"], ev["rounds"]["holdback"]
        assert ev["exercises"]["order_quorum"]["status"] == ev["exercises"]["warranty_revert"]["status"] == "exercised"
        assert q["fund1"]["already"] and (q["two"]["paid"], q["two"]["held_back"]) == (4_000_000, 1_000_000)
        assert w.landed(q["one"]["signature"])["ok"]          # the first judge's marker: the transaction the run sent
        assert ev["exercises"]["holdback_release"]["status"] == "exercised" and (h["paid"]["paid"], h["paid"]["held_back"]) == (4_000_000, 1_000_000)

        # an order funded and paid by the run before the round read its fund token: the funding is the transaction
        # that set the token's marker, with the amount and the fee knos_pay logged in it
        w.find = real
        o, n = w.o, w.issue()
        fund = w.forge(ex.pay.order_fund_audience(n, ex.AMOUNT, ex.pay.MERGE, o.TH, w.c.bal, 14 * 86_400), "fund.yml", o.TERMS,
                       event_name="issue_comment", actor_id=o.MAINT, repository_id=o.REPO, repository_owner_id=o.OWNER)
        first = w.submit(fund)
        order = ex.Pubkey.from_string(first["order"])
        wallet = ex.Keypair.from_seed(bytes([47]) * 32).pubkey()
        proof = w.forge(ex.pay.order_pay_audience(order, o.HEAD, o.TH, ex.pay.MERGE, 7, [(o.user(), 10_000, wallet)]), repository_id=o.REPO)
        assert w.submit(proof).get("ok") and w.account(order) is None
        assert not w.submit(fund).get("ok")          # what the relay answers a round now: the token was used, and its order is gone
        book, st = ex.Book(ev, w, said.append), {"round": "order"}
        _r, got = ex._fund(book, st, "fund1", fund, "the fund token")
        assert got == order and st["fund1"] == {"order": str(order), "amount": ex.AMOUNT, "fee": first["fee"], "signature": first["sigs"][-1], "already": True}
        assert w.consumed(proof, f"knos3:funded order={order} ") is None        # a line the token's transactions never logged finds nothing

        # one GitHub account: the only neutral run the release can start is the funder's, which a quorum does not count
        ev2 = ex.new_evidence(w, ex.simulated_programs())
        ev2["rounds"]["quorum"] = {"round": "quorum", "issue": w.issue(), "payee": o.user(), "wallet": str(wallet), "judge": o.MAINT}
        run(w, ev2, only="quorum", say=said.append)
        q2 = ev2["rounds"]["quorum"]
        assert ev2["exercises"]["order_quorum"]["status"].startswith("cannot: needs a second GitHub account") and q2["refused_neutral"]["actor"] == o.MAINT
        assert "two" not in q2 and ex.pay.read_order(w.account(ex.Pubkey.from_string(q2["fund1"]["order"]))).paid == 0
    finally:
        w.close()


def test_a_step_done_outside_is_held_to_the_chain_and_what_it_cannot_show_is_not_taken(ran, tmp_path):
    ev = ran[0]
    x = ev["rounds"]["x402"]
    assert x["fund"]["signature"] != x["paid"]["signature"] and ev["exercises"]["x402_knos_order"]["signature"] == x["paid"]["signature"]
    k = ev["rounds"]["issuer"]["verified"]
    assert k["issuer"] == "https://kind.knos-outcome.invalid" and len(k["transactions"]) == 6 and "under a private key this wallet registered" in ev["exercises"]["outcome_not_code"]["asserted"][0]
    said: list[str] = []
    w = ex.Simulated()
    try:
        new = lambda: ex.new_evidence(w, ex.simulated_programs())  # noqa: E731
        order = run(w, new(), only="expiry", say=said.append)["rounds"]["expiry"]
        real = order["order"]["signature"]              # a transaction of knos_pay that is on this chain
        # the passkey: nothing noted is a guided step, printed exactly; a transaction that never touched knos_passkey is refused
        got = run(w, new(), only="passkey", say=said.append)
        assert got["exercises"]["passkey_funder"]["status"] == "needs run: the site's Buy page"
        guide = next(line for line in said if line.startswith("  NEEDS A RUN of the site's Buy page: "))
        for press in ("https://drexthealpha.github.io/Knos/#buy", "`Create a passkey wallet`", "`Sign the order with the passkey`", "`Read the order from devnet`",
                      "note passkey --keys <keys> fund=<that transaction>"):
            assert press in guide
        buttons = (ROOT / "web" / "buyer.js").read_text(encoding="utf-8")
        assert all(f">{b}</button>" in buttons for b in ("Create a passkey wallet", "Check the balance", "Sign the order with the passkey", "Copy the comment", "Read the order from devnet"))
        w.fake["passkey"] = {"fund": real}
        got = run(w, new(), only="passkey", say=said.append)
        assert got["exercises"]["passkey_funder"]["status"] == f"failed: the transaction {real} does not name knos_passkey at its pinned id {IDS['knos_passkey']}"
        w.fake["passkey"] = {"fund": "1" * 87}
        assert run(w, new(), only="passkey", say=said.append)["exercises"]["buyer_page"]["status"] == f"failed: the cluster has no transaction {'1' * 87}"
        seen = w.landed
        w.landed = lambda sig: {**seen(sig), "accounts": [*seen(sig)["accounts"], IDS["knos_passkey"]]}        # as if the page's transaction had been one of knos_passkey
        w.fake["passkey"] = {"fund": real}
        got = run(w, new(), only="passkey", say=said.append)
        assert {got["exercises"][c]["signature"] for c in ("passkey_funder", "passkey_fund_relay", "buyer_page")} == {real}
        assert len(got["exercises"]["passkey_funder"]["asserted"]) == 1
        # how the passkey was had is written beside it when the note says (devnet's round used a virtual authenticator)
        w.fake["passkey"] = {"fund": real, "how": "the passkey was a Chromium virtual authenticator"}
        got = run(w, new(), only="passkey", say=said.append)
        assert got["exercises"]["buyer_page"]["asserted"][-1] == "the passkey was a Chromium virtual authenticator"
        w.landed = seen
        # an appeal: its comment must be on the pull request and answered; upheld moves no stage, overturned needs its payment
        pull = "drexthealpha/knos-playground#7"
        w.fake["appeal"] = {"pull": pull, "fund": real, "answer": "upheld"}
        assert run(w, new(), only="appeal", say=said.append)["exercises"]["supplier_appeal"]["status"] == f"failed: {pull} has no `/knos appeal <reason>` comment"
        w.fake["comments"] = {pull: ["Rejected: the change touches a protected path.", "/knos appeal the path is listed as allowed"]}
        assert run(w, new(), only="appeal", say=said.append)["exercises"]["supplier_appeal"]["status"] == "needs run: attest.yml"
        w.fake["comments"][pull].append("The neutral judge ran the checks again: the rejection stands.")
        got = run(w, new(), only="appeal", say=said.append)
        assert got["exercises"]["supplier_appeal"]["status"] == "ran: the neutral judge upheld the refusal" and "stage does not move" in got["exercises"]["supplier_appeal"]["note"]
        assert [t["signature"] for t in got["rounds"]["appeal"]["transactions"]] == [real]
        w.fake["appeal"] = {"pull": pull, "fund": real, "answer": "overturned"}
        assert run(w, new(), only="appeal", say=said.append)["exercises"]["supplier_appeal"]["status"].startswith("failed: an overturned refusal is paid")
        w.fake["appeal"]["paid"] = order["top_up"]["signature"]
        got = run(w, new(), only="appeal", say=said.append)
        assert got["exercises"]["supplier_appeal"]["status"] == "exercised" and got["exercises"]["supplier_appeal"]["signature"] == order["top_up"]["signature"]
        # a preflight: the memory engine must be on and must recall a refusal under the same terms
        w.fake["preflight"] = {"issue": "drexthealpha/knos-playground#3", "tree": str(tmp_path)}
        w.fake["report"] = {"terms_hash": "ab" * 32, "memory": {"on": False, "said": "Memory is off: the memory engine (sibyl-memory-client) is not installed."}}
        assert run(w, new(), only="preflight", say=said.append)["exercises"]["supplier_preflight"]["status"].startswith("failed: the memory engine was off")
        w.fake["report"]["memory"] = {"on": True, "warnings": []}
        assert "recalled no earlier refusal under these terms" in run(w, new(), only="preflight", say=said.append)["exercises"]["supplier_preflight"]["status"]
        w.fake["report"]["memory"]["warnings"] = [{"code": "path.protected", "path": ".github/workflows/ci.yml", "count": 1, "yours": True,
                                                    "said": "1 earlier submission was refused for touching .github/workflows/ci.yml: your change touches it too."}]
        got = run(w, new(), only="preflight", say=said.append)
        assert got["exercises"]["supplier_preflight"]["status"] == "ran: a remembered refusal was recalled"
        assert got["exercises"]["supplier_preflight"]["asserted"] == ["terms abababababab: 1 earlier submission was refused for touching .github/workflows/ci.yml: your change touches it too."]
        # a token of the cluster that the verifier's rule refuses is never sent: a new run is asked for
        good = w.outcome()
        w.fake["outcome"] = {**good, "audience": "knos:something-else"}
        got = run(w, new(), only="issuer", say=said.append)
        assert got["exercises"]["outcome_not_code"]["status"] == "needs run: outcome-k8s.yml" and "transactions" not in got["rounds"]["issuer"]
    finally:
        w.close()
    # `note` writes what a person saw where the round reads it
    keys = tmp_path / "keys"
    keys.mkdir()
    lines: list[str] = []
    assert ex.main(["note", "x402", "--keys", str(keys), "fund=" + "2" * 87, "order=Order1"], lines.append) == 0
    assert ex.main(["note", "x402", "--keys", str(keys), "paid=" + "3" * 87], lines.append) == 0
    assert json.loads((keys / "outside.json").read_text(encoding="utf-8")) == {"x402": {"fund": "2" * 87, "order": "Order1", "paid": "3" * 87}}
    assert "`run --resume --only x402` holds it to the chain" in lines[-1]


def test_propose_proposes_exactly_knos_oidc_and_knos_pay_as_one_set_and_refuses_any_other_plan(tmp_path, monkeypatch):
    import upgrade_feed
    root, keys, so = tree(tmp_path), tmp_path / "keys", tmp_path / "so"
    keys.mkdir()
    so.mkdir()
    strict, fee = b"knos_oidc with strict json and es256", b"knos_pay with one fee and the quorum fixes" + bytes(100)
    new = {"knos_oidc": strict, "knos_pay": fee}

    def builds(**other: bytes) -> None:
        for n in ex.PROGRAMS:
            (so / f"{n}.so").write_bytes(other.get(n, new.get(n, ELF[n])))
    builds()
    calls: list[tuple[list[str], dict]] = []

    def deploy(argv, env):
        calls.append((argv, env))
        (keys / "upgrade-schedule.json").write_text(json.dumps({"proposals": [
            {"program": "knos_oidc", "index": 7, "hash": "h7", "buffer": "Buf7", "executable_from": 1_791_500_000},
            {"program": "knos_pay", "index": 8, "hash": "h8", "buffer": "Buf8", "executable_from": 1_791_500_060}]}), encoding="utf-8")
        return 0
    vouched = {gate.executable_hash(e).hex(): type("R", (), {"sha": "ab" * 20, "run_id": 37_600_000_001 + i})() for i, e in enumerate(new.values())}
    monkeypatch.setattr(upgrade_feed, "gate_record", lambda account, program, build: vouched.get(build))
    assert ex.RELEASE_CHANGES == ("knos_oidc", "knos_pay")
    said: list[str] = []
    # 0.3.19 proposes nothing: its tree changes no program and both builds are proposals 7 and 8 already. Refused before
    # anything is read (the cluster here would raise), under either name
    def unread(address):
        raise AssertionError("propose read the cluster")
    assert ex.RELEASE_PROPOSES == () and ex.propose("rpc", keys, so, said.append, unread, deploy, root) == 1 and not calls
    assert said[-1] == ("refused: this release proposes nothing. Its tree changes no program, and knos_oidc 2.2 is proposal 7 and knos_pay 2.2 is proposal 8 "
                        "already: `status --want 2.2` says whether they executed. Nothing was read, written or proposed.")
    assert ex.propose_oidc("rpc", keys, so, said.append, unread, deploy, root) == 1 and not calls and "provenance" not in said[-1]
    assert ex.main(["propose", "--rpc", "rpc", "--keys", str(keys), "--so-dir", str(so)], said.append) == 1 and said[-1].startswith("refused: this release proposes nothing")
    said.clear()

    # the mechanism itself, as 0.3.18 ran it, with that release's set
    class ex18:
        @staticmethod
        def propose(*args):
            return ex.propose(*args, changes=ex.RELEASE_CHANGES)
    # before the four proposals have executed: refused, exit 3, nothing called
    seen = json.loads((root / "docs" / "provenance.json").read_text(encoding="utf-8"))
    seen["programs"]["knos_meter"]["on_chain_hash"] = gate.executable_hash(b"old meter").hex()
    (root / "docs" / "provenance.json").write_text(json.dumps(seen), encoding="utf-8")
    assert ex18.propose("rpc", keys, so, said.append, cluster({**ELF, "knos_meter": b"old meter"}), deploy, root) == 3 and not calls
    assert "proposals 3 to 6 have not all executed" in said[-1]
    # a third program's bytes differ from what is live: refused, nothing called
    builds(knos_meter=b"a rebuild of knos_meter")
    assert ex18.propose("rpc", keys, so, said.append, cluster(ELF), deploy, root) == 1 and not calls
    assert said[-1].startswith("refused: the build of knos_meter in ") and "this release changes knos_oidc, knos_pay and no other" in said[-1]
    assert said[-1].endswith("The plan would be [knos_oidc, knos_pay, knos_meter]; it must be [knos_oidc, knos_pay]. Nothing was proposed.")
    # one of the two is still the build that is live: the set is not split
    builds(knos_pay=ELF["knos_pay"])
    assert ex18.propose("rpc", keys, so, said.append, cluster(ELF), deploy, root) == 1 and not calls
    assert "the build of knos_pay in " in said[-1] and "is the one already live, and this release proposes knos_oidc, knos_pay as one set" in said[-1]
    assert "The plan would be [knos_oidc]; it must be [knos_oidc, knos_pay]." in said[-1]
    # a build the gate has no record of
    builds(knos_pay=b"not a verified build")
    assert ex18.propose("rpc", keys, so, said.append, cluster(ELF), deploy, root) == 1 and not calls and "holds no record of the build" in said[-1] and "of knos_pay" in said[-1]
    builds()
    said.clear()
    assert ex18.propose("rpc", keys, so, said.append, cluster(ELF), deploy, root) == 0
    (argv, env), = calls
    assert argv[0] == "bash" and argv[1].endswith("scripts/deploy_v2.sh") and argv[2:] == ["--propose"]
    assert (env["KNOS_CHANGES"], env["KNOS_SO_DIR"], env["KNOS_KEYS"], env["KNOS_RPC"]) == ("knos_oidc knos_pay", str(so), str(keys), "rpc")
    assert said[0] == "proposals 3 to 6 executed: knos_oidc runs 2.1, knos_pay runs 2.1, knos_meter runs 1.1, knos_passkey runs 1.1"
    # room: the bytes of each build against what its data account holds (the fake cluster leaves 40 bytes after a build)
    assert said[1] == f"knos_oidc: this build is {len(strict):,} bytes; its data account has room for {len(ELF['knos_oidc']) + 40:,} bytes: it fits"
    assert said[2] == (f"knos_pay: this build is {len(fee):,} bytes; its data account has room for {len(ELF['knos_pay']) + 40:,} bytes: "
                       f"{len(fee) - len(ELF['knos_pay']) - 40:,} bytes short, so deploy_v2.sh extends the account first (no code changes; the fee payer pays the rent)")
    assert said[3].startswith("the plan: propose [knos_oidc, knos_pay] as one set (") and said[3].endswith(f"knos_meter, knos_passkey run the builds of {so} already")
    assert said[4:6] == ["proposal 7 for knos_oidc (build h7, buffer Buf7): can be executed from 2026-10-08 22:53 UTC",
                         "proposal 8 for knos_pay (build h8, buffer Buf8): can be executed from 2026-10-08 22:54 UTC"]
    assert said[6].startswith("next: bash scripts/schedule_upgrade.sh arranges ONE run that executes proposal 7 and proposal 8") and "`knos status` shows them pending" in said[6]
    named = json.loads((root / "docs" / "provenance.json").read_text(encoding="utf-8"))["next"]
    assert named == {"knos_oidc": {"version": "2.2", "build_hash": gate.executable_hash(strict).hex(), "source_commit": "ab" * 20, "gate_run": 37_600_000_001},
                     "knos_pay": {"version": "2.2", "build_hash": gate.executable_hash(fee).hex(), "source_commit": "ab" * 20, "gate_run": 37_600_000_002}}
    # the provenance page gains the row of each new build, from that record
    import provenance
    page = provenance.render(provenance.load(root))
    rows = [line for line in page.splitlines() if line.startswith("| `" + "ab" * 20)]
    assert len(rows) == 2 and f"`{gate.executable_hash(fee).hex()}` | `{IDS['knos_pay']}` | not proposed yet | not live yet |" in rows[1] and "knos_pay 2.2" in rows[1]
    # once both builds are live, status knows them by the name docs/provenance.json gave them, and there is nothing left to propose
    live = cluster({**ELF, **new})
    assert [ex.read_programs(live, root)[n]["is"] for n in ex.PROGRAMS] == ["next", "next", "new", "new"] and ex.status_code(ex.read_programs(live, root)) == 0
    assert ex18.propose("rpc", keys, so, said.append, live, deploy, root) == 1 and "there is nothing to propose" in said[-1]
    # and scripts/schedule_upgrade.sh executes every proposal of the schedule, in the order of their indexes
    sh = (ROOT / "scripts" / "schedule_upgrade.sh").read_text(encoding="utf-8")
    assert "for each proposal, in the order of their indexes" in sh


def test_the_rehearsal_of_knos_pays_new_build_is_one_command_and_fails_on_a_build_without_the_fixes():
    """`rehearse --rc --simulate`: the chain starts on the test build of the LIVE source, an order is funded there,
    knos_pay is replaced in place by this tree's test build, and the steps run. What must come out depends on which
    build this tree holds, and is derived: while tests/fixtures/knos_pay_v2_test.so is still the live build, the fee
    and both quorum steps FAIL (that is the rehearsal doing its work); with the new build every step is ok."""
    said: list[str] = []
    ev, code = ex.rehearse_simulated(said.append)
    results = {name: ev["rounds"][name]["result"] for name in ex.RC_STEPS}
    new_build = "knos_pay" in ex.changed_fixtures()
    assert (ev["new_build"] != ev["old_build"]) == new_build and said[0].startswith("staging (simulated): knos_pay runs the live source's test build")
    # whatever the build: an order funded under the live build is read as it was written and paid by the build that replaced it
    old = ev["rounds"]["old_layout_fund"]["fund"]
    assert (old["amount"], old["fee"]) == (5_000_000, 400_000) and ev["rounds"]["old_layout_pay"]["paid"] == {
        "signature": ev["rounds"]["old_layout_pay"]["transactions"][0]["signature"], "amount": 5_000_000, "fee_kept": 400_000}
    assert results["old_layout_fund"] == results["old_layout_pay"] == results["two_owners"] == results["close"] == "ok"
    two = ev["rounds"]["two_owners"]
    assert two["one"]["actor"] != two["paid"]["actor"] and two["one"]["owner"] != two["paid"]["owner"]
    if new_build:
        assert code == 0 and set(results.values()) == {"ok"}, results
        fees = ev["rounds"]["fees"]
        assert (fees["fee100"]["fee"], fees["fee5"]["fee"]) == (300_000, 50_000)
        for step in ("one_owner", "same_second"):
            assert ev["rounds"][step]["answer"]["signature"] and "no money moved" in " ".join(t["what"] + str(t.get("means", "")) for t in ev["rounds"][step]["transactions"]) or \
                ev["rounds"][step]["answer"]["error"] is not None
        assert said[-1] == "the rehearsal passed: every step is ok, or cannot be done from here and says why"
    else:
        assert code == 1 and said[-1] == "the rehearsal FAILED: the build is not proposed until every step above is ok or cannot"
        assert results["fees"] == "failed: this build charged 2.50 on 100.00; the new rule (0.30%, at least 0.05) gives 0.30"
        assert results["one_owner"].startswith("failed: ONE account's two runs paid a quorum of two")
        assert results["same_second"].startswith("failed: ONE judge's token paid the order funded again")
    assert ev["rounds"]["same_second"]["second"]["not_before"] > 0            # the two fundings were in one second of the chain's clock
    # nothing of the rehearsal stays: every order still open went back
    assert all(ex._SIG.fullmatch(sig) for sig in ev["rounds"]["close"]["refunds"].values())


def test_the_rehearsal_on_devnet_is_five_commands_in_order_and_what_cannot_be_done_there_is_said(tmp_path):
    keys, live, so = tmp_path / "keys", tmp_path / "live", tmp_path / "so"
    keys.mkdir()
    calls: list[tuple[list[str], dict]] = []

    def call(argv, env):
        calls.append((argv, env))
        if "--phase" in argv:           # what the phase's own process leaves: here, every step final
            doc = json.loads((keys / "rehearse_rc.json").read_text(encoding="utf-8"))
            for name, (_fn, when) in ex.RC_STEPS.items():
                if when == argv[argv.index("--phase") + 1]:
                    doc["rounds"][name] = {"result": "cannot: needs a second repository owner" if name == "two_owners" else "ok"}
            (keys / "rehearse_rc.json").write_text(json.dumps(doc), encoding="utf-8")
        return 0
    said: list[str] = []
    assert ex.rehearse_public("rpc", keys, live, so, False, said.append, call) == 0
    shape = [("--rc" if a[-1] == "--rc" else "--rc-close" if a[-1] == "--rc-close" else "phase " + a[-1], e.get("KNOS_RC_SO_DIR"), e.get("KNOS_PROGRAM_IDS")) for a, e in calls]
    ids = str(keys / "rc" / "program_ids.json")
    assert shape == [("--rc", str(live), None), ("phase before", None, ids), ("--rc", str(so), None), ("phase after", None, ids), ("--rc-close", None, None)]
    assert all(a[0] == "bash" and a[1].endswith("scripts/deploy_v2.sh") for a, _e in calls if "--phase" not in a)
    # a step that waits for a workflow run keeps staging open, and --resume does not deploy again
    calls.clear()
    doc = json.loads((keys / "rehearse_rc.json").read_text(encoding="utf-8"))
    doc["rounds"]["old_layout_pay"] = {"result": "needs run: prove.yml and attest.yml"}
    (keys / "rehearse_rc.json").write_text(json.dumps(doc), encoding="utf-8")
    assert ex.rehearse_public("rpc", keys, live, so, True, said.append, lambda argv, env: calls.append((argv, env)) or 0) == 0
    assert [a[-1] for a, _e in calls] == ["after"] and said[-1].startswith("staging stays open for old_layout_pay: `rehearse --rc --resume` after those runs")
    # on devnet: the same second cannot be arranged, and a second owner is never invented
    src = (ROOT / "scripts" / "exercise_public.py").read_text(encoding="utf-8")
    assert "four transactions do not land in one second of devnet's clock at will" in src and "Nothing was sent in a second owner's name" in src


# ---- 0.3.19: after proposals 7 and 8 -----------------------------------------------------------------------------------
NEXT = {"knos_oidc": b"knos_oidc 2.2: strict json and es256", "knos_pay": b"knos_pay 2.2: one rate, owners, grace" + bytes(64)}
NEXT_HASH = {n: gate.executable_hash(e).hex() for n, e in NEXT.items()}


def test_status_want_2_2_exits_0_only_when_proposals_7_and_8_executed_and_json_names_each_live_build_by_hash(tmp_path, monkeypatch):
    root = tree(tmp_path)
    asked = {n: {"proposal": i, "version": "2.2", "status": "Approved", "executable_from": 1_791_534_000 + i} for n, i in ex.NEXT_PROPOSALS.items()}
    monkeypatch.setattr(ex, "next_proposals", lambda account, root=None: copy.deepcopy(asked))
    said: list[str] = []
    # 2.1 everywhere, 7 and 8 approved and waiting: plain status is 0 (the 0.3.18 rounds can run), --want 2.2 is 3, and nothing waits
    assert ex.status("rpc", said.append, cluster(ELF), root) == 0
    said.clear()
    assert ex.status("rpc", said.append, cluster(ELF), root, want="2.2") == 3
    assert said[-1] == ("proposal 7 (knos_oidc 2.2) has not executed: the multisig says Approved, executable from 2026-10-09 08:20 UTC; "
                        "proposal 8 (knos_pay 2.2) has not executed: the multisig says Approved, executable from 2026-10-09 08:20 UTC. "
                        "Nothing waits: ship without the after rounds; `run --phase after` runs them later (exit 3)")
    # one of the two executed: still 3, and only the other is named
    monkeypatch.setattr(ex, "NEXT_BUILD", {n: h[:8] for n, h in NEXT_HASH.items()})
    asked["knos_oidc"] = {"proposal": 7, "version": "2.2", "status": "Executed"}
    said.clear()
    half = cluster({**ELF, "knos_oidc": NEXT["knos_oidc"]})
    assert ex.status("rpc", said.append, half, root, want="2.2") == 3 and said[-1].startswith("proposal 8 (knos_pay 2.2) has not executed")
    assert "runs knos_oidc 2.2, the later build of proposal 7" in said[0] and "runs knos_pay 2.1, the build of proposal 4" in said[1]
    # both executed, and no file of the tree names the builds yet: the multisig's word and how each hash begins
    asked["knos_pay"] = {"proposal": 8, "version": "2.2", "status": "Executed"}
    both = cluster({**ELF, **NEXT})
    said.clear()
    assert ex.status("rpc", said.append, both, root, want="2.2", as_json=True) == 0
    doc = json.loads(said[0])
    assert doc["exit"] == 0 and doc["want"] == "2.2" and doc["says"] == ("knos_oidc 2.2 (proposal 7) and knos_pay 2.2 (proposal 8) are live at the public ids: "
                                                                         "run the after rounds (`run --phase after`)")
    assert doc["live"] == {"knos_oidc": {"version": "2.2", "hash": NEXT_HASH["knos_oidc"], "proposal": 7}, "knos_pay": {"version": "2.2", "hash": NEXT_HASH["knos_pay"], "proposal": 8},
                           "knos_meter": {"version": "1.1", "hash": HASH["knos_meter"], "proposal": 5}, "knos_passkey": {"version": "1.1", "hash": HASH["knos_passkey"], "proposal": 6}}
    assert doc["proposals"]["knos_pay"] == {"proposal": 8, "version": "2.2", "status": "Executed"} and doc["programs"]["knos_pay"]["is"] == "next"
    # a build that begins otherwise is nobody's, whatever the multisig says: 1
    monkeypatch.setattr(ex, "NEXT_BUILD", {"knos_oidc": "00000000", "knos_pay": "00000000"})
    assert ex.status("rpc", said.append, both, root, want="2.2") == 1
    # the feed's own entry for proposal 8 names the build: that is enough, with no word from the multisig
    monkeypatch.setattr(ex, "next_proposals", lambda account, root=None: {n: {"proposal": i, "version": "2.2", "status": None} for n, i in ex.NEXT_PROPOSALS.items()})
    feed = json.loads((root / "web" / "upgrades.json").read_text(encoding="utf-8"))
    feed["entries"][:0] = [{"index": i, "program": n, "build_hash": NEXT_HASH[n], "status": "executed", "squads_status": "Executed"} for n, i in ex.NEXT_PROPOSALS.items()]
    (root / "web" / "upgrades.json").write_text(json.dumps(feed), encoding="utf-8")
    assert ex.status("rpc", said.append, both, root, want="2.2") == 0 and ex.status("rpc", said.append, cluster(ELF), root, want="2.2") == 3
    # the real reader, on a cluster with no multisig: no status, never a guess, when the feed does not name 7 and 8
    monkeypatch.undo()
    alone = tmp_path / "feed_only"
    (alone / "web").mkdir(parents=True)
    (alone / "programs-v2").mkdir()
    (alone / "programs-v2" / "program_ids.json").write_bytes((ROOT / "programs-v2" / "program_ids.json").read_bytes())
    feed = json.loads((ROOT / "web" / "upgrades.json").read_text(encoding="utf-8"))
    feed["entries"] = [e for e in feed["entries"] if e.get("index") not in ex.NEXT_PROPOSALS.values()]
    (alone / "web" / "upgrades.json").write_text(json.dumps(feed), encoding="utf-8")
    assert ex.next_proposals(cluster(ELF), alone) == {"knos_oidc": {"proposal": 7, "version": "2.2", "status": None}, "knos_pay": {"proposal": 8, "version": "2.2", "status": None}}
    # a feed that names them: the multisig's word as the feed was generated, and said to be that
    feed["entries"][:0] = [{"index": i, "program": n, "status": "pending", "squads_status": "Approved"} for n, i in ex.NEXT_PROPOSALS.items()]
    (alone / "web" / "upgrades.json").write_text(json.dumps(feed), encoding="utf-8")
    assert ex.next_proposals(cluster(ELF), alone) == {n: {"proposal": i, "version": "2.2", "status": "Approved", "read": "web/upgrades.json, as it was generated"}
                                                      for n, i in ex.NEXT_PROPOSALS.items()}


@pytest.fixture(scope="module")
def phases():
    """`run --simulate --phase after`: both phases on the simulator, the live source's test build upgraded in place."""
    said: list[str] = []
    ev, code = ex.after_simulated(said.append)
    return ev, code, said


def test_the_after_rounds_run_on_the_live_build_upgraded_in_place_and_assert_the_one_rate_and_the_stored_fee(phases):
    ev, code, said = phases
    if "knos_pay" not in ex.changed_fixtures():
        pytest.skip("this tree's knos_pay test build is the live one: there is no 2.2 to run the after rounds on")
    results = {n: ev["rounds"][n]["result"] for n in ex.AFTER_STEPS}
    assert code == 0 and ev["old_build"] != ev["new_build"] and not [line for line in said if "FAILED" in line], results
    assert {n for n, r in results.items() if r != "ok"} == set(), results
    # ES256, through the client of knos.settle.v2.oidc: a private P-256 key registered, a token as long as one transaction of
    # this ledger carries verified in ONE transaction, and the same token again refused because its account exists (69)
    es = ev["rounds"]["es256"]
    assert [t.get("refused") for t in es["transactions"]] == [None, None, 69] and es["refused"]["error"] == 69
    assert 700 <= es["verified"]["signing_input_bytes"] <= ex.oidc.MAX_ES256_INPUT == 780 and len(es["token"].rsplit(".", 1)[0]) == es["verified"]["signing_input_bytes"]
    done = ev["exercises"]["es256_tokens"]
    assert done["status"] == "exercised" and done["signature"] == es["verified"]["signature"] and done["program"] == "knos_oidc"
    assert done["asserted"][0].startswith(f"knos_oidc verified an ES256 token of {es['verified']['signing_input_bytes']} bytes of https://es256.knos-exercise.invalid in one transaction")
    assert done["refusals"] == [{"signature": es["refused"]["signature"], "error": 69, "means": "the token account exists", "what": "the same token a second time"}]
    # the one rate, each fee read from the order's account: 5.00 -> 0.05, 100.00 -> 0.30, 1,500.00 -> 4.50; and all of it came back
    rate = ev["rounds"]["one_rate"]
    assert [(rate[k]["amount"], rate[k]["fee"]) for k in ("fee5", "fee100", "fee1500")] == [(5_000_000, 50_000), (100_000_000, 300_000), (1_500_000_000, 4_500_000)]
    assert all(ex._SIG.fullmatch(rate[k]["refund"]) for k in ("fee5", "fee100", "fee1500"))
    assert ev["exercises"]["fee_one_rate"]["asserted"][0].endswith("5.00 -> 0.05; 100.00 -> 0.30; 1,500.00 -> 4.50")
    # funded under 2.1 with 0.40 on 5.00; after the upgrade one is paid and one goes back, each with THAT fee
    before, stored = ev["rounds"]["stored_fund"], ev["rounds"]["stored_fee"]
    assert [(before[k]["amount"], before[k]["fee"]) for k in ("pay", "refund")] == [(5_000_000, 400_000)] * 2 and ex.fee_flat(5_000_000) == 50_000
    assert stored["pay"]["fee_kept"] == 400_000 and stored["refund"] == {"signature": stored["transactions"][1]["signature"], "amount": 5_000_000, "fee_back": 400_000, "refunded": True}
    assert said.index(next(line for line in said if line.startswith("upgraded in place"))) > said.index(next(line for line in said if "under knos_pay 2.1" in line))
    # one owner behind both judges: recorded, counted for nothing, nothing moved, and the answer says why
    one = ev["rounds"]["one_owner"]["answer"]
    assert (one["have"], one["of"], one["recorded"]) == (1, 2, True) and "runs in repositories of one owner are one judge" in one["why"][0]
    assert "says why: the neutral run was in a repository of the account that owns the order's repository" in ev["exercises"]["quorum_by_owner"]["asserted"][1]
    two = ev["rounds"]["two_owners"]
    assert two["one"]["owner"] != two["paid"]["owner"] and ev["rounds"]["earlier_marker"]["answer"]["signature"]
    # the grace: two minutes, the refund refused right after the deadline, paid inside the grace, back when it is over
    grace = ev["rounds"]["grace"]
    assert grace["fund"]["pay_until"] - grace["fund"]["deadline"] == 7200 and grace["early"]["error"] == 83 and 0 < grace["paid"]["after_deadline_s"] < 7200
    assert [t.get("refused") for t in grace["transactions"]] == [None, None, 83, None]
    # strict JSON: the control verified, the NaN claim refused with 61, under a private key that speaks for nobody
    strict = ev["exercises"]["oidc_strict_json"]
    assert strict["refusals"] == [{"signature": ev["rounds"]["strict"]["refused"]["signature"], "error": 61, "means": "the payload is not JSON", "what": "a NaN claim"}]
    done = {c for c, e in ev["exercises"].items() if e["status"] == "exercised"}
    registered = {"netting_reserve", "verify_gitlab", "gitlab_pay"}          # the registered rounds of the phase that have a path on the simulator and need no second owner
    assert done - registered == {"fee_one_rate", "quorum_by_owner", "presentation_grace", "oidc_strict_json", "es256_tokens"} and registered <= done
    assert (ev["rounds"]["private"]["exit"], ev["rounds"]["judge"]["exit"]) == (0, 3) and ev["rounds"]["judge"]["result"].startswith("skipped: no `--neutral")
    # nothing stays: every order these rounds opened is closed or went back
    assert set(ev["rounds"]["after_close"]["refunds"]) == {ev["rounds"]["one_owner"]["fund"]["order"], ev["rounds"]["earlier_marker"]["second"]["order"]}


def test_the_phases_run_at_the_public_ids_only_on_the_builds_they_are_for_and_a_second_owner_is_never_invented(tmp_path, monkeypatch):
    keys = tmp_path / "keys"
    keys.mkdir()
    where, said, made = keys / "exercise_public.json", [], []
    monkeypatch.setattr(ex, "next_proposals", lambda account, root=None: {n: {"proposal": i, "version": "2.2", "status": "Approved"} for n, i in ex.NEXT_PROPOSALS.items()})

    def world():
        made.append(1)
        raise AssertionError("a world was opened")
    live = cluster(ELF)
    # the committed tree: proposals 3 to 6 are the feed's, so the stand-in builds are unknown here; use the real records' hashes instead
    seen = json.loads((ROOT / "docs" / "provenance.json").read_text(encoding="utf-8"))["programs"]
    monkeypatch.setattr(ex, "read_programs", lambda account, root=ROOT: {n: {"id": IDS[n], "hash": seen[n]["on_chain_hash"], "slot": 1, "build": ex.NEW[n], "proposal": ex.PROPOSALS[n], "is": "new"}
                                                                         for n in ex.PROGRAMS})
    # after, while 2.1 is live: exit 3, nothing sent, no world opened, no file written
    assert ex.after_main("after", where, "rpc", keys, False, None, None, said.append, live, world) == 3 and not made and not where.exists()
    assert said[-1] == "nothing was sent: the after rounds run only on the builds of proposals 7 and 8"
    # before, once 2.2 is live: exit 3 as well
    monkeypatch.setattr(ex, "read_programs", lambda account, root=ROOT: {n: {"id": IDS[n], "hash": "ab" * 32, "slot": 1, "build": "2.2" if n in ex.NEXT_PROPOSALS else ex.NEW[n],
                                                                             "proposal": ex.NEXT_PROPOSALS.get(n, ex.PROPOSALS[n]), "is": "next" if n in ex.NEXT_PROPOSALS else "new"}
                                                                         for n in ex.PROGRAMS})
    assert ex.after_main("before", where, "rpc", keys, False, None, None, said.append, live, world) == 3 and not made
    assert said[-1].startswith("nothing was sent: knos_pay 2.1 is no longer what the public id runs")
    # after, with 2.2 live: the steps run in the world given, and what is kept is written (here: a world where the first step fails)
    class Broken:
        mode, neutral = "public", None

        def now(self):
            return 1_791_600_000
    assert ex.after_main("after", where, "rpc", keys, False, None, "someone/judge", said.append, live, Broken) == 1
    kept = json.loads(where.read_text(encoding="utf-8"))
    assert kept["mode"] == "public" and kept["programs"]["knos_pay"]["build"] == "2.2" and kept["rounds"]["stored_fee"]["result"].startswith("cannot: no order of this run's own was funded before the upgrade")
    assert "cannot: no client" not in json.dumps(kept) and kept["rounds"]["es256"]["result"] != "ok" and any(line.startswith("FAILED: ") for line in said)
    # a second owner: said as what cannot be done, unless --neutral names a repository, which is only ever read
    src = (ROOT / "scripts" / "exercise_public.py").read_text(encoding="utf-8")
    assert "`--neutral OWNER/REPO` names a repository of another" in src and "nothing is ever sent to that repository" in src
    assert "new += replay_tokens.capture(self.neutral, self.since, say=self.say)" in src and src.count("self.neutral") == 2
    # an order reserved for someone else is never looked for: the stored-fee step reads only the orders this evidence funded
    body = src[src.index("def after_stored_fee"):src.index("def after_one_rate")]
    assert "program_accounts" not in body and 'book.ev["rounds"].get("stored_fund"' in body


def test_an_order_funded_before_the_upgrade_that_another_sender_refunded_is_read_from_that_refund_and_never_assumed():
    """RefundOrder is anyone's to send once the deadline has passed, and the public relay sends every refund that is
    due: on 9 October 2026 the order of `stored_fund` due at 08:56 UTC went back 14 s later, in a transaction the relay
    sent, before `run --phase after` looked for it. The step reads knos_pay's own line of that refund: the amount and
    the fee as funded under 2.1 (5.40 on 5.00). A refund of any other sum, or none, is a failure."""
    relay_key = "5zGQCyrtK4gv61EYpUvoKApWAxvbPucpHABA1vdhAJ9V"
    orders = {k: ex.Keypair.from_seed(bytes([60 + i]) * 32).pubkey() for i, k in enumerate(("pay", "refund"))}

    def lines(order, amount, program=ex.pay.PAY_ID):
        return [f"Program {program} invoke [1]", f"Program log: knos3:refunded order={order} amount={amount}", f"Program {program} success"]

    class Ledger:
        def __init__(self, logs):
            self.said = logs

        def history(self, address, most=500):
            return [s for s in self.said if s.endswith(str(address))][:most]

        def logs(self, sig):
            return self.said[sig]

        def payer_of(self, sig):
            return relay_key

    class Gone(ex.World):
        def __init__(self, logs):
            self.ledger = Ledger(logs)

        def account(self, address):
            return None

    def run(logs):
        ev = {"rounds": {"stored_fund": {"issue": 7, **{k: {"order": str(o), "amount": 5_000_000, "fee": 400_000, "deadline": 1, "data": "00"}
                                                         for k, o in orders.items()}}}, "exercises": {}}
        said, st = [], {}
        ex.after_stored_fee(ex.Book(ev, Gone(logs), said.append), st)
        return st
    both = {f"sig-{o}": lines(o, 5_400_000) for o in orders.values()}
    st = run(both)
    for k, o in orders.items():
        assert st[k] == {"signature": f"sig-{o}", "amount": 5_000_000, "fee_back": 400_000, "refunded": True, "sent_by": relay_key}, k
    assert [t["signature"] for t in st["transactions"]] == [f"sig-{orders['pay']}", f"sig-{orders['refund']}"]
    assert all("went back whole: 5.00 and its stored fee of 0.40" in t["what"] and relay_key in t["what"] for t in st["transactions"])
    # gone back with the new rule's fee (5.05), or a line another program wrote, or nothing found: never taken for the stored fee
    for wrong in ({**both, f"sig-{orders['pay']}": lines(orders["pay"], 5_050_000)},
                  {**both, f"sig-{orders['pay']}": lines(orders["pay"], 5_400_000, program=ex.Keypair.from_seed(bytes([9]) * 32).pubkey())},
                  {f"sig-{orders['refund']}": both[f"sig-{orders['refund']}"]}):
        with pytest.raises(ex.Failed, match="no transaction of knos_pay refunded it with its amount and the fee it was funded with"):
            run(wrong)


def test_record_moves_the_2_2_capabilities_and_the_versions_only_where_the_hash_is_proposal_7s_or_8s(phases, tmp_path):
    if "knos_pay" not in ex.changed_fixtures():
        pytest.skip("this tree's knos_pay test build is the live one")
    ev = copy.deepcopy(phases[0])
    root = tree(tmp_path)
    shutil.copyfile(ROOT / "docs" / "capabilities.json", root / "docs" / "capabilities.json")       # the manifest of this release: the 2.2 capabilities are in it
    # as they stood before any run at the public ids: this release's own record moved some of them, and a capability
    # already exercised is never moved again, so the copy starts them at `tested`, with no transaction
    copied = json.loads((root / "docs" / "capabilities.json").read_text(encoding="utf-8"))
    for c in copied["capabilities"]:
        if c["id"] in ("fee_one_rate", "quorum_by_owner", "presentation_grace", "oidc_strict_json", "es256_tokens") and c["stage"] == "exercised":
            c["stage"] = "tested"
            c["evidence"].pop("exercised", None)
            c["evidence"].pop("deployed", None)
    (root / "docs" / "capabilities.json").write_text(json.dumps(copied, indent=1) + "\n", encoding="utf-8")
    feed = json.loads((root / "web" / "upgrades.json").read_text(encoding="utf-8"))
    feed["entries"][:0] = [{"index": i, "program": n, "build_hash": NEXT_HASH[n], "status": "executed", "squads_status": "Executed", "source_commit": "cd" * 20, "gate_run": 9}
                           for n, i in ex.NEXT_PROPOSALS.items()]
    (root / "web" / "upgrades.json").write_text(json.dumps(feed), encoding="utf-8")
    # knos_pay runs proposal 8's build; knos_oidc runs bytes nobody recorded
    ev["programs"] = ex.read_programs(cluster({**ELF, "knos_pay": NEXT["knos_pay"], "knos_oidc": b"bytes nobody recorded"}), root)
    assert [(r["is"], r["build"], r["proposal"]) for r in ev["programs"].values()] == [("unknown", None, None), ("next", "2.2", 8), ("new", "1.1", 5), ("new", "1.1", 6)]
    ev["mode"] = "public"
    # the slot knos_pay 2.1 went live at: kept as `before` once 2.2 replaces it, so a transaction of 2.1's time is still named by its slot
    prov = json.loads((root / "docs" / "provenance.json").read_text(encoding="utf-8"))
    prov["programs"]["knos_pay"]["live_slot"] = 508_314_432
    (root / "docs" / "provenance.json").write_text(json.dumps(prov, indent=1) + "\n", encoding="utf-8")
    said: list[str] = []
    ex.record(ev, root, said.append)
    data = json.loads((root / "docs" / "capabilities.json").read_text(encoding="utf-8"))
    was = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))
    assert data["programs"]["knos_pay"]["on_chain"] == "2.2" and "2.2" in data["programs"]["knos_pay"]["versions"]
    assert data["programs"]["knos_oidc"]["on_chain"] == was["programs"]["knos_oidc"]["on_chain"]
    assert any(line.startswith("knos_oidc: not the build of proposal 3 or 7 at the public id (unknown)") for line in said)
    by = {c["id"]: c for c in data["capabilities"]}
    for cid in ("fee_one_rate", "quorum_by_owner", "presentation_grace"):
        got = by[cid]
        assert got["stage"] == "exercised" and got["evidence"]["deployed"] == {"program": "knos_pay", "id": IDS["knos_pay"], "version": "2.2"}, cid
        assert got["evidence"]["exercised"]["signature"] == ev["exercises"][cid]["signature"] and got["evidence"]["exercised"]["ids"] == "public"
        assert "not deployed" not in got.get("note", "") and "is not live" not in got.get("note", ""), got.get("note")
    # knos_oidc's hash is not proposal 7's: its capability stays where it was, whatever the evidence holds
    assert by["oidc_strict_json"]["stage"] == "tested" and any(line.startswith("oidc_strict_json: not moved") for line in said)
    seen = json.loads((root / "docs" / "provenance.json").read_text(encoding="utf-8"))["programs"]["knos_pay"]
    assert (seen["proposal"], seen["proposal_status"], seen["on_chain_hash"], seen["on_chain_commit"]) == (8, "Executed", NEXT_HASH["knos_pay"], "cd" * 20) and "execution_signature" not in seen
    assert {k: seen["before"][k] for k in ("proposal", "live_slot")} == {"proposal": 4, "live_slot": 508_314_432} and seen["before"].get("read") == prov.get("read")
    text = (root / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8")
    assert "**one_rate.** The one rate on chain: 0.05 on an order of 5.00" in text[text.index(ex.BEGIN):text.index(ex.END)]


def test_resume_says_what_an_earlier_run_left_for_the_clock_and_the_2_1_tiers_are_not_claimed_on_2_2():
    said: list[str] = []
    ev = {"rounds": {"holdback": {"round": "holdback", "needs_time": 1_791_432_060, "stopped": "needs time: 2026-10-08 04:01 UTC: the end of the warranty"},
                     "order": {"round": "order", "needs_time": 1_792_555_980, "stopped": "needs time: 2026-10-21 04:13 UTC: the second order's deadline"},
                     "expiry": {"round": "expiry"}}}
    assert ex.due(ev, 1_791_500_000, said.append) == ["holdback", "order"]
    assert said[0].endswith("due now: this run finishes it") and said[1].endswith("not due before 2026-10-21 04:13 UTC")
    # at a public id that runs 2.2 the round `fees` does not mark the 2.1 tiers exercised with a 0.30% order
    src = (ROOT / "scripts" / "exercise_public.py").read_text(encoding="utf-8")
    body = src[src.index("def round_fees"):src.index("def round_holdback")]
    assert "the public id no longer charges knos_pay 2.1's tiers" in body and body.index("raise Skip") < body.index("fund_order_wallet_ix")
