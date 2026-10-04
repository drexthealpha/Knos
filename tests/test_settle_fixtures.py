"""sdk/settle/fixtures.json is what the Python client produces today (so other clients can test against it), and the
program ids the client uses are the ones the programs are built with."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fixtures_are_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "settle_fixtures.py"), "--check"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


def test_program_ids_agree_everywhere():
    ids = json.loads((ROOT / "programs" / "program_ids.json").read_text())
    assert json.loads((ROOT / "src" / "knos" / "settle" / "program_ids.json").read_text()) == ids
    pay_rs = (ROOT / "programs" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert re.search(r'OIDC_ID: Pubkey = pubkey!\("(\w+)"\)', pay_rs).group(1) == ids["knos_oidc"]


def test_the_rotate_pin_is_one_commit_everywhere():
    """ROTATE_SHA in the verifier's binary, the commit keys.yml calls the rotate workflow at, and the pin
    `knos mainnet-check` looks for are the same 40 hex characters."""
    ids = json.loads((ROOT / "programs" / "program_ids.json").read_text())
    pins = (ROOT / "programs" / "knos_oidc" / "src" / "pins.rs").read_text(encoding="utf-8")
    sha = re.search(r'pub const ROTATE_SHA: &\[u8; 40\] = b"([0-9a-f]{40})";', pins).group(1)
    keys = (ROOT / ".github" / "workflows" / "keys.yml").read_text(encoding="utf-8")
    assert re.search(r"drexthealpha/knos-oidc-rotate/\.github/workflows/rotate\.yml@([0-9a-f]{40})", keys).group(1) == sha
    assert ids["rotate_sha"] == sha


def test_genesis_keys_are_the_issuers_key_sets_of_2_october():
    """Every key in the saved GitHub and GitLab JWKS is a genesis constant in pins.rs, and nothing else is."""
    import base64
    import hashlib
    pins = (ROOT / "programs" / "knos_oidc" / "src" / "pins.rs").read_text(encoding="utf-8").split("pub const ROTATE_REF")[0]
    want = set(re.findall(r'\((\d), h\("([0-9a-f]{64})"\)\)', pins))
    got = set()
    for issuer, name in ((0, "github_jwks_2026-10-02.json"), (1, "gitlab_jwks_2026-10-02.json")):
        for k in json.loads((ROOT / "tests" / "fixtures" / name).read_text())["keys"]:
            n = base64.urlsafe_b64decode(k["n"] + "=" * (-len(k["n"]) % 4)).lstrip(b"\0")
            got.add((str(issuer), hashlib.sha256(n).hexdigest()))
    assert got == want and len(got) == 7


# -- the second deployment (programs-v2) --------------------------------------------------------------------------

def test_the_second_deployments_ids_agree_everywhere():
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text())
    assert json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text()) == ids
    pay_rs = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert re.search(r'OIDC_ID: Pubkey = pubkey!\("(\w+)"\)', pay_rs).group(1) == ids["knos_oidc"]
    first = json.loads((ROOT / "programs" / "program_ids.json").read_text())
    assert ids["knos_oidc"] != first["knos_oidc"] and ids["knos_pay"] != first["knos_pay"]
    from knos.settle import oidc as first_client
    from knos.settle.v2 import oidc
    assert str(oidc.OIDC_ID) == ids["knos_oidc"] and str(oidc.GUARDIAN) == ids["guardian"] and str(first_client.OIDC_ID) == first["knos_oidc"]


def test_the_second_verifiers_pins_are_the_pinned_values():
    """The guardian, the attester's account and repositories, the rotate pin, the delay and the expiry in pins.rs are
    the ones in programs-v2/program_ids.json and in the client, and the test-only values are the harness's."""
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey

    from knos.settle.v2 import oidc
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text())
    pins = (ROOT / "programs-v2" / "knos_oidc" / "src" / "pins.rs").read_text(encoding="utf-8")
    num = lambda text: int(text.replace("_", ""))  # noqa: E731
    assert re.search(r'pub const GUARDIAN: Pubkey = pubkey!\("(\w+)"\);', pins).group(1) == ids["guardian"]
    assert num(re.search(r"pub const ATTEST_OWNER_ID: u64 = ([\d_]+);", pins).group(1)) == ids["attest_owner_id"]
    repos = re.search(r"pub const ATTEST_REPO_IDS: \[u64; 2\] = \[([\d_, ]+)\];", pins).group(1)
    assert [num(x) for x in repos.split(",")] == ids["attest_repo_ids"]
    assert re.search(r'pub const ROTATE_SHA: &\[u8; 40\] = b"([0-9a-f]{40})";', pins).group(1) == ids["rotate_sha"]
    assert 'pub const ROTATE_REF: &[u8] = b"drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml@";' in pins
    assert 'pub const ATTEST_EVENTS: [&[u8]; 2] = [b"schedule", b"workflow_dispatch"];' in pins
    assert num(re.search(r"pub const KEY_DELAY: i64 = ([\d_]+);", pins).group(1)) == oidc.KEY_DELAY == 86_400
    days, day = re.search(r"pub const KEY_TTL: i64 = (\d+) \* ([\d_]+);", pins).groups()
    assert int(days) * num(day) == oidc.KEY_TTL == 30 * 86_400
    # the same rotate pin as the first deployment's, and as the workflow that calls it
    assert ids["rotate_sha"] == json.loads((ROOT / "programs" / "program_ids.json").read_text())["rotate_sha"]
    # every test-only value sits behind the testkeys feature, with a harmless twin for the real build
    for name, off in (("TEST_GENESIS", "&[]"), ("TEST_ROTATE_SHA", "None"), ("TEST_ATTEST", "None"), ("TEST_GUARDIAN", "None")):
        on, real = re.findall(rf'#\[cfg\((not\()?feature = "testkeys"\)?\)\]\npub const {name}: [^=]+ = ', pins), None
        assert sorted(on) == ["", "not("], name
        real = re.search(rf'#\[cfg\(not\(feature = "testkeys"\)\)\]\npub const {name}: [^=]+ = ([^;]+);', pins).group(1)
        assert real == off, name
    assert len(re.findall(r"pub const TEST_", pins)) == 8
    guardian = re.search(r"pub const TEST_GUARDIAN: Option<Pubkey> = Some\(Pubkey::new_from_array\(\[(.*?)\]\)\);", pins, re.S).group(1)
    test_guardian = Pubkey.from_bytes(bytes(int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})", guardian)))
    assert test_guardian == Keypair.from_seed(bytes([7]) * 32).pubkey() != oidc.GUARDIAN
    owner, repo = re.search(r"pub const TEST_ATTEST: Option<\(u64, u64\)> = Some\(\(([\d_]+), ([\d_]+)\)\);", pins).groups()
    assert (num(owner), num(repo)) == (424_242, 987_654_321)        # tests/_settle.py, github_claims


