"""Write the IDT benchmark's measured numbers into the home page (web/index.html, between <!-- home:idt --> marks).

    python scripts/idt_page.py          write the block from docs/idt/summary.json
    python scripts/idt_page.py --check  exit 1 when the page and the data disagree (tests/test_idt.py runs it)

The block is a sentence and a table, all from the measured runs (scripts/idt_bench.py): output tokens as Claude Code's
print mode returned them, pass or fail of each task's own check. Nothing is estimated."""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "index.html"
DATA = ROOT / "docs" / "idt" / "summary.json"
RAW = "https://github.com/drexthealpha/Knos/blob/main/docs/idt/runs.json"
PACKAGED = ROOT / "src" / "knos" / "idt_benchmark.json"
QLOO = ROOT / "docs" / "idt" / "qloo_summary.json"
QLOO_RAW = "https://github.com/drexthealpha/Knos/blob/main/docs/idt/qloo_runs.json"
E1 = "https://github.com/drexthealpha/Knos/blob/main/docs/reference/e1_results.json"
MARK = re.compile(r"(<!-- home:idt -->)(.*?)(<!-- /home:idt -->)", re.S)


def block(s: dict) -> str:
    n = f"{s['tasks']}"
    pct = lambda x: f"{round(100 * x)}%"  # noqa: E731
    rows = "".join(
        f"<tr><td>{html.escape(r['task'])}</td><td class=\"k-num\">{r['vague_output_tokens']:,}</td><td class=\"k-num\">{r['ready_output_tokens']:,}</td>"
        f"<td class=\"k-num\">{r['saved_output_tokens']:+,}</td><td>{'yes' if r['vague_passed'] else 'no'} / {'yes' if r['ready_passed'] else 'no'}</td></tr>"
        for r in s["rows"])
    # no saving is claimed: the pre-registered run (docs/reference/e1_results.json) found a padded control too close to
    # the Ready brief (its interval reaches 0.994), so the vague-to-Ready ratio is not stated as a result
    return (f"\n    <section id=\"home-idt\" aria-label=\"IDT benchmark\">"
            f"<p class=\"fine\" id=\"idt-line\" data-tasks=\"{n}\">Clear briefs: no token saving claimed "
            f"(<a href=\"{E1}\" rel=\"noopener\">padded control failed</a>).</p>"
            f"<details class=\"k-more\" id=\"idt-per-brief\" data-not-prose><summary>Each brief</summary>"
            f"<p class=\"fine\">One model ({html.escape(str(s['model']))}, {html.escape(str(s['effort']))} effort) for both. Vague: {s['vague_output_tokens']:,} tokens, {pct(s['vague_pass_rate'])} passed. "
            f"Ready: {s['ready_output_tokens']:,} tokens, {pct(s['ready_pass_rate'])} passed.</p>"
            f"<div class=\"k-table\"><table><thead><tr><th scope=\"col\">Task</th><th scope=\"col\">Vague</th><th scope=\"col\">Ready</th>"
            f"<th scope=\"col\">Saved</th><th scope=\"col\">Passed</th></tr></thead><tbody>{rows}</tbody></table></div>"
            f"<p class=\"fine\">Output tokens include thinking. <a href=\"{RAW}\" rel=\"noopener\">Every run, raw</a>.</p></details>"
            + qloo_block() + "</section>\n    ")


