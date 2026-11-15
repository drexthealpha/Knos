"""A receipt as a page a person reads and as a small badge. Both are drawn from the signed envelope only, with every
value escaped; the page embeds the envelope itself so it can be saved and verified offline
(`knos gate receipt verify page.html` reads it back)."""
from __future__ import annotations

import html
import json
import re

from . import core

_ENV = re.compile(r'<script type="application/json" id="knos-receipt">(.*?)</script>', re.S)


def badge(envelope: dict) -> str:
    """An SVG: "knos gate | passed" (green), "refused" (red) or "passed (public tests only)" (grey-blue). No script,
    no link, no font file."""
    r = envelope["receipt"]
    word = r["verdict"] + (" (public tests only)" if r["mode"] == "public-tests-only" and r["verdict"] == "passed" else "")
    color = {"passed": "#2e7d32", "refused": "#c62828"}.get(r["verdict"], "#546e7a")
    if r["mode"] == "public-tests-only" and r["verdict"] == "passed":
        color = "#546e7a"
    left, right = "knos", word
    lw, rw = 8 + 7 * len(left), 10 + 7 * len(right)
    w = lw + rw
    t = html.escape
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{t(left)}: {t(right)}">'
            f'<title>{t(left)}: {t(right)}</title>'
            f'<rect width="{lw}" height="20" fill="#333"/><rect x="{lw}" width="{rw}" height="20" fill="{color}"/>'
            f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">'
            f'<text x="5" y="14">{t(left)}</text><text x="{lw + 5}" y="14">{t(right)}</text></g></svg>')


def _row(k: str, v) -> str:
    return f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>"


def _counts(c) -> str:
    if not c:
        return "not run"
    return f"{c['passed']}/{c['total']} passed, {c['failed']} failed, {c['errors']} errors, {c['skipped']} skipped"


def render(envelope: dict) -> str:
    r = envelope["receipt"]
    v = core.verify(envelope)
    findings = r["cheat_checks"]["findings"]
    rows = [
        _row("Repository", r["repository"]), _row("Pull request", f"#{r['pull_request']}"),
        _row("Head commit", r["head"]), _row("Base commit", r["base"]),
        _row("Verdict", r["verdict"] + (f" ({r['rule']})" if r["rule"] else "")),
        _row("What was run", r["scope_note"]), _row("Spec hash (seal of the hidden tests)", r["spec_hash"] or "none"),
        _row("Hidden tests", _counts(r["tests"]["hidden"])), _row("Public tests", _counts(r["tests"]["public"])),
        _row("Test contents", r["tests"]["contents"]),
        _row("Cheat checks", f"{'passed' if r['cheat_checks']['passed'] else 'refused'}: {len(r['cheat_checks']['rules_run'])} rules, library {r['cheat_checks']['library']}"),
        _row("Re-run", "not run" if not r["rerun"].get("ran") else ("agreed" if r["rerun"].get("agrees") else "DISAGREED")),
        _row("Runner", f"{r['runner'].get('kind')} {r['runner'].get('runner_environment', '')} ({r['runner'].get('note', '')})"),
        _row("Issued", r["issued_at"]), _row("Issuer", f"{r['issuer']['name']} {r['issuer']['key']}"),
        _row("Signature", ("valid, by a key Knos lists" if v["issuer"] else "valid, but by a key Knos does not list: it shows only "
                          "that the key's holder signed") if v["valid"] else f"INVALID: {v['why']}"), _row("Receipt digest (sha256)", v["digest"]),
    ]
    flist = "".join(f"<li>{html.escape(f['category'])}: {html.escape(f['path'])} ({html.escape(f['rule'])})</li>" for f in findings) or "<li>none</li>"
    run = r["links"].get("run")
    blob = json.dumps(envelope, sort_keys=True).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Knos Receipt {html.escape(r['repository'])}#{r['pull_request']}</title>
<style>
:root{{--bg:#fff;--fg:#1b1b1b;--line:#ddd;--muted:#555}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121212;--fg:#eee;--line:#333;--muted:#aaa}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:0 auto;padding:16px}}
table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top;word-break:break-all}}
th{{width:34%;color:var(--muted);font-weight:500}}code{{font-size:13px}}
</style></head><body>
<h1>Knos receipt</h1>
<p>{badge(envelope)}</p>
<table>{''.join(rows)}</table>
<h2>Cheat-check findings</h2><ul>{flist}</ul>
<h2>Check it yourself, offline</h2>
<p>Save this page and run <code>knos gate receipt verify FILE</code>. The verifier needs only Python's standard library
(Ed25519, RFC 8032). The signed receipt is embedded below.</p>
{f'<p><a href="{html.escape(run)}">The run on GitHub</a></p>' if run else ''}
<p><a href="{html.escape(r['links']['install'])}">Turn on the Knos check for your repo</a></p>
<script type="application/json" id="knos-receipt">{blob}</script>
</body></html>
"""


def from_page(text: str) -> dict:
    m = _ENV.search(text)
    if not m:
        raise ValueError("no embedded receipt in this page")
    return json.loads(m.group(1).replace("<\\/", "</"))
