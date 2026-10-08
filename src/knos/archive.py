"""Evidence that outlives Knos: `knos archive make | verify | compare | policy`.

A Merkle root proves that a line is among the lines put under it. It cannot bring back evidence nobody kept, and it
cannot say that something was left out. So the evidence is kept by more than one holder, in a form that needs nothing
of Knos to be read again:

    make      one .zip, the same bytes whoever builds it from the same files: the log of events and each month's
              statement of it, the ledgers, the signed tokens (each under the SHA-256 of its bytes), receipts,
              statements for accounts payable, close records, the terms (each under its hash), the issuer's keys the
              tokens name with the day they were read, a manifest of hashes, and `verify.py`.
    verify    runs that `verify.py` (knos.standalone_verify: one file, the standard library only, no `knos` import,
              no network). A holder runs the copy inside the archive: `python verify.py`. Nothing else is needed.
    compare   two holders' archives: the same evidence (one root) or, by name, what differs, and how the two logs
              stand to each other (one continues the other, or they part at a line).
    policy    a retention policy (the one `knos vault retain` reads: keep N years, then delete or keep the hashes)
              set against archives: what is due. An archive a still-open month or dispute needs is held, whatever
              its age. Nothing is deleted here: the report is for the person who does.

No archive is written that its own verifier does not pass. What a root proves and does not, and who keeps what, is in
docs/RETENTION.md.
"""
from __future__ import annotations

import datetime
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from . import standalone_verify as V
from .ledger import Bad, canon

TYPE, VERSION = V.TYPE, V.VERSION
YEAR_DAYS = 365                     # a year of a retention policy, as knos.vault counts it
PARTIES_TO_CLOSE = 2                # a month is closed once this many parties have acknowledged a head that covers it
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
README = """This is a Knos evidence archive.

To check it, with Python 3.8 or later and nothing else:

    python verify.py

It opens no connection and needs no Knos. It reads the files beside it and says what it checked, what it can only
note, and what does not hold. MANIFEST.json lists every file with its SHA-256; its evidence_root is the one hash two
holders compare to know they hold the same evidence.
"""


def verifier() -> bytes:
    """The stand-alone verifier's own bytes: the file every archive carries (conformance/standalone/verify.py is the same file)."""
    return Path(V.__file__).with_suffix(".py").read_bytes()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _named(folder: str, given: dict[str, bytes]) -> dict[str, bytes]:
    for name in given:
        if not _NAME.fullmatch(name):
            raise Bad(f"{name!r} cannot be a file's name in an archive: letters, digits, dots, dashes and underscores, at most 100")
    return {f"{folder}/{name}": raw for name, raw in given.items()}


def _kid(token: str) -> object:
    try:
        return json.loads(V.unb64(token.strip().split(".")[0])).get("kid")
    except Exception:  # noqa: BLE001 - not a token: the verifier says so, in words
        return None


