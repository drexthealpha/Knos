"""scripts/provenance.py: one chain per program from source to a run on chain, with every absent link said to be
missing; docs/PROVENANCE.md held to the committed records; and docs/kani.json held to the harnesses it names."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provenance", ROOT / "scripts" / "provenance.py")
prov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prov)
DATA = prov.load()
SIG = "5" * 87
SIG2 = "4" * 87


def test_the_page_is_what_the_committed_records_give():
    doc = prov.DOC.read_text(encoding="utf-8")
    assert prov.placed(doc, prov.render(DATA)) == doc, "run: python scripts/provenance.py --write"
    assert prov.main(["--check"], say=lambda _: None) == 0
    block = doc.split(prov.BEGIN)[1].split(prov.END)[0]
    for program in prov.PROGRAMS:
        assert f"### {program}" in block and f"`{DATA['ids'][program]}`" in block
    assert doc.count(prov.BEGIN) == doc.count(prov.END) == 1


def test_every_program_has_the_seven_links_and_a_missing_one_gives_its_reason():
    for chain in prov.chains(DATA):
        assert tuple(chain["links"]) == prov.LINKS and chain["address"] == DATA["ids"][chain["program"]]
        for name, link in chain["links"].items():
            assert link["value"] or len(link["why"]) > 10, (chain["program"], name)
            assert link["where"].split("/")[0] in ("web", "docs")
        assert prov.complete(chain) == (not prov.missing(chain) and chain["links"]["hash on chain"].get("same") is True)
        e = chain["entry"]
        if e and e["status"] != "executed":           # a build that has not executed is never shown as running or exercised
            assert not prov.complete(chain)
            assert {"execution transaction", "exercised scenario"} <= set(prov.missing(chain))
            assert not chain["links"]["hash on chain"].get("same")


def test_what_the_feed_records_is_what_the_chain_shows_and_nothing_else():
    for chain in prov.chains(DATA):
        e = chain["entry"]
        if e is None:
            continue
        assert e in DATA["upgrades"]["entries"] and e["status"] in ("executed", "pending")
        assert chain["links"]["source commit"]["value"] == e["source_commit"]
        assert chain["links"]["build hash"]["value"] == e["build_hash"]
        assert chain["links"]["verified-build run"]["value"] == (str(e["gate_run"]) if e["gate_run"] else None)
        assert str(e["index"]) in chain["links"]["upgrade proposal"]["value"] and e["proposal"] in chain["links"]["upgrade proposal"]["value"]


def _executed(data: dict, program: str = "knos_pay") -> tuple[dict, dict]:
    """A copy of the records in which the program's proposal has executed and the release recorded everything."""
    d = copy.deepcopy(data)
    e = next(x for x in d["upgrades"]["entries"] if x["program"] == program and x["status"] in ("pending", "executed"))
    e.update(status="executed", squads_status="Executed")
    p = d["capabilities"]["programs"][program]
    p["on_chain"] = p["versions"][-1]
    d["record"] = {"read": "2026-10-07T00:00:00Z", "programs": {program: {
        "on_chain_hash": e["build_hash"], "proposal": e["index"], "execution_signature": SIG,
        "on_chain_commit": e["source_commit"], "on_chain_run": e["gate_run"]}}}
    d["capabilities"]["capabilities"].append({
        "id": "made_up_for_the_test", "what": "A payment at the public id.", "stage": "exercised",
        "evidence": {"deployed": {"program": program, "id": d["ids"][program], "version": p["on_chain"]}, "exercised": {"signature": SIG2}}})
    return d, e


def test_a_chain_is_complete_only_when_every_link_is_recorded_and_the_hash_on_chain_is_the_builds():
    d, e = _executed(DATA)
    chain = prov.chain_of(d, "knos_pay")
    assert prov.complete(chain) and prov.missing(chain) == []
    assert chain["links"]["execution transaction"]["value"] == SIG and chain["links"]["exercised scenario"]["value"].startswith(SIG2)
    text = prov.render(d)
    assert "Every link is recorded and the hash on chain is this build's." in text and f"tx/{SIG}?cluster=devnet" in text

    other = copy.deepcopy(d)                               # the program runs something else: never complete
    other["record"]["programs"]["knos_pay"]["on_chain_hash"] = "0" * 64
    chain = prov.chain_of(other, "knos_pay")
    assert not prov.complete(chain) and "NOT the build above" in chain["links"]["hash on chain"]["value"]

    for drop, name in (("execution_signature", "execution transaction"), ("on_chain_hash", "hash on chain")):
        less = copy.deepcopy(d)
        del less["record"]["programs"]["knos_pay"][drop]
        chain = prov.chain_of(less, "knos_pay")
        assert name in prov.missing(chain) and not prov.complete(chain)
        assert f"**{prov.MISSING}**" in prov.render(less)

    stale = copy.deepcopy(d)                               # a transaction recorded for another proposal is not this one's
    stale["record"]["programs"]["knos_pay"]["proposal"] = e["index"] - 1
    assert "execution transaction" in prov.missing(prov.chain_of(stale, "knos_pay"))

    staging = copy.deepcopy(d)                             # a transaction at another address is not a scenario at the public id
    staging["capabilities"]["capabilities"][-1]["evidence"]["deployed"]["id"] = "1" * 43
    assert "exercised scenario" in prov.missing(prov.chain_of(staging, "knos_pay"))
    older = copy.deepcopy(d)                               # nor is one on the version before
    older["capabilities"]["capabilities"][-1]["evidence"]["deployed"]["version"] = "2.0"
    assert "exercised scenario" in prov.missing(prov.chain_of(older, "knos_pay"))


