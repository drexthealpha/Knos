"""Fixes from a second review of the labs: lab verdict replay refused across processes; every lab
runnable with `python -m knos.labs try`; the devnet run supports every field it lists and always writes what ran;
referee keys never in the buyer's folder; PyLabRobot: one install script, the recorded runs as the labelled default."""
from __future__ import annotations

import io
import json
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from solders.keypair import Keypair

from knos import labs
from knos.labs import __main__ as cli
from knos.labs import devnet, verdicts

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


REFS = [Keypair() for _ in range(3)]


def signed(nonce: str = "n-1"):
    a = labs.get("adaptyv")
    spec = devnet.field_case("proteins")["spec"]
    r = a.results(a.order(spec, "E"))
    msg = verdicts.message("order-r", verdicts.lab_verdict(spec, r), amount=5, recipient="Lab", mint="Mint", expiry=2_000_000_000, nonce=nonce)
    return msg, verdicts.sign(msg, REFS[:2])


def test_an_accepted_lab_verdict_is_spent_and_its_replay_refused_even_in_another_process(tmp_path):
    store = tmp_path / "spent.jsonl"
    msg, sigs = signed()
    keys = [str(k.pubkey()) for k in REFS]
    assert verdicts.check(msg, sigs, keys, 2, now=0, spent=verdicts.SpentStore(store)) == []
    again = verdicts.check(msg, sigs, keys, 2, now=0, spent=verdicts.SpentStore(store))      # a fresh store on the same file
    assert any("already used" in p for p in again)
    assert verdicts.SpentStore.key(msg) in verdicts.SpentStore(store)


def test_the_default_store_is_persistent_and_the_callers_set_is_filled(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOS_LAB_VERDICTS_SPENT", str(tmp_path / "default.jsonl"))
    msg, sigs = signed("n-2")
    keys = [str(k.pubkey()) for k in REFS]
    seen: set = set()
    assert verdicts.check(msg, sigs, keys, 2, now=0, seen_nonces=seen) == [] and seen == {"n-2"}
    assert any("already used" in p for p in verdicts.check(msg, sigs, keys, 2, now=0))
    assert (tmp_path / "default.jsonl").read_text(encoding="utf-8").count("order-r:n-2") == 1


def test_a_dry_run_and_a_refusal_spend_nothing(tmp_path):
    store = verdicts.SpentStore(tmp_path / "s.jsonl")
    msg, sigs = signed("n-3")
    keys = [str(k.pubkey()) for k in REFS]
    assert verdicts.check(msg, sigs, keys, 2, now=0, spent=store, record=False) == []
    assert verdicts.check(msg, sigs[:1], keys, 2, now=0, spent=store) != []                  # m-1: refused
    assert verdicts.SpentStore.key(msg) not in store
    assert verdicts.check(msg, sigs, keys, 2, now=0, spent=store) == []                      # still unspent: accepted once


def run_cli(*args) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(list(args))
    return code, buf.getvalue()


def test_materials_project_runs_on_its_fixture_from_the_command_line():
    code, out = run_cli("try", "materials_project")
    got = json.loads(out)
    assert code == 0 and got["field"] == "materials" and got["results"]["mode"] == "fixture"
    assert got["results"]["lab_verdict"] == "PASS" and got["results"]["outcome_verdict"] == "PASS"
    assert "legacy" in got["results"]["source"].lower()


@pytest.mark.parametrize("name", ["adaptyv", "b12_selenium", "b12_foundry", "materials_project", "pcbway", "xometry", "pylabrobot"])
def test_every_lab_can_be_tried(name):
    code, out = run_cli("try", name)
    assert code == 0 and json.loads(out)["lab"] == name


def test_an_unknown_lab_is_named_not_guessed(capsys):
    assert cli.main(["try", "nolab"]) == 2


def test_robotics_defaults_to_the_recorded_runs_clearly_labelled():
    code, out = run_cli("try", "pylabrobot")
    got = json.loads(out)
    assert code == 0 and got["results"]["mode"] == "fixture" and got["results"]["source"].startswith("FIXTURE")
    assert got["results"]["outcome_verdict"] == "PASS"


def test_robotics_live_without_an_install_says_how_to_install(monkeypatch, capsys):
    from knos.labs import robotics
    monkeypatch.setattr(robotics, "python", lambda: None)
    assert cli.main(["try", "pylabrobot", "--live"]) == 2
    assert "scripts/install_pylabrobot.sh" in capsys.readouterr().err


def test_the_install_script_is_one_command_into_its_own_venv():
    text = (ROOT / "scripts" / "install_pylabrobot.sh").read_text(encoding="utf-8")
    assert '"pylabrobot==0.2.2"' in text and "-m venv" in text and "export KNOS_PYLABROBOT_PYTHON=" in text


@pytest.mark.parametrize("field", sorted(devnet.FIELDS))
def test_the_devnet_run_has_a_case_for_every_field_it_lists(field):
    case = devnet.field_case(field)
    lab = labs.get(case["lab"])
    o = lab.order(case["spec"], "E")
    r = lab.results(o, case["spec"]) if case["lab"] == "pylabrobot" else lab.results(o)
    if case.get("bench"):
        r = lab.with_bench(r, case["bench"])
    assert verdicts.lab_verdict(case["spec"], r).passed
    price, basis = devnet._price_units(case["lab"], case["spec"])
    assert price > 0 and basis
    with pytest.raises(ValueError, match="no demo for field"):
        devnet.field_case("astronomy")


def test_referee_keys_never_live_in_the_buyers_folder(tmp_path):
    wallets, payer = tmp_path / "buyer", Keypair()
    wallets.mkdir()
    for bad in (wallets, wallets / "referees"):
        with pytest.raises(ValueError, match="buyer's wallets folder"):
            devnet.referee_keys(wallets, bad, payer)
    keys = devnet.referee_keys(wallets, tmp_path / "panel", payer)
    assert len(keys) == 3 and not list(wallets.glob("referee-*.json")) and len(list((tmp_path / "panel").glob("referee-*.json"))) == 3


def test_the_devnet_run_writes_what_ran_when_a_later_field_fails(tmp_path, monkeypatch):
    class Fake:
        def __init__(self, wallets, referees):
            self.mint = self.ms = self.treasury = "Addr"
            self.payer, self.referees, self.sent = Keypair(), REFS, [{"step": "electronics: fund", "signature": "s"}]

        def run(self, field, record):
            if field == "materials":
                raise RuntimeError("the cluster did not answer")
            return {"field": field}
    monkeypatch.setattr(devnet, "Demo", Fake)
    out = tmp_path / "labs.json"
    code = devnet.main(["--wallets", str(tmp_path / "w"), "--referees", str(tmp_path / "r"), "--out", str(out),
                        "--fields", "electronics,materials,robotics"])
    got = json.loads(out.read_text(encoding="utf-8"))
    assert code == 1 and [r["field"] for r in got["runs"]] == ["electronics", "robotics"]
    assert got["failed"][0]["field"] == "materials" and "did not answer" in got["failed"][0]["error"]
    assert got["signatures"] and "not independent" in got["referees_note"]
