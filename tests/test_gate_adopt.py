"""The upgrade gate for another team's program (docs/GATE.md, examples/upgrade_gate/adopt.py): the commands the page
gives exist and parse; `init` writes this repository's gate with exactly three lines changed; `record` and `check`
work against the gate program in LiteSVM; the adopters' list is empty and says how to add a row. And the registry plan
of scripts/release.py: what would be published where, with no network. Nothing here opens a network connection."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE_DOC = (ROOT / "docs" / "GATE.md").read_text(encoding="utf-8")
ME = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"        # an address that is nobody's: the page's placeholders stand for one


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


adopt = _load("gate_adopt", ROOT / "examples" / "upgrade_gate" / "adopt.py")
release = _load("release_for_gate", ROOT / "scripts" / "release.py")


def commands(text: str) -> list[str]:
    """Every command line of the page: the lines of its bash blocks, and what stands in backticks in its prose."""
    blocks = [line.strip() for block in re.findall(r"```bash\n(.*?)```", text, flags=re.S) for line in block.splitlines() if line.strip()]
    inline = [part.strip() for code in re.findall(r"`([^`\n]+)`", text) for part in code.split(" && ")]
    return blocks + inline


def test_every_command_the_page_gives_exists_and_parses():
    lines = commands(GATE_DOC)
    ours = [c for c in lines if c.startswith("python examples/upgrade_gate/adopt.py ")]
    assert {c.split()[2] for c in ours} == {"init", "expect", "check"}, ours
    p = adopt.parser()
    for c in ours:
        argv = [ME if re.fullmatch(r"[A-Z_]+_ADDRESS", a) else a for a in c.split()[2:]]
        got = p.parse_args(argv)                                  # argparse exits 2 on a flag or a command that does not exist
        assert got.command == argv[0]
    # the three numbered commands, in order: make the gate, hand over the authority, check before a vote
    three = re.findall(r"(?m)^\*\*(\d)\. [^\n]+\n\n```bash\n([^\n]+)\n```", GATE_DOC)
    assert [n for n, _ in three] == ["1", "2", "3"]
    assert [c.split()[2] for _, c in three] == ["init", "set-upgrade-authority", "check"]
    # the Solana commands and their flags are the ones scripts/deploy_v2.sh itself runs
    deploy = (ROOT / "scripts" / "deploy_v2.sh").read_text(encoding="utf-8")
    solana = [c for c in lines if c.startswith("solana program ")]
    assert {c.split()[2] for c in solana} == {"set-upgrade-authority", "write-buffer", "set-buffer-authority", "deploy"}
    for c in solana:
        assert f"program {c.split()[2]} " in deploy, c
        for flag in re.findall(r"--[a-z-]+", c):
            assert flag in deploy or flag == "--program-id" or flag == "-u", (c, flag)
    assert "--program-id" in (ROOT / "examples" / "reader_template" / "README.md").read_text(encoding="utf-8")
    # what the page says Knos runs for itself is in those scripts' own usage
    mjs = (ROOT / "scripts" / "governance.mjs").read_text(encoding="utf-8")
    assert "bash scripts/deploy_v2.sh --propose" in lines and "--propose [--replace] [--ungated]" in deploy
    assert "node scripts/governance.mjs upgrade execute <index>" in lines and "governance.mjs upgrade execute <index>" in mjs
    assert "timeLock: WHICH[name].timeLock" in mjs and "timeLock: 172_800" in mjs and "172,800 s, 48 hours" in GATE_DOC
    # the three scripts the page links to, and the test it names, are files
    for rel in re.findall(r"\]\(\.\./([^)#]+)\)", GATE_DOC):
        assert (ROOT / rel).exists(), rel


def test_init_writes_this_gate_with_three_lines_changed_and_refuses_what_is_not_an_adopter(tmp_path):
    out = tmp_path / "my_gate"
    said: list[str] = []
    assert adopt.main(["init", "--repo-id", "123456789", "--workflow", "acme/vault/.github/workflows/build.yml", "--gate-id", ME, "--out", str(out)], said.append) == 0
    here = ROOT / "examples" / "upgrade_gate"
    old, new = (here / "src" / "lib.rs").read_text(encoding="utf-8").splitlines(), (out / "src" / "lib.rs").read_text(encoding="utf-8").splitlines()
    changed = [(a, b) for a, b in zip(old, new, strict=True) if a != b]
    assert [b for _a, b in changed] == [f'solana_program::declare_id!("{ME}");', "pub const KNOS_REPO_ID: u64 = 123456789;",
                                        'pub const WORKFLOW: &[u8] = b"acme/vault/.github/workflows/build.yml@";']
    toml = (out / "Cargo.toml").read_text(encoding="utf-8")
    assert f'knos-oidc-interface = {{ git = "https://github.com/drexthealpha/Knos", tag = "{adopt.tag()}" }}' in toml and "path =" not in toml
    job = (out / "gate-job.yml").read_text(encoding="utf-8")
    assert "id-token: write" in job and "audience=gate:$PROGRAM:$hash" in job and f"adopt.py record --gate {ME} --token-file gate.jwt" in job
    assert f"ref: {adopt.tag()}" in job and ".github/workflows/build.yml" in job
    pins = json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"]
    used = re.findall(r"uses: ([\w/-]+)@([0-9a-f]{40})", job)
    assert [a for a, _ in used] == ["actions/checkout", "actions/download-artifact"] and job.count("uses:") == 2
    for action, sha in used:
        assert sha in [v for k, v in pins.items() if k.startswith(action + "@")], action
    assert said[-1].startswith("Next: cd ") and "cargo build-sbf" in said[-1]
    # nothing is written over, and a workflow with a ref, a repository name for an id, or a bad address is refused in words
    for argv in (["--repo-id", "1", "--workflow", "acme/vault/.github/workflows/build.yml", "--gate-id", ME, "--out", str(out)],
                 ["--repo-id", "1", "--workflow", "acme/vault/.github/workflows/build.yml@refs/heads/main", "--gate-id", ME],
                 ["--repo-id", "0", "--workflow", "acme/vault/.github/workflows/build.yml", "--gate-id", ME],
                 ["--repo-id", "1", "--workflow", "acme/vault/.github/workflows/build.yml", "--gate-id", "not-an-address"]):
        said.clear()
        assert adopt.main(["init", *argv, *([] if "--out" in argv else ["--out", str(tmp_path / "other")])], said.append) == 1
        assert said and said[0].startswith("refused: ") and not (tmp_path / "other").exists()


def test_record_and_check_against_the_gate_program():
    pytest.importorskip("solders.litesvm")
    from solders.account import Account
    from solders.pubkey import Pubkey

    from _pay2 import ChainLedger
    from _settle import sign_jwt, signing_key
    from test_upgrade_gate import COMMIT, ELF, HASH, PROGRAM, Gate

    from knos.settle.v2 import gate, oidc, pay
    from _pay2 import github_claims

    c = Gate()
    ledger = ChainLedger(c)
    g = str(gate.GATE_ID)
    want = adopt.expect(g, str(PROGRAM), ELF + bytes(32))          # trailing zeros do not count
    assert want == {"executable_hash": HASH.hex(), "audience": f"gate:{PROGRAM}:{HASH.hex()}", "record": str(gate.record_pda(PROGRAM, HASH))}
    buffer, vault = Pubkey.from_bytes(hashlib.sha256(b"buffer").digest()), Pubkey.from_bytes(hashlib.sha256(b"vault").digest())
    loader = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")
    c.svm.set_account(buffer, Account(lamports=10 ** 9, data=(1).to_bytes(4, "little") + b"\x01" + bytes(vault) + ELF, owner=loader, executable=False))
    before = adopt.check(c.account, g, str(PROGRAM), buffer=str(buffer))
    assert before["ok"] is False and before["entries"][0]["recorded"] is False and "NOT recorded" in before["entries"][0]["words"]
    # the token program.yml's gate job asks GitHub for; `verify` stands for knos.settle.v2.relay.verify_only
    now = c.now()
    jwt = sign_jwt(signing_key(), github_claims(aud=want["audience"], iat=now, nbf=now - 600, exp=now + 300, jti="adopt-1", sha=COMMIT,
                                               job_workflow_ref="drexthealpha/Knos/.github/workflows/program.yml@refs/heads/main", job_workflow_sha=COMMIT,
                                               repository_id=gate.KNOS_REPO_ID, repository="drexthealpha/Knos", ref="refs/heads/main", run_id=77))
    verify = lambda _ledger, payer, token: {"ok": True, "account": str(c.verify(token, oidc.GITHUB, c.github, payer)), "sigs": ["v1"]}  # noqa: E731
    got = adopt.record(g, jwt, ledger, c.payer, verify)
    assert got["ok"] and got["record"] == want["record"] and got["hash"] == HASH.hex() and got["sigs"][0] == "v1" and len(got["sigs"]) == 2
    rec = gate.read_record(c.data(gate.record_pda(PROGRAM, HASH)))
    assert rec is not None and (rec.sha, rec.run_id, rec.program) == (COMMIT, 77, PROGRAM)
    again = adopt.record(g, jwt, ledger, c.payer, verify)           # done before: nothing is sent
    assert again == {"ok": True, "already": True, "record": want["record"], "commit": COMMIT, "run_id": 77, "sigs": []}
    after = adopt.check(c.account, g, str(PROGRAM), buffer=str(buffer))
    assert after["ok"] is True and COMMIT in after["entries"][0]["words"]
    # the record is of one program under one gate: another program, or a gate that is not this one, has none
    assert adopt.check(c.account, g, str(pay.PAY_ID if PROGRAM != pay.PAY_ID else oidc.OIDC_ID), buffer=str(buffer))["ok"] is False
    assert adopt.check(c.account, ME, str(PROGRAM), buffer=str(buffer))["ok"] is False
    # a token that is not a gate token, and one knos-oidc refused, record nothing and say so
    other = sign_jwt(signing_key(), github_claims(aud="knos3:x:y", iat=now, exp=now + 300))
    with pytest.raises(adopt.Refused, match="gate:<program>:<executable hash>"):
        adopt.record(g, other, ledger, c.payer, verify)
    fresh = hashlib.sha256(b"another build").digest()
    unsigned = sign_jwt(signing_key(), github_claims(aud=f"gate:{PROGRAM}:{fresh.hex()}", iat=now, exp=now + 300))
    with pytest.raises(adopt.Refused, match="did not verify"):
        adopt.record(g, unsigned, ledger, c.payer, lambda *_: {"ok": False, "why": "token expired"})
    assert c.data(gate.record_pda(PROGRAM, fresh)) is None


def test_check_reads_every_pending_upgrade_of_a_multisig_as_devnet_held_them():
    """The multisig accounts recorded from devnet for the site's tests: what `check --multisig` says of each pending upgrade."""
    from knos import mainnet_check as mc
    from knos.settle.v2 import gate
    doc = json.loads((ROOT / "tests" / "web" / "recorded" / "squads_upgrades.json").read_text(encoding="utf-8"))
    accounts = doc["accounts"]
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))

    def account(address: str):
        a = accounts.get(address)
        return (a["owner"], bytes.fromhex(a["data"])) if a else None
    ms, _ = mc.multisig_at(account, ids["upgrade_multisig"], ids["squads_program"])
    assert ms is not None
    pending = [p for p in mc.pending_proposals(account, ids["upgrade_multisig"], ms, ids["squads_program"]) if p.kind == "upgrade"]
    assert [(p.index, p.status) for p in pending] == [(5, "Draft"), (4, "Approved"), (3, "Active")]
    for name, index, at in (("knos_oidc", 3, None), ("knos_pay", 4, 1790154800)):
        got = adopt.check(account, str(gate.GATE_ID), ids[name], multisig=ids["upgrade_multisig"])
        assert got["time_lock"] == ms.time_lock == 172_800 and got["threshold"] == 2 and got["pending"] == 1
        assert [(e["index"], e["earliest_execution"], e["recorded"]) for e in got["entries"]] == [(index, at, False)]
        assert got["ok"] is False                   # the recording holds no buffer: nothing vouches for these bytes
    none = adopt.check(account, str(gate.GATE_ID), ids["knos_meter"], multisig=ids["upgrade_multisig"])
    assert none["entries"] == [] and none["pending"] == 0 and none["ok"] is True
    with pytest.raises(adopt.Refused, match="could not be read"):
        adopt.check(account, str(gate.GATE_ID), ids["knos_pay"], multisig=ME)


