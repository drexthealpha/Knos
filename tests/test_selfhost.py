"""The customer-hosted bundle (deploy/, src/knos/selfhost.py, docs/SELFHOST.md): the config is checked before anything
starts, keys are only ever named by file path, the compose file names only images built from digest-pinned bases, the
Dockerfile installs every package by its hash, and what `plan` prints is what compose defines. No network: the site's
server is asked once on the loopback."""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from knos import selfhost

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
ADDR = "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k"       # knos_pay's pinned id
KEY = json.dumps(list(range(64)))                           # a fixed 64-byte "keypair" file's text (never used to sign here)

GOOD = """
[chain]
cluster = "devnet"
rpc = "https://api.devnet.solana.com"

[keys]
relay = "secrets/relay.json"
relay_more = ["secrets/relay2.json"]
github_token = "secrets/gh"
record = "secrets/record.json"

[record]
offer = "offer.json"
records = "records"

[relay]
repos = ["acme/payments"]
workers = 2

[site]
enabled = true
"""


def _write(tmp_path: Path, text: str = GOOD) -> Path:
    (tmp_path / "secrets").mkdir()
    for name in ("relay.json", "relay2.json", "record.json"):
        (tmp_path / "secrets" / name).write_text(KEY, encoding="utf-8")
    (tmp_path / "secrets" / "gh").write_text("gh-test-token\n", encoding="utf-8")
    (tmp_path / "offer.json").write_text("{}", encoding="utf-8")
    cfg = tmp_path / "knos.toml"
    cfg.write_text(text, encoding="utf-8")
    return cfg


def test_good_config_names_roles_and_key_files(tmp_path):
    cfg = _write(tmp_path)
    c = selfhost.check(cfg.read_text(encoding="utf-8"), tmp_path)
    assert c.errors == [] and c.missing == [] and c.ok(files=True)
    assert c.roles() == ["record", "relay", "site"]
    assert [(r, n) for r, n, _p in selfhost.needs(c)] == [("relay", "relay"), ("relay", "relay_more"), ("relay", "github_token"), ("record", "record")]
    said = "\n".join(selfhost.describe(c))
    assert "the pinned ids" in said and "secrets/relay.json" in said and "identity proxy" in said


def test_example_config_is_good():
    c = selfhost.check((DEPLOY / "knos.example.toml").read_text(encoding="utf-8"))
    assert c.errors == [], c.errors
    assert c.roles() == list(selfhost.ROLES)
    assert c.missing and not c.ok(files=True)          # container paths: not on this machine, said, not an error unless --files


@pytest.mark.parametrize("change, said", [
    (('relay = "secrets/relay.json"', "relay = " + json.dumps(KEY)), "holds a key itself"),
    (('relay = "secrets/relay.json"', 'relay = "4Z7cXSyeFR8wNGMVXUE1TwtKn5D5Vu7FzEv69dokLv7KrQk7h6pu4LF8ZRR9yQBhc7uYM6RXTQ8B3Hd4E4LRHRbS"'), "holds a key itself"),
    (('cluster = "devnet"', 'cluster = "mainnet-beta"'), "devnet or localnet only"),
    (('rpc = "https://api.devnet.solana.com"', 'rpc = "https://api.mainnet-beta.solana.com"'), "names mainnet"),
    (('rpc = "https://api.devnet.solana.com"', 'rpc = "devnet"'), "chain.rpc must be"),
    (('[site]', '[chain.programs]\nknos_pay = "not-an-address"\n\n[site]'), "is not a Solana address"),
    (('[site]', f'[chain.programs]\nguardian = "{ADDR}"\n\n[site]'), "only knos_oidc"),
    (('repos = ["acme/payments"]', 'repos = ["payments"]'), "owner/name"),
    (('workers = 2', 'workers = 0'), "relay.workers must be"),
    (('github_token = "secrets/gh"\n', ''), "relay needs keys.github_token"),
    (('workers = 2', 'workers = 2\napi_token = "' + "gh" + "p_" + "x" * 36 + '"'), "not a setting of relay"),
    (('[site]', '[sso]\nissuer = "x"\n\n[site]'), "sso.issuer must be"),
    (('[site]', '[auth]\nissuer = "x"\n\n[site]'), "[auth] is not a table"),
    (('offer = "offer.json"', 'offer = 3'), "record.offer must be"),
    (('[chain]', 'x = = 1\n[chain]'), "not TOML"),
])
def test_bad_config_is_refused_with_a_reason(tmp_path, change, said):
    old, new = change
    assert old in GOOD
    c = selfhost.check(GOOD.replace(old, new, 1), tmp_path)
    assert not c.ok(), "accepted"
    assert any(said in e for e in c.errors), c.errors
    assert selfhost.describe(c)[0] == "This config is refused:"


