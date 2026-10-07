"""What Knos can do, and how far each thing has got: docs/capabilities.json, checked and rendered.

    python scripts/capabilities.py check          every stage has its evidence, and every evidence item that can be
                                                  verified without a network is verified; exit 1 and say what is wrong
    python scripts/capabilities.py check --rpc    also ask devnet: the program is there and runs the version named,
                                                  and every exercised signature exists and succeeded (the release runs this)
    python scripts/capabilities.py render         write the summary between the markers in README.md and the table
                                                  between the markers in docs/*.md (docs/CAPABILITIES.md)
    python scripts/capabilities.py render --check exit 1 when a table is not what the manifest says
    python scripts/capabilities.py reproduction [--live] FILE... [--own FILE...]
                                                  check reproductions someone sent (a pull request's files, as data):
                                                  GitHub's signature, the report's hash, that the run is not Knos's own,
                                                  that no check failed; --live reads GitHub's keys as they are now
    python scripts/capabilities.py keys           add the keys GitHub publishes now to scripts/github_oidc_keys.json

A capability's `stage` is the highest of five that has evidence, and each stage needs the ones below it:

    implemented   {"path", "names"}: a source file of this repository, and words in it that are the capability
    tested        {"test", "names"}: a test file (pytest's, Node's, the site's tests/web/*.mjs, or a Rust crate's
                  tests/*.rs), and words in it that
                  name the capability
    deployed      {"program", "id", "version"}: a PUBLIC program id (`public_ids`: the `knos_*` addresses of
                  programs-v2/program_ids.json, and upgrade_gate's own `declare_id!`), and the on-chain version there
                  that carries the capability. A capability with no program stops at `tested`
    exercised     {"signature"}: a transaction on devnet, at that public program id, that used it and succeeded. An
                  `ids` field, if given, must say `public`. scripts/exercise_public.py record adds what the run
                  checked (`asserted`) and the refusals it saw (`refusals`: transactions that landed and failed with
                  the error named, which `check --rpc` asks devnet about as well)
    reproduced    {"file"}: a file of reproductions/ (the report of `knos reproduce` and the token GitHub signed for it in
                  someone else's repository, docs/REPRODUCE.md) in which a check that supports this capability passed.
                  The signature is checked here with the archived key (scripts/github_oidc_keys.json); `check --rpc`
                  also asks GitHub whether it still publishes that key. A link alone is not evidence

A deployment of a build at an address of its own (a staging deployment, such as the 0.3.14 rehearsal's) is never
evidence for `deployed` or `exercised`, and `programs` lists no such address: what ran there is said in the
capability's note, with its transaction, and the capability stays `tested` until it runs at a public id.

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
# said after the stages in README.md: a stage above `tested` is a run at a public program id, and a staging run is not one
PUBLIC_ONLY = ("Deployed and exercised are counted only at the public program ids; what the 0.3.14 rehearsal ran at staging "
               "addresses of its own is in the note of each capability it ran, with its transaction.")
GATE = "examples/upgrade_gate/src/lib.rs"     # upgrade_gate is an example program: its public id is its own declare_id!
START, END = "<!-- capabilities:start -->", "<!-- capabilities:end -->"
DEVNET = "https://api.devnet.solana.com"
_ID = re.compile(r"[a-z][a-z0-9_]*")
_SIG = re.compile(r"[1-9A-HJ-NP-Za-km-z]{86,88}")
_ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def load(root: Path = ROOT) -> dict:
    return json.loads((root / MANIFEST).read_text(encoding="utf-8"))


def public_ids(root: Path = ROOT) -> dict[str, str]:
    """The public program ids, by name: the `knos_*` addresses of programs-v2/program_ids.json and upgrade_gate's own
    `declare_id!`. Nothing else is evidence for `deployed` or `exercised`."""
    ids = json.loads((root / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    out = {k: v for k, v in ids.items() if k.startswith("knos_") and isinstance(v, str)}
    gate = root / GATE
    if gate.is_file() and (m := re.search(r'declare_id!\("([1-9A-HJ-NP-Za-km-z]{32,44})"\)', gate.read_text(encoding="utf-8"))):
        out["upgrade_gate"] = m.group(1)
    return out


def ids_of(c: dict, root: Path = ROOT) -> str | None:
    """Where an exercised capability ran: "public" when its deployed evidence is a public program id at its address,
    "staging" for any other address (which `problems` refuses), "unknown" with no deployed evidence. None for a
    capability that is not exercised. The deployed evidence decides, never a word of a document."""
    ev = c.get("evidence") or {}
    if not ev.get("exercised"):
        return None
    dep = ev.get("deployed") or {}
    if not dep.get("program"):
        return "unknown"
    return "public" if public_ids(root).get(str(dep["program"])) == dep.get("id") else "staging"


def _file(root: Path, rel, names) -> str | None:
    """Why `rel` is not evidence: it is not a file of this repository, or it does not hold the words `names`."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in Path(rel).parts or not (root / rel).is_file():
        return f"{rel!r} is not a file of this repository"
    if not isinstance(names, str) or len(names) < 3:
        return f"{rel} needs `names`: words in the file that are this capability"
    return None if names in (root / rel).read_text(encoding="utf-8", errors="replace") else f"{rel} does not say {names!r}"