def test_the_second_verifiers_genesis_keys_are_githubs_four_and_no_others():
    """Every key in the saved GitHub JWKS is a genesis constant of programs-v2's pins.rs; GitLab's keys are not (they
    come in on GitHub's signature); and they are the same four hashes the first deployment starts with."""
    import base64
    import hashlib

    def genesis(tree: str) -> set:
        pins = (ROOT / tree / "knos_oidc" / "src" / "pins.rs").read_text(encoding="utf-8")
        body = pins[pins.index("pub const GENESIS"):]
        return set(re.findall(r'\((\d), h\("([0-9a-f]{64})"\)\)', body[:body.index("];")]))

    def published(issuer: int, name: str) -> set:
        out = set()
        for k in json.loads((ROOT / "tests" / "fixtures" / name).read_text())["keys"]:
            n = base64.urlsafe_b64decode(k["n"] + "=" * (-len(k["n"]) % 4)).lstrip(b"\0")
            out.add((str(issuer), hashlib.sha256(n).hexdigest()))
        return out

    github, gitlab = published(0, "github_jwks_2026-10-02.json"), published(1, "gitlab_jwks_2026-10-02.json")
    assert genesis("programs-v2") == github and len(github) == 4 and not genesis("programs-v2") & gitlab
    assert genesis("programs-v2") == {g for g in genesis("programs") if g[0] == "0"}