def test_the_adopters_list_is_empty_and_the_pages_point_at_each_other():
    compose = (ROOT / "docs" / "COMPOSE.md").read_text(encoding="utf-8")
    part = compose.split("## Who uses the upgrade gate")[1].split("\n## ")[0]
    rows = [r for r in re.findall(r"(?m)^\|(.+)\|$", part) if not set(r) <= set("|- ")]
    assert len(rows) == 2 and rows[1].split("|")[0].strip() == "none yet"          # the header and no adopter
    assert "outside this repository behind the upgrade gate: 0." in part and "open a pull request that adds one row" in part
    assert "(GATE.md)" in part and "time lock above zero" in part
    gov = (ROOT / "docs" / "GOVERNANCE.md").read_text(encoding="utf-8")
    use = gov.split("## Use the gate")[1].split("\n## ")[0]
    assert "(GATE.md)" in use and "Teams that have done it: 0" in use
    assert 'Adopters today: 0 ([COMPOSE.md](COMPOSE.md), "Who uses the upgrade gate")' in GATE_DOC
    assert "| [GATE.md](GATE.md) |" in (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    # the two things the page says the gate has shown are in the files it cites
    feed = json.loads((ROOT / "web" / "upgrades.json").read_text(encoding="utf-8"))
    late = [e["since"] - e["earliest_execution"] for e in feed["entries"] if e["index"] in (3, 4, 5, 6)]
    assert len(late) == 4 and all(e > 5 * 3600 for e in late) and max(late) < 5.5 * 3600 and "about five hours" in GATE_DOC
    assert "withdrawn before it could run" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## 0.3.14")[1].split("\n## ")[0]
    # no word the project does not use for itself
    for word in ("trustless", "bulletproof", "immutable", "audited"):
        assert word not in GATE_DOC.lower()


def test_the_registry_plan_says_what_would_be_published_where_and_publishes_nothing(tmp_path):
    calls: list[list[str]] = []

    def run(cmd, **kw):
        calls.append(list(cmd))
        out = json.dumps([{"files": [{"path": "index.js"}, {"path": "README.md"}]}]) if cmd[0] == "npm" else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="    Packaged 9 files, 91.4KiB (24.8KiB compressed)\n" if cmd[0] == "cargo" else "")
    code, lines = release.registry_overview(run=run)
    text = "\n".join(lines)
    assert code == 0 and lines[0].endswith("Nothing is published by this command.") and lines[-1].startswith("ready:")
    held = release.held("knos-oidc-interface")
    assert held == "0.3.14" and f"knos-oidc-interface {held} -> crates.io" in text and f"knos-pay-interface {held} -> crates.io" in text
    sdk = json.loads((ROOT / "sdk" / "settle" / "package.json").read_text(encoding="utf-8"))
    assert f"knos-settle {sdk['version']} -> npm (moves with the release)" in text
    # what ran packs and never uploads; no network was asked for a name, and the plan says who is
    assert [c[:2] for c in calls] == [["cargo", "package"], ["cargo", "package"], ["npm", "pack"]]
    assert all("--offline" in c and ("--dry-run" in c or "--no-verify" in c) for c in calls) and not any("publish" in c for c in calls)
    assert text.count("not asked here (no network)") == 3 and "cargo owner --list knos-pay-interface" in text and "npm owner ls knos-settle" in text
    # --online: a free name, a name that has the version, and a registry that does not answer
    index = {"knos-oidc-interface": None, "knos-pay-interface": b'{"vers": "0.3.14"}\n', "knos-settle": json.dumps({"versions": {"0.3.1": {}}}).encode()}
    code, lines = release.registry_overview(online=True, fetch=lambda url: index[url.rsplit("/", 1)[1]], run=run)
    text = "\n".join(lines)
    assert code == 0 and "free on crates.io: the first version is published by hand" in text
    assert "0.3.14 is already there, nothing to publish" in text and "on npm with 0.3.1: check that it is ours" in text

    def down(_url):
        raise OSError("no route")
    code, lines = release.registry_overview(online=True, fetch=down, run=run)
    assert code == 1 and lines[-1].startswith("NOT ready") and "did not answer" in "\n".join(lines)
    # a package that does not pack, or a README that points inside the repository, is red
    code, lines = release.registry_overview(run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 101, stdout="", stderr="error: no such crate\n"))
    assert code == 1 and "pack    FAILED" in "\n".join(lines)
    assert release.relative_links("[a](../../docs/OIDC.md) [b](https://x.test/y) [c](#here) ![d](img.png)") == ["../../docs/OIDC.md", "img.png"]
    for registry, name in release.PACKAGES:
        assert release.relative_links((release.package_dir(registry, name) / "README.md").read_text(encoding="utf-8")) == [], name
    # the one-package question release.yml asks is unchanged, and the bare command is the plan
    assert release.registry_plan("crates", "knos-pay-interface", "v9.9.9", held, fetch=lambda _u: None)[0] == 0
    compose = (ROOT / "docs" / "COMPOSE.md").read_text(encoding="utf-8").split("## Install from a registry")[1].split("\n## ")[0]
    assert "not published" not in compose.lower() and "https://crates.io/crates/knos-oidc-interface" in compose and "python scripts/release.py registry-plan" in compose
    assert f'knos-oidc-interface = "{held}"' in compose and f'knos-pay-interface = "{held}"' in compose and "npm install knos-settle" in compose
