"""Put YOUR Solana program behind the upgrade gate. docs/GATE.md is the page; this is what it runs.

    python examples/upgrade_gate/adopt.py init --repo-id N --workflow OWNER/REPO/.github/workflows/FILE.yml --gate-id ADDRESS [--out DIR]
        Writes a gate program of your own into DIR (default: my_gate): this folder's crate with three lines changed
        (the program id, your repository's numeric id, your build workflow), the interface crate taken by tag, and
        gate-job.yml, the job your build workflow adds. No network. Nothing here is Knos's afterwards: you build it and
        deploy it with your own key.
    python examples/upgrade_gate/adopt.py expect --gate ADDRESS --program ADDRESS FILE.so
        The executable hash of a build, the audience your workflow asks GitHub to sign for it, and the address of the
        record your gate writes. No network.
    python examples/upgrade_gate/adopt.py record --gate ADDRESS --token-file FILE [--rpc URL]
        Carries one GitHub-signed token to the cluster: knos-oidc verifies the signature, then your gate writes the
        record. The fee payer is KNOS_RELAY_KEY (a key with a little SOL; it holds no power). A token is good for an
        hour past its expiry, so the job that asked for it runs this.
    python examples/upgrade_gate/adopt.py check --gate ADDRESS --program ADDRESS (--buffer ADDRESS | --multisig ADDRESS) [--rpc URL] [--json FILE]
        Before any vote. --buffer: does the gate hold a record for the bytes in this buffer? --multisig: the same
        question for every pending upgrade of the program in a Squads v4 multisig, with the time each can run.
        Exit 0 only when every build asked about is recorded; 1 otherwise; 2 when the cluster did not answer.
        --json writes what was found as a file a page can show (GATE.md has the banner that reads it).

The gate is two things that already exist and one you deploy: a Squads v4 multisig with a time lock holds your program's
upgrade authority (the delay); knos-oidc on devnet verifies GitHub's signature (nothing to deploy); your copy of this
program records which commit GitHub's runner built a given executable from. What it cannot do is in docs/GATE.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

SQUADS = "SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf"      # Squads v4, the same address on every cluster
WORKFLOW = re.compile(r"[\w.-]+/[\w.-]+/\.github/workflows/[\w.-]+\.ya?ml")
JOB = """\
# Add this job to {file} (the workflow that builds your program). It runs on main and on release tags only: the gate
# refuses a token from any other ref, from another workflow file, and from a runner that is not GitHub's.
  gate:
    needs: build                  # the job that uploads the .so you will propose, as the artifact "program"
    if: github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    permissions:
      id-token: write             # GitHub signs the statement
      contents: read
    steps:
      - uses: actions/checkout@{checkout}
        with: {{repository: drexthealpha/Knos, ref: {tag}, path: knos}}
      - uses: actions/download-artifact@{download}
        with: {{name: program, path: built}}
      - run: pip install ./knos
      - name: GitHub signs the hash of the build; the gate records it
        env:
          KNOS_RELAY_KEY: ${{{{ secrets.GATE_FEE_PAYER }}}}     # any key with a little devnet SOL: it pays fees and can do nothing else
          PROGRAM: YOUR_PROGRAM_ID
        run: |
          set -euo pipefail
          hash="$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read().rstrip(b"\\0")).hexdigest())' built/YOUR_PROGRAM.so)"
          curl -sSf -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=gate:$PROGRAM:$hash" \\
            | python3 -c 'import json, sys; print(json.load(sys.stdin)["value"])' > gate.jwt
          python3 knos/examples/upgrade_gate/adopt.py record --gate {gate} --token-file gate.jwt
"""


class Refused(Exception):
    """What is wrong and what to do, in one line. Exit 1."""


def _address(text: str, what: str) -> str:
    from solders.pubkey import Pubkey
    try:
        return str(Pubkey.from_string(text))
    except Exception:  # noqa: BLE001 - solders raises its own types
        raise Refused(f"{what} must be a Solana address, and {text!r} is not one.") from None


def _once(text: str, pattern: str, new: str, what: str) -> str:
    out, n = re.subn(pattern, lambda _m: new, text, flags=re.M)
    if n != 1:
        raise Refused(f"examples/upgrade_gate no longer has exactly one line for {what}: this script is older than the crate beside it.")
    return out


def tag() -> str:
    """The release tag the example's Cargo.toml tells an outside team to take the interface crate at."""
    found = re.search(r'tag = "(v\d+\.\d+\.\d+)"', (HERE / "Cargo.toml").read_text(encoding="utf-8"))
    if not found:
        raise Refused("examples/upgrade_gate/Cargo.toml no longer names a release tag for knos-oidc-interface.")
    return found.group(1)