def files_of(events: bytes | None = None, ledgers: dict[str, bytes] | None = None, statements: dict[str, bytes] | None = None, tokens: list[str] | tuple = (),
             receipts: dict[str, bytes] | None = None, terms: list[bytes] | tuple = (), closes: dict[str, bytes] | None = None, others: dict[str, bytes] | None = None,
             jwks: dict | None = None, keys_read: str = "", keys_from: str = "", sealed: str = "") -> dict[str, bytes]:
    """Every file of an archive, by name. `events`: the log's bytes. `ledgers`, `statements`, `receipts`, `closes`,
    `others`: file name -> bytes. `tokens`: signed tokens. `terms`: each terms file's bytes, kept under their SHA-256.
    `jwks`: the issuer's keys; the ones a token of the archive names are kept, with `keys_read` (the day they were
    read, YYYY-MM-DD) and `keys_from` (where from). `sealed`: the day the archive is made, for a retention policy."""
    from . import events as E
    for day, what in ((sealed, "the day the archive is sealed"), (keys_read, "the day the keys were read")):
        if day:
            try:
                datetime.date.fromisoformat(day)
            except ValueError:
                raise Bad(f"{what} is written YYYY-MM-DD, not {day!r}") from None
    if not sealed:
        raise Bad("an archive names the day it is sealed (YYYY-MM-DD): a retention policy counts from it")
    files: dict[str, bytes] = {}
    kept = [t.strip() for t in tokens]
    head = None
    if events is not None:
        try:
            log, wrong = E.read(events.decode("utf-8"), jwks)
        except UnicodeDecodeError:
            raise Bad("the events log is not text") from None
        if wrong:
            raise Bad("the events log does not check, so it is not archived as evidence. " + wrong[0])
        files["events/log.jsonl"] = events
        head = log.head
        for m in sorted(log.by_month):
            files[f"statements/events-{m}.json"] = (canon(E.statement(log, m)) + "\n").encode()
        acks = [(log.events[n].ack or {})["token"] for n in log.acks]
    else:
        acks = []
    if any(name.startswith("events-") for name in statements or {}):
        raise Bad("a statement named events-... is one the archive makes itself from the log: give yours another name")
    for folder, given in (("ledgers", ledgers), ("statements", statements), ("receipts", receipts), ("closes", closes), ("other", others)):
        files.update(_named(folder, given or {}))
    files.update({f"tokens/{_sha(t.encode())}.jwt": (t + "\n").encode() for t in kept})
    files.update({f"terms/{_sha(raw)}.json": raw for raw in terms})
    kids = {_kid(t) for t in (*kept, *acks)}
    used = sorted((k for k in (jwks or {}).get("keys", []) if isinstance(k, dict) and k.get("kid") in kids), key=canon)
    keys = None
    if used:
        if not keys_read:
            raise Bad("say the day the issuer's keys were read (YYYY-MM-DD): an archive keeps the keys with that day")
        files["keys/jwks.json"] = (canon({"keys": used}) + "\n").encode()
        keys = {"from": keys_from, "read": keys_read, "sha256": _sha(files["keys/jwks.json"])}
    files["verify.py"], files["README.txt"] = verifier(), README.encode()
    listed = {name: _sha(raw) for name, raw in sorted(files.items())}
    manifest = {"type": TYPE, "version": VERSION, "sealed": sealed, "head": head, "keys": keys, "files": listed, "evidence_root": V.evidence_root(listed),
                "evidence_files": sum(1 for n in listed if n not in V.NOT_EVIDENCE)}
    return {**files, "MANIFEST.json": (canon(manifest) + "\n").encode()}