def _functions(source: str) -> dict[str, str]:
    """Every function of a Rust file that starts in column 0, by name: its text from `fn` to its closing brace
    (the comments above it and the tests module are not part of it)."""
    out, lines, at = {}, source.split("#[cfg(test)]")[0].splitlines(), 0
    while at < len(lines):
        m = re.match(r"(?:pub )?fn (\w+)", lines[at])
        if not m:
            at += 1
            continue
        end = at
        while not (lines[end] == "}" or (end == at and lines[end].rstrip().endswith("}"))):
            end += 1
        out[m.group(1)], at = "\n".join(lines[at:end + 1]), end + 1
    return out


def test_what_the_second_verifier_shares_with_the_first_is_the_same():
    """rsa.rs and the Wycheproof vectors it is tested with are the first deployment's files, byte for byte. So is
    every function of claims.rs but the two that read a key and a text, and every error code."""
    for name in ("src/rsa.rs", "tests/wycheproof.rs", "tests/vectors/rsa_signature_2048_sha256_test.json", "tests/vectors/rsa_signature_4096_sha256_test.json"):
        assert (ROOT / "programs-v2" / "knos_oidc" / name).read_bytes() == (ROOT / "programs" / "knos_oidc" / name).read_bytes(), name
    first, second = ((ROOT / tree / "knos_oidc" / "src" / "claims.rs").read_text(encoding="utf-8") for tree in ("programs", "programs-v2"))
    f1, f2 = _functions(first), _functions(second)
    assert len(f1) > 10 and set(f1) <= set(f2)
    assert {name for name in f1 if f1[name] != f2[name]} == {"fields", "text"}
    codes = lambda src: re.findall(r"^pub const (E_\w+): u32 = (\d+);", src, re.M)  # noqa: E731
    assert codes(first) == codes(second) and [c for _, c in codes(first)] == ["60", "61", "62", "63"]
    # the signatures other crates call are the same: what changed is inside
    signature = lambda text: text.split("{")[0]  # noqa: E731
    assert all(signature(f1[name]) == signature(f2[name]) for name in f1)