def pin(action: str) -> str:
    """`<commit> # <tag>` for an action, as scripts/action_pins.json pins it: a moved tag cannot change what runs."""
    pins = json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"]
    name, sha = max((k, v) for k, v in pins.items() if k.startswith(action + "@"))
    return f"{sha} # {name.split('@')[1]}"


def init(repo_id: int, workflow: str, gate_id: str, out: Path) -> list[Path]:
    """Your gate: this crate with the program id, the repository and the workflow changed. Returns what was written."""
    if repo_id <= 0:
        raise Refused("--repo-id is your repository's number: gh api repos/OWNER/REPO --jq .id")
    if not WORKFLOW.fullmatch(workflow):
        raise Refused("--workflow is OWNER/REPO/.github/workflows/FILE.yml: the file that builds your program, with no @ref.")
    gate_id = _address(gate_id, "--gate-id")
    if out.exists() and any(out.iterdir()):
        raise Refused(f"{out} is not empty. Nothing was written.")
    rs = (HERE / "src" / "lib.rs").read_text(encoding="utf-8")
    rs = _once(rs, r'^solana_program::declare_id!\("[1-9A-HJ-NP-Za-km-z]+"\);$', f'solana_program::declare_id!("{gate_id}");', "the program id")
    rs = _once(rs, r"^pub const KNOS_REPO_ID: u64 = [\d_]+;$", f"pub const KNOS_REPO_ID: u64 = {repo_id};", "the repository id")
    rs = _once(rs, r'^pub const WORKFLOW: &\[u8\] = b"[^"]+";$', f'pub const WORKFLOW: &[u8] = b"{workflow}@";', "the workflow")
    toml = (HERE / "Cargo.toml").read_text(encoding="utf-8")
    toml = _once(toml, r"^knos-oidc-interface = \{ path = [^\n]+\}$",
                 f'knos-oidc-interface = {{ git = "https://github.com/drexthealpha/Knos", tag = "{tag()}" }}', "the interface crate")
    toml = "\n".join(line for line in toml.splitlines() if not line.startswith("# What an outside team writes")) + "\n"
    files = {out / "src" / "lib.rs": rs, out / "Cargo.toml": toml,
             out / "gate-job.yml": JOB.format(file=workflow.split("/", 2)[2], tag=tag(), gate=gate_id, checkout=pin("actions/checkout"),
                                                download=pin("actions/download-artifact"))}
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return list(files)


def expect(gate_id: str, program: str, so: bytes) -> dict:
    from solders.pubkey import Pubkey

    from knos.settle.v2 import gate
    h = gate.executable_hash(so)
    p = Pubkey.from_string(_address(program, "--program"))
    return {"executable_hash": h.hex(), "audience": gate.audience(p, h),
            "record": str(gate.record_pda(p, h, Pubkey.from_string(_address(gate_id, "--gate"))))}


def record(gate_id: str, jwt: str, ledger, payer, verify: Callable | None = None) -> dict:
    """knos-oidc verifies the token; then the gate at `gate_id` writes ["build", program, hash]. `verify` is
    knos.settle.v2.relay.verify_only unless a test passes its own."""
    import base64

    from solders.pubkey import Pubkey

    from knos.settle.v2 import gate, oidc
    g = Pubkey.from_string(_address(gate_id, "--gate"))
    try:
        claims = json.loads(base64.urlsafe_b64decode(jwt.split(".")[1] + "=="))
        kind, program, hexhash = str(claims["aud"]).split(":")
        p, h = Pubkey.from_string(program), bytes.fromhex(hexhash)
        assert kind == "gate" and len(h) == 32
    except Exception:  # noqa: BLE001 - anything that is not such a token is the same refusal
        raise Refused("this is not a token whose audience is gate:<program>:<executable hash>. Nothing was sent.") from None
    at = gate.record_pda(p, h, g)
    before = gate.read_record(ledger.account(at))
    if before is not None:
        return {"ok": True, "already": True, "record": str(at), "commit": before.sha, "run_id": before.run_id, "sigs": []}
    if verify is None:
        from knos.settle.v2 import relay
        verify = relay.verify_only
    v = verify(ledger, payer, jwt)
    if not v.get("ok"):
        raise Refused(f"knos-oidc did not verify the token: {v.get('why') or v.get('reason') or v}. Nothing was recorded.")
    token = Pubkey.from_string(v["account"])
    read = oidc.read_token(ledger.account(token))
    if read is None or not read.verified:
        raise Refused(f"the token account {token} is not verified to the end. Nothing was recorded.")
    key = read.key
    sig = ledger.send([gate.record_ix(payer.pubkey(), token, key, p, h, g)], payer)
    return {"ok": True, "record": str(at), "program": str(p), "hash": h.hex(), "sigs": [*v.get("sigs", []), str(sig)]}


