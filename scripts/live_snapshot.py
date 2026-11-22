"""At the Pages build (.github/workflows/network.yml): the newest agent payout and the usage counter, read from the app
(GET /api/agent/payout/latest, GET /api/usage), written into the built front door so a reader sees them with no
request. The page asks the app again after load. A build never fails here: when the app does
not answer, the page keeps the line it was committed with.

    python scripts/live_snapshot.py _site/index.html
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

APP = "https://knos.onrender.com"


def get(path: str) -> dict | None:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(APP + path, headers={"User-Agent": "knos-pages-build"}), timeout=120) as r:
                return json.loads(r.read())
        except Exception as why:  # noqa: BLE001
            print(f"live_snapshot: {path}: {type(why).__name__} ({attempt + 1}/3)")
            time.sleep(10)
    return None


def paid_html(x: dict) -> str:
    day = str(x.get("at") or "")[:10]
    said = html.escape(x.get("released") or "the transaction")        # what released it links its transaction
    return (f'Agent paid <b>{html.escape(str(x["units"]))} test units</b>{", " + html.escape(day) if day else ""} · '
            f'<a href="{html.escape(x["explorer"])}" target="_blank" rel="noopener">{said}</a>')


def usage_html(u: dict) -> str | None:
    """The trend line of outside use, when the app gives one (real growth from at least 10); else none."""
    line = (u.get("trend") or {}).get("line")
    return html.escape(line) if line else None


def oidc_latest() -> tuple[str, str] | None:
    """The newest successful transaction of the knos_oidc program on devnet: (signature, day)."""
    import datetime as dt
    pid = json.loads((Path(__file__).resolve().parents[1] / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text())["knos_oidc"]
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [pid, {"limit": 20, "commitment": "confirmed"}]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://api.devnet.solana.com", body, {"Content-Type": "application/json"}), timeout=60) as r:
            rows = json.loads(r.read()).get("result") or []
    except Exception as why:  # noqa: BLE001
        print(f"live_snapshot: knos_oidc: {type(why).__name__}")
        return None
    x = next((t for t in rows if t.get("err") is None), None)
    if not x:
        return None
    day = dt.datetime.fromtimestamp(x["blockTime"], dt.timezone.utc).strftime("%Y-%m-%d") if x.get("blockTime") else ""
    return x["signature"], day


def oidc_html(sig: str, day: str) -> str:
    return (f'Latest signature check on devnet{", " + html.escape(day) if day else ""} · <a href="https://explorer.solana.com/tx/'
            f'{html.escape(sig)}?cluster=devnet" target="_blank" rel="noopener">the transaction</a>')


def main(path: str) -> int:
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    x = get("/api/agent/payout/latest")
    if x and x.get("found") and (x.get("units") or 0) > 0 and re.fullmatch(r"https://explorer\.solana\.com/tx/[1-9A-HJ-NP-Za-km-z]+\?cluster=devnet", str(x.get("explorer"))):
        s, n = re.subn(r'(<p class="k-paid" id="k-paid" data-not-prose>).*?(</p>)', lambda m: m[1] + paid_html(x) + m[2], s, count=1, flags=re.S)
        print(f"live_snapshot: payout {x['units']} units, {x.get('signature', '')[:8]}... ({n} line)")
    sig = oidc_latest()
    if sig:
        s, n = re.subn(r'(<p class="k-paid" id="k-oidc" data-not-prose>).*?(</p>)', lambda m: m[1] + oidc_html(*sig) + m[2], s, count=1, flags=re.S)
        print(f"live_snapshot: knos_oidc {sig[0][:8]}... ({n} line)")
    u = get("/api/usage")
    line = usage_html(u) if u else None
    if line:
        s, n = re.subn(r'<p class="fine" id="k-usage" data-not-prose hidden></p>',
                       lambda _: f'<p class="fine" id="k-usage" data-not-prose>{line}</p>', s, count=1)
        print(f"live_snapshot: usage trend line ({n} line)")
    elif u:
        print(f"live_snapshot: no usage line ({(u.get('trend') or {}).get('this_week')} outside checks this week)")
    p.write_text(s, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
