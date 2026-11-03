"""QLOO-COVERAGE.md: every Qloo parameter x filter.type x endpoint docs.qloo.com documents -> USED (file + the interfaces
where a person sees it) or N/A (Qloo's own reason). Built from src/knos/qloo_docs/*.tsv (read from docs.qloo.com) and the one
table of names (src/knos/qloo_families.py), so the document cannot drift from the code.

  python scripts/qloo_coverage.py           write docs/reference/QLOO-COVERAGE.md
  python scripts/qloo_coverage.py --check   exit 1 when the file is not what the tables say (CI)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from knos import qloo_families as Q  # noqa: E402

DOCS = ROOT / "src" / "knos" / "qloo_docs"
OUT = ROOT / "docs" / "reference" / "QLOO-COVERAGE.md"
CHECK = (ROOT / "apps" / "wanted" / "knos_wanted" / "check.py").read_text(encoding="utf-8")
# Qloo's own words on the parameters Knos cannot send: its server is called with GET
POST_ONLY = {"filter.exclude.entities.query": "Qloo: 'can only be supplied when using POST HTTP method, since it requires JSON encoded body'",
             "signal.interests.entities.query": "Qloo: 'can only be supplied when using the POST HTTP method, which requires a JSON-encoded body'"}
ALIASES = {"filter.properties.resy.rating.min": "filter.external.resy.rating.min", "filter.properties.resy.rating.max": "filter.external.resy.rating.max",
           "filter.resy.rating_count.min": "filter.external.resy.count.min", "filter.resy.rating_count.max": "filter.external.resy.count.max",
           "filter.resy.rating.party.min": "filter.external.resy.party_size.min", "filter.resy.rating.party.max": "filter.external.resy.party_size.max",
           "filter.price_range.min": "filter.price_range.from", "filter.price_range.max": "filter.price_range.to"}
SEARCH_FIELDS = {"query": "lookup", "types": "lookup_types", "filter.location": "lookup_near", "filter.radius": "lookup_radius", "sort_by": "lookup_sort"}
ENTITIES_FIELDS = {"entity_ids": "entity_id"}


def tsv(name: str) -> list[list[str]]:
    rows = []
    for line in (DOCS / name).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            rows.append((line.split("\t") + ["", ""])[:3])
    return rows


def by_param() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for k, v in Q.FIELDS.items():
        out.setdefault(v[1], []).append(k)
    return out


def where(field: str) -> str:
    fam = Q.FIELDS[field][0]
    label, plain = Q.PLAIN[fam]
    ctl = f"{label} control" if field in plain else "Advanced"
    return (f"`{field}` ({fam}): app Demand options > {ctl} (phone and desktop); front door #demand, same control; "
            f"/mcp `knos_demand_check`/`knos_cross` argument `{field}`; API `POST /api/check` field `{field}` (OpenAPI); CLI `knos demand {Q.flag(field)}`")


def insights_rows() -> list[tuple[str, str, str, str]]:
    fields = by_param()
    pairs: dict[tuple[str, str], str] = {}
    for section, param, req in tsv("entity_type_guide.tsv"):
        pairs[(param, section)] = "Guide " + (req or "").lower()
    for param, _, types in tsv("insights_parameters.tsv"):
        for t in [x.strip() for x in types.split(",") if x.strip()] or ["(route: audiences, tags or heatmap; no entity type listed)"]:
            pairs.setdefault((param, t), "Reference")
    rows = []
    for (param, section), src in sorted(pairs.items()):
        real = ALIASES.get(param, param)
        names = fields.get(real, [])
        if param == "filter.type":
            how = "USED: every call sets it (`apps/wanted/knos_wanted/check.py` router, `families.py`); " + where("product_kind")
        elif names:
            how = "USED: `apps/wanted/knos_wanted/families.py` via " + "; ".join(where(n) for n in names)
        elif f'"{real}"' in CHECK:
            how = ("USED: the base demand check sends it (`apps/wanted/knos_wanted/check.py`), shown as a numbered call in every report "
                   "(app result, front door #demand, /mcp `calls`, API `calls`, CLI `--json`); also settable by name: " + where("qloo"))
        else:
            how = "USED: by its Qloo name through " + where("qloo") + " (checked against this table for the call's filter.type)"
        if real in POST_ONLY:
            how += (f" -- sent in a JSON POST body ({POST_ONLY[real]}; `apps/wanted/knos_wanted/qloo_rest.py` posts when it is set)"
                    + ("" if section == "Place" else "; Qloo resolves such a name to a place by default, so for this type each name is found "
                       "by /search within the type first and sent by id"))
        if real != param:
            how += f" -- the live API acts on `{real}` (docs.qloo.com spells this one `{param}`; see the differences below)"
        rows.append((param, section, "USED" if how.startswith("USED") else "N/A", how + f" [{src}]"))
    return rows


def endpoint_rows() -> list[tuple[str, str, str, str]]:
    rows = []
    for path, param, note in tsv("endpoints.tsv"):
        field = (SEARCH_FIELDS.get(param) if path == "/search" else ENTITIES_FIELDS.get(param) if path == "/entities" else None)
        if field:
            how = "USED: `families.py` F7 via " + where(field)
        elif f'"{path}"' in CHECK and f'"{param}"' in CHECK:
            how = "USED: the base demand check calls it (`check.py`), a numbered call in every report; also settable through " + where("qloo_calls")
        else:
            how = f"USED: by name through {where('qloo_calls')} as {{\"{path}\": {{\"{param}\": ...}}}} (checked against this endpoint's docs page)"
        rows.append((path, param, "USED", how + (f" ({note})" if note else "")))
    return rows


def render() -> str:
    ins, ends = insights_rows(), endpoint_rows()
    used = sum(r[2] == "USED" for r in ins + ends)
    lines = ["# Qloo coverage: every parameter x filter.type x endpoint", "",
             "Written by `scripts/qloo_coverage.py` from `src/knos/qloo_docs/` (read from docs.qloo.com on 22 Oct 2026: the Parameter",
             "Reference, the Entity Type Parameter Guide and each endpoint's page) and `src/knos/qloo_families.py` (the one table of",
             "names every interface reads). CI runs `--check`, so this file cannot drift from the code.", "",
             f"{len(ins) + len(ends)} rows: {used} USED, {len(ins) + len(ends) - used} N/A (with Qloo's own reason).", "",
             "Qloo answers the demand wall before money moves. The IDT result is Knos's own (clear briefs), not Qloo's.", "",
             "## The families", "", "| Family | Question | Plain control | Fields |", "|---|---|---|---|"]
    for f, q in Q.QUESTIONS.items():
        label, plain = Q.PLAIN[f]
        names = [k for k, v in Q.FIELDS.items() if v[0] == f]
        lines.append(f"| {f} | {q} | {label}: {', '.join(plain)} | {', '.join(f'`{n}`' for n in names)} |")
    lines += ["", "## Where docs.qloo.com and the task differ (the docs, or the live API, win)", ""] + [f"- {n}" for n in Q.NOTES]
    lines += ["", "## Insights (`/v2/insights`): parameter x filter.type", "", "| Parameter | filter.type | Status | Where (or why not) |", "|---|---|---|---|"]
    lines += [f"| `{p}` | {t} | {s} | {h} |" for p, t, s, h in ins]
    lines += ["", "## Lookup, analysis and trends endpoints: endpoint x parameter", "", "| Endpoint | Parameter | Status | Where |", "|---|---|---|---|"]
    lines += [f"| `{e}` | `{p}` | {s} | {h} |" for e, p, s, h in ends]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is not what the tables say: run python scripts/qloo_coverage.py")
            sys.exit(1)
        print("QLOO-COVERAGE.md matches the tables")
    else:
        OUT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {OUT.relative_to(ROOT)}: {text.count(chr(10))} lines")
