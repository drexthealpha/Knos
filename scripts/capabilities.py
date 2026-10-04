"""What Knos can do, and how far each thing has got: docs/capabilities.json, checked and rendered.

    python scripts/capabilities.py check          every stage has its evidence, and every evidence item that can be
                                                  verified without a network is verified; exit 1 and say what is wrong
    python scripts/capabilities.py check --rpc    also ask devnet: the program is there and runs the version named,
                                                  and every exercised signature exists and succeeded (the release runs this)
    python scripts/capabilities.py render         write the summary between the markers in README.md and the table
                                                  between the markers in docs/*.md (docs/CAPABILITIES.md)
    python scripts/capabilities.py render --check exit 1 when a table is not what the manifest says

A capability's `stage` is the highest of five that has evidence, and each stage needs the ones below it:

    implemented   {"path", "names"}: a source file of this repository, and words in it that are the capability
    tested        {"test", "names"}: a test file (pytest's, Node's, or a Rust crate's tests/*.rs), and words in it that
                  name the capability
    deployed      {"program", "id", "version"}: the program of programs-v2/program_ids.json at that address, and the
                  on-chain version that carries the capability. A capability with no program stops at `tested`
    exercised     {"signature"}: a transaction on devnet that used it and succeeded
    reproduced    {"url"}: someone else's run, linked from a document of this repository

`stage: null` is a capability this tree does not hold yet: it has no evidence and the table says "not built".
Evidence above the stated stage is refused as well: the stage would then not be the highest. An exercised signature
that is not in docs/ is left empty here and filled by the release.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/capabilities.json"
FULL = "docs/CAPABILITIES.md"      # the whole table; README.md carries the summary
STAGES = ("implemented", "tested", "deployed", "exercised", "reproduced")
WORDS = {None: "not built", "implemented": "implemented", "tested": "tested locally", "deployed": "deployed on devnet",
         "exercised": "exercised on devnet", "reproduced": "reproduced by someone else"}
START, END = "<!-- capabilities:start -->", "<!-- capabilities:end -->"
DEVNET = "https://api.devnet.solana.com"
_ID = re.compile(r"[a-z][a-z0-9_]*")
_SIG = re.compile(r"[1-9A-HJ-NP-Za-km-z]{86,88}")
_ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def load(root: Path = ROOT) -> dict:
    return json.loads((root / MANIFEST).read_text(encoding="utf-8"))


def _file(root: Path, rel, names) -> str | None:
    """Why `rel` is not evidence: it is not a file of this repository, or it does not hold the words `names`."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in Path(rel).parts or not (root / rel).is_file():
        return f"{rel!r} is not a file of this repository"
    if not isinstance(names, str) or len(names) < 3:
        return f"{rel} needs `names`: words in the file that are this capability"
    return None if names in (root / rel).read_text(encoding="utf-8", errors="replace") else f"{rel} does not say {names!r}"


def _is_test(rel: str) -> bool:
    """A test file by its name: pytest's (test_*.py), Node's (*.test.mjs), or a Rust integration test (tests/*.rs in a crate)."""
    p = Path(rel)
    return p.name.startswith(("test_", "test.")) or ".test." in rel or (p.suffix == ".rs" and p.parent.name == "tests")


def _linked(root: Path, url: str) -> bool:
    return any(url in doc.read_text(encoding="utf-8", errors="replace") for doc in [root / "README.md", *sorted((root / "docs").glob("*.md"))] if doc.is_file())


