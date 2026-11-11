"""One page (scripts/one_page.py): the published root carries the first line, then the NEAR proof flow (#near), then the
IRIS proof check (#iris); /near/ and /iris/ send a visitor on to those sections."""
import os
import pathlib
import re
import subprocess

import _posix

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_root_is_one_page_and_the_old_addresses_send_on(tmp_path):
    env = _posix.environ(dict(os.environ))
    env.pop("KNOS_SPA_AT_ROOT", None)
    r = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(tmp_path / "site"), "ab" * 20],
                       capture_output=True, text=True, check=False, env=env)
    assert r.returncode == 0, r.stderr
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    first, near, iris = page.index('id="k-first"'), page.index('<section id="near-flow"'), page.index('<section id="iris"')
    assert page.index('<span id="near">') < first < near < iris and page.count("<h1") == 1
    assert 'id="go"' in page and 'id="counters"' in page and "iris/knos-iris.mp4" in page
    assert "../brand/" not in page[near:iris]
    assert 'href="./near/"' not in page and 'href="./iris/"' not in page and 'href="#near-flow"' in page   # the bar jumps within the page
    for sub, to in (("near", "../#near"), ("iris", "../#iris")):
        stub = (tmp_path / "site" / sub / "index.html").read_text(encoding="utf-8")
        assert f'url={to}"' in stub and f'location.replace("{to}"' in stub
        # a tab, a link preview or a search result of the old address shows the one page itself
        for tag in re.findall(r'<title>.*?</title>|<meta property="og:(?:title|description|image|url)"[^>]*>', page[:page.index("</head>")], re.S):
            assert tag in stub, tag
        assert '<link rel="canonical" href="https://drexthealpha.github.io/Knos/">' in stub and 'content="noindex"' in stub
    assert (tmp_path / "site" / "near" / "pay.js").is_file() and (tmp_path / "site" / "iris" / "knos-iris.mp4").is_file()
