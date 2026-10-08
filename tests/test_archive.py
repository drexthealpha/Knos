"""knos.archive: evidence that verifies with no Knos. Deterministic, no network, no clock."""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import _es256
from knos import archive as A
from knos import events as E
from knos import ledger as L
from knos import standalone_verify as V
from knos import statement as S
from test_events import BUYER, SELLER, Key, _ack, _b64, _ev

ROOT = Path(__file__).resolve().parents[1]
ES_KID = "es1"


@pytest.fixture(scope="module")
def key():
    return Key("knos archive test key")


@pytest.fixture(scope="module")
def jwks(key):
    x, y = _es256.mul(_es256.KEY_A, _es256.G)
    ec = {"kty": "EC", "crv": "P-256", "alg": "ES256", "kid": ES_KID, "x": _b64(x.to_bytes(32, "big")), "y": _b64(y.to_bytes(32, "big"))}
    return {"keys": [key.jwk("k1"), ec, Key("a key nobody signs with").jwk("k2")]}


def _es_token(**claims) -> str:
    signed = _b64(json.dumps({"typ": "JWT", "alg": "ES256", "kid": ES_KID}).encode()) + "." + _b64(json.dumps(claims).encode())
    return signed + "." + _b64(_es256.sign(_es256.KEY_A, signed.encode()))


def _batch_token(key: Key, b: L.Batch) -> str:
    return key.token("k1", iss=L.GITHUB_ISSUER, aud=L.batch_audience(b), repository_owner_id=str(BUYER), iat=1793491200)


def _evidence(key: Key, jwks: dict, acks: tuple[int, ...] = (SELLER,), invoiced: tuple[int, ...] = (1, 2, 3)) -> dict:
    """A small month: two batches in a ledger, both in the log, one invoice per accepted deliverable, an AP statement."""
    made = [L.batch([_ev(1), _ev(2, accepted=False)], 0, 202610), L.batch([_ev(3)], 1, 202610)]
    ledger = L.dump(made)
    log = E.Log()
    assert E.ingest(log, E.from_ledger(ledger)).ok
    assert E.ingest(log, [E.invoice_line(str(SELLER), "INV-7", n, "import", deliverable=_ev(n).dlv, month=202610, amount=2_000_000, unit="units")
                          for n in invoiced]).ok
    for owner in acks:
        assert E.ingest(log, [E.acknowledgement(_ack(key, log, owner))], jwks).ok
    text = log.text().encode()
    ap = S.make(text, {"date": "2026-10-31", "invoice": "INV-7", "supplier": str(SELLER), "buyer": str(BUYER), "currency": "USD"})
    terms = b'{"mode":"tests","v":1}'
    return dict(events=text, ledgers={"buyer.jsonl": ledger.encode()}, statements={"ap-statement.json": S.canonical(ap)},
                tokens=[_batch_token(key, made[0]), _es_token(iss="https://issuer.example", aud="knos:anything", iat=1793491200)],
                terms=[terms], jwks=jwks, keys_read="2026-10-07", keys_from=L.GITHUB_JWKS, sealed="2026-11-01")


def _sealed(files: dict[str, bytes], **change: bytes | None) -> dict[str, bytes]:
    """The archive with some files changed and the manifest written again for them: what a careful forger hands over."""
    files = {k: v for k, v in {**files, **change}.items() if v is not None and k != "MANIFEST.json"}
    m = json.loads(A.files_of(sealed="2026-11-01")["MANIFEST.json"])
    old = json.loads(change.get("MANIFEST.json") or b"{}")
    listed = {n: hashlib.sha256(raw).hexdigest() for n, raw in sorted(files.items())}
    m.update({"files": listed, "evidence_root": V.evidence_root(listed), **{k: old[k] for k in ("head", "keys") if k in old}})
    return {**files, "MANIFEST.json": (L.canon(m) + "\n").encode()}


