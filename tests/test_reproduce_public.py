"""The read-only checks `knos reproduce` holds the PUBLIC program ids and the published pages to (provenance, payments,
statement), and the one button: the workflow that follows a run of `knos reproduce` in a fork and prepares the pull
request. No network: the cluster, the record and GitHub are stand-ins."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

from knos import mainnet_check as mc
from knos import reproduce as rp
from knos.settle.v2 import gate

ROOT = Path(__file__).resolve().parents[1]
IDS = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
FOUR = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")
ELF = {n: bytes([i + 1]) * 48 + n.encode() for i, n in enumerate(FOUR)}
HASH = {n: gate.executable_hash(e).hex() for n, e in ELF.items()}


def cluster(runs: dict[str, bytes]):
    held = {str(mc.programdata_address(IDS[n])): ("BPFLoaderUpgradeab1e11111111111111111111111", (3).to_bytes(4, "little") + bytes(8) + bytes(33) + elf + bytes(24))
            for n, elf in runs.items()}
    return lambda address: held.get(address)


def record(**over) -> dict:
    return {"read": "2026-10-06T23:00:00Z", "programs": {n: {"address": IDS[n], "on_chain_hash": HASH[n]} for n in FOUR}, **over}


def test_the_new_checks_are_rows_of_the_same_report_after_the_five_and_name_capabilities_the_manifest_lists():
    listed = {c["id"] for c in json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]}
    assert tuple(rp.PUBLIC) == ("provenance", "payments", "statement") and list(rp.EVERY) == [*rp.ORDER, *rp.PUBLIC]
    assert all(set(caps) <= listed for caps in rp.PUBLIC.values()) and not set(rp.PUBLIC) & set(rp.SUPPORTS)
    assert set(rp.live(env={})) == set(rp.EVERY)
    report = rp.build({"statement": dict, "payment": dict, "provenance": dict}, version="x", now=lambda: 1, clock=lambda: 0.0)
    assert [(c["id"], c["capabilities"]) for c in report["checks"]] == [("payment", ["order_pay"]), ("provenance", ["provenance_chain"]), ("statement", ["statements"])]
    assert all(len(line.split()) > 3 for line in rp.lines(report))


def test_every_deployed_hash_is_held_to_the_provenance_record_or_to_the_feed_for_a_build_newer_than_it():
    def no_feed():
        raise AssertionError("the feed is asked only for a build the record does not name")
    got = rp.provenance(cluster(ELF), record, no_feed, IDS)
    assert got["read"] == "2026-10-06T23:00:00Z" and list(got["programs"]) == list(FOUR)
    assert got["programs"]["knos_pay"] == {"address": IDS["knos_pay"], "on_chain": HASH["knos_pay"], "recorded": HASH["knos_pay"], "next": None,
                                           "runs": "the build the record read there"}
    # the build this release proposes, once it is live: the record named it as `next`
    new = b"knos_pay with one fee"
    named = lambda: record(next={"knos_pay": {"version": "2.2", "build_hash": gate.executable_hash(new).hex()}})  # noqa: E731
    assert rp.provenance(cluster({**ELF, "knos_pay": new}), named, no_feed, IDS)["programs"]["knos_pay"]["runs"] == "the build the record names as next"
    # a build the record does not name: only the upgrade feed can vouch for it, and a build nobody names fails
    feed = lambda: {"entries": [{"program_address": IDS["knos_pay"], "build_hash": gate.executable_hash(new).hex(), "status": "executed", "index": 8}]}  # noqa: E731
    assert rp.provenance(cluster({**ELF, "knos_pay": new}), record, feed, IDS)["programs"]["knos_pay"]["runs"] == "a build newer than the record: the upgrade feed names it (proposal 8)"
    with pytest.raises(rp.Fail, match="knos_pay: devnet runs .* which neither docs/provenance.json nor the upgrade feed names"):
        rp.provenance(cluster({**ELF, "knos_pay": b"something else"}), record, feed, IDS)
    with pytest.raises(rp.Fail, match="knos_meter: not deployed at"):
        rp.provenance(cluster({n: e for n, e in ELF.items() if n != "knos_meter"}), record, no_feed, IDS)

    def unread():
        raise OSError("no route")
    with pytest.raises(rp.Skip, match="docs/provenance.json could not be read"):
        rp.provenance(cluster(ELF), unread, no_feed, IDS)
    # and the committed record is one this check can read
    assert set(json.loads((ROOT / "docs" / "provenance.json").read_text(encoding="utf-8"))["programs"]) == set(FOUR)


def test_the_recorded_payments_are_the_public_ones_and_none_was_recorded_before_the_round(monkeypatch):
    # the manifest before the round at the public ids (tests/fixtures/before_round) recorded no payment there
    before = json.loads((ROOT / "tests" / "fixtures" / "before_round" / "docs" / "capabilities.json").read_text(encoding="utf-8"))
    assert rp.recorded_payments(before, IDS) == []
    with pytest.raises(rp.Skip, match="records no payment of an order at the public program ids yet"):
        rp.payments(None, dict, lambda: before, IDS)
    # the committed one records the round's: the order's payment and x402's, each by the transaction the round kept
    manifest = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))
    by = {c["id"]: c for c in manifest["capabilities"]}
    assert rp.recorded_payments(manifest, IDS) == [(cid, by[cid]["evidence"]["exercised"]["signature"]) for cid in ("order_pay", "x402_knos_order")]

    def cap(cid: str, sig: str, ids: str = "public", at: str = IDS["knos_pay"]) -> dict:
        return {"id": cid, "evidence": {"deployed": {"program": "knos_pay", "id": at}, "exercised": {"signature": sig, "ids": ids}}}
    made = {"capabilities": [cap("x402_knos_order", "sigX"), cap("order_quorum", "sigQ"), cap("order_pay", "sigP"), cap("order_auto_accept", "sigA"),
                             cap("work_orders", "sigW"), cap("order_pay", "staging", ids="staging"), cap("order_pay", "elsewhere", at="SomeStagingId")]}
    assert rp.recorded_payments(made, IDS) == [("order_pay", "sigP"), ("order_quorum", "sigQ"), ("x402_knos_order", "sigX")]
    asked: list[dict] = []

    def one(call, jwks, target):
        asked.append(target)
        if target["signature"] == "sigQ" and len(asked) > 3:
            raise rp.Fail("the token was not signed to pay this order", {"audience": "x"})
        return {"transaction": target["signature"], "order": "Order", "paid": 5_000_000, "fee": 400_000, "payees": [7], "token_sha256": "ab", "kid": "k",
                "key": "the chain's key account", "signed_for": {}, "more": "not kept"}
    monkeypatch.setattr(rp, "payment", one)
    got = rp.payments("call", dict, lambda: made, IDS)
    assert asked == [{"signature": s, "pay": IDS["knos_pay"], "oidc": IDS["knos_oidc"]} for s in ("sigP", "sigQ", "sigX")]
    assert got["recorded"] == 3 and [(r["capability"], r["transaction"]) for r in got["verified"]] == [("order_pay", "sigP"), ("order_quorum", "sigQ"), ("x402_knos_order", "sigX")]
    assert len(rp.payments("call", dict, lambda: made, IDS, most=1)["verified"]) == 1
    with pytest.raises(rp.Fail, match="order_quorum: the token was not signed to pay this order") as bad:
        rp.payments("call", dict, lambda: made, IDS)
    assert [r["transaction"] for r in bad.value.evidence["verified"]] == ["sigP"] and bad.value.evidence["failed"]["transaction"] == "sigQ"


def test_the_published_statement_is_made_again_from_its_evidence_and_an_edited_one_is_not_the_same():
    doc = json.loads((ROOT / "web" / "statement_sample.json").read_text(encoding="utf-8"))
    whole = json.loads((ROOT / "tests" / "data" / "statement" / "sept.json").read_text(encoding="utf-8"))
    assert doc["evidence"]["embedded"] is None and whole["evidence"]["embedded"] is not None        # the site names its evidence; the repository keeps it
    got = rp.statement(lambda: doc, lambda: whole)
    assert got["sha256"] == doc["sha256"] and got["lines"] == len(doc["lines"]) == 5 and got["invoice"] == doc["invoice"]
    assert got["evidence_sha256"] == whole["evidence"]["sha256"] and got["evidence_from"].endswith("(tests/data/statement/sept.json)")
    edited = json.loads(json.dumps(doc))
    edited["lines"][0]["amount"] = "999999.00"
    with pytest.raises(rp.Fail, match="the published statement is not what its evidence gives: differs"):
        rp.statement(lambda: edited, lambda: whole)
    # evidence that is not the evidence the published statement names
    other = json.loads(json.dumps(whole))
    other["evidence"]["sha256"] = "00" * 32
    with pytest.raises(rp.Fail, match="does not hold the evidence the published one names"):
        rp.statement(lambda: doc, lambda: other)
    with pytest.raises(rp.Fail, match="cannot be made again"):
        rp.statement(lambda: {"kind": "something else"}, lambda: whole)

    def unread():
        raise OSError("no route")
    with pytest.raises(rp.Skip):
        rp.statement(unread, lambda: whole)
    with pytest.raises(rp.Skip):
        rp.statement(lambda: doc, unread)


# ---- the one button ---------------------------------------------------------------------------------------------------

SEND = ROOT / ".github" / "workflows" / "knos-reproduction-send.yml"


def test_the_second_workflow_follows_the_button_and_can_write_one_branch_of_the_fork_and_nothing_else():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(SEND.read_text(encoding="utf-8"))
    first = yaml.safe_load((ROOT / ".github" / "workflows" / "knos-reproduce.yml").read_text(encoding="utf-8"))
    on = doc.get(True) or doc.get("on")
    assert set(first.get(True) or first.get("on")) == {"workflow_dispatch"}                         # the one button
    assert on == {"workflow_run": {"workflows": [first["name"]], "types": ["completed"]}}           # and what follows it by itself
    assert doc["permissions"] == {} and list(doc["jobs"]) == ["send"]
    job = doc["jobs"]["send"]
    assert job["permissions"] == {"actions": "read", "contents": "write"} and "id-token" not in json.dumps(doc)
    assert job["if"] == "github.event.workflow_run.conclusion == 'success'"         # an own run completes too (0.3.19), and is filed apart:
    [step] = job["steps"]
    assert "uses" not in step and "secrets." not in SEND.read_text(encoding="utf-8")                # no action, no secret: gh and python3 of the runner
    run = step["run"]
    assert "${{" not in run                                                                          # what GitHub knows reaches the script as environment, never as text
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}", "RUN": "${{ github.event.workflow_run.id }}", "UPSTREAM": "drexthealpha/Knos",
                           "DEFAULT": "${{ github.event.repository.default_branch }}"}
    # the file's name is the one the signing job gave it, and the pull request can only come from a fork of Knos
    assert """sed 's/[^A-Za-z0-9._-]/-/g').json""" in run and 're.sub(r"[^A-Za-z0-9._-]", "-", f"{repo}-{run}") + ".json"' in (ROOT / ".github" / "workflows" / "knos-reproduce.yml").read_text(encoding="utf-8")
    own = run[run.index('= "${UPSTREAM%%/*}" ]; then'):run.index('parent="$(gh api')]
    assert 'branch="reproduction-own-$RUN"' in own and "contents/reproductions/own/$want" in own and "contents/reproductions/$want" not in own
    assert "not a reproduction and is never counted as one" in own and own.rstrip().endswith("fi")
    assert own.count("exit 0") == 1 and "compare/main...$GITHUB_REPOSITORY_OWNER" not in own       # it ends there: no pull request as an outsider's
    rest = run[run.index('parent="$(gh api'):]
    assert rest.index('"$parent" != "$UPSTREAM"') < rest.index("git/refs") < rest.index("contents/reproductions/$want") and "reproductions/own" not in rest
    assert not re.search(r"(?m)^\s*(pip|pipx|uv|knos|npm) ", run) and "import knos" not in run and "from knos" not in run     # it installs nothing and runs no knos code


def _link_script() -> str:
    text = SEND.read_text(encoding="utf-8")
    body = text[text.index("python3 - <<'LINK'\n") + len("python3 - <<'LINK'\n"):text.index("\n          LINK\n")]
    return "\n".join(line[10:] if line.startswith(" " * 10) else line for line in body.splitlines()) + "\n"


def test_the_link_it_prints_opens_the_pull_request_with_the_file_the_branch_and_the_text(tmp_path):
    name, checks = "octo-Knos-36905461215.json", [
        {"id": "programs", "result": "pass", "seconds": 4.7, "capabilities": ["upgrade_delay", "upgrade_feed"], "evidence": {}, "why": ""},
        {"id": "statement", "result": "pass", "seconds": 0.1, "capabilities": ["statements"], "evidence": {}, "why": ""}]
    report = {"format": rp.FORMAT, "knos": "0.3.18", "checks": checks, "pass": 2, "fail": 0, "skipped": 0}
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / name).write_text(json.dumps({"report": report, "token": "a.b.c"}, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    def run() -> str:
        env = {**os.environ, "GITHUB_REPOSITORY": "octo/Knos", "RUN": "36905461215", "WANT": name, "BRANCH": "reproduction-36905461215",
               "UPSTREAM": "drexthealpha/Knos", "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")}
        done = subprocess.run([sys.executable, "-c", _link_script()], cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert done.returncode == 0, done.stderr
        return done.stdout
    said = run()
    assert said.startswith("The reproduction is on the branch `reproduction-36905461215` of octo/Knos as `reproductions/octo-Knos-36905461215.json`.")
    link = re.search(r"\*\*\[Open the pull request\]\((\S+)\)\*\*", said)[1]
    at = urllib.parse.urlsplit(link)
    assert (at.netloc, at.path) == ("github.com", "/drexthealpha/Knos/compare/main...octo:Knos:reproduction-36905461215")
    asked = urllib.parse.parse_qs(at.query)
    assert asked["quick_pull"] == ["1"] and asked["title"] == ["Reproduction of Knos 0.3.18 by octo"]
    body = asked["body"][0]
    # the text is the one the signing job prints (knos.reproduce.body), with the report's own hash, and the question nobody inside can answer
    facts = {"repository": "octo/Knos", "repository_owner": "octo", "run_id": "36905461215", "run": "https://github.com/octo/Knos/actions/runs/36905461215",
             "report_sha256": rp.digest(report)}
    assert rp.file_name(facts) == name and body.startswith(rp.body({"report": report}, facts)) and body.rstrip().endswith("What was awkward or broken on the way:")
    assert (tmp_path / "summary.md").read_text(encoding="utf-8") == said.rstrip("\n") + "\n" or said.strip() in (tmp_path / "summary.md").read_text(encoding="utf-8")
    # a check that failed is a bug to report: no link is given
    checks[0]["result"] = "fail"
    (tmp_path / "out" / name).write_text(json.dumps({"report": report, "token": "a.b.c"}), encoding="utf-8")
    said = run()
    assert "Open the pull request" not in said and "A check failed (programs), so this is a bug to report and not a reproduction to send" in said


def test_the_page_gives_three_lines_and_the_count_is_what_the_folder_holds():
    page = (ROOT / "docs" / "REPRODUCE.md").read_text(encoding="utf-8")
    held = sorted(p.name for p in (ROOT / "reproductions").glob("*.json"))
    assert f"Outside reproductions: {len(held)}, which is the number of signed reports" in " ".join(page.split())
    assert f"{len(held)} reproductions" in (ROOT / "reproductions" / "README.md").read_text(encoding="utf-8")
    lead = page.split("## ", 2)[1]
    steps = re.findall(r"(?m)^(\d)\. ", lead)
    assert steps == ["1", "2", "3"] and lead.startswith("Two clicks and one button")
    one, two, three = (lead[lead.index(f"\n{n}. "):] for n in "123")
    assert "https://github.com/drexthealpha/Knos/fork" in one and "**knos reproduce**" in two and "**Run workflow**" in two
    assert "**knos reproduction, to send**" in " ".join(three.split()) and "Create pull request" in " ".join(three.split())
    assert "knos-reproduction-send.yml" in lead and "a workflow's token is good for the repository the workflow is in and for no other" in " ".join(lead.split())
    # every check the command runs has its row on the page
    for cid in rp.EVERY:
        assert f"| `{cid}` |" in page, cid
