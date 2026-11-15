"""The badge and the record say what the receipt says and no more: a scope, a date, which money, and what "paid" is."""

from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from knos import badge
from knos.settle.v2.pay import Record

ROOT = Path(__file__).resolve().parents[1]
NOW = 1791072000          # 2026-10-04 00:00 UTC
PR = {"repo": "o/r", "pr": 12, "amount": "100.00", "money": "test USDC", "date": "2026-10-03"}
REPO = {"repo": "o/r", "pr": None, "count": 3, "other": 0, "money": "test USDC", "as_of": "2026-10-04"}


def _row(pr, units, day, currency="test USDC"):
    return {"pull_request": pr, "amount_units": units, "date": day, "currency": currency, "repository_id": 7}


def test_a_badge_states_its_scope_its_money_and_its_date():
    assert badge.message(PR) == "#12: 100.00 test USDC, 2026-10-03"
    assert badge.message(REPO) == "3 payments in test USDC, as of 2026-10-04"
    assert badge.message({**REPO, "count": 1, "other": 2}) == "1 payment in test USDC, 2 in another token, as of 2026-10-04"
    for data in (PR, REPO):
        said = badge.message(data) + badge.title(data)
        assert "test USDC" in said and "2026-10-0" in said and "o/r" in badge.title(data) and "not a score" in badge.title(data)
        assert not any(w in said.lower() for w in ("verified", "audited", "trusted", "quality", "guarantee", "certified"))


def test_the_svg_is_one_file_with_an_accessible_title_and_nothing_fetched():
    for data in (PR, REPO, {**PR, "repo": 'o/<r>&"x'}):
        text = badge.svg(data)
        root = ET.fromstring(text)                                            # well-formed, whatever the repository is called
        ns = "{http://www.w3.org/2000/svg}"
        assert root.get("role") == "img" and root.get("aria-label") == f"paid on proof: {badge.message(data)}"
        assert root[0].tag == f"{ns}title" and root[0].text == badge.title(data)    # the title is the first child, as readers expect
        assert [t.text for t in root.iter(f"{ns}text")] == ["paid on proof", badge.message(data)]
        low = text.lower()
        assert not any(w in low for w in ("<script", "<image", "<a ", "href", "@font-face", "@import", "url(", "<style", "<foreignobject"))
        assert text.count("http") == 1 and "http://www.w3.org/2000/svg" in text     # the namespace is the only address in it
        assert int(root.get("width")) == sum(int(float(r.get("width"))) for r in root.iter(f"{ns}rect"))
    assert "#57606a" in badge.svg(PR) and "#1a7f37" not in badge.svg(PR)       # test money is never drawn green


def test_the_markdown_links_the_badge_to_the_repositorys_record_on_the_site():
    assert badge.markdown(PR, "knos-paid-12.svg") == ("[![paid on proof: #12: 100.00 test USDC, 2026-10-03](knos-paid-12.svg)]"
                                                      "(https://drexthealpha.github.io/Knos/r/o/r.html)")
    site = (ROOT / "scripts" / "pages_data.py").read_text(encoding="utf-8")   # the route is the one the site builds
    assert f'SITE = "{badge.SITE}"' in site and "{SITE}/{kind}/{path}.html" in site


def test_a_badge_is_made_from_the_receipts_and_from_nothing_else():
    rows = [_row(12, 60_000_000, "2026-10-02"), _row(12, 40_000_000, "2026-10-03"), _row(13, 5_500_000, "2026-10-03"),
            _row(14, 9, "2026-10-03", "mint X")]
    assert badge.from_rows("o/r", 12, rows, NOW) == PR                         # a split is one pull request: summed, dated by its last payment
    assert badge.from_rows("o/r", 13, rows, NOW)["amount"] == "5.50"
    assert badge.from_rows("o/r", 99, rows, NOW) is None and badge.from_rows("o/r", 14, rows, NOW) is None   # no payment in test USDC: no badge
    assert badge.from_rows("o/r", None, rows, NOW) == {**REPO, "other": 1}     # another token is counted apart, never as test USDC
    assert badge.from_rows("o/r", None, [], NOW)["count"] == 0