def test_a_cancelled_or_replaced_proposal_is_never_a_link_and_no_records_give_only_missing():
    d = copy.deepcopy(DATA)
    for e in d["upgrades"]["entries"]:
        e["status"] = "replaced"
    chain = prov.chain_of(d, "knos_oidc")
    assert chain["entry"] is None and set(prov.LINKS) - set(prov.missing(chain)) <= {"hash on chain"}
    empty = {"ids": DATA["ids"], "upgrades": {}, "capabilities": {}, "facts": [], "changelog": "", "record": {}}
    for chain in prov.chains(empty):
        assert prov.missing(chain) == list(prov.LINKS)
    text = prov.render(empty)
    assert text.count(f"**{prov.MISSING}**") >= 7 * len(prov.PROGRAMS) and "no read of the cluster is on file" in text


def test_the_execution_transaction_is_the_one_that_names_the_proposal_and_the_program_data():
    proposal, data_account = "P" * 44, "D" * 44
    txs = {"failed": None, "approve": {"transaction": {"message": {"accountKeys": [proposal, "X"]}}, "meta": {}},
           "execute": {"transaction": {"message": {"accountKeys": [proposal]}}, "meta": {"loadedAddresses": {"writable": [data_account], "readonly": []}}}}

    def call(method: str, params: list):
        if method == "getSignaturesForAddress":
            assert params[0] == proposal
            return [{"signature": "failed", "err": {"InstructionError": [0, "Custom"]}}, {"signature": "approve", "err": None},
                    {"signature": "execute", "err": None}]
        return txs[params[0]]
    assert prov.execution_signature(call, proposal, data_account) == "execute"
    assert prov.execution_signature(call, proposal, "E" * 44) is None


def test_record_needs_a_read_of_the_cluster():
    said: list[str] = []
    assert prov.main(["--record"], say=said.append) == 2 and "needs --rpc" in said[0]


# ---- docs/kani.json: the recorded run of the model checker ---------------------------------------------------------------

KANI = json.loads((ROOT / "docs" / "kani.json").read_text(encoding="utf-8"))
PROOFS = ROOT / "programs-v2" / "knos_pay" / "src" / "proofs.rs"


def test_the_kani_record_names_every_harness_of_proofs_rs_and_no_other():
    source = PROOFS.read_text(encoding="utf-8")
    harnesses = re.findall(r"#\[kani::proof\]\s*(?:#\[[^\]]*\]\s*)*fn (\w+)\s*\(", source)
    assert len(harnesses) == source.count("#[kani::proof]") >= 5
    assert [h["name"] for h in KANI["harnesses"]] == harnesses
    assert KANI["source"]["path"] == "programs-v2/knos_pay/src/proofs.rs"
    assert KANI["source"]["sha256"] == hashlib.sha256(PROOFS.read_bytes()).hexdigest(), \
        "proofs.rs changed since the recorded run: run the harnesses again and record them"
    assert re.fullmatch(r"[0-9a-f]{40}", KANI["source"]["commit"]) and re.fullmatch(r"\d{4}-\d\d-\d\d", KANI["date"])
    assert KANI["version"] == re.search(r'kani-version: "([\d.]+)"', (ROOT / ".github" / "workflows" / "program.yml").read_text(encoding="utf-8")).group(1)


@pytest.mark.parametrize("h", KANI["harnesses"], ids=lambda h: h["name"][:40])
def test_a_harness_counts_as_proved_only_when_kani_verified_it_within_the_limit(h):
    assert h["result"] in ("verified", "failed", "timed out")
    assert h["proved"] is (h["result"] == "verified")
    assert 0 < h["seconds"] <= KANI["limit_seconds"] + 1 and h["attempts"] >= 1
    if h["result"] == "verified":
        assert h["checks"] > 0 and h["failed_checks"] == 0 and h["verification_seconds"] <= h["seconds"]
    if h["result"] == "timed out":
        assert h["checks"] is None and h["seconds"] >= KANI["limit_seconds"] and "Not proved" in h["note"]


def test_the_conservation_harness_is_among_the_proved_ones():
    """What the capability `kani_fee_conservation` says is this harness: it may be called tested only while this holds."""
    by_name = {h["name"]: h for h in KANI["harnesses"]}
    assert by_name["what_a_funder_puts_in_is_what_the_payees_the_relayer_and_the_fee_owner_take_out"]["proved"]
    for h in KANI["harnesses"]:
        assert h["proved"] or len(h.get("note", "")) > 40, h["name"]        # one that is not proved says so and why