def pack(files: dict[str, bytes]) -> bytes:
    """One form only: names in order, no compression, one date (1 Jan 1980, the earliest a zip can say), one mode, so
    the same files are the same bytes on every machine and with every zlib."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type, info.create_system, info.external_attr = zipfile.ZIP_STORED, 3, 0o644 << 16
            z.writestr(info, raw)
    return out.getvalue()


def make(**given) -> bytes:
    """The archive's bytes (see `files_of` for what is given). Raises Bad with the first thing its own verifier does
    not accept: nothing is written that would not verify once Knos is gone."""
    files = files_of(**given)
    _done, _notes, problems = V.check(files)
    if problems:
        raise Bad("this evidence does not verify, so no archive is made of it. " + problems[0])
    return pack(files)


def read(path: Path) -> dict[str, bytes]:
    """name -> bytes of an archive, packed or unpacked."""
    try:
        return V.files_of(str(path))
    except (OSError, zipfile.BadZipFile) as why:
        raise Bad(f"cannot read {path} as an archive: {why}") from None


def manifest_of(files: dict[str, bytes]) -> dict:
    try:
        m = json.loads(files["MANIFEST.json"])
        assert m["type"] == TYPE and m["version"] == VERSION and isinstance(m["files"], dict)
    except Exception:  # noqa: BLE001 - missing, not JSON, or not a manifest: one sentence either way
        raise Bad("this is not a Knos evidence archive, version 1") from None
    return m


# -- two holders ----------------------------------------------------------------------------------------------------------
def compare(a: dict[str, bytes], b: dict[str, bytes]) -> dict:
    """Whether two holders hold the same evidence, by root, and by name what differs. Each side is hashed again from
    its own bytes: a manifest's word is not taken. The verifier and the README are not evidence and are not compared."""
    la, lb = ({n: _sha(raw) for n, raw in f.items() if n not in V.NOT_EVIDENCE} for f in (a, b))
    ra, rb = V.evidence_root(la), V.evidence_root(lb)
    out: dict = {"same": ra == rb, "root": {"a": ra, "b": rb}, "only_a": sorted(set(la) - set(lb)), "only_b": sorted(set(lb) - set(la)),
                 "differ": sorted(n for n in set(la) & set(lb) if la[n] != lb[n]), "log": ""}
    name = "events/log.jsonl"
    if name in out["differ"]:
        xa, xb = (f[name].decode("utf-8", "replace").split("\n") for f in (a, b))
        xa, xb = [x for x in xa if x], [x for x in xb if x]
        n = next((i for i, (p, q) in enumerate(zip(xa, xb)) if p != q), min(len(xa), len(xb)))
        if n == len(xa) or n == len(xb):
            longer, shorter, more = ("B", "A", len(xb) - n) if n == len(xa) else ("A", "B", len(xa) - n)
            out["log"] = f"{longer}'s log is {shorter}'s log and {more} more lines: {shorter} is behind, or lines were cut from the end of its log."
        else:
            out["log"] = f"The two logs are the same up to line {n - 1} and part at line {n}: one of them was rewritten from there."
        # each month's statement of the log names the log's head, so it differs whenever the log does: not a finding of its own
        out["follow_from_the_log"] = [x for x in out["differ"] + out["only_a"] + out["only_b"] if x.startswith("statements/events-")]
        for key in ("differ", "only_a", "only_b"):
            out[key] = [x for x in out[key] if not x.startswith("statements/events-")]
    return out


def compare_said(c: dict) -> list[str]:
    if c["same"]:
        return [f"The same evidence: both hold the root {c['root']['a']}."]
    said = [f"Not the same evidence: A holds the root {c['root']['a']}, B holds {c['root']['b']}."]
    said += [f"Only A holds {n}." for n in c["only_a"]] + [f"Only B holds {n}." for n in c["only_b"]] + [f"{n} differs." for n in c["differ"]]
    return said + ([c["log"]] if c["log"] else [])


# -- a retention policy -----------------------------------------------------------------------------------------------------
def holds(files: dict[str, bytes]) -> list[str]:
    """Why this archive is still needed, whatever its age: a month nobody closed, a missing number, a dispute. An
    archive that cannot be read as one, or that does not verify, is held too: a person reads it first."""
    from . import events as E
    _done, _notes, problems = V.check(files)
    if problems:
        return ["it does not verify: " + problems[0]]
    said: list[str] = []
    if "events/log.jsonl" in files:
        jwks = json.loads(files["keys/jwks.json"]) if "keys/jwks.json" in files else None
        log, _wrong = E.read(files["events/log.jsonl"].decode("utf-8"), jwks)
        for m in sorted(log.by_month):
            st = E.statement(log, m)
            if len(st["acknowledged"]["covers_month"]) < PARTIES_TO_CLOSE:
                said.append(f"{m} is open: {len(st['acknowledged']['covers_month'])} of {PARTIES_TO_CLOSE} parties have acknowledged a head that covers it")
            if st["line_states"]["disputed"]:
                said.append(f"{m} has {st['line_states']['disputed']} invoice lines in dispute")
            said += [f"{m}: {x}" for x in E.close_problems(log, m)[:1]]
        open_ = sorted(d for d in log.by_deliverable if log.verdict_of(d)[0] == "disputed")
        if open_:
            said.append(f"{len(open_)} deliverables are disputed and not resolved (first: {open_[0]})")
    for name in sorted(n for n in files if n.startswith("closes/")):
        try:
            if json.loads(files[name]).get("state") == "disputed":
                said.append(f"{name} is a close record in dispute")
        except ValueError:
            pass
    return said


