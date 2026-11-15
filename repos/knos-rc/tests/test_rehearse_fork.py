"""scripts/rehearse_fork.py and scripts/rehearse_fork.sh, offline: the parts of the rehearsal that are logic (reading a program's
error from a cluster's words, moving a clock that lands short, which failures are asked again and which are answers) and
what the shell script says when something is missing.

The rehearsal itself needs a Surfpool fork of mainnet-beta, which needs the network: set KNOS_TEST_FORK=1 to run it here
(it also needs node 20 and `npm ci --prefix scripts`).
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from knos import chain
from knos.settle.v2 import pay

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("rehearse_fork_script", ROOT / "scripts" / "rehearse_fork.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rf = _script()
NO_NETWORK = "http://127.0.0.1:9"      # the discard port: nothing answers


class FakeTime:
    """The script's `time`, with a clock that only moves when the script waits."""

    def __init__(self):
        self.t = 1_790_000_000.0

    def sleep(self, seconds):
        self.t += seconds

    def monotonic(self):
        return self.t

    def time(self):
        return self.t


def rehearsal() -> "rf.Rehearsal":
    return rf.Rehearsal(NO_NETWORK, say=lambda line: None)


def test_a_programs_error_is_read_from_either_wording_a_cluster_uses():
    assert rf.code_of(chain.RpcError("Transaction simulation failed: Error processing Instruction 1: custom program error: 0x59")) == 89
    assert rf.code_of(chain.RpcError("failed", {"err": {"InstructionError": [1, {"Custom": 83}]}})) == 83     # the JSON form
    assert rf.code_of(ValueError("InstructionError(1, Custom(83))")) == 83
    assert rf.code_of(chain.RpcError("Blockhash not found", {"err": "BlockhashNotFound"})) is None
    said = rf.Rehearsal.said
    assert said(None) == "accepted"
    assert said(chain.RpcError("custom program error: 0x52")) == "refused with error 82 (the account is not a job)"
    assert said(chain.RpcError("custom program error: 0x60")) == "refused with error 96"
    assert said(chain.RpcError("something else")).startswith("refused (something else")


def test_the_two_error_codes_the_rehearsal_expects_are_the_ones_knos_pay_defines():
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    for code, words in rf.CODES.items():
        assert re.search(rf"pub const E_[A-Z]+: u32 = {code};", lib), (code, words)
    assert "E_DEVNET: u32 = 89" in lib and "E_STATE: u32 = 83" in lib


def test_money_and_dates_read_as_a_person_writes_them():
    assert rf.usdc(19_500_000) == "19.5 USDC" and rf.usdc(100 * rf.USDC) == "100 USDC" and rf.usdc(1) == "0.000001 USDC"
    assert rf.usdc(8_421_204_031_135_785) == "8,421,204,031.135785 USDC"
    assert rf.day(1_790_000_000) == "2026-09-21 14:13:20 UTC"


def test_the_clock_is_moved_again_until_it_is_where_it_was_sent_even_when_it_lands_minutes_short(monkeypatch):
    r = rehearsal()
    clock = {"t": 1_790_000_000, "asked": []}

    def rpc(method, params, timeout=0):
        assert method == "surfnet_timeTravel" and list(params[0]) == ["absoluteTimestamp"]
        asked = params[0]["absoluteTimestamp"] // 1000
        clock["asked"].append(asked)
        if asked > clock["t"]:
            clock["t"] = asked - 600           # lands ten minutes short, as the worst measured did not, to force a second ask
    monkeypatch.setattr(r, "rpc", rpc)
    monkeypatch.setattr(r, "now", lambda: clock["t"])
    target = 1_790_000_000 + 3_600
    assert r.travel_to(target) >= target
    assert len(clock["asked"]) == 2 and clock["asked"][0] == target + 300 and clock["asked"][1] > clock["asked"][0]
    clock["asked"].clear()
    assert r.travel_to(target) >= target and clock["asked"] == []        # already there: the clock is not touched


def test_a_clock_that_does_not_move_stops_the_run_in_words(monkeypatch):
    r = rehearsal()
    monkeypatch.setattr(r, "rpc", lambda method, params, timeout=0: None)
    monkeypatch.setattr(r, "now", lambda: 1_790_000_000)
    with pytest.raises(rf.Failed, match="after six tries to move it to 2026-09-21 15:13:20 UTC"):
        r.travel_to(1_790_000_000 + 3_600)


