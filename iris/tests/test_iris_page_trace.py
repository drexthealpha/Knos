"""L6 the page's trace counts the decision after PAY: a check-run file for a brief over the payout threshold comes in
through CheckRunInbound (no caller waits for the reply), is approved on /knos/, and the session's trace on the page then
reads Decision 1.

    python iris/tests/test_iris_page_trace.py [container] [result file]     (needs: pip install playwright; playwright install chromium)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_iris_bonuses as b  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None


def main() -> int:
    brief = f"github:example/pagetrace-{int(time.time())}"
    repo = brief.split(":", 1)[1]
    code = json.loads((b.F / "briefs" / "code.json").read_text())
    r = b.post("/api/knos/brief", {"id": brief, "amount_usdc": 120, "brief": code})
    body = json.dumps({**json.loads((b.F / "checkruns" / "pass.json").read_text()), "repository": {"full_name": repo}})
    name = f"pagetrace-{int(time.time())}.json"
    subprocess.run(["docker", "exec", "-i", b.C, "sh", "-c", f"cat > /home/irisowner/knos/inbox/checkruns/{name}"], input=body, text=True, timeout=60, check=True)
    lines, kinds, outcome = [f"     brief {brief} locked (ready {r.get('ready')}), 120 USDC; file {name} into inbox/checkruns"], "", ""
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:  # noqa: BLE001 - no headless shell installed: the full Chromium build in its new headless mode
            br = p.chromium.launch(channel="chromium")
        page = br.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{b.BASE}/knos/")
        page.wait_for_selector("#login:not([hidden])", timeout=60000)
        page.fill("#user", "_SYSTEM")
        page.fill("#pass", os.environ["IRIS_PASSWORD"])
        page.click("#login button[type=submit]")
        task = page.locator("#tasks .task", has_text=repo)
        for _ in range(60):
            page.click("#refresh")
            page.wait_for_timeout(5000)
            if task.count():
                break
        lines.append(f"{'ok  ' if task.count() else 'FAIL'} the task is in the inbox on the page")
        if task.count():
            task.first.get_by_role("button", name="Approve").click()
            page.wait_for_selector("#toast:not([hidden])", timeout=30000)
            for _ in range(60):
                page.click("#refresh")
                page.wait_for_timeout(5000)
                row = page.locator("#decisions tr", has_text=repo).first
                outcome = row.inner_text() if row.count() else ""
                if "pay" in outcome.split("\t")[1:2] or "approved by a person" in outcome:
                    break
            row.click()
            for _ in range(30):              # the Decision message follows the approval by the time the payout is simulated
                page.wait_for_timeout(2000)
                kinds = page.locator("#trace .kinds").inner_text() if page.locator("#trace .kinds").count() else ""
                if re.search(r"Decision [1-9]", kinds):
                    break
                row.click()
            page.screenshot(path=str((OUT.parent if OUT else Path(".")) / "test_iris_page_trace.png"))
        br.close()
    lines.append(f"     decision row: {outcome.replace(chr(9), ' | ')}")
    lines.append(f"     trace kinds on the page: {kinds.replace(chr(10), ' ')}")
    paid = "approved by a person" in outcome
    one = bool(re.search(r"Decision 1\b", kinds))
    lines.append(f"{'ok  ' if paid else 'FAIL'} the decision is PAY after the approval")
    lines.append(f"{'ok  ' if one else 'FAIL'} the page's trace reads Decision 1")
    lines.append("PASS test_iris_trace_decision_count: Decision 1 after PAY on the page" if paid and one else
                 "FAIL test_iris_trace_decision_count: " + ("not PAY" if not paid else "the trace does not read Decision 1"))
    print("\n".join(lines))
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0 if paid and one else 1


if __name__ == "__main__":
    sys.exit(main())