def _is_test(rel: str) -> bool:
    """A test file by its name: pytest's (test_*.py), Node's (*.test.mjs, or a script of tests/web/, which holds nothing
    but the site's tests), or a Rust integration test (tests/*.rs in a crate)."""
    p = Path(rel)
    return (p.name.startswith(("test_", "test.")) or ".test." in rel or (p.suffix == ".rs" and p.parent.name == "tests")
            or (p.suffix == ".mjs" and p.parent.as_posix() == "tests/web"))


# ---- reproductions: someone else's run, signed by GitHub in their repository ------------------------------------------
REPRODUCTIONS = "reproductions"
KEYS = "scripts/github_oidc_keys.json"          # GitHub's keys as archived: what a signature is checked against with no network
OWN = "scripts/own_github_ids.json"
NOTHING = {"passed": [], "failed": [], "capabilities": []}


def _reproduce():
    """knos.reproduce from this tree (standard library only until a check runs, so a bare Python can verify)."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from knos import reproduce
    return reproduce


def archived_keys(root: Path = ROOT) -> dict[str, int]:
    path = root / KEYS
    return _reproduce().keys_of(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}


def reproduction(path: Path, keys: dict[str, int], ours: bool = False) -> tuple[dict, list[str]]:
    """(what GitHub signed and what passed, what is wrong) for one file sent as a reproduction. `ours`: the file is one
    of reproductions/own/: a run of Knos's own, which must be Knos's own and counts for nothing."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as why:
        return dict(NOTHING), [f"not JSON ({why})"]
    return _reproduce().verified(doc, keys, json.loads((ROOT / OWN).read_text(encoding="utf-8")), path.name, ours=ours)


def reproductions(root: Path = ROOT, keys: dict[str, int] | None = None) -> tuple[dict[str, dict], list[str]]:
    """({file: what it proves} for every valid file of reproductions/, one line for each that is not valid)."""
    keys = archived_keys(root) if keys is None else keys
    held, wrong = {}, []
    for path in sorted((root / REPRODUCTIONS).glob("*.json")) if (root / REPRODUCTIONS).is_dir() else []:
        rel = path.relative_to(root).as_posix()
        facts, bad = reproduction(path, keys)
        if bad:
            wrong.extend(f"{rel}: {line}" for line in bad)
        else:
            held[rel] = facts
    return held, wrong


def key_problems(root: Path = ROOT, fetch=None) -> list[str]:
    """The live key check: a key that signed a reproduction, where GitHub still publishes its id, is the key GitHub
    publishes. A key GitHub has rotated out cannot be asked about: the archive is then the only record of it."""
    held, _ = reproductions(root)
    used = {str(f["kid"]) for f in held.values()}
    if not used:
        return []
    rp, kept = _reproduce(), archived_keys(root)
    try:
        live = rp.keys_of((fetch or rp._fetch_json)(rp.JWKS))
    except (OSError, ValueError) as why:
        return [f"reproduced: GitHub's keys could not be read ({why})"]
    return [f"reproduced: GitHub publishes another key under {kid} than {KEYS} holds" for kid in sorted(used) if kid in live and live[kid] != kept.get(kid)]