def _resealed(files: dict[str, bytes], **change: bytes | None) -> dict[str, bytes]:
    return _sealed(files, **{"MANIFEST.json": files["MANIFEST.json"], **change})


# -- the archive ----------------------------------------------------------------------------------------------------------
def test_the_same_evidence_is_the_same_bytes_and_holds_what_a_reader_needs(key, jwks):
    blob = A.make(**_evidence(key, jwks))
    assert blob == A.make(**_evidence(key, jwks))
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = z.namelist()
        assert names == sorted(names) and all(i.date_time == (1980, 1, 1, 0, 0, 0) and i.compress_type == zipfile.ZIP_STORED for i in z.infolist())
        manifest = json.loads(z.read("MANIFEST.json"))
        kept = json.loads(z.read("keys/jwks.json"))
    assert {"events/log.jsonl", "ledgers/buyer.jsonl", "statements/events-202610.json", "statements/ap-statement.json", "keys/jwks.json", "verify.py",
            "README.txt"} <= set(names)
    assert sum(n.startswith("tokens/") for n in names) == 2 and sum(n.startswith("terms/") for n in names) == 1
    assert sorted(k["kid"] for k in kept["keys"]) == ["es1", "k1"]            # the keys the tokens name, and no other
    assert manifest["keys"]["read"] == "2026-10-07" and manifest["keys"]["from"] == L.GITHUB_JWKS and manifest["sealed"] == "2026-11-01"
    assert manifest["evidence_files"] == len(names) - 3


def test_the_verifier_is_one_file_of_the_standard_library_with_no_knos_and_no_network():
    source = Path(V.__file__).read_text(encoding="utf-8")
    assert (ROOT / "conformance" / "standalone" / "verify.py").read_text(encoding="utf-8") == source      # the published copy is the file archives carry
    imported = {a.name.split(".")[0] for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Import) for a in n.names} \
        | {(n.module or "").split(".")[0] for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)}
    assert imported == {"base64", "datetime", "hashlib", "json", "os", "re", "sys", "zipfile"}
    assert not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(ast.parse(source)))
    assert A.verifier() == source.encode("utf-8")