def test_the_payment_comment_ends_with_one_badge_line_and_other_comments_are_untouched():
    paid = "Knos: paid. @ann received 100.00 test USDC for issue #3, in full: its funder paid Knos's fee of 2.50 on top. It went to `W` (tx, 21 s)."
    got = badge.said("o/r", 12, paid, NOW)
    assert got.startswith(paid + "\n\n[![paid on proof: #12: 100.00 test USDC, 2026-10-04](https://img.shields.io/badge/paid_on_proof-")
    assert got.endswith("-57606a)](https://drexthealpha.github.io/Knos/r/o/r.html)") and "%2312%3A_100.00_test_USDC%2C_2026--10--04" in got
    order = "Knos: paid. The work order on issue #3 paid 80.00 test USDC in full (its funder paid Knos's fee of 2.00 on top): @a 40.00 (50%) to `W` (tx, 3 s)."
    assert "#12: 80.00 test USDC, 2026-10-04" in badge.said("o/r", 12, order, NOW)
    held = "Held for @ann. 20.00 test USDC for issue #7 waits for them until 2027-03-20. It is then paid in full."
    both = paid + "\n\nPaid. @ann received 4.875 test USDC as a tip for this pull request: the tip of 5.00 less Knos's fee of 0.125." + "\n\n" + held
    got = badge.said("o/r", 12, both, NOW)
    assert got.count("[![paid on proof") == 1 and got.endswith(".html)") and "#12: 104.875 test USDC, 2026-10-04" in got   # one line, at the end; what is held is not in it
    for other in ("Knos: held for @ann. 100.00 test USDC for issue #3 waits for them until 2026-11-01.", "Knos: not paid yet. @ann would have received 5.00 test USDC.",
                  "Knos: paid. With no amount in it.", "Knos: nothing is in escrow."):
        assert badge.said("o/r", 12, other, NOW) == other                      # nothing reached a wallet, or nothing says how much: no badge
    assert badge.said("o/r", 0, paid, NOW) == paid


def test_knos_flow_adds_the_line_where_the_settlement_comment_is_posted_and_the_cli_registers_both_commands():
    flow = (ROOT / "src" / "knos" / "flow.py").read_text(encoding="utf-8")
    assert flow.count("run.say(number, badge.said(run.repo, number, _join(parts), run.now()))") == 1 and flow.count("badge.") == 1
    from typer.testing import CliRunner

    from knos import cli
    names = {c.name for c in cli.app.registered_commands}
    assert {"badge", "record"} <= names
    got = CliRunner().invoke(cli.app, ["badge", "not-a-repo"])
    assert got.exit_code != 0 and isinstance(got.exception, cli.Stop) and "owner/repo" in got.exception.said


REP = Record(paid=3, funders=2, total=250_000_000, test_paid=5, self_paid=1, test_total=500_000_000, first=NOW - 86_400 * 3, last=NOW)


def test_the_record_keeps_test_money_and_self_paid_out_of_the_headline_and_says_what_paid_means():
    v = badge.record_view(REP, 42, "ann")
    assert v["headline"] == {"paid": 3, "distinct_funders": 2, "total": "250.00", "first": "2026-10-01", "last": "2026-10-04"}
    assert v["apart"] == {"test_paid": 5, "test_total": "500.00", "self_paid": 1}
    lines = badge.record_lines(v)
    assert lines[1] == "Paid 3 times by 2 distinct funders: 250.00 test USDC in all, first 2026-10-01, last 2026-10-04."
    assert "Shown apart, not in the count above: 5 payments in the faucet's test money (500.00 test USDC); 1 payment this account funded itself" in lines[2]
    assert not any(n in lines[1] for n in ("9 ", "8 ", "750", "4 times"))      # 3 + 5 + 1 and 250 + 500 are written nowhere
    said = "\n".join(lines)
    assert "not a score" in said and "Ten payments from one funder add one" in said and "test USDC, not money" in said
    empty = badge.record_lines(badge.record_view(Record(0, 0, 0, 2, 0, 9_000_000, 0, 0), 42))
    assert empty[1].startswith("No payment from someone else is recorded") and "2 payments in the faucet's test money (9.00 test USDC)" in empty[2]
    assert badge.record_view(Record(0, 0, 0, 2, 0, 9_000_000, 0, 0), 42)["headline"]["first"] is None


