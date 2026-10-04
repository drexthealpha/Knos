"""What other teams build on: the Rust interface crate (crates/knos-oidc-interface), the IDLs (idl/), the npm package
of the JavaScript client (sdk/settle). They carry one version, the crate points at the deployed program, its fixture
is what the test build of knos-oidc writes, and the npm tarball holds the client and nothing else."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "crates" / "knos-oidc-interface"
SDK = ROOT / "sdk" / "settle"


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _locked(lock: str, package: str) -> str:
    return re.search(rf'name = "{package}"\nversion = "([^"]+)"', lock).group(1)


def _versions() -> dict[str, str]:
    """Every place one of these artifacts states its version, or the release tag it is installed from."""
    v = {
        "crates/knos-oidc-interface/Cargo.toml": re.search(r'^version = "([^"]+)"', _read("crates", "knos-oidc-interface", "Cargo.toml"), re.M).group(1),
        "crates/knos-oidc-interface/Cargo.lock": _locked(_read("crates", "knos-oidc-interface", "Cargo.lock"), "knos-oidc-interface"),
        "examples/oidc_gate/Cargo.lock": _locked(_read("examples", "oidc_gate", "Cargo.lock"), "knos-oidc-interface"),
        "sdk/settle/package.json": json.loads(_read("sdk", "settle", "package.json"))["version"],
    }
    for idl in sorted((ROOT / "idl").glob("*.json")):
        v[f"idl/{idl.name}"] = json.loads(idl.read_text(encoding="utf-8"))["version"]
    if (ROOT / "server.json").exists():
        v["server.json"] = json.loads(_read("server.json"))["version"]
    # the install lines people copy
    for name, text in (("crates/knos-oidc-interface/README.md", _read("crates", "knos-oidc-interface", "README.md")),
                       ("examples/oidc_gate/Cargo.toml", _read("examples", "oidc_gate", "Cargo.toml"))):
        v[f"{name} (tag)"] = re.search(r'git = "https://github.com/drexthealpha/Knos", tag = "v([^"]+)"', text).group(1)
    readme = _read("sdk", "settle", "README.md")
    tag, tarball = re.search(r"releases/download/v([\d.]+)/knos-settle-([\d.]+)\.tgz", readme).groups()
    v["sdk/settle/README.md (release)"], v["sdk/settle/README.md (tarball)"] = tag, tarball
    v["sdk/settle/README.md (cdn)"] = re.search(r"cdn\.jsdelivr\.net/gh/drexthealpha/Knos@v([\d.]+)/sdk/settle/index\.js", readme).group(1)
    return v


def test_the_artifacts_carry_one_version():
    v = _versions()
    assert len(v) >= 11 and len(set(v.values())) == 1, v


def test_it_is_the_version_of_the_python_package():
    """The crate, the IDLs and the npm package are released with the Python package, under its version (pyproject.toml)."""
    version = re.search(r'^version = "([^"]+)"', _read("pyproject.toml"), re.M).group(1)
    stale = {where: got for where, got in _versions().items() if got != version}
    assert not stale, f"pyproject.toml says {version}; these do not: {stale}"


def test_the_npm_tarball_holds_the_client_and_nothing_else():
    # on Windows the npm on PATH is a .cmd; the extensionless `npm` beside it is a shell script CreateProcess cannot run
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        pytest.skip("needs npm")
    r = subprocess.run([npm, "pack", "--dry-run", "--json"], cwd=str(SDK), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    [packed] = json.loads(r.stdout)
    manifest = json.loads(_read("sdk", "settle", "package.json"))
    assert {f["path"] for f in packed["files"]} == {"package.json", "index.js", "index.d.ts", "agent.js", "agent.d.ts", "passkey.js", "passkey.d.ts", "README.md"}
    assert (packed["name"], packed["version"]) == ("knos-settle", manifest["version"])
    assert packed["filename"] == f"knos-settle-{manifest['version']}.tgz"       # the file name in the README's install line
    assert not list(SDK.glob("*.tgz")), "a dry run writes nothing"
    assert manifest["type"] == "module" and manifest["exports"] == {".": {"types": "./index.d.ts", "default": "./index.js"}, "./agent": {"types": "./agent.d.ts", "default": "./agent.js"},
                                                               "./passkey": {"types": "./passkey.d.ts", "default": "./passkey.js"}} and manifest["license"] == "MIT"
    assert not re.search(r"^\s*import\s|^export\s[^;\n]*\sfrom\s+[\x22\x27]", _read("sdk", "settle", "passkey.js"), re.M), "passkey.js imports nothing: a page loads it alone"
    assert manifest["repository"]["directory"] == "sdk/settle" and manifest["scripts"] == {"test": "node test.mjs"}
    assert not any(k in manifest for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"))


def test_the_interface_crate_names_the_deployed_program_and_depends_on_nothing():
    """`ID`, the first constant in the file and the one `Token::read` checks, is the SECOND deployment's address
    (programs-v2/program_ids.json): a program that names no deployment reads the one whose keys expire and can be revoked."""
    ids = json.loads(_read("programs-v2", "program_ids.json"))
    lib = (CRATE / "src" / "lib.rs").read_text(encoding="utf-8")
    assert re.search(r'pub const ID_STR: &str = "(\w+)";', lib).group(1) == ids["knos_oidc"]
    body = re.search(r"pub const ID: \[u8; 32\] = \[(.*?)\];", lib, re.S).group(1)
    assert bytes(int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})", body)) == bytes(Pubkey.from_string(ids["knos_oidc"]))
    assert "pub fn read(owner: &[u8; 32], data: &'a [u8], now: i64) -> Result<Token<'a>, Error> { Self::read_from(&ID, owner, data, now) }" in lib
    assert "pub fn read_any(owner: &[u8; 32], data: &'a [u8], now: i64) -> Result<Token<'a>, Error> { Self::read_any_from(&ID, owner, data, now) }" in lib
    v2 = lib.split("pub mod v2 {")[1].split("\n}\n")[0]
    assert "pub const ID: [u8; 32] = super::ID;" in v2 and "pub const ID_STR: &str = super::ID_STR;" in v2 and "Token::read_from(&ID, owner, data, now)" in v2
    assert "#![no_std]" in lib
    manifest = (CRATE / "Cargo.toml").read_text(encoding="utf-8")
    deps = manifest.split("[dependencies]")[1].split("[features]")[0]
    assert not [line for line in deps.splitlines() if line.strip() and not line.startswith("#")], deps
    # the example consumer reads tokens with the interface crate only, as an outside program would
    gate = _read("examples", "oidc_gate", "Cargo.toml")
    assert 'knos-oidc-interface = { path = "../../crates/knos-oidc-interface" }' in gate and "knos_oidc" not in gate
    readme = (CRATE / "README.md").read_text(encoding="utf-8")
    assert ids["knos_oidc"] in readme and "idl/knos_oidc_v2.json" in readme


def test_the_interface_crate_reads_the_first_deployment_only_by_name():
    """The first deployment's address (programs/program_ids.json) is in the `v1` module and nowhere else: its keys
    never expire and cannot be revoked, so no default reads it."""
    ids = json.loads(_read("programs", "program_ids.json"))
    lib = (CRATE / "src" / "lib.rs").read_text(encoding="utf-8")
    v1 = lib.split("pub mod v1 {")[1].split("\n}\n")[0]
    assert re.search(r'pub const ID_STR: &str = "(\w+)";', v1).group(1) == ids["knos_oidc"]
    body = re.search(r"pub const ID: \[u8; 32\] = \[(.*?)\];", v1, re.S).group(1)
    assert bytes(int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})", body)) == bytes(Pubkey.from_string(ids["knos_oidc"]))
    assert "Token::read_from(&ID, owner, data, now)" in v1
    code = "\n".join(line for line in lib.split("#[cfg(test)]")[0].splitlines() if not line.lstrip().startswith("//"))
    assert code.count(ids["knos_oidc"]) == 1 and lib.index("pub const ID: [u8; 32]") < lib.index("pub mod v2 {") < lib.index("pub mod v1 {")
    # the example consumer is a first-deployment program and says so
    assert "v1::read(&token.owner.to_bytes()" in _read("examples", "oidc_gate", "src", "lib.rs")
    readme = (CRATE / "README.md").read_text(encoding="utf-8")
    assert f"`{ids['knos_oidc']}` (`v1::ID`, `v1::ID_STR`)" in readme


def test_the_interface_fixture_is_what_knos_oidc_writes():
    """crates/knos-oidc-interface/tests/fixtures: a token account verified by the test build of knos-oidc, regenerated
    here byte for byte (nothing in it is random), and the claims the crate's tests expect are the ones in its bytes."""
    pytest.importorskip("solders.litesvm")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "interface_fixture.py"), "--check"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout
    from knos.settle import oidc
    want = json.loads((CRATE / "tests" / "fixtures" / "verified_token.json").read_text(encoding="utf-8"))
    tok = oidc.read_token((CRATE / "tests" / "fixtures" / "verified_token.bin").read_bytes())
    assert tok.verified and (tok.issuer, tok.exp, tok.claims()) == (want["issuer"], want["exp"], want["claims"])
    assert want["owner"] == str(oidc.OIDC_ID) and want["exp"] == want["now"] + 300
    # the second deployment's fixture: the same token from the same payer, so the same bytes but the key's address
    from knos.settle.v2 import oidc as oidc2
    want2 = json.loads((CRATE / "tests" / "fixtures" / "verified_token_v2.json").read_text(encoding="utf-8"))
    first, second = (CRATE / "tests" / "fixtures" / "verified_token.bin").read_bytes(), (CRATE / "tests" / "fixtures" / "verified_token_v2.bin").read_bytes()
    tok2 = oidc2.read_token(second)
    assert tok2.verified and (tok2.issuer, tok2.exp, tok2.claims(), tok2.payer) == (tok.issuer, tok.exp, tok.claims(), tok.payer)
    assert want2["owner"] == str(oidc2.OIDC_ID) != want["owner"] and want2["claims"] == want["claims"]
    assert len(first) == len(second) and [i for i in range(len(first)) if first[i] != second[i]][0] >= 18
    assert first[:18] == second[:18] and first[50:] == second[50:] and tok2.key != tok.key
