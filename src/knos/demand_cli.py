"""`knos demand "<idea>" --age ... --near ... --price-level ...`: the Qloo demand check from the command line.

One flag per field of knos.qloo_families (the same names as the app's controls, the /mcp tool's arguments and the API's
body, with dashes): --age, --gender, --hide-leader, --exclude, --popularity-max, --near, --radius, --price-level,
--references-brand, --product-kind, --year-min, --year-max, --lookup, --entity-id, ... and --qloo PARAM=VALUE for any other
documented Qloo parameter. It POSTs to the hosted demand check (KNOS_WANTED_URL, default https://knos.onrender.com), where
Qloo is called server side; no Qloo key is needed here. Read-only: nothing is locked or signed.
"""
import json
import re
import urllib.error
import urllib.request

from . import qloo_families as Q

BY_FLAG = {Q.flag(k): k for k in Q.FIELDS}
ID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")   # a Qloo entity id


def parse(args: list[str]) -> dict:
    """--name value / --name=value / --flag (booleans) / --qloo PARAM=VALUE (repeatable), checked against the table."""
    out: dict = {}
    i = 0
    while i < len(args):
        a = args[i]
        if not a.startswith("--"):
            raise ValueError(f"unexpected argument {a!r}: options are --name value (knos demand --help)")
        name, _, val = a.partition("=")
        if name == "--year":                         # --year 2015 or --year 2015-2024: the two year fields at once
            if not val:
                i += 1
                val = args[i] if i < len(args) else ""
            lo, _, hi = val.partition("-")
            if not lo.strip().isdigit() or (hi and not hi.strip().isdigit()):
                raise ValueError("--year YYYY or --year YYYY-YYYY")
            out["year_min"], out["year_max"] = lo.strip(), (hi or lo).strip()
            i += 1
            continue
        if name not in BY_FLAG:
            raise ValueError(f"unknown option {name} (knos demand --help lists them)")
        field = BY_FLAG[name]
        kind = Q.FIELDS[field][2]
        if not val and kind == "bool":
            val = "true"
        elif not val:
            i += 1
            if i >= len(args):
                raise ValueError(f"{name} needs a value")
            val = args[i]
        if field == "qloo":
            k, _, v = val.partition("=")
            if not k or not v:
                raise ValueError("--qloo PARAM=VALUE (a parameter docs.qloo.com documents)")
            out.setdefault("qloo", {})[k] = v
        elif field == "exclude" and not all(ID.fullmatch(x.strip()) for x in val.split(",") if x.strip()):
            out["exclude_names"] = val                # names, as the app's Gaps control takes them: Qloo resolves each one
        else:
            out[field] = val
        i += 1
    return Q.options(out)


def flags_help() -> str:
    rows = [f"{Q.flag(k)} ({Q.FIELDS[k][0]}): {Q.FIELDS[k][3]} [Qloo {Q.FIELDS[k][1]}]" for k in Q.FIELDS]
    rows.append("--year YYYY[-YYYY] (F6): both --year-min and --year-max at once; --exclude also takes names (sent as --exclude-names)")
    return "\n\n".join(rows)


def ask(idea: str, place: str | None, leader: str | None, opts: dict, picked: bool = False) -> dict:
    from .demand_tool import TIMEOUT_S, base_url
    url = base_url()
    if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise ValueError("KNOS_WANTED_URL must be an https URL (or a local server)")
    body = {"idea": idea, **({"place": place} if place else {}), **({"leader": leader} if leader else {}), **opts, **({"picked": True} if picked else {})}
    req = urllib.request.Request(url + "/api/check", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "knos-cli"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read(4_000_000))
    except urllib.error.HTTPError as e:
        try:
            why = json.loads(e.read(4000) or b"{}").get("error", "")
        except ValueError:
            why = ""
        raise ValueError(f"the demand check said {e.code}: {why or e.reason}") from None


def summary(rep: dict) -> dict:
    fam = rep.get("families") or {}
    # the reason in one plain sentence: Qloo's month line while it is used up, else the verdict's first reason
    reason = rep.get("qloo_limit") or next(iter((rep.get("decision") or {}).get("reasons") or []), None)
    return {"report": rep.get("hash"), "verdict": (rep.get("decision") or {}).get("verdict"), "reason": reason, "label": rep.get("label"), "qloo_calls": rep.get("qloo_calls"),
            "options": rep.get("options"), "grounding": rep.get("grounding"),
            "families": {f: {k: v for k, v in a.items() if k in ("question", "call", "answer", "hot", "by_id", "places", "brand_id")}
                         for f, a in fam.items()},
            "calls": len(rep.get("calls") or [])}