def test_the_record_command_reads_the_reputation_account_of_the_id(monkeypatch):
    from typer.testing import CliRunner

    from knos import cli
    from knos.settle.v2 import pay
    asked = []

    class Ledger:
        def account(self, address):
            asked.append(address)
            data = bytearray(pay.REP_LEN)
            data[0:4] = (3).to_bytes(4, "little")
            data[4:8] = (2).to_bytes(4, "little")
            data[8:16] = (250_000_000).to_bytes(8, "little")
            data[16:20] = (5).to_bytes(4, "little")
            data[20:24] = (1).to_bytes(4, "little")
            data[32:40] = (500_000_000).to_bytes(8, "little")
            data[40:48] = (NOW - 86_400 * 3).to_bytes(8, "little")
            data[48:56] = NOW.to_bytes(8, "little")
            return bytes(data)
    monkeypatch.setattr(cli, "_ledger", lambda: Ledger())
    got = CliRunner().invoke(cli.app, ["record", "42", "--json"])
    assert got.exit_code == 0, got.output
    assert asked == [pay.rep_pda(42)] and json.loads(got.output) == badge.record_view(REP, 42)
    text = CliRunner().invoke(cli.app, ["record", "42"]).output
    assert "Paid 3 times by 2 distinct funders" in " ".join(text.split()) and "not a score" in text


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_site_draws_the_same_badge_and_shows_the_record_with_its_caveats_in_the_same_view():
    rep = badge.record_view(REP, 42, "ann<b>")
    script = f"""
      import {{ badgeSvg, badgeMessage, badgeTitle, receiptUrl, renderBadge, renderRecord }} from {json.dumps((ROOT / "web" / "badge.js").as_uri())};
      const cases = {json.dumps([PR, REPO, {**PR, "repo": 'o/<r>&"x'}])}, a = {{}}, b = {{}};
      renderBadge(a, cases[0]); renderRecord(b, {json.dumps(rep)});
      console.log(JSON.stringify({{ svgs: cases.map(badgeSvg), messages: cases.map(badgeMessage), titles: cases.map(badgeTitle),
        url: receiptUrl("o/r"), badge: a.innerHTML, record: b.innerHTML }}));
    """
    got = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert got.returncode == 0, got.stderr
    out = json.loads(got.stdout)
    cases = [PR, REPO, {**PR, "repo": 'o/<r>&"x'}]
    assert out["svgs"] == [badge.svg(c) for c in cases]                        # byte for byte what `knos badge` writes
    assert out["messages"] == [badge.message(c) for c in cases] and out["titles"] == [badge.title(c) for c in cases]
    assert out["url"] == badge.receipt_url("o/r") and f'href="{badge.receipt_url("o/r")}"' in out["badge"]
    assert "One pull request: #12 of o/r, paid on 2026-10-03 (UTC)." in out["badge"] and "Test USDC on Solana devnet: not money." in out["badge"]
    rec = out["record"]
    assert "<strong>Paid 3 times</strong> by <strong>2 distinct funders</strong>: 250.00 test USDC in all" in rec
    head, apart = rec.split("Shown apart, not in the count above")
    assert "500.00" not in head and "5 payments, 500.00 test USDC" in apart and "1 payment (the program keeps their number" in apart
    assert all(c.replace("'", "&#x27;") in rec for c in rep["caveats"]) and len(rep["caveats"]) == 4     # the caveats are in the same view
    # nobody looked for an opt-in: only what the chain shows anyway, under the id the chain knows it by, and no profile
    assert 'data-profile="chain-only"' in rec and "<h3>GitHub id 42</h3>" in rec and "<h4>Profile</h4>" not in rec and "Accepted work" not in rec
    assert "has not opted in to a profile" in rec and "no place in any list" in rec and "<strong>Devnet demonstration.</strong>" in rec
    assert "ann&lt;b&gt;/ann&lt;b&gt;" in rec and "<b>" not in rec                                       # the login appears only where the file would go, as text