def test_the_one_thing_the_second_claim_reader_does_that_the_first_does_not():
    """The first deployment compares a key of the claims with a wanted name as the bytes between its quotes, so
    "\\u0061ud" is not "aud" to it. Every other JSON reader decodes the escape. The second deployment's reader compares
    the text a key spells: it finds a claim under any spelling of its name, and a second copy of a claim cannot hide
    behind another spelling (62). That is the whole difference: two functions it adds, and their two callers."""
    first, second = ((ROOT / tree / "knos_oidc" / "src" / "claims.rs").read_text(encoding="utf-8") for tree in ("programs", "programs-v2"))
    f1, f2 = _functions(first), _functions(second)
    assert set(f2) - set(f1) == {"key_is", "unescape"}
    assert "if key == *w {" in f1["fields"] and "if key_is(key, escaped, w) {" in f2["fields"] and "key ==" not in f2["fields"]
    # `fields`: one line more (is there an escape in this key?) and the comparison; nothing else of it changed
    lines = f2["fields"].splitlines()
    added = [line for line in lines if line.strip() == "let escaped = key.contains(&b'\\\\');"]
    assert len(added) == 1
    assert "\n".join(line for line in lines if line not in added).replace("if key_is(key, escaped, w) {", "if key == *w {") == f1["fields"]
    # the text of a value is decoded by the same rule as before, now in a function the key comparison shares
    assert "unescape(r, i)" in f2["text"] and "unescape(raw, i)" in f2["key_is"] and "unescape" not in first
    for line in ("Some(b'/') =>", "Some(b'\\\\') =>", "Some(b'\"') =>", "Some(b'u') =>", "if !(0x20..0x7f).contains(&v) { return Err(err(E_CLAIM)); }"):
        assert line in f1["text"] and line in f2["unescape"], line
    # outside the functions: the doc comment of `fields`, the tests, and Raw can be printed (the tests print it)
    assert "#[derive(Clone, Copy)]\npub struct Raw" in first and "#[derive(Clone, Copy, Debug)]\npub struct Raw" in second
    assert "#[cfg(test)]" not in first and "another spelling of the name" in second.split("#[cfg(test)]")[1]
    # the interface crate (what other programs read a token with) carries the second deployment's rule
    interface = _functions((ROOT / "crates" / "knos-oidc-interface" / "src" / "lib.rs").read_text(encoding="utf-8"))
    assert "if key_is(key, escaped, w) {" in interface["fields"] and "key_is" in interface
    # and all three are asked the same questions: serde_json, claims.rs and the interface crate, by one function
    fuzz = (ROOT / "programs-v2" / "knos_oidc" / "fuzz" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert 'oracle::check(b, &p, "claims.rs");' in fuzz and 'oracle::check(b, &i, "knos-oidc-interface");' in fuzz and "assert_eq!(p, i," in fuzz
    assert "knos_oidc_fuzz::agree(data)" in (ROOT / "programs-v2" / "knos_oidc" / "fuzz" / "fuzz_targets" / "claims.rs").read_text(encoding="utf-8")
    assert "agree(" in (ROOT / "programs-v2" / "knos_oidc" / "fuzz" / "tests" / "random.rs").read_text(encoding="utf-8")


def test_the_two_deployments_differ_on_a_claim_spelled_with_an_escape_and_on_nothing_else_here():
    """The same signed tokens, sent to both verifiers in the runtime. `exp` written a second time as "\\u0065xp": the
    first deployment does not see the copy and verifies the token; the second refuses it (62). `exp` written only
    that way: the first finds no expiry (63); the second reads it. A plain token: both verify, and store the same."""
    import pytest
    pytest.importorskip("solders.litesvm")
    sys.path.insert(0, str(ROOT / "tests"))
    from _oidc2 import Chain2
    from _settle import NOW, Chain, github_claims, modulus, sign_jwt, signing_key

    from knos.settle import oidc as oidc1
    from knos.settle.v2 import oidc as oidc2
    key, n = signing_key(), modulus(signing_key())
    old, new = Chain(), Chain2()
    assert old.register(oidc1.GITHUB, n) and new.register(oidc2.GITHUB, n), (old.err, new.err)
    claims = github_claims(jti="spelled")
    plain = json.dumps(claims, separators=(",", ":"))
    assert f'"exp":{NOW + 300}' in plain
    twice = sign_jwt(key, {}, raw_payload=(plain[:-1] + ',"\\u0065xp":%d}' % (NOW + 10 ** 6)).encode())
    escaped = sign_jwt(key, {}, raw_payload=plain.replace('"exp":', '"\\u0065xp":').encode())
    assert json.loads(plain[:-1] + ',"\\u0065xp":%d}' % (NOW + 10 ** 6))["exp"] == NOW + 10 ** 6       # what another reader would take
    # written twice
    tok = old.verify(twice, oidc1.GITHUB, n)
    assert tok is not None and oidc1.read_token(old.data(tok)).exp == NOW + 300, old.err
    assert new.verify(twice, oidc2.GITHUB, n) is None and "Custom(62)" in new.err, new.err
    # written once, with an escape
    assert old.verify(escaped, oidc1.GITHUB, n) is None and "Custom(63)" in old.err, old.err
    tok = new.verify(escaped, oidc2.GITHUB, n)
    assert tok is not None and oidc2.read_token(new.data(tok)).exp == NOW + 300, new.err
    # written as GitHub writes it
    a, b = old.verify(sign_jwt(key, claims), oidc1.GITHUB, n), new.verify(sign_jwt(key, claims), oidc2.GITHUB, n)
    assert a is not None and b is not None, (old.err, new.err)
    assert oidc1.read_token(old.data(a)).claims() == oidc2.read_token(new.data(b)).claims() == claims


def test_the_javascript_client_matches_the_python_client(tmp_path):
    """sdk/settle/index.js (what the web app loads) against the fixtures, and its transaction read back by solders."""
    import shutil

    import pytest
    if not shutil.which("node"):
        pytest.skip("needs node")
    out = tmp_path / "tx.bin"
    r = subprocess.run(["node", str(ROOT / "sdk" / "settle" / "test.mjs"), str(out)], capture_output=True, text=True, check=False)
    assert r.returncode == 0 and "checks match the Python client" in r.stdout, r.stderr or r.stdout
    from solders.transaction import Transaction
    msg = Transaction.from_bytes(out.read_bytes()).message
    fx = json.loads((ROOT / "sdk" / "settle" / "fixtures.json").read_text())
    assert str(msg.account_keys[0]) == fx["inputs"]["funder"] and len(msg.instructions) == 2
    fund = msg.instructions[1]
    assert str(msg.account_keys[fund.program_id_index]) == fx["programs"]["knos_pay"]
    assert bytes(fund.data).hex() == fx["instructions"]["pay.fund merge"]["data"]
    assert [str(msg.account_keys[i]) for i in fund.accounts] == [a["pubkey"] for a in fx["instructions"]["pay.fund merge"]["accounts"]]


def test_the_recorded_rpc_of_the_agent_calls_reads_the_same_in_python():
    """sdk/settle/agent.recorded.json (what scripts/record_settle_agent.py got from the programs' test builds in LiteSVM) is read
    by the Python client to the numbers sdk/settle/agent.test.mjs expects of agent.js, and the file is a recording of today's scenario."""
    import base64

    from knos import terms
    from knos.chain import said
    from knos.settle.v2 import meter, pay
    rec = json.loads((ROOT / "sdk" / "settle" / "agent.recorded.json").read_text(encoding="utf-8"))
    ids = json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text())
    want = rec["expect"]

    def data(address: str) -> bytes:
        return base64.b64decode(rec["accounts"][address]["data"])
    assert rec["programs"] == {"knos_pay": ids["knos_pay"], "knos_meter": ids["knos_meter"]}
    defaults = re.search(r"DEPLOYMENT = Object\.freeze\((\{.*?\})\);", (ROOT / "sdk" / "settle" / "agent.js").read_text(encoding="utf-8"), re.S).group(1)
    assert {k: v for k, v in re.findall(r'(\w+): "(\w+)"', defaults)} == {k: ids[k] for k in ("knos_oidc", "knos_pay", "knos_meter")}
    for o in want["orders"]:
        got = pay.read_order(data(o["address"]))
        assert (got.state, got.mode, got.amount, got.fee, got.paid, got.deadline, str(got.mint), got.decimals, got.terms.hex()) == (
            o["state"], o["mode"], o["amount"], o["fee"], o["paid"], o["deadline"], o["mint"], o["decimals"], o["terms"])
    job = pay.read_job(data(want["job"]["address"]))
    assert (job.state, job.mode, job.amount, job.deadline, str(job.source), job.terms.hex(), job.amount - pay.fee_of(job.amount)) == (
        want["job"]["state"], want["job"]["mode"], want["job"]["amount"], want["job"]["deadline"], want["job"]["source"], want["job"]["terms"], want["job"]["net"])
    # the terms the funding logged are the ones whose hash the accounts hold, and their words are the Python client's
    for name, text in want["terms_json"].items():
        assert terms.describe(terms.parse(text)) == want["terms_words"][name]
    held = {o["terms"] for o in want["orders"]} | {want["job"]["terms"]}
    logged = {pay.terms_hash(line.split(" ", 1)[1].encode()).hex() for t in rec["transactions"].values() for line in said(t["logs"], str(pay.PAY_ID))
              if line.startswith(("knos2:terms ", "knos3:terms "))}
    assert held <= logged
    st = want["statement"]
    for buyer, row in st["meter_accounts"].items():
        month = meter.read_month(data(str(meter.month_pda(int(buyer), st["seller"], want["month"]))), int(buyer), st["seller"], want["month"])
        assert vars(month) == row == st["meter"][buyer]
    # every payment the statement expects was logged by the escrow, in a transaction of the recording
    for paid in st["escrow"]:
        assert paid["line"] in said(rec["transactions"][paid["signature"]]["logs"], str(pay.PAY_ID))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "record_settle_agent.py"), "--check"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


