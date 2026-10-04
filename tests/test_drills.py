"""scripts/drills.py with a fake RPC in the cluster's place. The fake serves the TEST builds of both programs as the
"deployed" ones (their ProgramData accounts, zero padding and all), so the token drills can run here with tokens the
test key signed: the released build would refuse those, and only GitHub can sign what it accepts. What is tested is
the script: that it drills exactly the bytes the RPC gave it, what each row says, the table, and the exit code."""
from __future__ import annotations

import base64
import json
import sys

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _oidc2 import attest_claims  # noqa: E402
from _pay2 import WF_REPO, WF_SHA, github_claims  # noqa: E402
from _settle import FIX, NOW, b64, modulus, sign_jwt, signing_key  # noqa: E402

from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import oidc, pay  # noqa: E402

sys.path.insert(0, str(FIX.parents[1] / "scripts"))
import drills  # noqa: E402

BUILDS = {"knos_oidc": "knos_oidc_v2_test.so", "knos_pay": "knos_pay_v2_test.so"}
DEVNET = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
REPO, OWNER, MAINT, PAYEE, ISSUE, USDC = 987654321, 424242, 555000, 31337, 7, 1_000_000
TH = pay.terms_hash(drills.TERMS)
JWKS = {"keys": [{"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": "k", "n": b64(oidc.modulus_bytes(modulus(signing_key())))}]}


class Rpc:
    """A cluster that holds two upgradeable programs and answers getGenesisHash and getAccountInfo, nothing else."""
    def __init__(self, builds: dict[str, str] = BUILDS, padding: int = 4096):
        self.calls: list[tuple[str, str]] = []
        self.accounts: dict[str, tuple[str, bytes]] = {}
        for name, build in builds.items():
            address = pay.IDS[name]
            home = mc.programdata_address(address)
            self.accounts[address] = (str(mc.LOADER), (2).to_bytes(4, "little") + bytes(home))
            self.accounts[str(home)] = (str(mc.LOADER), (3).to_bytes(4, "little") + (4242).to_bytes(8, "little") + b"\x01"
                                        + bytes(Pubkey.from_string(pay.IDS["upgrade_authority"])) + (FIX / build).read_bytes() + bytes(padding))

    def __call__(self, url: str, method: str, params: list, timeout: float = 10.0):
        self.calls.append((method, str(params[0]) if params else ""))
        if method == "getGenesisHash":
            return DEVNET
        assert method == "getAccountInfo", f"the script asked the cluster for {method}"
        got = self.accounts.get(params[0])
        return {"value": None if got is None else {"owner": got[0], "data": [base64.b64encode(got[1]).decode(), "base64"], "executable": True}}


def token(aud: str, iat: int, file: str = "prove.yml", **over) -> str:
    claims = dict(aud=aud, iat=iat, nbf=iat - 600, exp=iat + 300, jti=f"d{iat}", repository_id=REPO, repository_owner_id=OWNER,
                  job_workflow_ref=f"{WF_REPO}/.github/workflows/{file}@refs/tags/v0.3.12", job_workflow_sha=WF_SHA)
    claims.update(over)
    return sign_jwt(signing_key(), github_claims(**claims))


def token_file(tmp_path, wallet: Pubkey | None, spoil=lambda kind, jwt: jwt):
    """A token file as the release run captures one, signed by the test key: the rotate workflow naming that key, a
    maintainer's funding comment that spends the faucet, and the proof of the same bounty."""
    n = modulus(signing_key())
    rows = [("key", sign_jwt(signing_key(), attest_claims(oidc.GITHUB, n, iat=NOW + 50, nbf=NOW - 550, exp=NOW + 350, jti="a1")), None),
            ("fund", token(pay.fund_audience(ISSUE, 5 * USDC, pay.MERGE, TH, pay.faucet_balance_pda(OWNER)), NOW + 100, "fund.yml",
                           event_name="issue_comment", actor_id=MAINT), drills.TERMS.decode()),
            ("pay", token(pay.pay_audience(REPO, ISSUE, PAYEE, "a" * 40, TH, pay.MERGE, wallet), NOW + 400), None)]
    path = tmp_path / "tokens.jsonl"
    path.write_text("".join(json.dumps({"token": spoil(kind, jwt), "jwks": JWKS, **({"terms": terms} if terms else {}),
                                        "source": f"https://github.com/octo/widgets/issues/{ISSUE}"}) + "\n" for kind, jwt, terms in rows), encoding="utf-8")
    return path


def results(said: list[str]) -> dict[str, str]:
    return {line.split(" [")[0]: line.rsplit(": ", 1)[1] if line.endswith(": pass") else line.split("]: ", 1)[1] for line in said if " [" in line}