def test_no_role_is_refused():
    c = selfhost.check('[chain]\nrpc = "https://api.devnet.solana.com"\n[site]\nenabled = false\n')
    assert any("no role is enabled" in e for e in c.errors)


def test_address():
    assert selfhost.address(ADDR) and selfhost.address("11111111111111111111111111111111")
    assert not selfhost.address(ADDR[:-1] + "0") and not selfhost.address("abc") and not selfhost.address(None)


def test_cli_check_exit_status(tmp_path, capsys):
    cfg = _write(tmp_path)
    assert selfhost.main(["check", str(cfg), "--files"]) == 0
    (tmp_path / "secrets" / "gh").unlink()
    assert selfhost.main(["check", str(cfg)]) == 0
    assert selfhost.main(["check", str(cfg), "--files"]) == 1
    assert "MISSING: keys.github_token" in capsys.readouterr().out


def test_environment_reads_key_files_and_writes_staging_ids(tmp_path):
    cfg = _write(tmp_path, GOOD.replace("[site]", f'[chain.programs]\nknos_pay = "{ADDR}"\n\n[site]'))
    c = selfhost.check(cfg.read_text(encoding="utf-8"), tmp_path)
    env = selfhost.environment(c, "relay", tmp_path, state=tmp_path / "state")
    assert env["KNOS_RELAY_KEY"] == KEY and json.loads(env["KNOS_RELAY_KEYS"]) == [list(range(64))] * 2
    assert env["GH_TOKEN"] == "gh-test-token" and env["KNOS_RELAY_REPOS"] == "acme/payments" and env["KNOS_RELAY_WORKERS"] == "2"
    assert env["KNOS_CLUSTER"] == "devnet" and json.loads(Path(env["KNOS_PROGRAM_IDS"]).read_text(encoding="utf-8")) == {"knos_pay": ADDR}
    assert "KNOS_PROGRAM_IDS" not in selfhost.environment(c, "site", tmp_path, state=tmp_path / "nowhere")
    assert "KNOS_RELAY_KEY" not in selfhost.environment(c, "record", tmp_path, state=tmp_path / "state")
    (tmp_path / "secrets" / "gh").unlink()
    with pytest.raises(SystemExit, match="keys.github_token"):
        selfhost.environment(c, "relay", tmp_path, state=tmp_path / "state")


def test_argv_of_each_role(tmp_path):
    cfg = _write(tmp_path)
    c = selfhost.check(cfg.read_text(encoding="utf-8"), tmp_path)
    rec = selfhost.argv_of(c, "record", tmp_path, state=tmp_path / "s")
    assert rec[0] == str(tmp_path / "offer.json") and rec[rec.index("--key") + 1] == str(tmp_path / "secrets/record.json")
    assert rec[rec.index("--port") + 1] == "8402" and rec[rec.index("--records") + 1] == str(tmp_path / "records")
    assert selfhost.argv_of(c, "relay") == ["relay", "--serve", "3600", "--every", "3"]
    from knos import flow
    assert flow.takes(selfhost.argv_of(c, "relay"))             # the relay's own entry reads these words


def test_run_refuses_a_bad_config_before_anything_starts(tmp_path, capsys):
    cfg = _write(tmp_path, GOOD.replace('cluster = "devnet"', 'cluster = "mainnet-beta"'))
    assert selfhost.run("relay", cfg) == 2
    assert "devnet or localnet only" in capsys.readouterr().err
    cfg.write_text(GOOD.replace("[site]\nenabled = true", "[site]\nenabled = false"), encoding="utf-8")
    assert selfhost.run("site", cfg) == 2


def _compose() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((DEPLOY / "compose.yaml").read_text(encoding="utf-8"))


DIGEST = re.compile(r"^FROM\s+\S+@sha256:[0-9a-f]{64}(\s+AS\s+\w+)?$", re.M)