def test_the_site_is_built_at_one_commit(tmp_path):
    import os

    import _posix
    sha = "ab" * 20
    r = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(tmp_path / "site"), sha], capture_output=True, text=True, check=False,
                       env=_posix.environ(dict(os.environ)))
    assert r.returncode == 0, r.stderr
    site = tmp_path / "site"
    assert {"index.html", "app.js", "front.js", "settle.js", "knos-claim.yml", "program_ids.json"} <= {p.name for p in site.iterdir()}
    front = (site / "front.js").read_text(encoding="utf-8")
    # the site's own commit; the workflows it hands out name a commit of drexthealpha/knos-workflows (tests/test_workflows2.py)
    assert "KNOS_COMMIT_SHA" not in front and f'KNOS_SHA = "{sha}"' in front
    assert (site / "settle.js").read_bytes() == (ROOT / "sdk" / "settle" / "index.js").read_bytes()
    # the second deployment's addresses ship as a file, and the first deployment's are only in the page, as history
    assert (site / "program_ids.json").read_bytes() == (ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_bytes()
    assert subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(tmp_path / "x"), "main"], capture_output=True,
                          env=_posix.environ(dict(os.environ))).returncode != 0


# -- the site's words against the code they describe -----------------------------------------------------------------

WEB = ROOT / "web"