def test_the_bytes_drilled_are_the_ones_the_cluster_holds_and_the_hash_ignores_the_padding():
    rpc = Rpc()
    programs = drills.fetch("http://cluster", rpc)
    assert [p.name for p in programs] == ["knos_oidc", "knos_pay"]
    for p in programs:
        built = (FIX / BUILDS[p.name]).read_bytes()
        assert p.elf == built + bytes(4096)                              # exactly what the ProgramData account holds after its header
        assert p.sha256 == mc.elf_hash(built)                            # the hash solana-verify prints: trailing zeros trimmed
        assert (p.address, p.data, p.authority, p.slot) == (pay.IDS[p.name], str(mc.programdata_address(pay.IDS[p.name])), pay.IDS["upgrade_authority"], 4242)
    assert {m for m, _ in rpc.calls} == {"getAccountInfo"}
    assert {a for _, a in rpc.calls} == {pay.IDS[n] for n in BUILDS} | {str(mc.programdata_address(pay.IDS[n])) for n in BUILDS}


def test_a_program_the_cluster_does_not_hold_stops_the_run_in_words():
    rpc = Rpc()
    del rpc.accounts[pay.IDS["knos_pay"]]
    with pytest.raises(SystemExit, match="knos_pay .* is not an upgradeable program on http://cluster"):
        drills.fetch("http://cluster", rpc)
    rpc = Rpc()
    del rpc.accounts[str(mc.programdata_address(pay.IDS["knos_oidc"]))]
    with pytest.raises(SystemExit, match="the ProgramData account .* of knos_oidc is not on"):
        drills.fetch("http://cluster", rpc)


def test_every_drill_that_needs_no_token_passes_and_the_table_says_what_was_not_run(tmp_path):
    said, out = [], tmp_path / "DRILLS.md"
    assert drills.main(["--rpc", "http://cluster", "--out", str(out), "--now", str(NOW)], Rpc(), said.append) == 0
    got = results(said)
    assert [name for name, *_ in drills.DRILLS] + list(drills.UPGRADE) == list(got)
    assert [r for r in got.values() if r == "pass"] == ["pass"] * 6
    assert all(got[name].startswith("not run: it needs real GitHub tokens") for name, _how, needs, _f in drills.DRILLS if needs)
    doc = out.read_text(encoding="utf-8")
    for name in BUILDS:
        assert f"`{mc.elf_hash((FIX / BUILDS[name]).read_bytes())}`" in doc and pay.IDS[name] in doc
    for name, how, _needs, _f in drills.DRILLS:
        assert f"| {name} | {how} |" in doc
    assert all(got[name].startswith("not run: bash scripts/drill_upgrade.sh runs it") for name in drills.UPGRADE)
    assert "6 of 14 rows passed, 0 failed, 8 were not run." in doc and "python scripts/drills.py --rpc http://cluster\n" in doc
    assert doc.count("authority simulated") >= 4 and "held state written" in doc
    # a row that was not run is a failure only when the caller says every row must run
    assert drills.main(["--rpc", "http://cluster", "--out", str(out), "--now", str(NOW), "--strict"], Rpc(), said.append) == 1


@pytest.mark.parametrize("wallet", [Keypair.from_seed(bytes([9]) * 32).pubkey(), None], ids=["paid to the wallet the proof names", "held: the proof names no wallet"])
def test_with_a_token_file_and_the_upgrade_drills_log_every_row_runs(tmp_path, wallet):
    said, out, log = [], tmp_path / "DRILLS.md", tmp_path / "upgrade.log"
    tokens = token_file(tmp_path, wallet)
    log.write_text("".join(f"{name}\tproposal {i} of the upgrade multisig\tpass\n" for i, name in enumerate(drills.UPGRADE)), encoding="utf-8")
    args = ["--rpc", "http://cluster", "--out", str(out), "--tokens", str(tokens), "--strict"]
    assert drills.main(args, Rpc(), said.append) == 1                   # the upgrade drill was not run: with --strict that is a failure
    said.clear()
    assert drills.main([*args, "--upgrade-log", str(log)], Rpc(), said.append) == 0, said
    got = results(said)
    assert list(got.values()) == ["pass"] * 14, got
    line = next(s for s in said if s.startswith("a payment "))
    assert ("4.875 to the wallet the proof names and 0.125 to the fee account" in line) if wallet else (f"held for GitHub user {PAYEE}" in line)
    replay = next(s for s in said if s.startswith("a replay is refused "))
    assert "the pay token again: error 8" in replay and "the fund token again: error 91" in replay and "no money moved" in replay
    doc = out.read_text(encoding="utf-8")
    assert "14 of 14 rows passed, 0 failed, 0 were not run." in doc and f"This run read 3 tokens from `{tokens}`." in doc
    assert f"| a cancelled upgrade never runs | {drills.VOTED} | proposal 3 of the upgrade multisig | pass |" in doc
    assert f"python scripts/drills.py --rpc http://cluster --tokens {tokens} --upgrade-log {log}\n" in doc and f"KNOS_DRILL_LOG={log} bash scripts/drill_upgrade.sh --from-devnet\n" in doc