def _run(folder: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    return subprocess.run([sys.executable, "-I", "-S", "verify.py", *args], cwd=folder, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_it_verifies_in_an_empty_directory_with_knos_unimportable(tmp_path, key, jwks):
    (tmp_path / "archive.zip").write_bytes(A.make(**_evidence(key, jwks)))
    alone = tmp_path / "elsewhere"
    with zipfile.ZipFile(tmp_path / "archive.zip") as z:
        z.extractall(alone)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    gone = subprocess.run([sys.executable, "-I", "-S", "-c", "import knos"], cwd=alone, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert gone.returncode != 0 and "No module named 'knos'" in gone.stderr
    r = _run(alone)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "VERIFIED:" in out and "No network, no Knos." in out and "DOES NOT HOLD" not in out
    for said in ("the log of events holds: 9 lines", f"owner {SELLER} up to line 7", "1 monthly statements of the log were made again from the log: the same bytes",
                 "ledgers/buyer.jsonl recomputes: 2 batches", "for batch 0 of 202610 in ledgers/buyer.jsonl", "for the audience knos:anything",
                 "its totals are the totals of its 3 lines (3 of them rest on lines of the archived log)", "1 terms files hash to the names they are kept under",
                 "1 batches carry no signed token in this archive, so their roots are checked by hash only", "were read on 2026-10-07"):
        assert said in out, said
    assert _run(alone, "--strict").returncode == 1                              # a root nobody signed is a note, and --strict fails on notes
    packed = subprocess.run([sys.executable, "-I", "-S", str(alone / "verify.py"), str(tmp_path / "archive.zip")], cwd=tmp_path, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=120)
    assert packed.returncode == 0 and "VERIFIED:" in packed.stdout
    (alone / "ledgers" / "buyer.jsonl").write_bytes((alone / "ledgers" / "buyer.jsonl").read_bytes().replace(b'"rate":2000000', b'"rate":9000000', 1))
    r = _run(alone)
    assert r.returncode == 1 and "DOES NOT HOLD: ledgers/buyer.jsonl is not the file the manifest lists" in r.stdout and "NOT VERIFIED" in r.stdout


def test_the_standalone_checks_agree_with_knos_on_every_format(key, jwks):
    files = A.files_of(**_evidence(key, jwks))
    done, _notes, problems = V.check(files)
    assert problems == [] and len(done) >= 9
    log = V.read_log(files["events/log.jsonl"].decode(), jwks, problems.append)
    mine, _ = E.read(files["events/log.jsonl"].decode(), jwks)
    assert problems == [] and log.head == mine.head and L.canon(V.log_statement(log, 202610)) == L.canon(E.statement(mine, 202610))
    stored = L.load(files["ledgers/buyer.jsonl"].decode())
    batches, chains = V.read_ledger("x", files["ledgers/buyer.jsonl"].decode(), problems.append)
    assert [b["h"]["root"] for b in batches] == [s.batch().root.hex() for s in stored] and chains == {202610: L.totals(stored, 202610).chain.hex()}
    old = L.dump([L.batch([_ev(1), _ev(2)], 0, 202610, format=1)])                 # commitment format 1, and a batch that re-commits it in format 2
    assert V.read_ledger("old", old, problems.append)[0][0]["h"]["root"] == L.merkle_root([_ev(1).id, _ev(2).id]).hex() and problems == []
    moved = old + "".join(x + "\n" for x in L.migrate(L.load(old)))
    assert L.verify(L.load(moved)) == [] and len(V.read_ledger("moved", moved, problems.append)[0]) == 1 and problems == []
    V.read_ledger("moved", moved.replace('"rate":2000000', '"rate":1', 1), problems.append)        # a line changed under both commitments
    # format 1 binds the ids and the totals, so its root stands and its value does not; format 2 binds the line itself
    assert any("the lines give count 2, accepted 2, value 2000001" in x for x in problems) and any("does not commit to that batch's lines in format 2" in x for x in problems)


def test_what_was_changed_is_found_even_when_the_manifest_was_written_again(key, jwks):
    files = A.files_of(**_evidence(key, jwks))
    token = next(n for n in files if n.startswith("tokens/") and b"." in files[n] and json.loads(V.unb64(files[n].split(b".")[0].decode()))["alg"] == "RS256")
    es = next(n for n in files if n.startswith("tokens/") and n != token)
    ledger, log = files["ledgers/buyer.jsonl"], files["events/log.jsonl"]

    def said(**change) -> str:
        return " ".join(V.check(_resealed(files, **change))[2])

    assert said() == ""
    assert "the lines give root" in said(**{"ledgers/buyer.jsonl": ledger.replace(b'"rate":2000000', b'"rate":9000000', 1)})
    cut = b"".join(x + b"\n" for x in ledger.split(b"\n")[:3])                      # the second batch taken out: the first one's token still holds
    assert said(**{"ledgers/buyer.jsonl": cut}) == ""
    first = b"".join(x + b"\n" for x in ledger.split(b"\n")[3:5])                   # the first batch taken out: the token names a batch nobody holds, and the numbering has a hole
    assert "signed for a batch that no archived ledger holds" in said(**{"ledgers/buyer.jsonl": first}) and "numbered [1], not 0 to 0" in said(**{"ledgers/buyer.jsonl": first})
    assert "does not follow the line before it" in said(**{"events/log.jsonl": log.replace(b'"verdict":"accepted"', b'"verdict":"rejected"', 1)})
    assert "removed from the end" in said(**{"events/log.jsonl": b"".join(x + b"\n" for x in log.split(b"\n")[:-2])})
    st = json.loads(files["statements/ap-statement.json"])
    st["totals"]["agreed"]["amount"] = "9.00"
    assert "its sha256 is not its own" in said(**{"statements/ap-statement.json": S.canonical(st)})
    st["sha256"] = S.digest(st)
    assert "its totals are not the totals of its lines" in said(**{"statements/ap-statement.json": S.canonical(st)})
    month = json.loads(files["statements/events-202610.json"])
    month["accepted_deliverables"] = 3
    assert "is not the statement the log gives" in said(**{"statements/events-202610.json": (L.canon(month) + "\n").encode()})
    h, c, s = files[token].strip().split(b".")
    forged = b".".join([h, _b64(json.dumps({**json.loads(V.unb64(c.decode())), "aud": "knosm:batch:1:2:202610:0:1:1:1:" + "0" * 64}).encode()).encode(), s])
    name = f"tokens/{hashlib.sha256(forged).hexdigest()}.jwt"
    assert "does not carry the signature of the archived key 'k1'" in said(**{token: None, name: forged + b"\n"})
    h, c, s = files[es].strip().split(b".")
    forged = b".".join([h, _b64(b'{"aud":"knos:other"}').encode(), s])
    assert "does not carry the signature of the archived key 'es1'" in said(**{es: None, f"tokens/{hashlib.sha256(forged).hexdigest()}.jwt": forged + b"\n"})
    terms = next(n for n in files if n.startswith("terms/"))
    assert "do not hash to the name" in said(**{terms: b'{"mode":"merge","v":1}'})
    swapped = json.loads(files["keys/jwks.json"])
    swapped["keys"] = [k for k in swapped["keys"] if k["kid"] != "k1"] + [Key("another issuer").jwk("k1")]
    assert "does not carry the signature" in said(**{"keys/jwks.json": (L.canon(swapped) + "\n").encode()})
    plain = V.check({**files, "ledgers/buyer.jsonl": cut})[2]                       # without the manifest written again: the file is named
    assert plain == ["ledgers/buyer.jsonl is not the file the manifest lists (its SHA-256 differs): it was changed after the archive was made."]
    assert V.check({k: v for k, v in files.items() if k != "MANIFEST.json"})[2] == ["This is not a Knos evidence archive, version 1: it has no MANIFEST.json of one."]


def test_no_archive_is_made_of_evidence_that_does_not_verify(key, jwks):
    given = _evidence(key, jwks)
    with pytest.raises(L.Bad, match="does not check"):
        A.make(**{**given, "events": given["events"].replace(b'"verdict":"accepted"', b'"verdict":"rejected"', 1)})
    with pytest.raises(L.Bad, match="no archive is made"):
        A.make(**{**given, "ledgers": {"buyer.jsonl": given["ledgers"]["buyer.jsonl"].replace(b'"rate":2000000', b'"rate":9000000', 1)}})
    with pytest.raises(L.Bad, match="the day the issuer's keys were read"):
        A.make(**{**given, "keys_read": ""})
    with pytest.raises(L.Bad, match="the day it is sealed"):
        A.make(**{**given, "sealed": ""})
    with pytest.raises(L.Bad, match="makes itself from the log"):
        A.make(**{**given, "statements": {"events-202610.json": b"{}"}})


# -- completeness: what the root cannot say ---------------------------------------------------------------------------------
def test_a_missing_number_is_named_by_the_verifier_and_explained_only_by_an_acknowledged_correction(key, jwks):
    made = [L.batch([_ev(1)], 0, 202610), L.batch([_ev(2)], 1, 202610), L.batch([_ev(3)], 2, 202610)]
    log = E.Log()
    assert E.ingest(log, E.from_ledger(L.dump([made[0], made[2]]))).ok              # batch 1 never arrived
    stream = f"{BUYER}:{SELLER}:202610"

    def notes() -> str:
        return " ".join(V.check(A.files_of(events=log.text().encode(), jwks=jwks, keys_read="2026-10-07", sealed="2026-11-01"))[1])

    assert f"INCOMPLETE: number 1 of {stream} never arrived and nothing explains it" in notes()
    assert E.ingest(log, [E.gap_correction(stream, 1, "the run was cancelled before it sent anything")]).ok
    assert "says why (the run was cancelled before it sent anything) and nobody has acknowledged that line" in notes()
    assert E.ingest(log, [E.acknowledgement(_ack(key, log, SELLER))], jwks).ok
    done = " ".join(V.check(A.files_of(events=log.text().encode(), jwks=jwks, keys_read="2026-10-07", sealed="2026-11-01"))[0])
    assert "INCOMPLETE" not in notes() and f"number 1 of {stream} never arrived: line 4 says why" in done and f"acknowledged by owner {SELLER}" in done


# -- two holders ------------------------------------------------------------------------------------------------------------
def test_two_holders_compare_by_root_and_what_differs_is_named(key, jwks):
    a = A.files_of(**_evidence(key, jwks))
    same = A.compare(a, A.files_of(**{**_evidence(key, jwks), "sealed": "2027-01-01"}))        # sealed on another day: the same evidence
    assert same["same"] and A.compare_said(same) == [f"The same evidence: both hold the root {json.loads(a['MANIFEST.json'])['evidence_root']}."]
    given = _evidence(key, jwks)
    log, _ = E.read(given["events"].decode(), jwks)
    E.ingest(log, [E.correction(log.events[1].id, verdict="disputed", reason="contested")])
    ahead = A.files_of(**{**given, "events": log.text().encode(), "statements": {}, "terms": []})
    c = A.compare(a, ahead)
    assert not c["same"] and c["root"]["a"] != c["root"]["b"] and c["differ"] == ["events/log.jsonl"] and c["only_b"] == []
    assert c["only_a"] == sorted(["statements/ap-statement.json", *(n for n in a if n.startswith("terms/"))])
    assert c["log"] == "B's log is A's log and 1 more lines: A is behind, or lines were cut from the end of its log."
    assert c["follow_from_the_log"] == ["statements/events-202610.json"]
    rewritten = E.Log()
    E.ingest(rewritten, list(E.from_ledger(given["ledgers"]["buyer.jsonl"].decode()))[::-1])
    parted = A.compare(a, A.files_of(events=rewritten.text().encode(), sealed="2026-11-01"))
    assert parted["log"] == "The two logs are the same up to line -1 and part at line 0: one of them was rewritten from there."
    assert A.compare(a, {k: v for k, v in a.items() if k != "verify.py"})["same"]               # the verifier is not evidence


# -- retention ----------------------------------------------------------------------------------------------------------------
def test_a_retention_policy_reports_what_is_due_and_holds_what_an_open_month_or_dispute_needs(key, jwks):
    rules = json.loads((ROOT / "examples" / "private" / "retention.json").read_text(encoding="utf-8"))
    one = A.files_of(**{**_evidence(key, jwks, invoiced=(1, 3)), "sealed": "2018-01-01"})                      # one party acknowledged: the month is open
    both = A.files_of(**{**_evidence(key, jwks, acks=(SELLER, BUYER), invoiced=(1, 3)), "sealed": "2018-01-01"})
    young = A.files_of(**{**_evidence(key, jwks, acks=(SELLER, BUYER), invoiced=(1, 3)), "sealed": "2026-01-01"})
    given = _evidence(key, jwks, acks=(), invoiced=(1, 3))
    log, _ = E.read(given["events"].decode(), jwks)
    E.ingest(log, [E.correction(log.events[1].id, verdict="disputed", reason="contested")])
    for owner in (SELLER, BUYER):
        E.ingest(log, [E.acknowledgement(_ack(key, log, owner))], jwks)
    disputed = A.files_of(**{**given, "events": log.text().encode(), "statements": {}, "sealed": "2018-01-01"})
    got = {r["archive"]: r for r in A.policy(rules, {"one": one, "both": both, "young": young, "disputed": disputed, "junk": {"x": b"y"}}, "2026-10-07")}
    assert got["both"]["action"] == "hashes" and got["both"]["why"] == [] and got["both"]["age_days"] == 3201
    assert got["one"]["action"] == "held" and got["one"]["why"] == ["202610 is open: 1 of 2 parties have acknowledged a head that covers it"]
    assert got["young"]["action"] == "keep" and got["young"]["age_days"] == 279
    assert got["disputed"]["action"] == "held" and any("in dispute" in w or "disputed and not resolved" in w for w in got["disputed"]["why"])
    assert got["junk"]["action"] == "held"
    assert A.policy({**rules, "then": "delete"}, {"both": both}, "2026-10-07")[0]["action"] == "delete"
    with pytest.raises(L.Bad):
        A.policy({"keep_years": 7}, {"both": both}, "2026-10-07")


# -- the commands -----------------------------------------------------------------------------------------------------------
def test_the_commands_make_verify_compare_and_policy(tmp_path, key, jwks):
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    app, help_lines = typer.Typer(), []
    A.register(app, help_lines)

    @app.command("other")
    def other() -> None: ...
    given, run = _evidence(key, jwks), CliRunner()
    (tmp_path / "events.jsonl").write_bytes(given["events"])
    (tmp_path / "events.jsonl.jwks.json").write_text(json.dumps(jwks), encoding="utf-8")
    (tmp_path / "buyer.jsonl").write_bytes(given["ledgers"]["buyer.jsonl"])
    (tmp_path / "ap-statement.json").write_bytes(given["statements"]["ap-statement.json"])
    (tmp_path / "batch.jwt").write_text(given["tokens"][0], encoding="ascii")
    (tmp_path / "terms.json").write_bytes(given["terms"][0])
    args = ["--events", str(tmp_path / "events.jsonl"), "--ledger", str(tmp_path / "buyer.jsonl"), "--statement", str(tmp_path / "ap-statement.json"),
            "--token", str(tmp_path / "batch.jwt"), "--terms", str(tmp_path / "terms.json"), "--keys-read", "2026-10-07", "--sealed", "2018-01-01"]
    assert help_lines[0][0] == "archive"
    m = run.invoke(app, ["archive", "make", str(tmp_path / "a.zip"), *args])
    assert m.exit_code == 0 and "evidence files, root " in m.output and "python verify.py" in m.output
    assert run.invoke(app, ["archive", "make", str(tmp_path / "b.zip"), *args]).exit_code == 0
    assert (tmp_path / "a.zip").read_bytes() == (tmp_path / "b.zip").read_bytes()
    v = run.invoke(app, ["archive", "verify", str(tmp_path / "a.zip")])
    assert v.exit_code == 0 and "VERIFIED:" in v.output
    assert run.invoke(app, ["archive", "compare", str(tmp_path / "a.zip"), str(tmp_path / "b.zip")]).output.startswith("The same evidence")
    less = run.invoke(app, ["archive", "make", str(tmp_path / "c.zip"), *args[:4], "--keys-read", "2026-10-07", "--sealed", "2018-01-01"])
    assert less.exit_code == 0
    c = run.invoke(app, ["archive", "compare", str(tmp_path / "a.zip"), str(tmp_path / "c.zip")])
    assert c.exit_code == 1 and "Only A holds statements/ap-statement.json." in c.output
    p = run.invoke(app, ["archive", "policy", str(ROOT / "examples" / "private" / "retention.json"), str(tmp_path / "a.zip"), "--today", "2026-10-07"])
    assert p.exit_code == 0 and "HELD: due, and still needed" in p.output and "0 due, 1 held, 0 kept. Nothing was deleted." in p.output
    assert (tmp_path / "a.zip").exists()