def problems(data: dict, root: Path = ROOT) -> list[str]:
    """Everything wrong with the manifest that can be seen without a network, one line each."""
    out, seen = [], set()
    outside, invalid = reproductions(root)
    out += [f"{line}: it does not belong in {REPRODUCTIONS}/" for line in invalid]
    rp = _reproduce()       # Knos's own runs (reproductions/own/): held to GitHub's signature like anyone's, and counted for nothing
    out += [f"{line}: it does not belong in {REPRODUCTIONS}/{rp.OWN_DIR}/" for line in rp.own_runs(root, archived_keys(root), json.loads((ROOT / OWN).read_text(encoding="utf-8")))[1]]
    if list(data.get("stages") or []) != list(STAGES):
        out.append(f"`stages` must be {list(STAGES)}")
    public = public_ids(root)
    programs = data.get("programs") or {}
    for name, p in programs.items():
        if name not in public:
            out.append(f"programs.{name}: not a public program (programs-v2/program_ids.json, or {GATE}): a staging "
                       "deployment is never evidence; say what ran there in the capability's note")
        elif public[name] != p.get("id") or not _ADDRESS.fullmatch(str(p.get("id", ""))):
            out.append(f"programs.{name}: the address is not its public program id {public[name]}")
        if not p.get("on_chain") or p.get("on_chain") not in (p.get("versions") or []):
            out.append(f"programs.{name}: `on_chain` (the version devnet runs) is missing, or not one of its `versions`")
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
                if public.get(str(e.get("program"))) != e.get("id"):
                    say(f"deployed: {e.get('program')} {e.get('id')} is not a public program id: a staging deployment is never "
                        f"evidence for {stage}; the capability stays `tested`, and its note says what ran there")
                elif not p or e.get("id") != p["id"]:
                    say("deployed: the program and its address are not ones `programs` lists")
                elif e.get("version") not in p.get("versions", []):
                    say(f"deployed: {e.get('version')!r} is not a version of {e['program']}")
                elif p["versions"].index(e["version"]) > p["versions"].index(p["on_chain"]):
                    say(f"deployed: {e['program']} {e['version']} carries it, and devnet runs {p['on_chain']}")
            if s == "exercised" and not _SIG.fullmatch(str(e.get("signature", ""))):
                say("exercised: a transaction signature on devnet is needed")
            if s == "exercised" and ids_of(c, root) != "public":
                say(f"exercised: the transaction ran on {ids_of(c, root)} program ids; only a run at a public program id is `exercised`")
            if s == "exercised" and e.get("ids") not in (None, "public"):
                say(f"exercised: `ids` says {e.get('ids')!r}; only `public` is evidence")
            if s == "reproduced":
                run = outside.get(str(e.get("file")))
                if run is None:
                    say(f"reproduced: a link to someone else's run is not evidence: name a `file` of {REPRODUCTIONS}/ that GitHub signed in their repository")
                elif cid not in run["capabilities"]:
                    say(f"reproduced: no check that supports it passed in {e['file']} (it supports {', '.join(run['capabilities']) or 'nothing'})")
                elif e.get("url", run["run"]) != run["run"]:
                    say(f"reproduced: the run of {e['file']} is {run['run']}")
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
    # a refusal kept beside an exercised transaction: on devnet, and failed with the program's error it names
    refused = {r["signature"]: (c["id"], r.get("error")) for c in data["capabilities"] for r in (c.get("evidence", {}).get("exercised") or {}).get("refusals", [])}
    for at in range(0, len(refused), 100):
        batch = list(refused)[at:at + 100]
        try:
            got = rpc(url, "getSignatureStatuses", [batch, {"searchTransactionHistory": True}])["value"]
        except OSError as e:
            out.append(f"exercised: devnet did not answer ({e})")
            continue
        for sig, status in zip(batch, got):
            cid, error = refused[sig]
            if status is None or f"'Custom': {error}" not in str(status.get("err")):
                out.append(f"{cid}: the refusal {sig[:12]}... " + ("is not on devnet" if status is None else f"did not fail with error {error}"))
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
        said.append(f"[outside run]({ev['reproduced']['url']})" if ev["reproduced"].get("url") else f"[`{ev['reproduced']['file']}`]({ev['reproduced']['file']})")
    return ", ".join(said) + (f". {c['note']}" if c.get("note") else "")


def table(data: dict, prefix: str = "") -> str:
    """The manifest as a Markdown table. `prefix` leads from the document to the repository's root ("../" in docs/)."""
    lines = ["| capability | stage | evidence |", "|---|---|---|"]
    for c in data["capabilities"]:
        lines.append(f"| {c['what']} | {WORDS[c['stage']]} | {_evidence(c)} |".replace("](", "](" + prefix).replace("](" + prefix + "https://", "](https://"))
    # no count is printed: the rows are the count, and a number in README.md needs a fact in docs/facts.json
    lines += ["", "Each stage needs evidence and the stages below it: a source file, a test, the on-chain version that carries it, a devnet "
              f"transaction, someone else's run. The list is [`{MANIFEST}`]({prefix}{MANIFEST}); `python scripts/capabilities.py check` holds it "
              "to the files, and `check --rpc` to devnet.", "", PUBLIC_ONLY]
    return "\n".join(lines)