def policy(rules: dict, archives: dict[str, dict[str, bytes]], today: str) -> list[dict]:
    """What a retention policy asks of each archive, oldest first: {"archive", "sealed", "age_days", "action", "why",
    "evidence_root"}. `action`: `keep` (not due), `held` (due, and a still-open month or dispute needs it), or what
    the policy says is done after its years: `delete` or `hashes` (the manifest stays, the evidence goes). Nothing is
    touched: this reports."""
    from . import vault
    try:
        rules, now = vault.policy_of(rules), datetime.date.fromisoformat(today)
    except ValueError as err:
        raise Bad(str(err)) from None
    out: list[dict] = []
    for name, files in archives.items():
        try:
            m = manifest_of(files)
            age = (now - datetime.date.fromisoformat(str(m.get("sealed")))).days
        except (Bad, ValueError):
            out.append({"archive": name, "sealed": None, "age_days": None, "action": "held", "why": ["it is not an archive with a day it was sealed: read it first"],
                        "evidence_root": None})
            continue
        due, why = age > rules["keep_years"] * YEAR_DAYS, holds(files)
        out.append({"archive": name, "sealed": m["sealed"], "age_days": age, "action": "keep" if not due else "held" if why else rules["then"],
                    "why": why if due else [], "evidence_root": m.get("evidence_root")})
    return sorted(out, key=lambda r: (-(r["age_days"] if r["age_days"] is not None else 10 ** 9), r["archive"]))


