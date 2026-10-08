"""The two interface crates and the JavaScript client can be published as they are: the metadata each registry asks
for is there, nothing depends on a path, the release publishes them without a stored secret once their first version
exists, and docs/RELEASE.md says how that first version gets there. `cargo publish --dry-run` and `npm publish
--dry-run` themselves are run when the tools are on PATH and KNOS_PUBLISH_DRY_RUN=1 (they compile; minutes)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
CRATES = ("knos-oidc-interface", "knos-pay-interface")
REPO = "https://github.com/drexthealpha/Knos"
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def _version() -> str:
    return re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)


@pytest.mark.parametrize("name", CRATES)
def test_a_crate_has_what_crates_io_asks_for_and_no_dependency_it_cannot_resolve(name):
    here = ROOT / "crates" / name
    doc = tomllib.loads((here / "Cargo.toml").read_text(encoding="utf-8"))
    p = doc["package"]
    # its version is the package's, or, while scripts/bump_version.py holds the program crates (a release that changes
    # no program: a version is in a build's bytes), the version of the builds made from it
    bump = (ROOT / "scripts" / "bump_version.py").read_text(encoding="utf-8")
    held = f'"{name}"' in re.search(r"(?m)^PROGRAMS_FROZEN: tuple\[str, \.\.\.\] = \((.*)\)$", bump).group(1)
    version = re.search(r'(?m)^FROZEN_AT = "([^"]+)"$', bump).group(1) if held else _version()
    assert (p["name"], p["version"], p["license"], p["repository"], p["readme"], p["edition"]) == (name, version, "MIT", REPO, "README.md", "2021")
    assert 20 <= len(p["description"]) <= 200 and re.fullmatch(r"1\.\d+", p["rust-version"])
    # crates.io: at most five keywords, each up to 20 characters of [a-z0-9_-+]; categories are slugs it knows
    assert 1 <= len(p["keywords"]) <= 5 and all(re.fullmatch(r"[a-z0-9][a-z0-9_+-]{0,19}", k) for k in p["keywords"]) and "solana" in p["keywords"]
    assert p["categories"] and set(p["categories"]) <= {"no-std", "cryptography::cryptocurrencies"} and len(p["categories"]) <= 5
    assert (here / "README.md").is_file() and (here / "Cargo.lock").is_file() and (here / "src" / "lib.rs").is_file()
    # a dependency is a version from crates.io: a path or a git source would be refused at publish
    for table in ("dependencies", "dev-dependencies", "build-dependencies"):
        for dep, spec in (doc.get(table) or {}).items():
            assert isinstance(spec, str) or (set(spec) <= {"version", "features", "default-features", "optional"} and "version" in spec), (name, table, dep, spec)
    assert "workspace" not in doc and not (ROOT / "crates" / "Cargo.toml").exists()        # each crate stands alone
    # a test that reads files outside the crate is left out of the package, so the packaged crate's tests still build
    for test in (here / "tests").glob("*.rs"):
        if "../../" in test.read_text(encoding="utf-8"):
            assert f"tests/{test.name}" in p.get("exclude", []), f"{name}: tests/{test.name} reads outside the crate and is packaged"


def test_the_oidc_crate_depends_on_nothing_and_the_pay_crate_on_solana_program_alone():
    oidc, pay = (tomllib.loads((ROOT / "crates" / c / "Cargo.toml").read_text(encoding="utf-8")) for c in CRATES)
    assert oidc.get("dependencies", {}) == {} and pay["dependencies"] == {"solana-program": "2.2"}
    assert "#![no_std]" in (ROOT / "crates" / CRATES[0] / "src" / "lib.rs").read_text(encoding="utf-8")


def test_the_npm_package_has_what_npm_asks_for():
    m = json.loads((ROOT / "sdk" / "settle" / "package.json").read_text(encoding="utf-8"))
    assert (m["name"], m["version"], m["license"], m["type"]) == ("knos-settle", _version(), "MIT", "module")
    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]*", m["name"]) and "private" not in m and len(m["description"]) >= 20
    assert m["repository"] == {"type": "git", "url": f"git+{REPO}.git", "directory": "sdk/settle"}       # npm's provenance compares this with the run's repository
    assert m["publishConfig"] == {"access": "public", "registry": "https://registry.npmjs.org/"} and m["bugs"]["url"] == f"{REPO}/issues"
    assert m["engines"] == {"node": ">=20"} and m["types"] == "./index.d.ts" and "solana" in m["keywords"]
    for f in m["files"]:
        assert (ROOT / "sdk" / "settle" / f).is_file(), f
    for target in m["exports"].values():
        assert {target["types"][2:], target["default"][2:]} <= set(m["files"])
    assert not any(k in m for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies", "bundledDependencies"))


def _job(name: str) -> str:
    return re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:\n|\Z)", RELEASE).group(1)


def test_the_release_publishes_all_three_without_a_stored_secret_once_a_first_version_exists():
    crates, npm = _job("crates-trusted"), _job("npm-trusted")
    for job, after in ((crates, "crates"), (npm, "npmjs")):
        # behind the gate, after the token job (so a version is never published twice), with this run's identity and no secret
        assert f"needs: [tests, pypi, {after}]" in job and "id-token: write" in job and "contents: read" in job and "secrets." not in job
        # what it says of a package that is not on its registry yet, or of a version the registry has, is the one
        # rule's (scripts/release.py registry-plan: tests/test_release_gate.py runs it)
        assert "python3 scripts/release.py registry-plan " in job and "published by hand" in job
    plan = (ROOT / "scripts" / "release.py").read_text(encoding="utf-8")
    assert "Its first version is published by hand (docs/RELEASE.md)" in plan and "already has {name} {version}" in plan
    pins = json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"]
    sha = pins["rust-lang/crates-io-auth-action@v1.0.5"]
    assert f"uses: rust-lang/crates-io-auth-action@{sha} # v1.0.5" in crates and "CARGO_REGISTRY_TOKEN: ${{ steps.auth.outputs.token }}" in crates
    assert f"crate: [{', '.join(CRATES)}]" in crates and crates.rstrip().endswith("cargo publish --locked")
    assert "package-manager-cache: false" in npm and "node-version: 24" in npm and "11.5.1" in npm and "NODE_AUTH_TOKEN" not in npm
    assert npm.rstrip().endswith("npm publish --provenance --access public") and npm.index("node test.mjs") < npm.index("npm publish")
    # the token job covers both crates too
    assert all(f"cd crates/{c}" in _job("crates") for c in CRATES)


def test_the_release_page_gives_the_first_publish_and_says_each_package_is_published():
    page = (ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8")
    part = page.split("## Publishing the crates and the npm package")[1].split("\n## ")[0]
    for line in ("cargo login", "(cd crates/knos-oidc-interface && cargo publish --locked)", "(cd crates/knos-pay-interface  && cargo publish --locked)",
                 "npm login", "(cd sdk/settle && node test.mjs && npm publish --access public)", "cargo publish --dry-run --locked", "npm publish --dry-run"):
        assert line in part, line
    # the first versions went up by hand on 8 October 2026: the page names each with its registry, version and page,
    # and no longer says that none is published or that the first publish has not been done
    assert "by hand, once, by the owner, signed in to each registry" in part and "it was done on 8 October 2026 for all three" in part
    flat = " ".join(part.split())
    for name, version, url in (("knos-oidc-interface", "0.3.14", "https://crates.io/crates/knos-oidc-interface"),
                               ("knos-pay-interface", "0.3.14", "https://crates.io/crates/knos-pay-interface"),
                               ("knos-settle", "0.3.20", "https://www.npmjs.com/package/knos-settle")):
        assert f"`{name}` {version}" in flat and f"({url})" in flat, name
    for stale in ("none published yet", "has not been done", "Neither has been published", "Until the first publish"):
        assert stale not in flat, stale
    assert "workflow `release.yml`" in part and "crates-trusted" in part and "npm-trusted" in part
    # a package is published at its own version: the page says why a held crate's is not the tag's, and names the one rule
    assert "A package is published at ITS OWN version" in part and "python scripts/release.py registry-plan" in part and "`PROGRAMS_FROZEN`" in part


def test_copying_the_gate_is_a_readme_and_a_template_and_no_outside_user_is_claimed():
    gate = ROOT / "examples" / "oidc_gate"
    readme, template = (gate / "README.md").read_text(encoding="utf-8"), (gate / "template.rs").read_text(encoding="utf-8")
    compose = (ROOT / "docs" / "COMPOSE.md").read_text(encoding="utf-8")
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    lib = (ROOT / "crates" / CRATES[0] / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "## Use it from your program in ten minutes" in compose and ids["knos_oidc"] in compose and ids["knos_oidc"] in readme
    assert "no program outside it is known to read a token yet" in " ".join(compose.split())
    assert "no program outside this repository is known to read a token yet" in " ".join(readme.split())
    # every call the README and the template show is a function the crate has
    for text in (readme, template):
        for call in ("Token::read(", ".check_key(", ".issuer()", ".audience()", '.claim("job_workflow_ref")', '.claim_u64("repository_id")', ".starts_with("):
            assert call in text, call
    for fn in ("pub fn read(", "pub fn check_key(", "pub fn issuer(", "pub fn audience(", "pub fn claim(", "pub fn claim_u64(", "pub fn starts_with("):
        assert fn in lib, fn
    code = [ln for ln in template.splitlines() if ln.strip() and not ln.lstrip().startswith("//")]
    assert len(code) <= 30 and template.count("// CHANGE") == 3


@pytest.mark.skipif(os.environ.get("KNOS_PUBLISH_DRY_RUN") != "1", reason="set KNOS_PUBLISH_DRY_RUN=1: it compiles each crate (minutes) and asks both registries")
def test_the_dry_runs_pass():
    cargo, npm = shutil.which("cargo"), shutil.which("npm")
    if not cargo or not npm:
        pytest.skip("needs cargo and npm")
    for c in CRATES:
        r = subprocess.run([cargo, "publish", "--dry-run", "--locked", "--allow-dirty"], cwd=ROOT / "crates" / c, capture_output=True, text=True, check=False)
        assert r.returncode == 0 and "aborting upload due to dry run" in r.stderr, r.stderr[-2000:]
    for args in (["pack", "--dry-run"], ["publish", "--dry-run"]):
        r = subprocess.run([npm, *args], cwd=ROOT / "sdk" / "settle", capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr[-2000:]