def test_a_row_that_fails_carries_the_exact_error_and_the_run_exits_1(tmp_path):
    def spoil(kind: str, jwt: str) -> str:      # the proof's signature with one character changed: nobody signed this
        head, body, sig = jwt.split(".")
        return jwt if kind != "pay" else f"{head}.{body}.{sig[:10]}{'A' if sig[10] != 'A' else 'B'}{sig[11:]}"
    said, out = [], tmp_path / "DRILLS.md"
    tokens = token_file(tmp_path, Keypair().pubkey(), spoil)
    assert drills.main(["--rpc", "http://cluster", "--out", str(out), "--tokens", str(tokens)], Rpc(), said.append) == 1
    got = results(said)
    assert got["a payment"] == "FAIL: the pay token of octo/widgets was refused: the signature is not the issuer's"
    assert got["a replay is refused"].startswith("FAIL: ") and got["a key is refreshed"] == "pass" and got["a token under a revoked key is refused"] == "pass"
    assert "| a payment | real GitHub tokens |  | FAIL: the pay token of octo/widgets was refused: the signature is not the issuer's |" in out.read_text(encoding="utf-8")
    assert said[-1].startswith("8 passed, 2 failed, 4 not run")


def test_the_upgrade_drills_log_is_read_line_by_line_and_a_step_it_lacks_was_not_run(tmp_path):
    log = tmp_path / "upgrade.log"
    log.write_text(f"{drills.UPGRADE[0]}\tproposal 1\tpass\n{drills.UPGRADE[1]}\tproposal 1\tpass\n", encoding="utf-8")
    rows = drills.upgrade_rows(log, lambda _line: None)
    assert [(r.name, r.result.split(":")[0]) for r in rows] == list(zip(drills.UPGRADE, ["pass", "pass", "not run", "not run"]))
    assert "stopped before it" in rows[2].result
    log.write_text("an upgrade nobody asked for\tx\tpass\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="line 1 of .* is not a line scripts/drill_upgrade.sh writes"):
        drills.upgrade_rows(log)


def test_a_token_file_with_a_line_that_is_not_a_token_stops_the_run_with_its_line_number(tmp_path):
    path = tmp_path / "tokens.jsonl"
    path.write_text(json.dumps({"token": token("x", NOW), "jwks": JWKS}) + "\n\n" + json.dumps({"token": "not a token", "jwks": JWKS}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"line 3 of .*tokens\.jsonl is not a captured token"):
        drills.corpus(path)
    path.write_text(json.dumps({"token": token("x", NOW)}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="line 1 of"):
        drills.corpus(path)


def test_an_unsigned_token_is_a_whole_token_that_no_key_signed():
    n = modulus(signing_key())
    jwt = drills.unsigned_token(n, "k", NOW, "t")
    head, body, sig = jwt.split(".")
    assert json.loads(base64.urlsafe_b64decode(head + "=="))["alg"] == "RS256"
    raw = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
    assert len(raw) == 256 and int.from_bytes(raw, "big") < n
    from knos.settle.v2 import relay
    assert not relay.signed(jwt, n)


def test_the_committed_table_has_a_row_for_every_drill_and_none_of_them_failed():
    """docs/DRILLS.md is written by the script from a run against devnet. A drill added to the script without a new run,
    a row that failed, or an upgrade row that does not come from the committed log shows up here."""
    docs = FIX.parents[1] / "docs"
    doc = (docs / "DRILLS.md").read_text(encoding="utf-8")
    rows = {line.split(" | ")[0][2:]: line for line in doc.splitlines() if line.startswith("| ") and line.count(" | ") == 3}
    assert [name for name in [n for n, *_ in drills.DRILLS] + list(drills.UPGRADE) if name not in rows] == []
    assert not [line for line in rows.values() if "FAIL" in line]
    assert all(rows[name].endswith("| pass |") for name, _how, needs, _f in drills.DRILLS if not needs)
    for p in BUILDS:
        assert pay.IDS[p] in doc
    logged = drills.upgrade_rows(docs / "drill_upgrade.log", lambda _line: None)
    assert all(f"| {r.name} | {r.how} | {r.checked} | {r.result} |" in doc for r in logged) and all(r.result == "pass" for r in logged)