def _text(html: str) -> str:
    """The words of a page: code in backticks, the rest as it reads, one space between words."""
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    html = re.sub(r"<code>(.*?)</code>", lambda m: "`" + m.group(1) + "`", html, flags=re.S)
    import html as h
    return " ".join(h.unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _view(name: str) -> str:
    page = (WEB / "index.html").read_text(encoding="utf-8")
    return re.search(rf'<section id="view-{name}".*?</section>', page, re.S).group(0)


def test_the_site_ships_the_second_deployments_ids_and_names_the_first_once_as_history():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    first = json.loads((ROOT / "src" / "knos" / "settle" / "program_ids.json").read_text())
    second = json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text())
    history = re.search(r'<div id="first-deployment".*?</div>', page, re.S).group(0)
    assert re.findall(r'<span class="mono">(\w+)</span>', history) == [first["knos_oidc"], first["knos_pay"]]
    for address in (first["knos_oidc"], first["knos_pay"]):
        assert page.count(address) == 1 and address not in app
    # the second deployment's addresses are read from the program_ids.json the build ships, never typed into the page
    for value in (v for v in second.values() if isinstance(v, str) and len(v) > 30):
        assert value not in page and value not in app
    assert "program_ids.json" in app and "first deployment" in _text(history)
    stats = json.loads((ROOT / "tests" / "web" / "recorded" / "stats_with_data.json").read_text())
    assert stats["programs"]["first"] == {"knos_oidc": first["knos_oidc"], "knos_pay": first["knos_pay"]}
    # the second deployment's programs, the meter among them once it is counted
    assert all(stats["programs"]["second"][name] == second[name] for name in stats["programs"]["second"])
    assert {"knos_oidc", "knos_pay"} <= set(stats["programs"]["second"])