def qloo_block() -> str:
    """Qloo's own measured part (scripts/qloo_bench.py), apart from the IDT ratio, which is Knos's: the research briefs run with
    and without their "Grounding (Qloo)" line, same model and effort; shown as measured, whatever it is."""
    if not QLOO.exists():
        return ""
    q = json.loads(QLOO.read_text(encoding="utf-8"))
    rows = "".join(
        f"<tr><td>{html.escape(r['task'])}</td><td class=\"k-num\">{r['without_output_tokens']:,}</td><td class=\"k-num\">{r['with_output_tokens']:,}</td>"
        f"<td>{'yes' if r['without_passed'] else 'no'} / {'yes' if r['with_passed'] else 'no'}</td></tr>" for r in q["rows"])
    d = q["delta_share"]
    said = f"{abs(round(100 * d, 1))}% {'fewer' if d < 0 else 'more'}" if d else "no change in"
    # the line sits inside its fold: the first screen's prose stays within its budget (tests/test_site_home.py)
    return (f"<details class=\"k-more\" id=\"qloo-per-brief\" data-not-prose><summary>With and without Qloo</summary>"
            f"<p class=\"fine\" id=\"qloo-line\" data-delta=\"{d}\">With Qloo's line: {said} tokens, "
            f"Ready {q['without_pass']} vs {q['with_pass']} of {q['tasks']}.</p>"
            f"<p class=\"fine\">The {q['tasks']} research briefs, each run without and with its Grounding (Qloo) line ({html.escape(str(q['model']))}, "
            f"{html.escape(str(q['effort']))} effort): {q['without_output_tokens']:,} vs {q['with_output_tokens']:,} output tokens, "
            f"${q['without_cost_usd']} vs ${q['with_cost_usd']} estimated. The IDT benchmark above is Knos's own (clear briefs), not Qloo's.</p>"
            f"<div class=\"k-table\"><table><thead><tr><th scope=\"col\">Task</th><th scope=\"col\">Without</th><th scope=\"col\">With Qloo</th>"
            f"<th scope=\"col\">Ready</th></tr></thead><tbody>{rows}</tbody></table></div>"
            f"<p class=\"fine\"><a href=\"{QLOO_RAW}\" rel=\"noopener\">Every run, raw</a>.</p></details>")


def packaged(s: dict) -> str:
    """The benchmark as the server reads it (knos.idt.benchmark_for): each task's two briefs and measured tokens."""
    tasks = {t["id"]: t for t in json.loads((ROOT / "bench" / "idt" / "tasks.json").read_text(encoding="utf-8"))["tasks"]}
    keep = ("task", "kind", "vague_output_tokens", "ready_output_tokens", "saved_output_tokens", "vague_passed", "ready_passed")
    rows = [{**{k: r[k] for k in keep}, "vague": tasks[r["task"]]["vague"], "ready": tasks[r["task"]]["ready"]} for r in s["rows"]]
    return json.dumps({"v": 1, "model": s["model"], "effort": s["effort"], "tasks": s["tasks"], "ratio_vague_to_ready": s["ratio_vague_to_ready"],
                       "raw": RAW, "rows": rows}, indent=1, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    s = json.loads(DATA.read_text(encoding="utf-8"))
    page = PAGE.read_text(encoding="utf-8")
    m = MARK.search(page)
    if not m:   # the home page shows no IDT since the first-screen rule of 5 Nov 2026: the packaged numbers are what remain
        if check:
            ok = PACKAGED.exists() and PACKAGED.read_text(encoding="utf-8") == packaged(s)
            print("src/knos/idt_benchmark.json matches docs/idt/summary.json" if ok else "src/knos/idt_benchmark.json differs from docs/idt/summary.json")
            return 0 if ok else 1
        PACKAGED.write_text(packaged(s), encoding="utf-8", newline="\n")
        print("wrote src/knos/idt_benchmark.json (the home page has no IDT block)")
        return 0
    want = block(s)
    if check:
        ok = m.group(2) == want and PACKAGED.exists() and PACKAGED.read_text(encoding="utf-8") == packaged(s)
        print("the home page's IDT numbers match docs/idt/summary.json" if ok else "the home page's IDT numbers differ from docs/idt/summary.json")
        return 0 if ok else 1
    PAGE.write_text(page[:m.start(2)] + want + page[m.end(2):], encoding="utf-8", newline="\n")
    PACKAGED.write_text(packaged(s), encoding="utf-8", newline="\n")
    print(f"wrote the IDT block: ratio {s['ratio_vague_to_ready']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