def test_compose_parses_and_names_only_pinned_images():
    doc = _compose()
    services = doc["services"]
    assert set(services) == set(selfhost.ROLES)
    for name, s in services.items():
        image = s.get("image", "")
        if "@sha256:" in image:
            continue
        # a local image: it must be built here, never pulled, from the Dockerfile whose every base is pinned by digest
        assert s.get("pull_policy") == "build" and s["build"]["dockerfile"] == "deploy/Dockerfile", name
        assert s["command"][:2] == ["run", name] and s["read_only"] is True
        for port in s.get("ports", []):
            assert port.startswith("127.0.0.1:"), (name, port)     # behind the buyer's identity proxy, never open
        assert "./knos.toml:/etc/knos/knos.toml:ro" in s["volumes"] and "./secrets:/run/secrets:ro" in s["volumes"]
    froms = [ln for ln in (DEPLOY / "Dockerfile").read_text(encoding="utf-8").splitlines() if ln.startswith("FROM ")]
    assert froms and all(DIGEST.match(ln) for ln in froms), froms
    assert len({ln.split()[1] for ln in froms}) == 1               # one base, one digest
    images = re.findall(r"^\s*image:\s*(\S+)", (DEPLOY / "compose.yaml").read_text(encoding="utf-8"), re.M)
    assert images == ["knos-selfhost:local"]                      # the one image, written once (the anchor), nothing pulled


def test_plan_is_what_compose_defines(capsys):
    services = _compose()["services"]
    assert selfhost.main(["plan"]) == 0
    said = capsys.readouterr().out
    for s in selfhost.services(selfhost.Checked({r: {} for r in selfhost.ROLES})):
        assert s["command"] == services[s["service"]]["command"]
        if s["port"]:
            assert f"127.0.0.1:{s['port']}:{s['port']}" in services[s["service"]]["ports"]
            assert f"127.0.0.1:{s['port']}" in said
        assert s["command"][-1] == "/etc/knos/knos.toml" == selfhost.CONFIG.as_posix()     # the path inside the container, on every OS (a Windows str() gave \etc\knos)
    assert said.rstrip().endswith("up -d --build record relay site")


def test_dockerfile_installs_by_hash_only():
    text = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    installs = re.findall(r"pip install[^\n\\]*", text)
    assert len(installs) == 2 and all("--require-hashes" in i and "--no-deps" in i and "--only-binary :all:" in i for i in installs)
    assert "requirements/faucet.txt" in text and "tail -n 1 sign.txt" in text
    assert not re.search(r"pip install[^\n]*(?<!-r )\b(knos|\.)(\s|$)", text)      # never from the source tree, never by name alone
    for f in ("faucet.txt", "sign.txt"):       # each line the image installs carries its hash
        reqs = [ln for ln in (ROOT / "requirements" / f).read_text(encoding="utf-8").splitlines() if re.match(r"^[A-Za-z]", ln)]
        assert reqs and all("==" in ln for ln in reqs)
    text = (ROOT / "requirements" / "sign.txt").read_text(encoding="utf-8")
    if "\nknos==" not in text:     # a bumped tree before its release locks the wheel (as tests/test_pypi_wait.py): the line it appends
        assert not re.search(r"(?m)^knos", text)
        text += "knos" "==0.3.21 --hash=sha256:c848187f1881c4d5986c8be8a8f89a1abe619bf1b0df689b411efd2aca54e82a\n"
    last = text.splitlines()[-1]
    assert re.fullmatch(r"knos==[0-9][0-9.]* --hash=sha256:[0-9a-f]{64}", last)
    pattern = re.search(r"grep -Eq '([^']+)' knos.txt", (DEPLOY / "Dockerfile").read_text(encoding="utf-8"))
    assert pattern and re.fullmatch(pattern.group(1).strip("^$"), last)     # the image's own check takes that line


def test_site_server_serves_files_and_no_listing(tmp_path):
    (tmp_path / "index.html").write_text("<title>k</title>", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    httpd = selfhost.serve_site(tmp_path, 0, host="127.0.0.1")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(base + "/index.html", timeout=5) as r:
            assert r.read() == b"<title>k</title>" and r.headers["X-Content-Type-Options"] == "nosniff"
        with pytest.raises(urllib.error.HTTPError) as got:
            opener.open(base + "/sub/", timeout=5)
        assert got.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(5)


def test_selfhost_doc_states_the_limits():
    doc = (ROOT / "docs" / "SELFHOST.md").read_text(encoding="utf-8")
    for must in ("not been run in any cloud", "fake sign-in provider only", "oauth2-proxy", "Pomerium", "127.0.0.1", "knos selfhost check",
                 "05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f"):
        assert must in doc, must