def summary(data: dict) -> str:
    """The manifest in one short paragraph, for README.md: the ids at the stages above `tested`, highest first (a run
    at a public program id, or someone else's), and where the table with every capability and its evidence is."""
    said = []
    for s in reversed(STAGES[2:]):
        ids = [f"`{c['id']}`" for c in data["capabilities"] if c["stage"] == s]
        said.append(f"**{WORDS[s].capitalize()}:** {', '.join(ids) if ids else 'none recorded yet'}.")
    return (" ".join(said) + f" Everything else is tested locally, implemented or not built: [the table with the evidence]({FULL}) has "
            f"one row for each capability, from [`{MANIFEST}`]({MANIFEST}). " + PUBLIC_ONLY)


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
                doc.write_text(new, encoding="utf-8", newline="")
    return changed


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["check"]:
        data = load()
        wrong = problems(data)
        if "--rpc" in argv and not wrong:
            wrong += chain_problems(data, os.environ.get("KNOS_RPC") or DEVNET) + key_problems()
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
    if argv[:1] == ["reproduction"]:
        rest = [a for a in argv[1:] if a != "--live"]
        cut = rest.index("--own") if "--own" in rest else len(rest)      # after --own: files of reproductions/own/ (Knos's own runs)
        return sent([Path(a) for a in rest[:cut]], "--live" in argv, own=[Path(a) for a in rest[cut + 1:]])
    if argv[:1] == ["keys"]:
        rp, path = _reproduce(), ROOT / KEYS
        doc = json.loads(path.read_text(encoding="utf-8"))
        have = {k["kid"] for k in doc["keys"]}
        new = [k for k in rp._fetch_json(rp.JWKS)["keys"] if k.get("kid") not in have]        # added, never removed: an old signature stays checkable
        doc["keys"] += new
        path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="")
        print(f"capabilities: {KEYS} holds {len(doc['keys'])} keys ({len(new)} added)")
        return 0
    print(__doc__)
    return 2


def sent(paths: list[Path], live: bool = False, say=print, fetch=None, root: Path = ROOT, own: list[Path] | None = None) -> int:
    """`reproduction FILE... [--own FILE...]`: what a pull request's files are worth, in Markdown for the run's page.
    Exit 1 unless every file is a valid outside reproduction with no failed check and at least one that passed, and
    every file after --own (reproductions/own/) a valid run of Knos's own, which counts for nothing. Files are read as data."""
    own = list(own or [])
    rp = _reproduce()
    kept = archived_keys(root)
    keys = dict(kept)
    if live:
        try:
            keys.update(rp.keys_of((fetch or rp._fetch_json)(rp.JWKS)))
        except (OSError, ValueError) as why:
            say(f"GitHub's keys could not be read ({why}); the archived keys were used.")
    bad = not paths and not own
    for path in own:
        facts, wrong = reproduction(path, keys, ours=True)
        if not wrong and facts["failed"]:
            wrong = [f"the check `{c}` failed in this run" for c in facts["failed"]]
        if not wrong and not facts["passed"]:
            wrong = ["no check passed in this run (every one was skipped)"]
        if wrong:
            bad = True
            say(f"**{rp.OWN_DIR}/{path.name}: not accepted.** " + "; ".join(wrong) + ".")
            continue
        say(f"**{rp.OWN_DIR}/{path.name}: a valid run of Knos's own.** GitHub signed report `{facts['report_sha256'][:16]}...` for [this run]({facts['run']}) of "
            f"`{facts['repository']}`. Passed: {', '.join(facts['passed'])}. It is not a reproduction, is not counted and supports no capability.")
    if not paths and not own:
        say(f"No file was given: a reproduction adds one JSON file under {REPRODUCTIONS}/.")
    for path in paths:
        facts, wrong = reproduction(path, keys)
        if not wrong and facts["failed"]:
            wrong = [f"the check `{c}` failed in this run: that is a bug report, not a reproduction, so open an issue with the report" for c in facts["failed"]]
        if not wrong and not facts["passed"]:
            wrong = ["no check passed in this run (every one was skipped)"]
        if wrong:
            bad = True
            say(f"**{path.name}: not accepted.** " + "; ".join(wrong) + ".")
            continue
        say(f"**{path.name}: a valid outside reproduction.** GitHub signed report `{facts['report_sha256'][:16]}...` for [this run]({facts['run']}) of "
            f"`{facts['repository']}` (owner id {facts['repository_owner_id']}, started by id {facts['actor_id']}; workflow `{facts['workflow_ref']}`). "
            f"Passed: {', '.join(facts['passed'])}. It supports: {', '.join(facts['capabilities'])}."
            + ("" if str(facts["kid"]) in kept else f" Its key {facts['kid']} is GitHub's now and not yet in {KEYS}: run `python scripts/capabilities.py keys` when merging."))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