def _node(script: str) -> dict:
    got = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_profile_is_shown_only_to_an_account_that_opted_in_and_every_line_has_its_sample_size():
    rep = badge.record_view(REP, 42, "ann")
    out = _node(f"""
      import {{ recordHtml, optIn, readOptIn, profileUrl, PROFILE_FILE }} from {json.dumps((ROOT / "web" / "badge.js").as_uri())};
      const rep = {json.dumps(rep)}, b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64").replace(/(.{{20}})/g, "$1\\n");
      const asked = [], get = (file) => async (url) => {{ asked.push(url); return file; }};
      const yes = await readOptIn("ann", get({{ content: b64({{ public_record: true, github_id: 42 }}), encoding: "base64" }}), 42);
      console.log(JSON.stringify({{ url: profileUrl("ann"), file: PROFILE_FILE, asked, yes,
        plain: optIn({{ public_record: true }}, "ann", 42),
        no: [optIn(null, "ann"), optIn({{ public_record: "true" }}, "ann"), optIn({{ public_record: false }}, "ann"), optIn([true], "ann"),
             optIn({{ public_record: true, github_id: 7 }}, "ann", 42), optIn({{ content: "!!", encoding: "base64" }}, "ann"),
             await readOptIn("ann", async () => {{ throw new Error("offline"); }}), await readOptIn("", get(null))],
        without: recordHtml(rep), refused: recordHtml({{ ...rep, profile: optIn(null, "ann") }}),
        with: recordHtml({{ ...rep, profile: yes }}),
        counted: recordHtml({{ ...rep, profile: yes, history: {{ repeat_funders: 1, disputes: 0, reverts: 1, of: 3 }} }}),
        mainnet: recordHtml({{ ...rep, cluster: "mainnet", profile: yes }}) }}));
    """)
    assert out["url"] == "https://api.github.com/repos/ann/ann/contents/.knos/profile.json" and out["asked"] == [out["url"]]   # the public API, the repository named after the account
    assert out["yes"] == out["plain"] == {"opted_in": True, "source": "ann/ann/.knos/profile.json"}
    assert [n["opted_in"] for n in out["no"]] == [False] * 8 and all(n["why"] for n in out["no"])       # only a literal true, in a file about this account
    for html in (out["without"], out["refused"]):
        assert 'data-profile="chain-only"' in html and "<h4>Profile</h4>" not in html and "Repeat funders" not in html and "<h3>GitHub id 42</h3>" in html
        assert "Paid 3 times" in html and "rank" not in html.lower()                                 # what the chain shows anyway, and no ranking
    assert "(the file is not there)" in out["refused"] and '{&quot;public_record&quot;: true}' in out["without"].replace('"', "&quot;")
    prof = out["with"]
    assert 'data-profile="opted-in"' in prof and "<h3>ann</h3>" in prof and "ann/ann/.knos/profile.json says" in prof and "rank" not in prof.lower()
    assert "<dt>Accepted work</dt><dd>3 payments from someone else" in prof and prof.count("sample: 3 payments; too few to say much") == 3
    assert "<dt>Distinct funders</dt><dd>2 <span" in prof
    assert "1 of 3 payments came from a funder who had paid this account before" in prof
    assert "not counted: the program's record of a payee keeps no count of disputes or reverts" in prof and "sample: 0 read" in prof
    assert prof.count("sample:") == 4                                                                # every line of the profile has its sample size
    counted = out["counted"]
    assert "1 of 2 funders paid more than once" in counted and "sample: 2 distinct funders" in counted
    assert "0 disputes and 1 revert" in counted and "sample: 3 accepted payments in the site's history" in counted
    # test money and self-funded stay apart and are in no line of the profile or the headline; the devnet label is in the view
    for html in (prof, counted, out["without"]):
        head, rest = html.split("Shown apart, not in the count above")
        section = rest.split("<h4>Profile</h4>")[1].split("<h4>How to read it</h4>")[0] if "<h4>Profile</h4>" in rest else ""
        assert "500.00" not in head and "500.00" not in section and "5 payments" not in section and "750" not in html and "9 payments" not in html
        assert html.index("<strong>Devnet demonstration.</strong>") < html.index("<h3>") and "is not a record of money earned" in html
    assert "Devnet demonstration" not in out["mainnet"]


