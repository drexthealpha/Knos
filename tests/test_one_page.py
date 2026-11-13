"""The product pages (scripts/site_pages.py): the published root is the front door (web/door.html), the proof on NEAR is
prove/, the IRIS check labs/; every page carries the one header; /near/ and /iris/ send a visitor on."""
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
    assert page.count("<h1") == 1 and 'id="paper"' in page and 'id="go"' in page and 'id="sample"' in page
    assert 'id="near-flow"' not in page and "k-hero" not in page   # the proof and the older tools are pages of their own
    prove = (site / "prove" / "index.html").read_text(encoding="utf-8")
    labs = (site / "labs" / "index.html").read_text(encoding="utf-8")
    assert 'id="go"' in prove and 'fetch("../near/latest.json"' in prove and "../iris/knos-iris.mp4" in labs
    for p in (page, prove, labs):
        assert p.count('<header class="kh" id="kh">') == 1 and 'id="k-bar"' not in p and "bar.js" not in p
    assert 'aria-current="page">Prove' in prove and 'aria-current="page">For labs' in labs
    nav = re.search(r'<nav aria-label="Pages">(.*?)</nav>', page).group(1)
    assert re.findall(r'>([^<]+)</a>', nav) == ["Claims", "Prove", "For agents", "For labs (IRIS)", "Check a PR"]   # one header, on every page
    for rel in ("claims/index.html", "claim/hyperloglog/index.html", "agents/index.html", "pricing/index.html", "status/index.html", "privacy.html"):
        p = (site / rel).read_text(encoding="utf-8")
        assert p.count('<header class="kh" id="kh">') == 1 and ".kh .logo" in p and "solana" not in p.lower(), rel   # the header, styled
    for rel in ("tools.html", "app.html", "faq.html"):   # check/ is the Colosseum checker again (T9)
        assert 'http-equiv="refresh"' in (site / rel).read_text(encoding="utf-8"), rel   # older pages left the product
    for sub, to in (("near", "../prove/"), ("iris", "../labs/")):
        stub = (site / sub / "index.html").read_text(encoding="utf-8")
        assert f'url={to}"' in stub and f'location.replace("{to}" + location.hash)' in stub and 'content="noindex"' in stub
        for tag in re.findall(r'<title>.*?</title>|<meta property="og:(?:title|description|image|url)"[^>]*>', page[:page.index("</head>")], re.S):
            assert tag in stub, tag   # a link preview of the old address shows the front door
    assert (site / "near" / "pay.js").is_file() and (site / "iris" / "knos-iris.mp4").is_file() and not (site / "door.html").exists()
