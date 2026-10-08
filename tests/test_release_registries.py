"""`scripts/release.py registry-plan`: one line per registry, OK or blocked with the reason. "Signed in" is asked
without starting a sign-in: cargo's stored token, and `npm whoami`. docs/RELEASE.md gives the same commands in order."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("knos_release_registries", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = release
_spec.loader.exec_module(release)


def packs(cmd, **kw):
    out = json.dumps([{"files": [{"path": "index.js"}]}]) if cmd[0] == "npm" else ""
    return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="    Packaged 9 files\n" if cmd[0] == "cargo" else "")


def whoami(code: int, out: str = "", err: str = ""):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout=out, stderr=err)


def test_signed_in_is_cargos_stored_token_and_npm_whoami_and_no_token_is_read(tmp_path):
    assert release.signed_in("crates", env={"CARGO_REGISTRY_TOKEN": "x"}) == (True, "CARGO_REGISTRY_TOKEN is set")
    no, why = release.signed_in("crates", env={}, home=tmp_path)
    assert not no and "CARGO_REGISTRY_TOKEN is not set" in why and "credentials.toml is missing or empty" in why and "`cargo login` was never run here" in why
    cargo = tmp_path / ".cargo"
    cargo.mkdir()
    (cargo / "credentials.toml").write_text("", encoding="utf-8")
    assert release.signed_in("crates", env={}, home=tmp_path)[0] is False                  # an empty file is no token
    (cargo / "credentials.toml").write_text('[registry]\ntoken = "a-word-that-stands-for-a-token"\n', encoding="utf-8")
    yes, why = release.signed_in("crates", env={}, home=tmp_path)
    assert yes and "credentials.toml" in why and "a-word-that-stands-for-a-token" not in why
    assert release.signed_in("crates", env={"CARGO_HOME": str(cargo)})[0] is True
    assert release.signed_in("npm", run=whoami(0, "drex\n")) == (True, "`npm whoami` answers drex")
    assert release.signed_in("npm", run=whoami(1, err="npm error code ENEEDAUTH\n")) == (False, "not signed in: `npm whoami` did not answer with a name (ENEEDAUTH)")
    assert release.signed_in("npm", run=whoami(1, err="npm error code E401\n"))[1].endswith("(E401)")

    def gone(cmd, **kw):
        raise FileNotFoundError("npm")
    assert release.signed_in("npm", run=gone) == (False, "not signed in: `npm whoami` could not be asked (FileNotFoundError)")


def test_the_plan_says_ok_or_blocked_per_registry_with_the_reason_and_the_commands_in_order():
    code, lines = release.registry_overview(run=packs, signin=lambda registry: (registry == "crates", "CARGO_REGISTRY_TOKEN is set" if registry == "crates" else "not signed in: `npm whoami` did not answer with a name (ENEEDAUTH)"))
    crates, npm = lines[-3], lines[-2]
    assert code == 0 and lines[-1].startswith("ready:")                                     # blocked by a sign-in is not red
    assert crates.startswith("crates.io: OK: CARGO_REGISTRY_TOKEN is set. In this order: ")
    first, second = crates.index("crates/knos-oidc-interface"), crates.index("crates/knos-pay-interface")
    assert first < second and crates.count("cargo publish --dry-run --locked") == 2 and crates.index("--dry-run") < crates.index("cargo publish --locked")
    assert npm == "npm: blocked: not signed in: `npm whoami` did not answer with a name (ENEEDAUTH). Nothing is published there, no sign-in is started and no account is created."
    # a package that does not pack blocks its registry whoever is signed in, and that is red
    code, lines = release.registry_overview(run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 101, stdout="", stderr="error\n"), signin=lambda r: (True, "signed in"))
    assert code == 1 and lines[-3] == "crates.io: blocked: knos-oidc-interface does not pack; knos-pay-interface does not pack" and lines[-2].startswith("npm: blocked: knos-settle does not pack")
    # online, with every version on its registry already: OK, and nothing to publish
    sdk = json.loads((ROOT / "sdk" / "settle" / "package.json").read_text(encoding="utf-8"))["version"]
    index = {"knos-oidc-interface": b'{"vers": "0.3.14"}\n', "knos-pay-interface": b'{"vers": "0.3.14"}\n', "knos-settle": json.dumps({"versions": {sdk: {}}}).encode()}
    code, lines = release.registry_overview(online=True, fetch=lambda url: index[url.rsplit("/", 1)[1]], run=packs, signin=lambda r: (True, "signed in"))
    assert code == 0 and lines[-3] == "crates.io: OK: nothing to publish, the registry has every version (signed in)" and lines[-2].startswith("npm: OK: nothing to publish")
    # without `signin` (the tests of the plan itself) no such line is added
    assert not [ln for ln in release.registry_overview(run=packs)[1] if ln.startswith(("crates.io: ", "npm: "))]


def test_the_release_page_says_what_signed_in_means_and_gives_the_commands_in_order():
    page = (ROOT / "docs" / "RELEASE.md").read_text(encoding="utf-8")
    part = page.split("### Registries: is this machine signed in, and the commands in order")[1].split("\nA package is published at ITS OWN version")[0]
    assert "python scripts/release.py registry-plan" in part and "`OK`" in part and "`blocked`" in part
    assert "`CARGO_REGISTRY_TOKEN` is set" in part and "credentials.toml" in part and "`npm whoami` answers with a user name" in part
    for registry, name in release.PACKAGES:
        assert release.FIRST[registry].format(name=name).replace("&& (cd crates", "&&  (cd crates") in part.replace("  ", " ").replace("&& (cd crates", "&&  (cd crates"), name
    assert part.index("knos-oidc-interface && cargo publish --dry-run") < part.index("knos-pay-interface  && cargo publish --dry-run") < part.index("npm publish --dry-run")
    assert "no `cargo login`, no\n`npm login`, no account" in part and "Neither has been published" in part