def test_a_cluster_that_was_not_ready_is_asked_again_and_a_programs_refusal_is_an_answer(monkeypatch):
    monkeypatch.setattr(rf, "time", FakeTime())
    r = rehearsal()
    calls: list[int] = []

    def not_ready(ixs, payer, signers=None):
        calls.append(1)
        if len(calls) < 3:
            raise chain.RpcError("Transaction simulation failed: Blockhash not found", {"err": "BlockhashNotFound", "logs": None})
        return "sig"
    monkeypatch.setattr(r.ledger, "send", not_ready)
    assert r.send([]) == "sig" and len(calls) == 3

    calls.clear()

    def refuses(ixs, payer, signers=None):
        calls.append(1)
        raise chain.RpcError("Transaction simulation failed: Error processing Instruction 1: custom program error: 0x53",
                             {"err": {}, "logs": ["Program x invoke [1]", "Program x failed: custom program error: 0x53"]})
    monkeypatch.setattr(r.ledger, "send", refuses)
    with pytest.raises(chain.RpcError):
        r.send([])
    assert len(calls) == 1, "a refusal is not sent again"
    assert rf.code_of(r.refusal([])) == 83 and r.said(r.refusal([])).startswith("refused with error 83")

    calls.clear()

    def drops(ixs, payer, signers=None):
        calls.append(1)
        raise OSError("connection reset")
    monkeypatch.setattr(r.ledger, "send", drops)
    with pytest.raises(rf.Failed, match="did not take the transaction after three tries"):
        r.send([])
    assert len(calls) == 3


def test_the_logs_of_a_transaction_are_asked_for_with_version_1_and_are_the_escrows_own_lines(monkeypatch):
    """A transaction a relay sends to a 2.1 program is a version 1 transaction, and a cluster refuses to give one to a
    reader that names a lower version: the rehearsal would then print no line of it."""
    asked = []

    def cluster(url, method, params, timeout=0):
        asked.append((url, method, params))
        if params[1].get("maxSupportedTransactionVersion", -1) < 1:
            raise chain.RpcError("Transaction version (1) is not supported by the requesting client", {"code": -32015})
        return {"version": 1, "meta": {"logMessages": ["Program P invoke [1]", "Program log: knos2:paid repo=1 issue=2 author=3 amount=4 fee=5", "Program log: other",
                                                       "Program P success"]}}
    monkeypatch.setattr(rf.chain, "call", cluster)
    assert rehearsal().logs("S") == ["knos2:paid repo=1 issue=2 author=3 amount=4 fee=5"]
    assert asked == [(NO_NETWORK, "getTransaction", ["S", {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}])]
    # the logs are a courtesy: a cluster that will not give the transaction costs the rehearsal nothing
    monkeypatch.setattr(rf.chain, "call", lambda *a, **kw: (_ for _ in ()).throw(chain.RpcError("gone", None)))
    assert rehearsal().logs("S") == []


def test_a_read_is_tried_three_times_and_the_third_failure_is_raised(monkeypatch):
    monkeypatch.setattr(rf, "time", FakeTime())
    seen: list[int] = []

    def flaky():
        seen.append(1)
        if len(seen) < 3:
            raise chain.RpcError("no block time")
        return 7
    assert rf.Rehearsal.again(flaky) == 7 and len(seen) == 3
    seen.clear()

    def broken():
        seen.append(1)
        raise OSError("refused")
    with pytest.raises(OSError):
        rf.Rehearsal.again(broken)
    assert len(seen) == 3


def test_a_fork_that_has_no_clock_yet_is_waited_for_and_then_named_in_the_failure(monkeypatch):
    r = rehearsal()
    monkeypatch.setattr(rf, "time", FakeTime())

    def no_time():
        raise chain.RpcError("no block time")
    monkeypatch.setattr(r.ledger, "now", no_time)
    with pytest.raises(rf.Failed, match=r"gave no clock in 5 s \(no block time\)"):
        r.started(within=5)
    answers = iter([chain.RpcError("no block time"), chain.RpcError("no block time"), 1_790_000_000])

    def later():
        got = next(answers)
        if isinstance(got, Exception):
            raise got
        return got
    monkeypatch.setattr(r.ledger, "now", later)
    assert r.started(within=30) == 1_790_000_000


