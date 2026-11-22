"""Round 13, H3 a, b, e and f on a build of the site: the four screens (the front door, the tool page, the result page and
the pricing page) in every language, by tests/web/test_h3_lang.mjs, and on a cheap phone and a slow network, by
tests/web/test_h3_budget.mjs (the numbers of LAWS/UX/U7.md R22 and R23 and LAWS/DISTRIBUTION/D9.md Annex C), in
headless Chromium. Here, with no browser: the front door's source names its strings by key, and the build writes them
from web/i18n/en.json. No node, no `playwright` package or no browser: the browser parts are skipped, with the reason."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _posix
import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"
# each English message as the pages use it: its text, or its plural forms (en.json also holds a description and a
# max_length for the translator, U7 R31)
EN = {k: (v["text"] if "text" in v else {c: f for c, f in v.items() if c in ("zero", "one", "two", "few", "many", "other")}) if isinstance(v, dict) else v
      for k, v in json.loads((ROOT / "web" / "i18n" / "en.json").read_text(encoding="utf-8"))["strings"].items()}


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("h3") / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    env.pop("KNOS_SPA_AT_ROOT", None)
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(out), "d" * 40],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert built.returncode == 0, built.stdout + built.stderr
    return out


def node(script: str, site: Path, timeout: int) -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node is not installed")
    env = {**os.environ, "PYTHON": sys.executable}
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    run = subprocess.run([exe, str(ROOT / "tests" / "web" / script), str(site)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    return run.stdout


def test_the_front_doors_source_writes_no_visible_string_of_its_own():
    door = (ROOT / "web" / "door.html").read_text(encoding="utf-8")
    body = door.split("<body>", 1)[1]
    body = re.sub(r"<script\b.*?</script>|<!--.*?-->|<style\b.*?</style>", " ", body, flags=re.S)
    text = re.sub(r"\{\{@?[\w.]+(?: \w+=[^ }]+)*\}\}", " ", re.sub(r"<[^>]+>", " ", body))
    words = [w for w in text.split() if re.search(r"[A-Za-z]", w)]
    assert words == ["Knos"], words                                  # the brand only (F1B: the sample's column is a key too)
    for key in re.findall(r"\{\{@?([\w.]+)", door):
        assert key in EN or key in ("tool.sample_label", "five", "fold.sample", "fold.built"), key
    for key in re.findall(r"""\bT\(\s*"([\w.]+)\"""", door):
        assert key in EN, key


def test_the_build_writes_every_string_from_the_english_file(site: Path):
    door = (site / "index.html").read_text(encoding="utf-8")
    assert "{{" not in door and "/*I18N*/" not in door
    assert 'data-language-switcher' in door and "window.KI" in door
    for key in ("door.headline", "tool.title", "tool.try", "res.mine", "res.copy", "ask.h", "ask.speak", "fold.listen", "fold.embed", "fold.print"):
        assert EN[key] in door, key
    for k in ("q.get", "q.next", "q.pay", "q.why", "q.who"):
        assert f"<dt>{EN[k]}</dt>" in door, k
    for lang in json.loads(re.search(r"LANGS = (\[.*?\]), BASE", door).group(1)):
        assert (site / "i18n" / f"{lang['code']}.json").is_file(), lang       # every language file is published beside the page
    price = (site / "pricing" / "index.html").read_text(encoding="utf-8")
    assert 'data-language-switcher' in price and '"../i18n/"' in price and price.count("<dt>") == 5


def test_the_goal_line_is_the_english_files(site: Path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import site_product
    # IQ PLAN.md:25-27 (L02, UX/UX-SOTA-2026-11-06.md:45): the line is the one sentence "Knos is a [category] that helps
    # [anyone] [get X done]", under 125 characters, no longer a "The goal: " mission line (WIN/WIN-LAW.md:20)
    assert EN["goal"] == site_product.GOAL and re.match(r"^Knos is an? .+ that helps .+", EN["goal"]) and len(EN["goal"]) < 125


def test_every_screen_in_every_language(site: Path):
    out = node("test_h3_lang.mjs", site, 1800)
    assert out.strip().splitlines()[-1] == "all passed"


def test_every_screen_on_a_cheap_phone_and_a_slow_network(site: Path):
    out = node("test_h3_budget.mjs", site, 2400)
    assert "with scripts blocked the result page shows the result sentence" in out and out.strip().splitlines()[-1] == "all passed"
