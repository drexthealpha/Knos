"""The referee panel's trust model in Knos's client tools (fix phase 2 of the 0.3.34 branch, released in 0.4.0): a spent verdict stays spent across
processes, panels come from the published registry (config/referees.yaml) and never hold a party's own key unless
--unlisted-panel says so (and the output says UNLISTED PANEL), and the MCP graduation tool takes only a signed
verdict. Synthetic keys and data; the registry in these tests is a temporary file (KNOS_REFEREES)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from solders.keypair import Keypair

from knos.platform import referees, verdict as v

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_790_000_000
JOB, EVIDENCE, RECIPIENT = bytes([1]) * 32, bytes([2]) * 32, bytes([3]) * 32


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    """Three referees published in a registry of this test's own."""
    panel = [Keypair() for _ in range(3)]
    lines = ["version: 1", "referees:"] + [f"  - {{key: {k.pubkey()}, name: r{i}, label: test referee {i}, test: true}}" for i, k in enumerate(panel)]
    path = tmp_path / "referees.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("KNOS_REFEREES", str(path))
    return panel


def _signed(panel, nonce: int, n: int = 2):
    m = v.message(JOB, EVIDENCE, "PASS", 5_000_000, RECIPIENT, NOW + 3600, nonce)
    return m, [v.sign(m, k) for k in panel[:n]], [bytes(k.pubkey()) for k in panel]


_CHILD = """
import json, sys
from knos.platform import verdict as v
a = json.loads(sys.argv[1])
ok, why = v.check(bytes.fromhex(a["m"]), [(bytes.fromhex(k), bytes.fromhex(s)) for k, s in a["sigs"]],
                  [bytes.fromhex(k) for k in a["keys"]], 2, now=a["now"], unlisted_panel=False)
print(json.dumps([ok, why]))
"""


