"""L35: the sourced teardown page (web/teardown/index.html). Every raw material has a source and a date, each cost and
the Idiot Index shown are the ones the page's data block gives (price over priced raw-material cost), the index says
which price it uses, one bottleneck is named with its sources, and every source is a link a stranger can open."""
from __future__ import annotations

import json
import re
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "web" / "teardown" / "index.html").read_text(encoding="utf-8")
DATA = json.loads(re.search(r'<script type="application/json" id="td-data">(.*?)</script>', PAGE, re.S).group(1))


def usd(x: float) -> str:
    return f"${x:,.2f}"


def test_every_cost_and_the_index_come_from_the_data():
    total = 0.0
    for r in DATA["raw"]:
        assert r["source"] and r["date"]
        cost = r["kg"] * r["usd_per_t"] / 1000
        total += cost
        assert usd(cost) in PAGE, f"{r['name']}: {usd(cost)} not shown"
    assert f'id="td-raw">{usd(total)}<' in PAGE
    assert f'id="td-price">${DATA["price"]["usd"]:,}<' in PAGE
    index = DATA["price"]["usd"] / total
    assert f'id="td-index">{index:.2f}x<' in PAGE
    assert DATA["price"]["which"] == "component cost" and "Cost over raw material, for the cells" in PAGE
    assert DATA["not_priced"] and "At most" in PAGE   # an index over a partial raw cost is an upper bound and says so


def test_inferences_say_how_and_sources_open():
    for r in DATA["raw"]:
        if r.get("kind") == "inference":
            assert "inference" in PAGE
    srcs = re.findall(r'<li id="s(\d)">(.*?)</li>', PAGE, re.S)
    assert len(srcs) == 4
    for _, text in srcs:
        assert re.search(r'href="https://[^"]+"', text) and "Read 22 Nov 2026" in text
    cited = {int(n) for n in re.findall(r'href="#s(\d)"', PAGE)}
    assert cited == {int(n) for n, _ in srcs}


def test_one_bottleneck_with_its_sources():
    assert PAGE.count("Bottleneck:") == 1
    block = PAGE[PAGE.index('id="td-bottleneck"'):PAGE.index("</div>", PAGE.index('id="td-bottleneck"'))]
    for n in DATA["bottleneck"]["source"]:
        assert f'href="#s{n}"' in block


def test_public_text_rules():
    text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", PAGE, flags=re.S)
    assert "—" not in text
    for w in ("escrow", "marketplace", "pay on proof"):
        assert w not in text.lower()