def which_lines(w: dict) -> list[str]:
    """Which one do you mean? The readings, numbered, and how to pick one."""
    out = ["Which one do you mean?"]
    pp = w.get("paper")
    if pp:
        out.append(f"Paper: {pp.get('title')} ({pp.get('year')}), cited {pp.get('cited_by_count')} times; {', '.join(pp.get('concepts') or [])}")
    for i, r in enumerate(w.get("readings") or [], 1):
        d = r.get("differs") or {}
        out.append(f"  {i}. {r['text']}" + (f"  ({d.get('theirs') or 'no word'} against {d.get('yours') or 'no word'})" if d else ""))
    if w.get("name_box"):
        out.append(f"  {w.get('name_prompt') or 'Name the product this result enables'}: knos demand \"<product>\" --picked")
    out.append("Run again with --pick N, or --picked to check your words exactly.")
    return out


def lines(rep: dict) -> list[str]:
    """The answer in three plain lines: the verdict, the reason (Qloo's month, else the first call's error, else the
    verdict's first reason) and the report with its page. A queued check: what it was read as, when Qloo answers,
    and its Ready brief's criteria hash."""
    if rep.get("kind") == "which_one":
        return which_lines(rep)
    if rep.get("queued"):
        rd = rep.get("ready") or {}
        return [rep.get("result_line") or f"Read as {rep.get('idea')}", rep["queued"]["line"],
                f"Ready brief: criteria hash {rd.get('criteria_hash') or 'none'}" + (f"; stand-in: {rep['stand_in']['said']}" if rep.get("stand_in") else "")]
    d = rep.get("decision") or {}
    err = next((c.get("error") for c in rep.get("calls") or [] if isinstance(c, dict) and c.get("error")), None)
    reason = rep.get("qloo_limit") or err or next(iter(d.get("reasons") or []), "") or "no reason given"
    near = rep.get("nearest") or {}
    h = str(rep.get("hash") or "")
    return [f"Verdict: {d.get('verdict') or 'none'}" + (f", from the nearest idea Qloo has answered: {near.get('idea')}" if near.get("idea") else ""),
            f"Why: {reason}",
            f"Report: {h[:16] or 'none'}, {len(rep.get('calls') or [])} Qloo calls" + (f", https://knos.onrender.com/r/{h[:16]}" if h else "")]


def register(app, help_lines: list | None = None) -> None:
    """`knos demand "<idea>" [--flags]` on the main app. `help_lines`: cli._HELP."""
    import importlib
    typer = importlib.import_module("typer")          # annotations here are evaluated (no postponed annotations in this module)

    if help_lines is not None:
        help_lines.append(("demand", None, "Is it wanted? Qloo's demand check with every family's option as a flag."))

    @app.command("demand", context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
                 help="Qloo demand check: who, gaps, where, price tier, who serves it, media kind, look up. Prints three lines; --json the report.",
                 epilog="Qloo's options, each a flag:\n\n" + flags_help())
    def demand_(ctx: typer.Context,  # type: ignore[name-defined]  # typer: imported on registration only
                idea: str = typer.Argument(..., help="the product idea in plain words (3 to 500 characters)"),
                place: str = typer.Option("", "--place", help="the launch market (city or country)"),
                leader: str = typer.Option("", "--leader", help="the market leader to compare against"),
                as_json: bool = typer.Option(False, "--json", help="the whole report, not the three lines"),
                pick: int = typer.Option(0, "--pick", help="check reading N of the ones `knos demand` listed (which one do you mean?)"),
                picked: bool = typer.Option(False, "--picked", help="check the words exactly as typed, with no readings step")) -> None:
        try:
            opts = parse(list(ctx.args))
            rep = ask(idea, place or None, leader or None, opts, picked=picked)
            if rep.get("kind") == "which_one" and pick:
                rs = rep.get("readings") or []
                if not 1 <= pick <= len(rs):
                    raise ValueError(f"--pick 1 to {len(rs)}")
                rep = ask(rs[pick - 1]["text"], place or None, leader or None, opts, picked=True)
        except ValueError as why:
            typer.echo(str(why), err=True)
            raise typer.Exit(2) from None
        if as_json:
            typer.echo(json.dumps(rep, indent=1, ensure_ascii=False, default=str))
        else:
            typer.echo("\n".join(lines(rep)))