def test_the_rehearsal_has_the_nine_steps_it_says_and_loads_pinned_builds_at_the_pinned_ids():
    steps = re.findall(r"^        self\.step\(", (ROOT / "scripts" / "rehearse_fork.py").read_text(encoding="utf-8"), re.M)
    assert len(steps) == rf.STEPS == 9
    assert len([line for line in (rf.__doc__ or "").splitlines() if re.match(r"    \d  ", line)]) == 9
    sums = (ROOT / "tests" / "fixtures" / "SHA256SUMS").read_text(encoding="utf-8")
    assert set(rf.BUILDS) == {"knos_oidc", "knos_pay"}
    for name, build in rf.BUILDS.items():
        assert build in sums and (rf.FIX / build).is_file(), build
        assert pay.IDS[name]
    assert rf.BUILDS["knos_pay"] == "knos_pay_v2_nodevnet.so"        # the build without the test-USDC faucet
    assert str(rf.USDC_MINT) == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" and str(rf.SQUADS) == pay.IDS["squads_program"]


def test_a_run_that_stops_says_at_which_step_and_returns_1(monkeypatch, capsys):
    def stops(self):
        self.n = 4
        raise rf.Failed("the wallet holds nothing")
    monkeypatch.setattr(rf.Rehearsal, "run", stops)
    assert rf.main(["--rpc", NO_NETWORK]) == 1
    assert "STOPPED at step 4 of 9: the wallet holds nothing" in capsys.readouterr().err

    def drops(self):
        self.n = 1
        raise OSError("connection refused")
    monkeypatch.setattr(rf.Rehearsal, "run", drops)
    assert rf.main(["--rpc", NO_NETWORK]) == 1
    assert f"STOPPED at step 1 of 9: OSError: connection refused (the fork is at {NO_NETWORK}: is it running?)" in capsys.readouterr().err


# ---- the shell script -------------------------------------------------------------------------------------------------------

def _bash(*args, env=None, timeout=120) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is not installed (on Windows, run the scripts in WSL)")
    return subprocess.run([bash, "scripts/rehearse_fork.sh", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, **(env or {})})


def test_the_script_says_what_it_does_with_help_and_refuses_anything_else():
    done = _bash("--help")
    assert done.returncode == 0 and "surfnet_setTokenAccount" in done.stdout and "KNOS_FORK_RPC" in done.stdout and "WSL" in done.stdout
    other = _bash("--now")
    assert other.returncode == 2 and "usage: bash scripts/rehearse_fork.sh" in other.stderr


def test_the_script_names_a_python_that_is_missing_and_a_fork_that_does_not_answer():
    missing = _bash(env={"PYTHON": "/nonexistent/python3"})
    assert missing.returncode == 1 and "stopped: /nonexistent/python3 is not on PATH" in missing.stderr
    nothing = _bash(env={"PYTHON": sys.executable, "KNOS_FORK_RPC": NO_NETWORK}, timeout=180)
    assert nothing.returncode == 1 and f"Surfpool at {NO_NETWORK} (KNOS_FORK_RPC): used as it is" in nothing.stdout
    assert "STOPPED at step 1 of 9" in nothing.stderr and "is it running?" in nothing.stderr


def test_the_script_stops_the_fork_it_started_by_its_process_id_and_nothing_else():
    text = (ROOT / "scripts" / "rehearse_fork.sh").read_text(encoding="utf-8")
    assert "pkill" not in text and "killall" not in text and 'kill "$SURF"' in text and "trap cleanup EXIT" in text
    assert "scripts/node_modules/@solana/surfpool" in text and "npm ci --prefix scripts" in text and "WSL" in text


@pytest.mark.skipif(not os.environ.get("KNOS_TEST_FORK"),
                    reason="the rehearsal on a real fork needs the network and the embedded Surfpool: set KNOS_TEST_FORK=1 "
                           "(node 20, npm ci --prefix scripts, https access to mainnet-beta)")
def test_the_rehearsal_passes_on_a_fork_of_mainnet():
    done = _bash(env={"PYTHON": sys.executable}, timeout=600)
    assert done.returncode == 0, f"{done.stdout[-3000:]}\n{done.stderr[-2000:]}"
    assert "all 9 steps passed" in done.stdout and "the Balance holds 100 USDC again" in done.stdout
