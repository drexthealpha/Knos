"""The registry of published terms (terms/, docs/TERMS.md "Knos Terms 1") and the script that builds and reads it.

terms/ is what scripts/terms_registry.py publishes from knos.terms_templates; a published version never changes (an
edit to a listed file fails here, and a changed template becomes the next version); `verify` names the template and
version of a terms JSON or a hash, or says it is not a published template; `cite` gives the sentence a contract
carries. docs/TERMS.md states the canonical form knos.terms writes, and its example is a published version. The
page that browses the registry (web/terms.js) is run in headless Chromium by tests/web/terms.mjs.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from knos import terms, terms_templates

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


def _script():
    spec = importlib.util.spec_from_file_location("terms_registry", ROOT / "scripts" / "terms_registry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


reg = _script()


def _copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(ROOT / "terms", tmp_path / "terms"))


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "terms_registry.py"), *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})


def test_the_registry_is_what_the_script_publishes_from_the_templates_in_the_code():
    assert reg.build(write=False) == [], "run python scripts/terms_registry.py build"
    rows = reg.check()
    newest = reg.latest(rows)
    assert list(newest) == sorted(terms_templates.TEMPLATES)
    for name, row in newest.items():
        ex = terms_templates.export(name)
        assert (row["hash"], row["comment"]) == (ex["terms_hash"], ex["comment"])
        body = json.loads((ROOT / "terms" / name / f"{row['version']}.json").read_text(encoding="utf-8"))
        assert body["standard"] == "Knos Terms 1" and body["terms_json"] == ex["terms_json"] and body["terms"] == ex["terms"]
        assert hashlib.sha256(body["terms_json"].encode("ascii")).hexdigest() == row["hash"] == body["terms_hash"]
        assert terms.canonical(terms.parse(body["terms_json"])).decode("ascii") == body["terms_json"]     # the program's reader takes these bytes
        assert body["cite"] == f"Acceptance is governed by Knos Terms 1, template {name} version {row['version']}, sha256 {row['hash']}"
        assert row["trust"]["judge"] == ("merge" if ex["terms"]["mode"] == "merge" else "black-box") and row["trust"]["quorum"] == 1
    assert len({r["hash"] for r in newest.values()}) == len(newest)        # no two templates fund the same terms
    index = json.loads((ROOT / "terms" / "index.json").read_text(encoding="utf-8"))
    assert set(index) == {"standard", "site", "templates"} and all({"name", "version", "hash", "sentence"} <= set(r) for r in index["templates"])


def test_a_published_file_that_changes_fails_and_is_never_rewritten(tmp_path):
    root = _copy(tmp_path)
    path = root / "bugfix" / "1.json"
    was = path.read_text(encoding="utf-8")
    path.write_text(was.replace("Pays 50 test USDC", "Pays 60 test USDC"), encoding="utf-8", newline="")      # the words
    with pytest.raises(reg.Changed, match="changed after it was published.*version 2"):
        reg.check(root)
    with pytest.raises(reg.Changed):
        reg.build(root)                                                     # a build does not paper over it
    assert "Pays 60" in path.read_text(encoding="utf-8")
    path.write_text(was.replace('"reserve": 7', '"reserve": 8'), encoding="utf-8", newline="")                   # the terms
    with pytest.raises(reg.Changed):
        reg.verify("0" * 64, root)                                          # nothing is answered from a registry that changed
    path.write_text(was.replace("\n", "\r\n"), encoding="utf-8", newline="")                                   # one byte of form
    with pytest.raises(reg.Changed):
        reg.check(root)
    path.write_text(was, encoding="utf-8", newline="")
    assert reg.check(root) and reg.build(root) == []
    path.unlink()
    with pytest.raises(reg.Changed, match="listed and missing"):
        reg.check(root)
    path.write_text(was, encoding="utf-8", newline="")
    (root / "bugfix" / "2.json").write_text(was, encoding="utf-8", newline="")
    with pytest.raises(reg.Changed, match="not listed"):
        reg.check(root)


def test_an_index_edited_to_match_a_changed_file_is_caught_by_the_terms_themselves(tmp_path):
    root = _copy(tmp_path)
    path, index = root / "bugfix" / "1.json", root / "index.json"
    changed = path.read_text(encoding="utf-8").replace('"reserve": 7', '"reserve": 8')
    path.write_text(changed, encoding="utf-8", newline="")
    doc = json.loads(index.read_text(encoding="utf-8"))
    next(r for r in doc["templates"] if r["name"] == "bugfix")["file_sha256"] = hashlib.sha256(changed.encode()).hexdigest()
    index.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(reg.Changed, match="does not say what terms/index.json lists"):
        reg.check(root)


def test_a_changed_template_is_published_as_the_next_version_beside_the_old_one(tmp_path, monkeypatch):
    root = _copy(tmp_path)
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.glob("*/*.json")}
    old = terms_templates.TEMPLATES["bugfix"]
    new = terms_templates.Template("bugfix", "/knos fund 50 checks: unit, lint, types paths: src/**, tests/**", old.where, assumes=old.assumes)
    monkeypatch.setitem(terms_templates.TEMPLATES, "bugfix", new)
    assert reg.build(root, write=False) == ["bugfix/2.json", "index.json"]              # --check: the registry is behind the code
    assert reg.build(root) == ["bugfix/2.json", "index.json"] and reg.build(root) == []
    assert {k: (root / k).read_bytes() for k in before} == before                       # no published file was touched
    rows = [r for r in reg.check(root) if r["name"] == "bugfix"]
    assert [r["version"] for r in rows] == [1, 2] and rows[0]["hash"] != rows[1]["hash"] and "`types`" in rows[1]["sentence"]
    assert reg.cite("bugfix", root=root)[0].startswith("Acceptance is governed by Knos Terms 1, template bugfix version 2, sha256 " + rows[1]["hash"])
    assert reg.cite("bugfix", 1, root=root)[0].endswith(rows[0]["hash"])                # version 1 can still be cited
    assert [r["version"] for r in reg.verify(rows[0]["hash"], root)] == [1]
    monkeypatch.setitem(terms_templates.TEMPLATES, "bugfix", old)                       # the code goes back: that is a third version, not a rewrite
    assert reg.build(root) == ["bugfix/3.json", "index.json"]
    assert [r["version"] for r in reg.verify(rows[0]["hash"], root)] == [1, 3]


def test_verify_names_the_template_and_version_of_terms_or_of_a_hash():
    row = reg.latest(reg.check())["bugfix"]
    body = json.loads((ROOT / "terms" / "bugfix" / f"{row['version']}.json").read_text(encoding="utf-8"))
    for what in (row["hash"], row["hash"].upper() + "\n", body["terms_json"], body["terms"], json.dumps(body), json.dumps(body["terms"], indent=4),
                 {**body["terms"], "paths": ["tests/**", "src/**", "src/**"]}, (ROOT / "examples" / "terms" / "bugfix.json").read_text(encoding="utf-8")):
        assert [(r["name"], r["version"]) for r in reg.verify(what)] == [("bugfix", row["version"])], what
    for what in ("0" * 64, {**body["terms"], "reserve": 8}, {**body["terms"], "v": 2}, "not json", "[]", '{"terms": 1}', b"\xff"):
        assert reg.verify(what) == [] and reg.said(reg.verify(what)) == "not a published template"
    assert reg.said(reg.verify(row["hash"])).startswith(f"Knos Terms 1, template bugfix version {row['version']}, sha256 {row['hash']}\n    Pays ")


def test_cite_gives_the_contract_sentence_and_the_address_of_the_file_on_the_site():
    row = reg.latest(reg.check())["milestone"]
    line, url = reg.cite("milestone")
    assert line == f"Acceptance is governed by Knos Terms 1, template milestone version {row['version']}, sha256 {row['hash']}"
    assert url == f"https://drexthealpha.github.io/Knos/terms/milestone/{row['version']}.json" and reg.cite("milestone", row["version"]) == (line, url)
    with pytest.raises(KeyError, match="no template named nope is published: the published ones are bugfix"):
        reg.cite("nope")
    with pytest.raises(KeyError, match="milestone has no version 99"):
        reg.cite("milestone", 99)


def test_the_command_line_builds_checks_verifies_and_cites(tmp_path):
    assert _run("build", "--check").returncode == 0
    hash_ = reg.latest(reg.check())["standing-rate"]["hash"]
    got = _run("verify", hash_)
    assert got.returncode == 0 and got.stdout.startswith("Knos Terms 1, template standing-rate version ")
    got = _run("verify", str(ROOT / "examples" / "terms" / "private-attested.json"))
    assert got.returncode == 0 and "template private-attested version" in got.stdout
    other = tmp_path / "other.json"
    other.write_text('{"accept":"","checks":[],"deny":[],"mode":"merge","paths":[],"reserve":0,"v":1}', encoding="utf-8")
    got = _run("verify", str(other))
    assert got.returncode == 1 and got.stdout.strip() == "not a published template"
    got = _run("cite", "feature-blackbox", "1")
    assert got.returncode == 0 and got.stdout.splitlines()[1] == "https://drexthealpha.github.io/Knos/terms/feature-blackbox/1.json"
    assert _run("cite", "nope").returncode == 1 and _run().returncode == 2


def test_knos_terms_cite_and_verify_read_the_registry_from_the_package(tmp_path, monkeypatch, capsys):
    """`knos terms cite` and `knos terms verify`: the script's answers, from src/knos/terms_registry.py, which a wheel
    carries with the registry (pyproject.toml force-includes terms/ as knos/_terms). An installation with no registry
    says so in plain words and exits 1."""
    from knos import cli, terms_registry as pkg
    assert (reg.cite, reg.verify, reg.check, reg.Changed) == (pkg.cite, pkg.verify, pkg.check, pkg.Changed)      # one implementation
    assert pkg.where() == ROOT / "terms"
    row = reg.latest(reg.check())["feature-blackbox"]

    def knos(*args: str) -> tuple[int, str]:
        rc = cli.main(["terms", *args])
        return rc, capsys.readouterr().out

    line, url = reg.cite("feature-blackbox", 1)
    assert knos("cite", "feature-blackbox", "1") == (0, f"{line}\n{url}\n") == (0, _run("cite", "feature-blackbox", "1").stdout)
    assert knos("cite", "feature-blackbox")[1].startswith(f"Acceptance is governed by Knos Terms 1, template feature-blackbox version {row['version']}, sha256 {row['hash']}")
    rc, said = knos("cite", "nope")
    assert rc == 1 and said.startswith("no template named nope is published")
    assert knos("cite", "milestone", "99")[0] == 1
    rc, said = knos("verify", row["hash"])
    assert rc == 0 and said == reg.said(reg.verify(row["hash"])) + "\n"
    body = json.loads((ROOT / "terms" / "bugfix" / "1.json").read_text(encoding="utf-8"))
    spaced = tmp_path / "terms.json"
    spaced.write_text(json.dumps(body["terms"], indent=4, sort_keys=True), encoding="utf-8")       # other spacing, the same terms
    rc, said = knos("verify", str(spaced))
    assert rc == 0 and "template bugfix version 1" in said
    assert knos("verify", "0" * 64) == (1, "not a published template\n")
    # the wheel's copy is read first, and it is the registry itself
    packaged = Path(shutil.copytree(ROOT / "terms", tmp_path / "_terms"))
    monkeypatch.setattr(pkg, "PLACES", (packaged, tmp_path / "absent"))
    assert pkg.where() == packaged and knos("cite", "feature-blackbox", "1") == (0, f"{line}\n{url}\n")
    monkeypatch.setattr(pkg, "PLACES", (tmp_path / "absent",))
    rc, said = knos("cite", "bugfix")
    assert rc == 1 and "not in this installation" in said and "terms/index.json" in said and "Traceback" not in said
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '[tool.hatch.build.targets.wheel.force-include]\n"terms" = "knos/_terms"' in project.replace("\r\n", "\n") and '"/terms"' in project


def test_the_standard_states_the_canonical_form_the_code_writes():
    doc = (ROOT / "docs" / "TERMS.md").read_text(encoding="utf-8")
    assert doc.startswith("# Knos Terms 1\n") and "Acceptance is governed by Knos Terms 1, template <name> version <n>, sha256 <hash>" in doc
    assert f"at most {terms.MAX_BYTES} bytes" in doc
    for key in sorted(terms._KEYS | terms._ORDER_KEYS):                     # every field the reader takes has its line
        assert f"| `{key}` | " in doc, key
    assert "`accept`, `checks`, `deny`, `image`, `mode`, `paths`, `policy`,\n  `reserve`, `v`, `vendor`" in doc
    body = json.loads((ROOT / "terms" / "bugfix" / "1.json").read_text(encoding="utf-8"))
    assert f"    {body['terms_json']}\n" in doc and f"`{body['terms_hash']}`: the template `bugfix`, version 1" in doc   # the example is a published version
    odd = {**body["terms"], "paths": ["src/\u00e9/**"], "image": "ghcr.io/o/judge@sha256:" + "a" * 64, "mode": "tests", "accept": "b" * 64, "vendor": 7, "policy": "c" * 64}
    raw = terms.canonical(odd)                                              # the four rules, on terms with every field
    assert raw == json.dumps(odd, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") and b"src/\\u00e9/**" in raw
    assert list(json.loads(raw)) == ["accept", "checks", "deny", "image", "mode", "paths", "policy", "reserve", "v", "vendor"]
    for word in ("billion", "ARR", "immutable", "audited"):
        assert word not in doc


def test_the_terms_page_names_templates_and_copies_the_sentence_in_a_browser(tmp_path):
    """web/terms.js against the committed registry: first its own canonical form and sha256 with no browser, then the
    page in headless Chromium (tests/web/terms.mjs says what it holds)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    site = Path(shutil.copytree(ROOT / "web", tmp_path / "site"))           # the site serves web/ at its root, and terms/ beside it
    shutil.copytree(ROOT / "terms", site / "terms")
    (tmp_path / "package.json").write_text('{"type": "module"}\n', encoding="utf-8")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "terms.mjs"), str(site)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170)
    failed = "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert run.returncode == 0, failed
    assert "the page's sha256 of them is the hash the index lists" in run.stdout
    if "SKIP the browser part" in run.stdout:
        pytest.skip(run.stdout.split("SKIP the browser part: ", 1)[1].splitlines()[0])
    assert "the Terms page holds" in run.stdout and "the page asked nobody but this site" in run.stdout
