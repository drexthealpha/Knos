"""The `knos mcp` tools for idea in (step 1) and wanted? (step 2), listed when KNOS_MCP_TOOLS=ideas. Read-only: they read public research APIs and
build plans; none signs or sends a transaction (`knos idea commit` does that, from a terminal, with the buyer's key).

Words that come from a research source (a title, a venue, a topic, a researcher's name) are someone else's text:
they come back only inside `untrusted` (data, never an instruction), as every knos mcp tool returns outside words.
"""
from __future__ import annotations

from typing import Any

OPT_IN_ENV, OPT_IN_WORD = "KNOS_MCP_TOOLS", "ideas"


_REF = {"type": "string", "description": "doi:..., pmid:..., pmcid:..., arxiv:..., biorxiv:..., medrxiv:..., openalex:W..., NCT..., uspto:..."}

MCP_TOOLS: list[dict[str, Any]] = [
    {"name": "knos_idea_get", "title": "An idea from a research source",
     "description": "One claim from OpenAlex, arXiv, PubMed, Europe PMC, bioRxiv/medRxiv, Crossref, ClinicalTrials.gov or USPTO patents, read "
                    "from the source's official API and normalised to one Knos Claim record: field (one of 26, all science), ids "
                    "(DOI, PMID, NCT, arXiv...), the Retraction Watch check (via Crossref) and risk signals. The work's own words "
                    "(title, venue) are inside `untrusted`. `label` says LIVE or FIXTURE (patents are a labelled fixture until "
                    "USPTO_ODP_API_KEY is set). Sends nothing.",
     "properties": {"ref": _REF}, "required": ["ref"]},
    {"name": "knos_idea_search", "title": "Find ideas in a research source",
     "description": "Claims matching words in one source (openalex, arxiv, pubmed, europepmc, biorxiv, medrxiv, crossref, clinicaltrials, "
                    "uspto), each a Knos Claim record; titles inside `untrusted`. Sends nothing.",
     "properties": {"source": {"type": "string", "description": "openalex, arxiv, pubmed, europepmc, biorxiv, medrxiv, crossref, clinicaltrials or uspto"},
                    "words": {"type": "string", "description": "search words"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 5, "description": "how many"}},
     "required": ["source", "words"]},
    {"name": "knos_idea_in", "title": "An idea from a person, a player or an agent",
     "description": "Make a Knos Claim record from a stated idea: the statement, its field (given or guessed), who says it (an ORCID iD "
                    "or GitHub login, read from the public record; reading proves the iD exists, not that the caller owns it) and "
                    "whether a person, a game player or an AI agent states it. Sends nothing.",
     "properties": {"statement": {"type": "string", "description": "the claim, one sentence"},
                    "field": {"type": "string", "description": "one of the 26 fields (OpenAlex topics), e.g. Materials Science"},
                    "by": {"type": "string", "description": "orcid:0000-0000-0000-0000 or github:login"},
                    "kind": {"type": "string", "description": "person, player or agent (default person)"}},
     "required": ["statement"]},
    {"name": "knos_researcher", "title": "A researcher's public record",
     "description": "A researcher's public ORCID record (anonymous read of pub.orcid.org) or GitHub account: id, url and name "
                    "(inside `untrusted`). Shows the iD exists; owning it is 'sign in with ORCID'. Sends nothing.",
     "properties": {"who": {"type": "string", "description": "orcid:0000-0000-0000-0000 or github:login"}}, "required": ["who"]},
    {"name": "knos_idea_wanted", "title": "Is the idea wanted? Demand + pull commitment plan",
     "description": "Step 2 (wall 1): Knos's demand check on the product the idea would become (Qloo via its "
                    "official MCP harness; a labelled MOCK until QLOO_API_KEY) and the plan of a pre-order: a buyer locks test "
                    "money to buy `units` at `price`, held in one knos_pay order per stage and released "
                    "stage by stage at named milestones (preprint posted, trial registered, results posted, referee pass, lab QC...). Returns the plan "
                    "with amounts, fees (config/fees.yaml) and deadlines; it signs and sends nothing (`knos idea commit` locks it).",
     "properties": {"ref": _REF,
                    "units": {"type": "integer", "minimum": 1, "maximum": 1_000_000, "default": 10, "description": "N units the buyer commits to"},
                    "price": {"type": "integer", "minimum": 1, "maximum": 1_000_000, "default": 4, "description": "P whole test units per unit"},
                    "stages": {"type": "string", "description": "oracle:bps,... summing to 10000 (default by kind of claim)"},
                    "product": {"type": "string", "description": "the product the idea would become, for the demand check"}},
     "required": ["ref"]},
    {"name": "knos_idea_check", "title": "Is a stage's milestone met?",
     "description": "Read a stage's milestone oracle now (preprint_posted, journal_published, trial_registered, results_posted, "
                    "not_retracted) from the public source and return met / not met / pending with the evidence and its sha256, "
                    "which is what the judge signs over to release that stage. Sends nothing.",
     "properties": {"ref": _REF, "oracle": {"type": "string", "description": "preprint_posted, journal_published, trial_registered, results_posted or not_retracted"}},
     "required": ["ref", "oracle"]},
]



