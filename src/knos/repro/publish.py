"""Where a reproduction's result goes, and the "Reproduced by Knos" badge.

Every result is first written to the PRIVATE folder (<out>/private/<digest>/): the result, the run logs and, when it
is not reproduced, a notice for the authors. Only `publish` writes to <out>/public/, and it refuses every result that
is not `reproduced` with every claim holding, no cheat rule fired and a digest that checks. A contested result goes
to its authors privately first; Knos never publishes it. There is no flag that changes this.

The badge is drawn with knos.badge's drawing (the same mark, size and fonts as "checked by Knos" and "Knos-verified"),
from a result that checks and from nothing else. The result page has one section per claim; the funding link a spec
names appears there and only there, and only on a reproduced result.
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from . import run as rr

LABEL = "Reproduced by Knos"
NOT_FOR_SALE = "This badge is issued only from a reproduction whose result checks. It cannot be bought."
PRIVATE, PUBLIC = "private", "public"
AUDIENCE = "knos-research:"         # a workflow asks GitHub for a token with this audience + the result's digest


class NotPublishable(ValueError):
    """The result may not be published. Its text says why; the result stays in the private folder."""


def checks(result: dict) -> str:
    """Why the result does not check ('' when it does): its digest, its status, every claim, the cheat rules."""
    if not isinstance(result, dict) or result.get("format") != rr.FORMAT:
        return f"not a {rr.FORMAT} result"
    if result.get("digest") != rr.digest(result):
        return "the result does not hash to its digest: it was edited after Knos wrote it"
    if result.get("status") != "reproduced":
        return f"the result is {result.get('status')}, not reproduced"
    if result.get("private") is not False:
        return "the result is marked private"
    if result.get("cheats"):
        return "a cheat rule fired"
    claims = result.get("claims") or []
    if not claims or not all(c.get("holds") is True and c.get("rerun") is not None and c.get("heldout") is not None for c in claims):
        return "not every claim holds on both the re-run and the held-out split"
    return ""


def _day(t: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(int(t)))


def message(result: dict) -> str:
    n = len(result["claims"])
    return f"{n}/{n} claim{'' if n == 1 else 's'}, held-out split, {_day(result['at'])}"


def badge_svg(result: dict) -> str:
    """The badge, for a result that checks. ValueError (NotPublishable) for anything else: there is no badge for a
    result that is contested, failed or incomplete."""
    why = checks(result)
    if why:
        raise NotPublishable(f"no badge: {why}")
    from .. import badge
    tip = (f"Reproduced by Knos: {result['name']}, every claim within its stated tolerance on a second machine and on a held-out "
           f"split; result {result['digest']}. It says the claims reproduced, not that the research is right. {NOT_FOR_SALE}")
    return badge._draw(LABEL, message(result), tip, "#1a7f37")


def badge_markdown(result: dict, image: str, page: str) -> str:
    return f"[![{LABEL}: {message(result)}]({image})]({page})"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", text)[:64] or "result"


def _num(v) -> str:
    return "none" if v is None else f"{v:.6g}"


def page(result: dict) -> str:
    """The result page: one section per claim. Plain HTML, no script."""
    e = html.escape
    rows = []
    for c in result["claims"]:
        rows.append(f'<section id="{e(c["id"])}"><h2>{e(c["id"])}</h2><table>'
                    f'<tr><th>metric</th><td>{e(c["metric"])}</td></tr>'
                    f'<tr><th>claimed</th><td>{_num(c["expected"])} &plusmn; {_num(c["tolerance"])}</td></tr>'
                    f'<tr><th>re-run (second machine)</th><td>{_num(c["rerun"])}</td></tr>'
                    f'<tr><th>held-out split</th><td>{_num(c["heldout"])} (tolerance {_num(c["heldout_tolerance"])})</td></tr>'
                    f'<tr><th>holds</th><td>{"yes" if c["holds"] else "no"}</td></tr></table></section>')
    m = result["machine"]
    funding = (f'<p class="funding">The authors take pre-orders or funding here: <a href="{e(result["funding"])}" rel="nofollow">{e(result["funding"])}</a>. '
               "Knos does not hold or vouch for that money.</p>") if result.get("funding") else ""
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{e(LABEL)}: {e(result['name'])}</title>"
            "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#1f2328;background:#fff}"
            "table{border-collapse:collapse}th,td{text-align:left;padding:.2rem .8rem .2rem 0}th{font-weight:500;color:#59636e}"
            "code{font-size:13px}@media(prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}th{color:#9198a1}a{color:#4493f8}}</style></head><body>"
            f"<h1>{e(LABEL)}: {e(result['name'])}</h1>"
            f"<p>Every claim below was re-run by Knos in a fresh copy of the repository on a second machine, and again on a held-out split "
            f"({e(result['heldout']['source'])}). Each holds within the tolerance the authors stated in <code>knos.yml</code> before the re-run.</p>"
            + "".join(rows) +
            f"<h2>The run</h2><table><tr><th>knos.yml sha256</th><td><code>{e(result['spec_sha256'])}</code></td></tr>"
            f"<tr><th>commit</th><td><code>{e(result['commit'] or 'not a git checkout')}</code></td></tr>"
            f"<tr><th>machine</th><td>Python {e(m['python'])}, {e(m['platform'])}, {m['cpus']} CPUs</td></tr>"
            f"<tr><th>when</th><td>{_day(result['at'])} (UTC)</td></tr>"
            f"<tr><th>result sha256</th><td><code>{e(result['digest'])}</code></td></tr></table>"
            f"{funding}<p>{e(NOT_FOR_SALE)} A reproduction says the stated numbers came back within tolerance; it does not say the method is sound.</p>"
            "</body></html>\n")


def notice(result: dict) -> str:
    """The private note to the authors of a result that is not reproduced. Knos sends nothing: whoever ran the
    reproduction passes it to the authors (the spec's `authors`) privately."""
    who = ", ".join("@" + a["github"] if a.get("github") else (a.get("name") or a.get("email") or "") for a in result.get("authors") or []) or "the authors"
    lines = [f"# Private: reproduction of {result['name']} is {result['status']}", "",
             f"To {who}. This note is private. Knos has not published this result and will not publish it.", "",
             "What came back:", ""]
    lines += [f"- {line.strip()}" for line in rr.summary(result)[1:]]
    lines += ["", f"knos.yml sha256 `{result['spec_sha256']}`, commit `{result['commit'] or 'none'}`, result sha256 `{result['digest']}`.", "",
              "If the run was wrong (a missing dependency, a budget too small), fix knos.yml and ask for a re-run. If the claim was wrong, "
              "correct it; a later reproduction that holds gets the badge. Nothing about this run is public."]
    return "\n".join(lines) + "\n"


def keep(result: dict, logs: dict, out: Path) -> Path:
    """Write the result to the private folder; for a result that is not reproduced, with the authors' notice."""
    folder = Path(out) / PRIVATE / f"{_slug(result['name'])}-{result['digest'][:16]}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "result.json").write_bytes(rr.canonical(result))
    (folder / "logs.json").write_text(json.dumps(logs, indent=1), encoding="utf-8")
    if result["status"] != "reproduced":
        (folder / "NOTICE-TO-AUTHORS.md").write_text(notice(result), encoding="utf-8")
    return folder


def publish(result: dict, out: Path) -> Path:
    """Write the public files (result.json, index.html, badge.svg, badge.md) for a result that checks. Raises
    NotPublishable, writing nothing, for any other."""
    why = checks(result)
    if why:
        raise NotPublishable(f"not published: {why}. The result stays private")
    folder = Path(out) / PUBLIC / _slug(result["name"])
    folder.mkdir(parents=True, exist_ok=True)
    public = {k: v for k, v in result.items()}
    (folder / "result.json").write_bytes(rr.canonical(public))
    (folder / "index.html").write_text(page(result), encoding="utf-8")
    (folder / "badge.svg").write_text(badge_svg(result), encoding="utf-8", newline="\n")
    (folder / "badge.md").write_text(badge_markdown(result, "badge.svg", "index.html") + "\n", encoding="utf-8")
    return folder


def verify_signed(doc: dict, keys: dict[str, int]) -> tuple[dict, list[str]]:
    """A result GitHub signed in a workflow: {"result", "token"}, the token's audience knos-research:<digest>. Uses
    knos.reproduce's RS256 check (no network; `keys` = {kid: modulus}, knos.reproduce.keys_of). Returns (facts, wrong)."""
    from .. import reproduce as rp
    if not isinstance(doc, dict) or set(doc) != {"result", "token"} or not isinstance(doc.get("result"), dict) or not isinstance(doc.get("token"), str):
        return {}, ['a signed reproduction is {"result": the result, "token": GitHub\'s token} and nothing else']
    result, token = doc["result"], doc["token"].strip()
    try:
        head, claims = (json.loads(rp._unb64(part)) for part in token.split(".")[:2])
    except Exception:  # noqa: BLE001
        return {}, ["the token is not a signed token"]
    wrong = []
    n = keys.get(str(head.get("kid")))
    if n is None or not rp.rs256(token, n):
        wrong.append("the token's signature is not one of GitHub's keys given here")
    if claims.get("iss") != rp.ISSUER:
        wrong.append(f"the token's issuer is not {rp.ISSUER}")
    if claims.get("aud") != AUDIENCE + str(result.get("digest")):
        wrong.append("the token was not signed for this result")
    if result.get("digest") != rr.digest(result):
        wrong.append("the result does not hash to its digest")
    why = checks(result) if result.get("status") == "reproduced" else ""
    if why and why not in wrong[-1:]:
        wrong.append(why)
    return {k: claims.get(k) for k in ("repository", "run_id", "sha", "workflow_ref")}, wrong