def test_the_numbers_the_site_states_are_the_codes():
    from knos import commands
    from knos.settle.v2 import oidc, pay
    fund, claim, build = (_text(_view(n)) for n in ("fund", "claim", "build"))
    usdc = lambda units: f"{units / 10 ** 6:g}"                                    # noqa: E731
    whole = lambda units: f"{units // 10 ** 6:,}"                                  # noqa: E731
    # `/knos fund` opens a work order, and an order's least amount is its own (knos_pay ORDER_MIN_AMOUNT, lib.rs): 5, where a 2.0 job's is 1
    assert f"from {usdc(pay.ORDER_MIN_AMOUNT)} to {whole(pay.MAX_AMOUNT)} test USDC, with at most 6 decimals" in fund
    assert (pay.MIN_AMOUNT, pay.ORDER_MIN_AMOUNT, pay.MAX_AMOUNT) == (1_000_000, 5_000_000, 100_000_000_000)
    assert f"at most {usdc(pay.FAUCET_CAP)} per comment, once per repository per minute" in fund and pay.FUND_PERIOD == 60
    assert f"{commands.DAYS} days unless you say, {commands.MAX_DAYS} at most" in fund
    assert f"{commands.RESERVE} unless you say" in fund
    # an order's fee: its funder pays it on top of the amount, in three tiers above a floor and with no maximum, and gets it back with a refund
    for part in (f"{pay.FEE_BPS / 100:g}% of the first {whole(pay.FEE_TIER_1)}", f"{pay.FEE_BPS_2 / 100:g}% from {whole(pay.FEE_TIER_1)} to {whole(pay.FEE_TIER_2)}",
                 f"{pay.FEE_BPS_3 / 100:g}% above", f"at least {pay.ORDER_FEE_MIN / 10 ** 6:.2f} test USDC", "paid by the funder on top",
                 "only when someone is paid: a refund returns it with the amount"):
        assert part in fund, part
    assert "at most 25)" not in fund and not hasattr(pay, "ORDER_FEE_MAX"), "the fee has no maximum any more"
    assert (pay.order_fee(pay.ORDER_MIN_AMOUNT), pay.order_fee(pay.FEE_TIER_1), pay.order_fee(pay.FEE_TIER_2), pay.order_fee(pay.MAX_AMOUNT),
            pay.order_fee(10 ** 12)) == (pay.ORDER_FEE_MIN, 25_000_000, 515_000_000, 765_000_000, 5_265_000_000)
    # which of the two fees applies is the program's version, and the page sends the reader to where it is read
    assert "Pricing says which fee the program on devnet applies today" in fund and 'id="price-version-now"' in _view("pricing")
    assert f"held for you for {pay.HOLD // 86_400} days" in claim and f"After {pay.HOLD // 86_400} days it goes back to the funder" in claim
    assert f"stops working after {oidc.KEY_TTL // 86_400} days" in build and "waits a day" in build and oidc.KEY_DELAY == 86_400
    app = (WEB / "app.js").read_text(encoding="utf-8")
    plan = "upgradeable only through a multisig with a public 48-hour delay, until an outside review"
    assert plan in app and plan in _text((WEB / "index.html").read_text(encoding="utf-8"))
    assert "172800" in app and 172_800 == 48 * 3600                                  # the delay the page checks the chain against
    assert "PAUSE_MAX" in app and pay.PAUSE_MAX == 7 * 86_400                          # the pause length shown is the client's constant


def test_the_sample_reply_says_what_the_terms_say():
    """The sentences of the reply the page shows are the ones the code writes for the terms of `/knos fund 20 checks: test`."""
    from knos import commands, terms
    fund = commands.parse("/knos fund 20 checks: test")
    built = terms.build(fund, required=[], check_runs={"check_runs": [{"name": "test", "app": {"id": 15368}, "status": "completed", "conclusion": "success"}]},
                        statuses={"statuses": []})
    sample = _text(re.search(r'<blockquote id="fund-reply">(.*?)</blockquote>', (WEB / "index.html").read_text(encoding="utf-8"), re.S).group(0))
    for sentence in terms.describe(built.terms, built.source):
        assert sentence in sample, sentence
    assert re.search(r"<pre id=\"fund-comment\">/knos fund 20 checks: test</pre>", (WEB / "index.html").read_text(encoding="utf-8"))
    from knos.settle.v2 import pay
    assert "20.00 test USDC" in sample and f"until you bind a wallet ({pay.HOLD // 86_400} days at most)" in sample and "`/knos address <your Solana address>`" in sample