def problems(data: dict, root: Path = ROOT) -> list[str]:
    """Everything wrong with the manifest that can be seen without a network, one line each."""
    out, seen = [], set()
    if list(data.get("stages") or []) != list(STAGES):
        out.append(f"`stages` must be {list(STAGES)}")
    ids = json.loads((root / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    programs = data.get("programs") or {}
    for name, p in programs.items():
        if ids.get(name, p.get("id")) != p.get("id") or not _ADDRESS.fullmatch(str(p.get("id", ""))):
            out.append(f"programs.{name}: the address is not the one of programs-v2/program_ids.json")
        if not p.get("on_chain"):
            out.append(f"programs.{name}: `on_chain` (the version devnet runs) is missing")
    for c in data.get("capabilities") or []:
        cid = c.get("id")
        say = lambda text: out.append(f"{cid}: {text}")       # noqa: E731
        if not isinstance(cid, str) or not _ID.fullmatch(cid) or cid in seen:
            say("an id is lowercase words joined by _, and is used once")
        seen.add(cid)
        what = c.get("what")
        if not isinstance(what, str) or not what.endswith(".") or what.count(". ") or len(what) > 240:
            say("`what` is one plain sentence")
        stage, ev = c.get("stage"), c.get("evidence")
        if stage is not None and stage not in STAGES or not isinstance(ev, dict) or set(ev) - set(STAGES):
            say(f"`stage` is one of {list(STAGES)} or null, and `evidence` has one object per stage reached")
            continue
        reached = STAGES[:STAGES.index(stage) + 1] if stage else ()
        for s in STAGES:
            e = ev.get(s)
            if s not in reached:
                if e:
                    say(f"has {s} evidence but says stage {stage}: the stage is the highest with evidence")
                continue
            if not isinstance(e, dict) or not e:
                say(f"stage {stage} without {s} evidence")
                continue
            if s == "implemented" and (why := _file(root, e.get("path"), e.get("names"))):
                say(f"implemented: {why}")
            if s == "tested" and (why := _file(root, e.get("test"), e.get("names"))):
                say(f"tested: {why}")
            if s == "tested" and not _is_test(str(e.get("test"))):
                say(f"tested: {e.get('test')} is not a test file")
            if s == "deployed":
                p = programs.get(e.get("program"))
                if not p or e.get("id") != p["id"]:
                    say("deployed: the program and its address are not ones `programs` lists")
                elif e.get("version") not in p.get("versions", []):
                    say(f"deployed: {e.get('version')!r} is not a version of {e['program']}")
                elif p["versions"].index(e["version"]) > p["versions"].index(p["on_chain"]):
                    say(f"deployed: {e['program']} {e['version']} carries it, and devnet runs {p['on_chain']}")
            if s == "exercised" and not _SIG.fullmatch(str(e.get("signature", ""))):
                say("exercised: a transaction signature on devnet is needed")
            if s == "reproduced" and not (str(e.get("url", "")).startswith("https://") and _linked(root, e["url"])):
                say("reproduced: a link to someone else's run that a document of this repository gives")
    if not seen:
        out.append("no capability is listed")
    return out


# ---- the chain -------------------------------------------------------------------------------------------------------
def _rpc(url: str, method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "knos-capabilities"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - the RPC the caller named
        got = json.load(r)
    if "error" in got:
        raise OSError(str(got["error"])[:200])
    return got["result"]


def pay_version(url: str, program: str, payer: str, rpc=_rpc) -> str:
    """knos_pay's version, asked of the program itself: 2.1 answers the Version instruction (it logs
    `knos2:version 1`), 2.0 refuses it. Simulated, so nothing is sent and nothing is paid."""
    import base64
    from solders.hash import Hash
    from solders.instruction import Instruction
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction
    tx = Transaction.new_unsigned(Message.new_with_blockhash([Instruction(Pubkey.from_string(program), b"\x0c", [])], Pubkey.from_string(payer), Hash.default()))
    got = rpc(url, "simulateTransaction", [base64.b64encode(bytes(tx)).decode(), {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True}])["value"]
    logs = " ".join(got.get("logs") or [])
    if "knos2:version 1" in logs:
        return "2.1"
    if got.get("err") and f"Program {program} invoke" in logs:        # the program ran and refused the instruction
        return "2.0"
    raise OSError(f"the simulation did not reach the program: {got.get('err')}")


def chain_problems(data: dict, url: str = DEVNET, rpc=_rpc, root: Path = ROOT) -> list[str]:
    """What devnet says against the manifest: a program that is not there, a version it does not run, a signature
    that does not exist or failed. A program whose version cannot be asked (only knos_pay answers; knos_oidc is
    upgraded in the same proposal) is held to being there."""
    out = []
    used = {c["evidence"]["deployed"]["program"] for c in data["capabilities"] if c.get("evidence", {}).get("deployed")}
    payer = json.loads((root / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))["fee_owner"]
    for name in sorted(used):
        p = data["programs"][name]
        try:
            info = rpc(url, "getAccountInfo", [p["id"], {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])["value"]
            if not info or not info.get("executable"):
                out.append(f"{name}: no program at {p['id']} on devnet")
            elif name == "knos_pay" and (runs := pay_version(url, p["id"], payer, rpc)) != p["on_chain"]:
                out.append(f"knos_pay: devnet runs {runs}, the manifest says {p['on_chain']}: move `on_chain`, then the stages that waited for it")
        except OSError as e:
            out.append(f"{name}: devnet did not answer ({e})")
    sigs = {c["evidence"]["exercised"]["signature"]: c["id"] for c in data["capabilities"] if c.get("evidence", {}).get("exercised")}
    for at in range(0, len(sigs), 100):
        batch = list(sigs)[at:at + 100]
        try:
            got = rpc(url, "getSignatureStatuses", [batch, {"searchTransactionHistory": True}])["value"]
        except OSError as e:
            out.append(f"exercised: devnet did not answer ({e})")
            continue
        for sig, status in zip(batch, got):
            if status is None or status.get("err") is not None:
                out.append(f"{sigs[sig]}: the transaction {sig[:12]}... " + ("is not on devnet" if status is None else "failed"))
    return out


# ---- the table -------------------------------------------------------------------------------------------------------
def _evidence(c: dict) -> str:
    ev, stage = c["evidence"], c["stage"]
    if stage is None:
        return c.get("note", "")
    said = [f"[`{ev['implemented']['path']}`]({ev['implemented']['path']})"]
    if "tested" in ev:
        said.append(f"[`{ev['tested']['test']}`]({ev['tested']['test']})")
    if "deployed" in ev:
        said.append(f"`{ev['deployed']['program']} {ev['deployed']['version']}`")
    if "exercised" in ev:
        sig = ev["exercised"]["signature"]
        said.append(f"[{sig[:8]}...](https://explorer.solana.com/tx/{sig}?cluster=devnet)")
    if "reproduced" in ev:
        said.append(f"[outside run]({ev['reproduced']['url']})")
    return ", ".join(said) + (f". {c['note']}" if c.get("note") else "")


def table(data: dict, prefix: str = "") -> str:
    """The manifest as a Markdown table. `prefix` leads from the document to the repository's root ("../" in docs/)."""
    lines = ["| capability | stage | evidence |", "|---|---|---|"]
    for c in data["capabilities"]:
        lines.append(f"| {c['what']} | {WORDS[c['stage']]} | {_evidence(c)} |".replace("](", "](" + prefix).replace("](" + prefix + "https://", "](https://"))
    # no count is printed: the rows are the count, and a number in README.md needs a fact in docs/facts.json
    lines += ["", "Each stage needs evidence and the stages below it: a source file, a test, the on-chain version that carries it, a devnet "
              f"transaction, someone else's run. The list is [`{MANIFEST}`]({prefix}{MANIFEST}); `python scripts/capabilities.py check` holds it "
              "to the files, and `check --rpc` to devnet."]
    return "\n".join(lines)


def summary(data: dict) -> str:
    """The manifest in one paragraph, for README.md (which a test keeps short): the ids at each stage, highest first,
    and where the table with the evidence is."""
    said = []
    for s in (*reversed(STAGES), None):
        ids = [f"`{c['id']}`" for c in data["capabilities"] if c["stage"] == s]
        said.append(f"**{WORDS[s].capitalize()}:** {', '.join(ids) if ids else 'none recorded yet'}.")
    return (f"**Every capability and how far it has got** ([the table with the evidence]({FULL}), from [`{MANIFEST}`]({MANIFEST}); a stage needs "
            "its evidence and the stages below it). " + " ".join(said))


def targets(root: Path = ROOT) -> list[Path]:
    return [p for p in [root / "README.md", *sorted((root / "docs").glob("*.md"))] if p.is_file() and START in p.read_text(encoding="utf-8")]


def rendered(text: str, body: str) -> str:
    a, b = text.index(START) + len(START), text.index(END)
    return text[:a] + "\n" + body + "\n" + text[b:]


def render(root: Path = ROOT, check: bool = False) -> list[str]:
    """Write the table into every document that has the markers. Returns the documents that were (or, with `check`,
    would be) changed."""
    data, changed = load(root), []
    for doc in targets(root):
        old = doc.read_text(encoding="utf-8")
        new = rendered(old, summary(data) if doc.parent == root else table(data, "../"))
        if new != old:
            changed.append(doc.relative_to(root).as_posix())
            if not check:
                doc.write_text(new, encoding="utf-8")
    return changed


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["check"]:
        data = load()
        wrong = problems(data)
        if "--rpc" in argv and not wrong:
            wrong += chain_problems(data, os.environ.get("KNOS_RPC") or DEVNET)
        for line in wrong:
            print("capabilities: " + line)
        if not wrong:
            print(f"capabilities: {len(data['capabilities'])} entries hold" + (" (devnet asked)" if "--rpc" in argv else " (offline: deployed and exercised are not asked of the chain)"))
        return 1 if wrong else 0
    if argv[:1] == ["render"]:
        changed = render(check="--check" in argv)
        for doc in changed:
            print(f"capabilities: {doc} " + ("is not what the manifest says: run `python scripts/capabilities.py render`" if "--check" in argv else "written"))
        return 1 if changed and "--check" in argv else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