# ---- the "Knos-verified" badge: from a receipt that checks, and from nothing else ------------------------------------

VECTORS = json.loads((ROOT / "docs" / "receipt" / "vectors.json").read_text(encoding="utf-8"))
GOOD = VECTORS["valid_v3"][0]


def test_the_verified_badge_is_issued_only_from_a_receipt_that_checks_and_says_accepted():
    from knos import ids
    v = badge.verified(GOOD["receipt"], digest=GOOD["sha256"])
    assert v["issued"] and v["verdict"] == "accepted" and v["digest"] == GOOD["sha256"] and v["why"] == ""
    art = ET.fromstring(badge.verified_svg(v))
    assert art.attrib["aria-label"] == f"Knos-verified: #12: accepted, receipt {GOOD['sha256'][:12]}"
    assert "cannot be bought" in v["note"] and "cannot be bought" in art[0].text and "not that the work is good" in art[0].text
    # every valid vector of versions 2 and 3 gets one; a version 1 receipt names no verdict and gets none
    assert all(badge.verified(x["receipt"])["issued"] for k in ("valid_v2", "valid_v3") for x in VECTORS[k])
    assert all(not badge.verified(x["receipt"])["issued"] for x in VECTORS["valid"])
    # nothing else does: a changed receipt, another digest, a verdict that is not accepted, a dispute, no receipt at all
    changed = json.loads(json.dumps(GOOD["receipt"])); changed["evaluator_observed"]["artifact"]["pull_request"] = 13
    rejected = json.loads(json.dumps(GOOD["receipt"])); rejected["evaluator_observed"]["verdict"] = "rejected"
    for bad in (badge.verified(changed, digest=GOOD["sha256"]), badge.verified(GOOD["receipt"], digest="0" * 64), badge.verified(rejected),
                badge.verified(None), badge.verified({}), badge.verified("paid, honest"), badge.verified(GOOD["receipt"], disputed=True)):
        assert not bad["issued"] and bad["why"] and bad["verdict"] in ids.VERDICTS and bad["words"] == ids.VERDICT_WORDS[bad["verdict"]]
        with pytest.raises(ValueError):
            badge.verified_svg(bad)
    assert badge.verified(rejected)["verdict"] == "insufficient_evidence"        # a receipt that does not check is not a rejection
    assert badge.verified(GOOD["receipt"], disputed=True)["verdict"] == "disputed"
    with pytest.raises(ValueError):                                              # and a result nobody issued draws nothing
        badge.verified_svg({**v, "issued": "yes"})
    # the badge links to the evidence: on a public cluster, the transaction the signature was verified in
    on_devnet = badge.verified({**GOOD["receipt"], "cluster": "devnet"})
    tx = GOOD["receipt"]["issuer_authenticated"]["verified"]["transaction"]
    assert on_devnet["issued"] and on_devnet["evidence"][0]["url"] == f"https://explorer.solana.com/tx/{tx}?cluster=devnet"
    assert badge.verified_markdown(on_devnet, "b.svg").endswith(f"(b.svg)](https://explorer.solana.com/tx/{tx}?cluster=devnet)")
    assert v["evidence"] == []                                                   # a local cluster has no public page


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_site_draws_the_same_verified_badge_and_none_for_anything_else():
    v = badge.verified({**GOOD["receipt"], "cluster": "devnet"})
    receipt = {**GOOD["receipt"], "cluster": "devnet"}
    no = badge.verified({})
    out = _node(f"""
      import {{ verifiedSvg, receiptDigest, renderVerified, verifiedIssued }} from {json.dumps((ROOT / "web" / "badge.js").as_uri())};
      const v = {json.dumps(v)}, receipt = {json.dumps(receipt)}, no = {json.dumps(no)}, vectors = {json.dumps([x["receipt"] for x in VECTORS["valid_v3"]])};
      const a = {{}}, b = {{}}, c = {{}}, d = {{}};
      await renderVerified(a, v, receipt); await renderVerified(b, no); await renderVerified(c, v, {{ ...receipt, order: "x" }});
      await renderVerified(d, {{ ...v, verdict: "rejected" }});
      let threw = false; try {{ verifiedSvg(no); }} catch (e) {{ threw = true; }}
      console.log(JSON.stringify({{ svg: verifiedSvg(v), digests: await Promise.all(vectors.map(receiptDigest)), a: a.innerHTML, b: b.innerHTML,
        c: c.innerHTML, d: d.innerHTML, threw, issued: [v, no, null, {{ ...v, issued: 1 }}].map(verifiedIssued) }}));
    """)
    assert out["svg"] == badge.verified_svg(v)                                   # byte for byte
    assert out["digests"] == [x["sha256"] for x in VECTORS["valid_v3"]]          # the same digest as knos.receipt.digest
    assert 'data-verified="yes"' in out["a"] and v["evidence"][0]["url"].replace("&", "&amp;") in out["a"] and "cannot be bought" in out["a"]
    assert out["b"] == '<p class="fine" data-verified="no">No badge: ' + no["why"].replace("'", "&#x27;").replace('"', "&quot;") + ".</p>"
    assert "does not hash to the digest" in out["c"] and "<svg" not in out["c"] and "<svg" not in out["d"] and "<svg" not in out["b"]
    assert out["threw"] and out["issued"] == [True, False, False, False]