# -- the command line -------------------------------------------------------------------------------------------------------
def register(app, help_lines: list | None = None) -> None:
    """`knos archive make | verify | compare | policy`, on the main app. `help_lines`: cli._HELP."""
    import importlib
    typer = importlib.import_module("typer")

    archive = typer.Typer(add_completion=False, no_args_is_help=True,
                          help="Evidence that outlives Knos: one archive with its own verifier, compared between holders, kept by a policy.")
    app.add_typer(archive, name="archive")
    if help_lines is not None:
        help_lines.append(("archive", "For money", "Evidence that outlives Knos: make, verify with no Knos, compare two holders, retention policy."))

    def stop(said: str, fix: str = ""):
        from . import cli
        return cli.Stop(said, fix)

    def by_name(paths: list[Path] | None) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for p in paths or []:
            if p.name in out:
                raise stop(f"Two files are named {p.name}: an archive keeps each under its own name.")
            try:
                out[p.name] = p.read_bytes()
            except OSError:
                raise stop(f"Cannot read {p}.") from None
        return out

    @archive.command("make")
    def make_(out: Path = typer.Argument(..., help="the .zip to write"),
              events: Path = typer.Option(None, "--events", help="the log of events (knos events)"),
              ledger: list[Path] = typer.Option(None, "--ledger", help="a meter ledger file (repeat)"),
              statement: list[Path] = typer.Option(None, "--statement", help="a statement (knos statement make, knos meter statement --json) (repeat)"),
              token: list[Path] = typer.Option(None, "--token", help="a signed token: a batch's, a close's (repeat)"),
              receipt: list[Path] = typer.Option(None, "--receipt", help="a receipt (repeat)"),
              terms: list[Path] = typer.Option(None, "--terms", help="a terms file, kept under its hash (repeat)"),
              close: list[Path] = typer.Option(None, "--close", help="a close record (knos meter close) (repeat)"),
              other: list[Path] = typer.Option(None, "--other", help="anything else to keep, checked by hash only (repeat)"),
              keys: Path = typer.Option(None, "--keys", help="the issuer's keys (a JWKS file); default: <events log>.jwks.json"),
              keys_read: str = typer.Option("", "--keys-read", metavar="YYYY-MM-DD", help="the day those keys were read from the issuer"),
              keys_from: str = typer.Option("", "--keys-from", help="where they were read from (the issuer's JWKS address)"),
              sealed: str = typer.Option("", "--sealed", metavar="YYYY-MM-DD", help="the day the archive is made; default: today")) -> None:
        """Write one archive of the evidence, with the file that checks it when Knos is gone. Refused when the evidence does not verify."""
        if events is None and not ledger:
            raise stop("Give --events, --ledger, or both: an archive holds evidence.")
        jwks_path = keys or (events.with_name(events.name + ".jwks.json") if events is not None else None)
        jwks = None
        try:
            if jwks_path is not None and (keys is not None or jwks_path.exists()):
                jwks = json.loads(jwks_path.read_text(encoding="utf-8"))
            blob = make(events=events.read_bytes() if events is not None else None, ledgers=by_name(ledger), statements=by_name(statement),
                        tokens=[p.read_text(encoding="ascii") for p in token or []], receipts=by_name(receipt), terms=[p.read_bytes() for p in terms or []],
                        closes=by_name(close), others=by_name(other), jwks=jwks, keys_read=keys_read, keys_from=keys_from,
                        sealed=sealed or datetime.date.today().isoformat())
        except (OSError, ValueError) as why:
            raise stop(str(why)) from None
        out.write_bytes(blob)
        m = manifest_of(read(out))
        typer.echo(f"{out}: {m['evidence_files']} evidence files, root {m['evidence_root']}. Check it anywhere: unzip, then `python verify.py`.")

    @archive.command("verify")
    def verify_(path: Path = typer.Argument(..., help="an archive (.zip) or a folder it was unpacked into"),
                strict: bool = typer.Option(False, "--strict", help="also fail on what is only noted")) -> None:
        """Check an archive with the stand-alone verifier. The copy inside the archive does the same with no Knos installed."""
        raise typer.Exit(V.main([str(path), *(["--strict"] if strict else [])]))

    @archive.command("compare")
    def compare_(a: Path = typer.Argument(..., help="one holder's archive"), b: Path = typer.Argument(..., help="another holder's"),
                 as_json: bool = typer.Option(False, "--json", help="print JSON")) -> None:
        """Say whether two holders hold the same evidence (one root), and name what differs. Exit 1 when they differ."""
        try:
            c = compare(read(a), read(b))
        except Bad as why:
            raise stop(str(why)) from None
        typer.echo(json.dumps(c, indent=1, sort_keys=True) if as_json else "\n".join(compare_said(c)))
        raise typer.Exit(0 if c["same"] else 1)

    @archive.command("policy")
    def policy_(rules: Path = typer.Argument(..., help="a retention policy (examples/private/retention.json)"),
                archives: list[Path] = typer.Argument(..., help="the archives to set it against"),
                today: str = typer.Option("", "--today", metavar="YYYY-MM-DD", help="the day to count ages to; default: today"),
                as_json: bool = typer.Option(False, "--json", help="print JSON")) -> None:
        """Report what a retention policy makes due. An archive a still-open month or dispute needs is held. Nothing is deleted."""
        try:
            got = policy(json.loads(rules.read_text(encoding="utf-8")), {str(p): read(p) for p in archives}, today or datetime.date.today().isoformat())
        except (OSError, ValueError) as why:
            raise stop(f"{why}") from None
        if as_json:
            typer.echo(json.dumps(got, indent=1, sort_keys=True))
            return
        words = {"keep": "keep: not due", "held": "HELD: due, and still needed", "delete": "due: delete", "hashes": "due: remove the evidence, keep the manifest's hashes"}
        for r in got:
            typer.echo(f"{r['archive']}: sealed {r['sealed']}, {r['age_days']} days old. {words[r['action']]}" + ("".join(f"\n    {w}" for w in r["why"])))
        typer.echo(f"{sum(1 for r in got if r['action'] in ('delete', 'hashes'))} due, {sum(1 for r in got if r['action'] == 'held')} held, "
                   f"{sum(1 for r in got if r['action'] == 'keep')} kept. Nothing was deleted.")