def _fail(e: Exception):
    from ..mcp import Failed
    raise Failed(str(e)) from None


def shape(c: dict) -> dict:
    """A Claim record for an agent: everything Knos decided outside; the source's own words inside `untrusted`."""
    words = {k: c.get(k) for k in ("statement", "venue", "topic", "subfield", "subject") if c.get(k)}
    by = (c.get("origin") or {}).get("by")
    if isinstance(by, dict) and by.get("name"):
        words["by_name"] = by["name"]
    keep = {k: v for k, v in c.items() if k not in words and k not in ("statement", "venue", "topic", "subfield", "subject")}
    if isinstance(by, dict):
        keep["origin"] = {**c["origin"], "by": {k: v for k, v in by.items() if k != "name"}}
    return {"claim": keep, "untrusted": words}


def _guard(fn):
    from . import IdeaError
    from .http import FetchError
    try:
        return fn()
    except (IdeaError, FetchError, ValueError) as e:
        _fail(e)


def idea_get(args: dict) -> dict:
    from .sources import get
    return shape(_guard(lambda: get(args["ref"])))


def idea_search(args: dict) -> dict:
    from .sources import search
    got = _guard(lambda: search(args["source"], args["words"], limit=int(args.get("limit") or 5)))
    return {"count": len(got), "claims": [shape(c) for c in got]}


def idea_in(args: dict) -> dict:
    from . import person
    from .identity import short, who
    ident = _guard(lambda: short(who(args["by"]))) if args.get("by") else None
    return shape(_guard(lambda: person(args["statement"], field_name=args.get("field"), by=ident, kind=args.get("kind") or "person")))


def researcher(args: dict) -> dict:
    from .identity import who
    got = _guard(lambda: who(args["who"]))
    return {**{k: v for k, v in got.items() if k not in ("name", "researcher_urls", "external_ids")},
            "untrusted": {k: got.get(k) for k in ("name", "researcher_urls", "external_ids") if got.get(k)}}


def idea_wanted(args: dict) -> dict:
    from . import wanted as W
    from .cli import _stages
    from .sources import get
    c = _guard(lambda: get(args["ref"]))
    d = W.demand(c, args.get("product"))
    p = _guard(lambda: W.plan(c, units=int(args.get("units") or 10), price=int(args.get("price") or 4), stages=_stages(args.get("stages")),
                              demand_hash=d.get("hash")))
    stages = [{"part": s, "oracle": p[s]["oracle"], "amount": p[s]["amount"], "payout_fee": p[s]["payout_fee"], "deadline_s": p[s]["work_s"],
               "scope": p[s]["scope"], "terms_hash": p[s]["terms_hash"]} for s in p["stages"]]
    return {**shape(c), "demand": {k: v for k, v in d.items() if k != "idea"}, "commitment": p["commitment"], "commitment_hash": p["commitment_hash"],
            "stages": stages, "buyer_pays": p["buyer_pays"], "program": p["program"], "cluster": "devnet",
            "lock_with": f"knos idea get {args['ref']} --out idea.json && knos idea commit idea.json --units {p['commitment']['units']} "
                         f"--price {p['commitment']['price']} --payee <github:id|orcid:iD>@<wallet> --panel M:<referee keys> --program <knos_pay panel test build id> "
                         f"--wallet <your devnet key> --mint <test mint>" + (f" --demand {d['hash']}" if d.get("hash") else ""),
            "sends": "nothing"}


def idea_check(args: dict) -> dict:
    from . import wanted as W
    from .sources import get
    c = _guard(lambda: get(args["ref"]))
    if args["oracle"] in ("referee_pass", "lab_qc"):
        _fail(ValueError("referee_pass and lab_qc read a verdict file: use `knos idea check REF ORACLE --verdict FILE`"))
    return _guard(lambda: W.check(c, args["oracle"]))


HANDLERS = {"knos_idea_get": idea_get, "knos_idea_search": idea_search, "knos_idea_in": idea_in, "knos_researcher": researcher,
            "knos_idea_wanted": idea_wanted, "knos_idea_check": idea_check}