def test_an_outside_script_shows_the_badge_for_a_receipt_that_checks_and_not_otherwise(tmp_path):
    import sys
    script = ROOT / "examples" / "receipt_consumer" / "show_badge.py"
    assert len(script.read_text(encoding="utf-8").splitlines()) <= 60
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(GOOD["receipt"]), encoding="utf-8")
    bad.write_text(json.dumps({**GOOD["receipt"], "order": "not an address"}), encoding="utf-8")
    env = {**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}

    def run(*args):
        got = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, encoding="utf-8", env=env)
        return got.returncode, json.loads(got.stdout)
    code, said = run(good, "--digest", GOOD["sha256"], "--out", tmp_path / "b.svg")
    assert code == 0 and said["show"] and said["verdict"] == "accepted" and said["receipt"] == GOOD["sha256"]
    assert (tmp_path / "b.svg").read_text(encoding="utf-8") == badge.verified_svg(badge.verified(GOOD["receipt"]))
    for args in ((bad, "--out", tmp_path / "c.svg"), (good, "--digest", "1" * 64, "--out", tmp_path / "c.svg"), (tmp_path / "missing.json",)):
        code, said = run(*args)
        assert code == 1 and not said["show"] and said["verdict"] == "insufficient evidence" and said["why"]
    assert not (tmp_path / "c.svg").exists()
