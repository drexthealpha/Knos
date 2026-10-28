"""What each Qloo signal changes: for each recorded sample chip and each Qloo call family its card used, the verdict,
the launch city and the pre-order target recomputed with that family's answer removed, by check.py's own rules
(decide, and metros.terms for the city and the target). Offline, from the private recordings; what it writes holds
derived values only (labels, Census metro names, numbers), never a Qloo answer.

    python scripts/qloo_ablation.py <private recordings file>          write docs/reference/qloo_ablation.json and the page's table
    python scripts/qloo_ablation.py <private recordings file> --check  exit 1 when either differs
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps" / "wanted"), str(ROOT / "src")]
from knos_wanted import signals  # noqa: E402

OUT = ROOT / "docs" / "reference" / "qloo_ablation.json"
PAGE = ROOT / "web" / "how-we-test.html"
START, END = "<!-- ablation:start -->", "<!-- ablation:end -->"
FAMILIES = signals.FAMILIES        # one table of call families for this script and the card (knos_wanted.signals)


def rows(cards: dict) -> list[dict]:
    return [r for key in sorted(cards) for r in signals.ablate(cards[key])]       # the app's own rule (knos_wanted.signals)


def table(rs: list[dict]) -> str:
    e = lambda v: html.escape("none" if v is None else str(v))  # noqa: E731
    body = "".join(f"<tr><td>{e(r['chip'])}</td><td>{e(r['removed'])}</td><td>{e(r['city'][0])} → {e(r['city'][1])}</td>"
                   f"<td>{e(r['target'][0])} → {e(r['target'][1])}</td><td>{e(r['label'][0])} → {e(r['label'][1])}</td></tr>" for r in rs)
    moved = lambda r: r["city"][0] != r["city"][1] or r["target"][0] != r["target"][1] or r["label"][0] != r["label"][1]  # noqa: E731
    one = [r for r in rs if r["removed"] != "every Qloo answer"]
    every = [r for r in rs if r["removed"] == "every Qloo answer"]
    return (f'{START}\n    <section class="t" id="ablation">\n      <h2>What does each Qloo signal change?</h2>\n'
            f'      <p class="t-n" data-one="{sum(map(moved, one))}" data-of="{len(one)}">On 6 recorded samples, removing one Qloo signal changes the city, the target or the verdict in {sum(map(moved, one))} of {len(one)} removals; removing every answer, in {sum(map(moved, every))} of {len(every)}.</p>\n'
            f'      <details><summary>The table</summary><div class="k-table"><table>\n'
            f'        <thead><tr><th scope="col">Sample</th><th scope="col">Removed</th><th scope="col">Launch city</th><th scope="col">Target</th><th scope="col">Verdict</th></tr></thead>\n'
            f'        <tbody>{body}</tbody>\n      </table></div></details>\n'
            f'      <p class="fine">Recomputed by the check\'s own rules from cards recorded on 22 Oct 2026; live, the later questions are asked from the search\'s matches (<a href="https://github.com/drexthealpha/Knos/blob/main/docs/reference/qloo_ablation.json" rel="noopener">the values</a>).</p>\n'
            f'    </section>\n    {END}')


def main(argv: list[str]) -> int:
    cards = json.loads(Path(argv[0]).read_text(encoding="utf-8"))["cards"]
    rs = rows(cards)
    doc = {"about": "derived values only: the verdict, the launch city (a Census metro) and the target, before and after each removal",
           "rules": "apps/wanted/knos_wanted/check.py decide, metros.terms", "samples": len(cards), "rows": rs}
    page = PAGE.read_text(encoding="utf-8")
    if START in page:
        a, b = page.index(START), page.index(END) + len(END)
        new_page = page[:a] + table(rs) + page[b:]
    else:
        anchor = '    <section class="t" id="board">'
        new_page = page.replace(anchor, "    " + table(rs) + "\n" + anchor, 1)
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        same = (OUT.is_file() and OUT.read_text(encoding="utf-8") == text and new_page == page
                and signals.TABLE.is_file() and signals.TABLE.read_text(encoding="utf-8") == text)
        print("ablation table is current" if same else "ablation table differs: run python scripts/qloo_ablation.py <file>")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    signals.TABLE.write_text(text, encoding="utf-8", newline="\n")      # the app's copy (its image holds no docs/)
    PAGE.write_text(new_page, encoding="utf-8", newline="\n")
    print(f"{len(rs)} rows written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