def _child(m, sigs, keys) -> list:
    arg = json.dumps({"m": m.hex(), "sigs": [[k.hex(), s.hex()] for k, s in sigs], "keys": [k.hex() for k in keys], "now": NOW})
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    out = subprocess.run([sys.executable, "-c", _CHILD, arg], capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_verdict_spent_in_one_process_is_refused_in_another(registry):
    m, sigs, keys = _signed(registry, 501)
    assert _child(m, sigs, keys)[0] is True                                   # another process accepts it, and spends it
    assert v.check(m, sigs, keys, 2, now=NOW, unlisted_panel=False) == (False, "replay: this job and nonce were used")
    m2, sigs2, _ = _signed(registry, 502)
    assert v.check(m2, sigs2, keys, 2, now=NOW, unlisted_panel=False)[0]      # this process spends the other one first
    assert _child(m2, sigs2, keys) == [False, "replay: this job and nonce were used"]
    spent = Path(os.environ["KNOS_HOME"]) / "verdicts" / "spent"
    assert len(list(spent.iterdir())) == 2


def test_a_panel_is_drawn_from_the_registry_and_never_holds_a_partys_own_key(registry):
    m, sigs, keys = _signed(registry, 503)
    assert v.check(m, sigs, keys, 2, now=NOW, unlisted_panel=False, record=False) == (True, "2 of 2 distinct registered re-runners signed")
    outsiders = [Keypair() for _ in range(3)]
    mo, so, ko = _signed(outsiders, 504)
    ok, why = v.check(mo, so, ko, 2, now=NOW, unlisted_panel=False)
    assert not ok and why.startswith("panel:") and "registry" in why
    ok, why = v.check(mo, so, ko, 2, now=NOW, unlisted_panel=True)
    assert ok and why.startswith("UNLISTED PANEL")
    # the funder's key, or the recipient's, in the panel: refused unless --unlisted-panel, and then labelled
    funder = registry[0].pubkey()
    m5, s5, k5 = _signed(registry, 505)
    assert v.check(m5, s5, k5, 2, now=NOW, funder=funder, unlisted_panel=False)[1].startswith("panel:")
    assert v.check(m5, s5, k5, 2, now=NOW, funder=funder)[1].startswith("panel:")
    mr = v.message(JOB, EVIDENCE, "PASS", 5_000_000, bytes(registry[1].pubkey()), NOW + 3600, 506)
    assert not v.check(mr, [v.sign(mr, k) for k in registry[:2]], k5, 2, now=NOW)[0]
    with pytest.raises(referees.PanelError):
        referees.panel_rule(k5, payees=[(77, 10_000, registry[2].pubkey())], unlisted_panel=False)
    assert referees.panel_rule(k5, funder=funder, unlisted_panel=True) == referees.SELF_LABEL


def test_the_idea_panel_tools_refuse_an_unlisted_panel_or_the_funders_key(registry):
    from knos.ideas import wanted as W
    keys = [bytes(k.pubkey()) for k in registry]
    outsiders = [bytes(Keypair().pubkey()) for _ in range(3)]
    p = {"stages": ["s1"]}
    funder = Keypair().pubkey()
    with pytest.raises(W.IdeaError, match="registry"):
        W.fund_panel_ix(p, "s1", funder, funder, funder, 2, outsiders, unlisted_panel=False)
    with pytest.raises(W.IdeaError, match="own key"):
        W.fund_panel_ix(p, "s1", registry[0].pubkey(), funder, funder, 2, keys, unlisted_panel=False)
    with pytest.raises(W.IdeaError, match="own key"):
        W.fund_panel_ix(p, "s1", registry[0].pubkey(), funder, funder, 2, keys)       # whatever the caller says, short of --unlisted-panel


def _grad_args(verdict: dict) -> dict:
    return {"verdict": json.dumps(verdict), "claim_id": "trust-claim", "repo_id": 27_182_818, "amount": 10_000_000,
            "contributors": json.dumps([{"role": "researcher", "github_id": 5}])}


def test_the_mcp_graduation_tool_takes_only_a_verdict_a_registry_panel_signed(registry):
    from knos import graduation, mcp
    spec = "cd" * 32
    with pytest.raises(mcp.Failed, match="not signed"):
        mcp._money_call("knos_graduate", _grad_args({"passed": True, "spec_hash": spec, "checks": []}))

    def signed(panel, claim="trust-claim", spec_hash=spec, n=2, **extra):
        msg = graduation.graduation_message(claim, spec_hash, expiry=4_000_000_000)
        sigs = [[str(k.pubkey()), v.sign(msg, k)[1].hex()] for k in panel[:n]]
        return {"passed": True, "spec_hash": spec, "checks": [], **extra,
                "signed": {"message": msg.hex(), "signatures": sigs, "m": 2, "keys": [str(k.pubkey()) for k in panel]}}
    got = mcp._money_call("knos_graduate", _grad_args(signed(registry)))
    assert got["plan"]["escrow"]["amount"] == 10_000_000 and "panel" not in got
    for bad, why in [(signed(registry, claim="another-claim"), "another claim"), (signed(registry, spec_hash="ef" * 32), "another spec"),
                     (signed(registry, n=1), "below threshold")]:
        with pytest.raises(mcp.Failed, match=why):
            mcp._money_call("knos_graduate", _grad_args(bad))
    outsiders = [Keypair() for _ in range(3)]
    with pytest.raises(mcp.Failed, match="registry"):
        mcp._money_call("knos_graduate", _grad_args(signed(outsiders)))
    got = mcp._money_call("knos_graduate", _grad_args(signed(outsiders, unlisted_panel=True)))
    assert got["panel"].startswith("UNLISTED PANEL") and got["said"].startswith("UNLISTED PANEL")


def test_record_verify_says_how_to_verify_your_own_record():
    from knos.record import verifier
    problems: list[str] = []
    line = {"seq": 0, "kind": "anchor", "payload": {"signer": "MyOwnWa11et1111111111111111111111111111111", "cluster": "devnet"}}
    verifier._check_anchors([line], None, True, problems, frozenset({"8aukezen9sAALWShcZKK3hi8WawBi4vR6qmLf764PGBv"}))
    assert any("--signer MyOwnWa11et1111111111111111111111111111111" in p and "KNOS_RECORD_SIGNERS=" in p for p in problems)
    from knos.record import cli
    assert "YOUR OWN record" in Path(cli.__file__).read_text(encoding="utf-8")
