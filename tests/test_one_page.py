"""The product pages (scripts/site_pages.py): the published root is the front door (web/door.html), the proof on NEAR is
prove/; every page carries the one header; /near/ sends a visitor on."""
import os
import pathlib
import re
import subprocess

import _posix

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_root_is_the_front_door_and_the_old_addresses_send_on(tmp_path):
    env = _posix.environ(dict(os.environ))
    env.pop("KNOS_SPA_AT_ROOT", None)
    r = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(tmp_path / "site"), "ab" * 20],
                       capture_output=True, text=True, check=False, env=env)
    assert r.returncode == 0, r.stderr
    site = tmp_path / "site"
    page = (site / "index.html").read_text(encoding="utf-8")
    # L01: one box, whose button checks a table and answers a question (the question box is the same box)
    assert page.count("<h1") == 1 and 'id="list"' in page and 'id="try"' in page and 'id="ask-out"' in page and 'id="paper"' not in page
    assert 'id="near-flow"' not in page and "k-hero" not in page   # the proof and the older tools are pages of their own
    prove = (site / "prove" / "index.html").read_text(encoding="utf-8")
    assert 'id="go"' in prove and 'fetch("../near/latest.json"' in prove
    for p in (page, prove):
        assert p.count('<header class="kh" id="kh">') == 1 and 'id="k-bar"' not in p and "bar.js" not in p
    papers = (site / "papers" / "index.html").read_text(encoding="utf-8")   # L16: Papers opens papers/, which leads to prove/
    assert 'aria-current="page">Papers' in papers and 'href="../prove/"' in papers and '<a href="../papers/">Papers</a>' in prove
    nav = re.search(r'<nav aria-label="Pages">(.*?)</nav>', page).group(1)
    assert re.findall(r'>([^<]+)</a>', nav) == ["Claims", "Papers", "Builders", "Code checker"]   # one header, on every page
    for rel in ("claims/index.html", "claim/hyperloglog/index.html", "agents/index.html", "pricing/index.html", "status/index.html", "privacy.html"):
        p = (site / rel).read_text(encoding="utf-8")
        assert p.count('<header class="kh" id="kh">') == 1 and ".kh .logo" in p and "solana" not in p.lower(), rel   # the header, styled
    for rel in ("tools.html", "app.html", "faq.html"):   # check/ is the Colosseum checker again (T9)
        assert 'http-equiv="refresh"' in (site / rel).read_text(encoding="utf-8"), rel   # older pages left the product
    for sub, to in (("near", "../prove/"),):
        stub = (site / sub / "index.html").read_text(encoding="utf-8")
        assert f'url={to}"' in stub and f'location.replace("{to}" + location.hash)' in stub and 'content="noindex"' in stub
        for tag in re.findall(r'<title>.*?</title>|<meta property="og:(?:title|description|image|url)"[^>]*>', page[:page.index("</head>")], re.S):
            assert tag in stub, tag   # a link preview of the old address shows the front door
    assert (site / "near" / "pay.js").is_file() and not (site / "door.html").exists()
