"""The vault (src/knos/vault.py): the primitives against their RFCs, the sealed file against its vector, checkpoints,
retention, and the restore test: seal, delete the working copy and the chain reference, restore from the export
alone, and `knos bundle verify --no-chain` still passes on every receipt. Every key and nonce here is fixed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import typer
from solders.keypair import Keypair
from typer.testing import CliRunner

from knos import bundle, receipt, vault
from knos import vault_crypto as vc

VECTOR = json.loads((Path(__file__).parent / "data" / "vault_v1.json").read_text(encoding="utf-8"))
KEYS = {who: bytes.fromhex(k) for who, k in VECTOR["private_keys"].items()}
TO = [(who, vc.public_of(k)) for who, k in KEYS.items()]
NOW, DAY = 1_790_000_000, 86400
h = bytes.fromhex


def _rand(*parts: bytes):
    left = list(parts)

    def rand(n: int) -> bytes:
        out = left.pop(0)
        assert len(out) == n
        return out
    return rand


def _vector_rand():
    return _rand(h(VECTOR["ephemeral_private"]), h(VECTOR["content_key"]), h(VECTOR["nonce"]))


def _app():
    app = typer.Typer()
    lines: list = []
    vault.register(app, lines)
    bundle.register(app, [])
    assert lines == [("vault", "For money", lines[0][2])] and "outlives devnet" in lines[0][2]
    return app


@pytest.mark.parametrize("pure", [True, False])
def test_the_primitives_give_their_rfcs_vectors_with_and_without_the_cryptography_package(pure):
    if not pure and vc._native() is None:
        pytest.skip("the cryptography package is not installed: the standard-library code is the only one")
    a, b = h("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"), h("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
    assert vc.public_of(a, pure).hex() == "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"        # RFC 7748, 6.1
    assert vc.public_of(b, pure).hex() == "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
    assert vc.x25519(a, vc.public_of(b, pure), pure).hex() == "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"
    with pytest.raises(ValueError, match="small order"):
        vc.x25519(a, bytes(32), pure)
    key, nonce, aad = bytes(range(0x80, 0xA0)), h("070000004041424344454647"), h("50515253c0c1c2c3c4c5c6c7")              # RFC 8439, 2.8.2
    plain = b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it."
    sealed = vc.aead_seal(key, nonce, plain, aad, pure)
    assert sealed[:16].hex() == "d31a8d34648e60db7b86afbc53ef7ec2" and sealed[-16:].hex() == "1ae10b594f09e26a7e902ecbd0600691"
    assert vc.aead_open(key, nonce, sealed, aad, pure) == plain
    for bad in (sealed[:-1] + bytes([sealed[-1] ^ 1]), bytes([sealed[0] ^ 1]) + sealed[1:]):
        with pytest.raises(ValueError, match="tag does not hold"):
            vc.aead_open(key, nonce, bad, aad, pure)
    with pytest.raises(ValueError, match="tag does not hold"):
        vc.aead_open(key, nonce, sealed, aad + b"x", pure)


def test_hkdf_and_poly1305_give_their_rfcs_vectors():
    assert vc.hkdf(h("0b" * 22), h("000102030405060708090a0b0c"), h("f0f1f2f3f4f5f6f7f8f9"), 42).hex() == \
        "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"                        # RFC 5869, A.1
    key = h("85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b")                                         # RFC 8439, 2.5.2
    assert vc.poly1305(key, b"Cryptographic Forum Research Group").hex() == "a8061dc1305136c6c22b8baf0c0127a9"


def test_the_sealed_file_is_the_documented_vector_and_each_recipient_opens_it_alone(monkeypatch):
    plain = VECTOR["plain"].encode()
    sealed = vault.seal(plain, TO, VECTOR["name"], VECTOR["sealed_at"], _vector_rand())
    assert sealed.decode() == VECTOR["sealed"] and hashlib.sha256(sealed).hexdigest() == VECTOR["sealed_sha256"]
    assert {who: vc.public_of(k).hex() for who, k in KEYS.items()} == VECTOR["public_keys"]
    monkeypatch.setattr(vc, "_native", lambda: None)             # the standard library alone writes the same bytes and reads them
    assert vault.seal(plain, TO, VECTOR["name"], VECTOR["sealed_at"], _vector_rand()) == sealed
    for who, key in KEYS.items():
        got, head = vault.open_(sealed, key)
        assert got == plain and head["plain_sha256"] == VECTOR["plain_sha256"] and [r["label"] for r in head["recipients"]] == ["auditor", "buyer", "supplier"]
    monkeypatch.undo()
    assert vault.open_(sealed, KEYS["supplier"])[0] == plain
    with pytest.raises(ValueError, match="was not sealed to that key"):
        vault.open_(sealed, hashlib.sha256(b"a stranger").digest())
    doc = json.loads(sealed)
    assert VECTOR["plain"][:20] not in sealed.decode() and set(doc) == {*vault._HEAD, "recipients", "nonce", "ciphertext"}
    # one content key, wrapped once for each: three different 48-byte wraps of the same 32 bytes
    assert len({r["wrapped"] for r in doc["recipients"]}) == 3 and all(len(vault._unb64(r["wrapped"])) == 48 for r in doc["recipients"])


def test_any_change_to_a_sealed_file_stops_every_recipient_from_opening_it():
    sealed = vault.seal(b"evidence", TO, "a.tar", NOW, _vector_rand())
    doc = json.loads(sealed)
    stranger = vc.public_of(hashlib.sha256(b"a stranger").digest())
    changes = [{"name": "b.tar"}, {"sealed_at": NOW - 10 * 365 * DAY}, {"size": 9}, {"plain_sha256": "0" * 64},
               {"recipients": doc["recipients"][:2]},                                                                # a recipient dropped
               {"recipients": [{**doc["recipients"][0], "label": "buyer2"}, *doc["recipients"][1:]]},                # one relabelled
               {"recipients": [*doc["recipients"], {**doc["recipients"][0], "id": vault.key_id(stranger), "label": "x", "public": vault._b64(stranger)}]},   # one added
               {"ciphertext": vault._b64(vault._unb64(doc["ciphertext"])[::-1])}, {"nonce": vault._b64(bytes(12))}]
    for change in changes:
        with pytest.raises(ValueError, match="does not open|opens to other bytes"):
            vault.open_(vault._json({**doc, **change}), KEYS["buyer"])
    for bad in (b"not json", vault._json({**doc, "version": 2}), vault._json({**doc, "extra": 1}), vault._json({**doc, "name": "../x"})):
        with pytest.raises(ValueError):
            vault.header(bad)
    for recipients in ([], [TO[0], TO[0]], [("buyer", TO[0][1]), ("buyer", TO[1][1])], [("Buyer!", TO[0][1])]):
        with pytest.raises(ValueError):
            vault.seal(b"x", recipients, "a.tar", NOW, _vector_rand())


def _folder(tmp_path: Path, ages=(0, 3, 8)) -> tuple[Path, list[str]]:
    folder, shas = tmp_path / "vault", []
    for i, years in enumerate(ages):
        plain = f"bundle {i}".encode()
        seed = hashlib.sha256(b"seal %d" % i).digest()
        vault.put(folder, vault.seal(plain, TO, f"order-{i}.bundle.tar", NOW - years * vault.YEAR - DAY, _rand(seed, seed[::-1], seed[:12])))
        shas.append(hashlib.sha256(plain).hexdigest())
    return folder, shas


def test_a_checkpoint_is_one_hash_anyone_recomputes_signed_when_a_key_is_given_and_verified_with_no_chain(tmp_path):
    folder, shas = _folder(tmp_path)
    assert vault.root_of([VECTOR["plain_sha256"]]) == VECTOR["checkpoint_root"]
    plain = vault.checkpoint(shas, NOW)
    assert plain["entries"] == sorted(shas) and plain["root"] == vault.root_of(reversed(shas)) and plain["signature"] is None
    assert "signed by nobody" in vault.check_checkpoint(plain)[1]
    signer = Keypair.from_seed(bytes([7]) * 32)
    signed = vault.checkpoint(shas, NOW + 1, previous=plain["root"], keypair=signer)
    assert signed["previous"] == plain["root"] and str(signer.pubkey()) in vault.check_checkpoint(signed)[1]
    said, missing = vault.verify(signed, vault.held_in(folder))
    assert not missing and sum("the header names it" in line for line in said) == 3
    said, missing = vault.verify(signed, vault.held_in(folder, KEYS["auditor"]))
    assert not missing and sum("opened with the key and hashed" in line for line in said) == 3
    for change in ({"entries": signed["entries"][:2], "count": 2}, {"root": "0" * 64}, {"at": NOW + 2}, {"previous": None},
                   {"signature": {**signed["signature"], "public": str(Keypair.from_seed(bytes([8]) * 32).pubkey())}}):
        with pytest.raises(ValueError, match="root is not the hash|signature does not hold"):
            vault.check_checkpoint({**signed, **change})
    (folder / f"{shas[0]}.vault").unlink()                           # a bundle that is gone is named, and the check fails
    assert vault.verify(signed, vault.held_in(folder))[1] == [shas[0]]
    (folder / f"{shas[1]}.vault").rename(folder / f"{shas[0]}.vault")
    with pytest.raises(ValueError, match="renamed or replaced"):
        vault.held_in(folder)


def test_a_retention_policy_keeps_n_years_then_deletes_or_keeps_the_hash_and_a_dry_run_touches_nothing(tmp_path):
    folder, shas = _folder(tmp_path)
    policy = json.loads((Path(__file__).parents[1] / "examples" / "private" / "retention.json").read_text(encoding="utf-8"))
    assert vault.policy_of(policy)["keep_years"] == 7 and policy["then"] == "hashes"
    before = sorted(p.name for p in folder.iterdir())
    rows = vault.retain(folder, policy, NOW, dry_run=True)
    assert {r["sha256"]: r["action"] for r in rows} == {shas[0]: "keep", shas[1]: "keep", shas[2]: "hashes"} and sorted(p.name for p in folder.iterdir()) == before
    mark = vault.checkpoint(shas, NOW)
    run, policy_file = CliRunner(), tmp_path / "policy.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    dry = run.invoke(_app(), ["vault", "retain", str(folder), "--policy", str(policy_file), "--dry-run", "--now", str(NOW)])
    assert dry.exit_code == 0 and "would be removed, its hash kept" in dry.output and "1 of 3 would go. Dry run: nothing was touched." in dry.output
    assert sorted(p.name for p in folder.iterdir()) == before
    done = run.invoke(_app(), ["vault", "retain", str(folder), "--policy", str(policy_file), "--now", str(NOW)])
    assert done.exit_code == 0 and "1 of 3 went." in done.output and not (folder / f"{shas[2]}.vault").exists()
    kept = json.loads((folder / vault.HASHES).read_text(encoding="utf-8"))["kept"]
    assert list(kept) == [shas[2]] and kept[shas[2]]["removed_at"] == NOW
    said, missing = vault.verify(mark, vault.held_in(folder))        # the old checkpoint still holds: the hash was kept
    assert not missing and any("hash only: a retention policy removed the file" in line for line in said)
    assert [r["action"] for r in vault.retain(folder, policy, NOW, dry_run=False)] == ["keep", "keep"]          # a second run finds nothing to do
    gone = vault.retain(folder, {**policy, "keep_years": 1, "then": "delete"}, NOW, dry_run=False)       # delete: no trace is kept
    assert {r["sha256"]: r["action"] for r in gone} == {shas[0]: "keep", shas[1]: "delete"} and vault.verify(mark, vault.held_in(folder))[1] == [shas[1]]
    for bad in ({**policy, "then": "archive"}, {**policy, "keep_years": -1}, {**policy, "keep_years": "7"}, {**policy, "other": 1}, {}):
        with pytest.raises(ValueError, match="a retention policy is"):
            vault.policy_of(bad)


def test_restore_from_the_export_alone_after_the_working_copy_and_the_chain_are_gone(tmp_path, monkeypatch):
    """The restore test. Nothing is left but one archive the customer kept, and every receipt still verifies."""
    import shutil

    import test_bundle as tb
    monkeypatch.setattr(bundle, "published_keys", lambda issuer: None)       # no network in a test
    net = tb.Chain()
    r, files = bundle.gather(net.call, net.events(), tb.ORDER, tb.host())
    blob = bundle.make(files, r["order"])
    run, app = CliRunner(), _app()
    work, customer = tmp_path / "work", tmp_path / "customer"
    work.mkdir()
    customer.mkdir()
    (work / "order.bundle.tar").write_bytes(blob)
    for who, key in KEYS.items():
        (customer / f"{who}.json").write_bytes(vault._json({"type": vault.KEY_TYPE, "version": 1, "label": who, "id": vault.key_id(vc.public_of(key)),
                                                           "public": vc.public_of(key).hex(), "private": key.hex()}))
    to = [x for who, pub in TO for x in ("--to", f"{who}={pub.hex()}")]
    sealed = run.invoke(app, ["vault", "seal", str(work / "order.bundle.tar"), *to, "--vault", str(work / "vault"), "--now", str(NOW)])
    assert sealed.exit_code == 0 and "sealed to 3 (auditor, buyer, supplier)" in sealed.output, sealed.output
    assert blob[:200] not in (work / "vault" / f"{bundle._sha(blob)}.vault").read_bytes()
    mark = run.invoke(app, ["vault", "checkpoint", str(work / "vault"), "--out", str(customer / "checkpoint.json"), "--now", str(NOW)])
    root = mark.output.strip().splitlines()[-1]
    assert mark.exit_code == 0 and root.startswith(vault.ANCHOR)             # the line the customer writes down somewhere else
    out = run.invoke(app, ["vault", "export", str(work / "vault"), "--key", str(customer / "supplier.json"), "--out", str(customer / "knos-evidence.tar"), "--now", str(NOW)])
    assert out.exit_code == 0 and root in out.output and "not encrypted" in out.output, out.output
    again = vault.export(work / "vault", KEYS["buyer"], NOW)[0]             # another party's key, the same archive: it is deterministic
    assert again == (customer / "knos-evidence.tar").read_bytes()

    shutil.rmtree(work)                                                     # the working copy, the vault with it
    net.reset = True                                                        # and the chain reference
    with pytest.raises(bundle.Unavailable):
        bundle.gather(net.call, net.events(), tb.ORDER, tb.host())

    back = run.invoke(app, ["vault", "restore", str(customer / "knos-evidence.tar"), "--to", str(tmp_path / "restored")])
    assert back.exit_code == 0 and "1 bundles restored and checked against the checkpoint" in back.output, back.output
    restored = sorted(p for p in (tmp_path / "restored").iterdir() if p.name != "CHECKPOINT.json")
    assert [p.read_bytes() for p in restored] == [blob]
    for path in restored:                                                   # every receipt, with no chain and no network
        ok = run.invoke(app, ["bundle", "verify", str(path), "--no-chain", "--no-network"])
        assert ok.exit_code == 0 and "verified with no cluster. bundle sha256:" + bundle._sha(blob) in ok.output, ok.output
        assert receipt.check(bundle.verify_offline(path.read_bytes(), None)[0]) is None
    held = run.invoke(app, ["vault", "verify", str(customer / "checkpoint.json"), "--against", str(customer / "knos-evidence.tar"), "--root", root])
    assert held.exit_code == 0 and "verified with no chain and no network" in held.output and "its bytes hashed" in held.output, held.output
    plain = run.invoke(app, ["vault", "verify", str(customer / "checkpoint.json"), "--against", str(tmp_path / "restored")])
    assert plain.exit_code == 0 and "a plain file, its bytes hashed" in plain.output and "does not list" not in plain.output
    wrong = run.invoke(app, ["vault", "verify", str(customer / "checkpoint.json"), "--root", "0" * 64])
    assert wrong.exit_code == 1 and "the root you give is not this checkpoint's" in wrong.output
    # an archive that was changed restores nothing
    bad = (customer / "knos-evidence.tar").read_bytes().replace(b"src/a.py", b"src/b.py")
    (customer / "bad.tar").write_bytes(bad)
    refused = run.invoke(app, ["vault", "restore", str(customer / "bad.tar"), "--to", str(tmp_path / "never")])
    assert refused.exit_code == 1 and "nothing was restored" in refused.output and not (tmp_path / "never").exists()


def test_keygen_writes_a_key_once_and_open_gives_the_bundle_back(tmp_path):
    run, app = CliRunner(), _app()
    made = run.invoke(app, ["vault", "keygen", "buyer", "--out", str(tmp_path / "buyer.json")])
    line = made.output.strip().splitlines()[-1]
    assert made.exit_code == 0 and line.startswith("buyer=") and len(line) == 6 + 64
    twice = run.invoke(app, ["vault", "keygen", "buyer", "--out", str(tmp_path / "buyer.json")])
    assert twice.exit_code == 1 and "is not overwritten" in twice.output
    (tmp_path / "evidence.tar").write_bytes(b"evidence")
    assert run.invoke(app, ["vault", "seal", str(tmp_path / "evidence.tar"), "--to", line, "--vault", str(tmp_path / "v"), "--now", str(NOW)]).exit_code == 0
    sealed = next((tmp_path / "v").glob("*.vault"))
    opened = run.invoke(app, ["vault", "open", str(sealed), "--key", str(tmp_path / "buyer.json"), "--out", str(tmp_path / "back.tar")])
    assert opened.exit_code == 0 and (tmp_path / "back.tar").read_bytes() == b"evidence" and "sealed 2026-" in opened.output
    (tmp_path / "other.json").write_bytes(vault._json(vault.new_key("auditor", lambda n: bytes([3]) * n)))
    no = run.invoke(app, ["vault", "open", str(sealed), "--key", str(tmp_path / "other.json")])
    assert no.exit_code == 1 and "was not sealed to that key" in no.output and "buyer (" in no.output


def test_the_documents_say_the_format_the_vector_and_the_limits():
    docs = Path(__file__).parents[1] / "docs"
    page = (docs / "VAULT.md").read_text(encoding="utf-8")
    assert VECTOR["sealed_sha256"] in page and VECTOR["checkpoint_root"] in page and "tests/data/vault_v1.json" in page
    assert all(word in page for word in (vault.KEM, vault.AEAD, vault.WRAP_INFO.decode(), vault.ANCHOR, "not constant-time", "RFC 7748", "RFC 8439", "RFC 5869"))
    assert all(f"knos vault {c}" in page for c in ("keygen", "seal", "open", "export", "restore", "retain", "checkpoint", "verify"))
    assert "devnet is reset and the operator's copies are deleted" in (docs / "DRILLS.md").read_text(encoding="utf-8")
    assert "VAULT.md" in (docs / "PRIVACY.md").read_text(encoding="utf-8") and "VAULT.md" in (docs / "drills_recovery.md").read_text(encoding="utf-8")