def check(account: Callable, gate_id: str, program: str, buffer: str | None = None, multisig: str | None = None, squads: str = SQUADS) -> dict:
    """What the gate says about one buffer, or about every pending upgrade of `program` in `multisig`. `account(address)`
    gives (owner, data) or None, as knos.mainnet_check's reads do."""
    from solders.pubkey import Pubkey

    from knos import mainnet_check as mc
    from knos.settle.v2 import gate
    g, program = Pubkey.from_string(_address(gate_id, "--gate")), _address(program, "--program")
    out: dict = {"gate": str(g), "program": program, "entries": []}

    def one(buf: str, **more) -> None:
        said = gate.words(account, program, buf, g).lstrip("; ")
        out["entries"].append({"buffer": buf, "recorded": " is recorded by upgrade_gate" in said, "words": said, **more})
    if multisig:
        ms, why = mc.multisig_at(account, _address(multisig, "--multisig"), squads)
        if ms is None:
            raise Refused(f"the multisig could not be read ({why}).")
        out.update(multisig=multisig, time_lock=ms.time_lock, threshold=ms.threshold, members=len(ms.members))
        for p in mc.pending_proposals(account, multisig, ms, squads):
            if p.kind == "upgrade" and p.program == program and p.buffer:
                one(p.buffer, index=p.index, status=p.status, approved=p.approved, earliest_execution=p.executes_at)
    else:
        one(_address(buffer or "", "--buffer"))
    out["pending"] = len(out["entries"]) if multisig else None
    out["ok"] = all(e["recorded"] for e in out["entries"])
    return out


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Put your Solana program behind the upgrade gate (docs/GATE.md).")
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("init", help="write a gate program of your own, and the job your build workflow adds")
    a.add_argument("--repo-id", type=int, required=True, help="your repository's number: gh api repos/OWNER/REPO --jq .id")
    a.add_argument("--workflow", required=True, help="OWNER/REPO/.github/workflows/FILE.yml, the workflow that builds your program")
    a.add_argument("--gate-id", required=True, help="the address your gate will be deployed at: solana address -k gate.json")
    a.add_argument("--out", type=Path, default=Path("my_gate"))
    a = sub.add_parser("expect", help="the hash, audience and record address of one build (no network)")
    a.add_argument("--gate", required=True)
    a.add_argument("--program", required=True)
    a.add_argument("so", type=Path)
    a = sub.add_parser("record", help="carry one GitHub-signed token to the cluster and have the gate record it")
    a.add_argument("--gate", required=True)
    a.add_argument("--token-file", type=Path, required=True)
    a.add_argument("--rpc", default="https://api.devnet.solana.com")
    a = sub.add_parser("check", help="does the gate hold a record for a buffer, or for every pending upgrade of a multisig")
    a.add_argument("--gate", required=True)
    a.add_argument("--program", required=True)
    which = a.add_mutually_exclusive_group(required=True)
    which.add_argument("--buffer")
    which.add_argument("--multisig")
    a.add_argument("--rpc", default="https://api.devnet.solana.com")
    a.add_argument("--json", type=Path, help="also write what was found to this file")
    return ap


def main(argv: list[str] | None = None, say: Callable[[str], None] = print) -> int:
    o = parser().parse_args(argv)
    try:
        if o.command == "init":
            for path in init(o.repo_id, o.workflow, o.gate_id, o.out):
                say(f"wrote {path}")
            say(f"Next: cd {o.out} && cargo build-sbf && solana program deploy -u devnet --program-id gate.json target/deploy/upgrade_gate.so")
            return 0
        if o.command == "expect":
            for k, v in expect(o.gate, o.program, o.so.read_bytes()).items():
                say(f"{k}: {v}")
            return 0
        from knos import chain, mainnet_check as mc
        try:
            if o.command == "record":
                got = record(o.gate, o.token_file.read_text(encoding="utf-8").strip(), chain.Ledger(o.rpc), chain.key())
                say(json.dumps(got))
                return 0
            got = check(mc._rpc(o.rpc), o.gate, o.program, o.buffer, o.multisig)
        except (Refused, SystemExit):
            raise
        except Exception as why:  # noqa: BLE001 - no answer is not a refusal and not a pass
            say(f"stopped: {o.rpc} could not be read ({type(why).__name__}: {why}). Nothing is known; run it again.")
            return 2
        if o.json:
            o.json.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8", newline="\n")
        for e in got["entries"]:
            say(e["words"])
        if not got["entries"]:
            say("no upgrade of this program is pending in the multisig")
        return 0 if got["ok"] else 1
    except Refused as why:
        say(f"refused: {why}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