def test_the_first_view_has_no_numbers_outside_code_but_the_one_measurement_it_leads_with():
    """scripts/claims_check.py holds every number in this view to a fact; the easiest way to keep it true is to have
    almost none. A command shown in a <pre> is code, like one in <code>. The one measurement the view states (how many
    cheating pull requests passed the black-box check, and how many passed plain CI) is the totals row of docs/TAMPER.md."""
    view = re.sub(r"<pre>(.*?)</pre>", lambda m: "<code>" + m.group(1) + "</code>", _view("check"), flags=re.S)
    said = re.sub(r"`[^`]*`", " ", _text(view))
    row = re.search(r"^\| \*\*all\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \|$", (ROOT / "docs" / "TAMPER.md").read_text(encoding="utf-8"), re.M)
    cases, plain_ci, _in_process, black_box = row.groups()
    assert f"{black_box} of {cases} cheating pull requests passed it, {plain_ci} passed plain CI" in said
    assert re.findall(r"\d+", said) == [black_box, cases, plain_ci], re.findall(r"\d+", said)


def test_the_site_says_nothing_it_may_not():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    words = _text(page)
    app = (WEB / "app.js").read_text(encoding="utf-8")
    banned = "|".join(("cla" "ude", "anthro" "pic", "hack" "athon", "win" "ner", "assis" "tant"))     # in pieces: no file spells them out
    stale = rf"\b(veto|no admin|nobody can (?:change|upgrade)|no one can change|never be changed|one-hour|hour later|about a minute|{banned})\b"
    assert not re.search(stale, words, re.I), re.search(stale, words, re.I).group(0)
    assert not re.search(stale, app, re.I), re.search(stale, app, re.I).group(0)
    # the second deployment is never called immutable: the page says how it can be upgraded. The one place the word
    # stands is the name of the state the page shows for a program whose upgrade authority the chain says is gone.
    assert "immutable" not in words.lower() and "immutable" not in app.replace('data-state="immutable"', "").replace('"immutable"', "")
    # Every "USDC" on the page is "test USDC", but for one name: the record counts as real money only what was paid in
    # Circle's mint, and the ranks have to say which mint that is. "Circle's USDC" names the mint; it is not an amount
    # anyone is paid or puts in on this page.
    usdc = r"(?<!test )(?<!Test )(?<!Circle's )USDC"
    assert not re.search(usdc, words), re.search(r".{20}" + usdc, words).group(0)
    assert words.count("Circle's USDC") == words.count("real money (Circle's USDC)") == 2 and "real USDC" not in words
    # devnet money is called test USDC wherever the page says what a person is paid or puts in
    assert "test USDC" in words and "mainnet" not in words.lower()


def test_the_site_asks_nobody_but_github_and_devnet():
    hosts = {"api.github.com", "api.devnet.solana.com", "github.com", "explorer.solana.com", "faucet.circle.com", "drexthealpha.github.io"}
    for name in ("app.js", "front.js", "index.html"):
        found = set(re.findall(r"https?://([\w.-]+)", (WEB / name).read_text(encoding="utf-8")))
        assert found <= hosts, (name, found - hosts)
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'const RPC = "https://api.devnet.solana.com"' in app and 'const CHAIN = "solana:devnet"' in app
    assert 'const DEVNET = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"' in app          # devnet's first block, which no other cluster has


def test_the_pages_workflow_watches_the_ids_the_site_ships():
    network = (ROOT / ".github" / "workflows" / "network.yml").read_text(encoding="utf-8")
    watched = json.loads(re.search(r"paths: (\[.*?\])", network).group(1))
    assert "src/knos/settle/v2/program_ids.json" in watched
    for path in watched:
        assert path.endswith("/**") or (ROOT / path).exists(), path
    assert "src/knos/settle/v2/program_ids.json" in (ROOT / "scripts" / "build_site.sh").read_text(encoding="utf-8")
