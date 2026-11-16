"""Idea in: a claim from anyone or any research source, in every field of science, made into ONE record that the
rest of knos.ideas (wanted, commit) and knos.graduation read.

Where an idea comes from (`origin.kind`):
    person      anyone, with an identity: ORCID iD and/or GitHub account (knos.ideas.identity), or none
    player      a player of a Knos game (the same record; the game names the player)
    agent       an AI agent (its name; it states the claim, Knos checks it like any other)
    literature  a claim found in a research source (knos.ideas.sources): OpenAlex, arXiv, PubMed/Europe PMC,
                bioRxiv/medRxiv, Crossref, ClinicalTrials.gov, patents (USPTO Open Data Portal)

The Claim record (`claim()` builds it; `check()` refuses a malformed one):
    v, id            "knos-idea:" + 32 hex of sha256(the first source id, or the statement); stable across reads
    field            one of FIELDS (the 26 fields of OpenAlex's topic taxonomy: all of science, not one field)
    statement        the claim in one sentence (for literature: the work's title; Knos never rewrites a paper's words)
    origin           {kind, by: identity or name, at}
    ids              doi, pmid, pmcid, nct, arxiv, biorxiv, medrxiv, openalex, patent (those known)
    sources          [{source, id, url, mode: live|fixture, read}] every read that built the record
    retraction       {checked, retracted, notices: [{doi, type, source, date}], via}: Crossref's Retraction Watch data
    risk             cheat/risk signals: "retracted", "corrected", "expression-of-concern", "withdrawn-trial", ...
    links            landing pages
    year, venue      when and where (if known)
    label            "LIVE ..." or "FIXTURE ..." in words, so a fixture is never mistaken for a read
    hash             sha256 of the record without `hash` and the read times (what a pull commitment's terms carry)

A retracted or corrected key paper is a RISK signal the referee and buyers see, never silently dropped.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

V = 1
PREFIX = "knos-idea:"
KINDS = ("person", "player", "agent", "literature")

# OpenAlex topic taxonomy: 26 fields in 4 domains (docs.openalex.org "Topics"; the ASJC fields). All science.
FIELDS = (
    "Agricultural and Biological Sciences", "Arts and Humanities", "Biochemistry, Genetics and Molecular Biology",
    "Business, Management and Accounting", "Chemical Engineering", "Chemistry", "Computer Science", "Decision Sciences",
    "Dentistry", "Earth and Planetary Sciences", "Economics, Econometrics and Finance", "Energy", "Engineering",
    "Environmental Science", "Health Professions", "Immunology and Microbiology", "Materials Science", "Mathematics",
    "Medicine", "Neuroscience", "Nursing", "Pharmacology, Toxicology and Pharmaceutics", "Physics and Astronomy",
    "Psychology", "Social Sciences", "Veterinary",
)
_FOLD = {f.lower(): f for f in FIELDS}

# arXiv primary category prefix -> field
ARXIV_FIELD = {
    "cond-mat.mtrl-sci": "Materials Science", "cond-mat": "Physics and Astronomy", "physics.chem-ph": "Chemistry",
    "physics.bio-ph": "Biochemistry, Genetics and Molecular Biology", "physics.med-ph": "Medicine", "physics.app-ph": "Engineering",
    "physics.ao-ph": "Earth and Planetary Sciences", "physics.geo-ph": "Earth and Planetary Sciences", "physics": "Physics and Astronomy",
    "astro-ph": "Physics and Astronomy", "gr-qc": "Physics and Astronomy", "hep": "Physics and Astronomy", "nucl": "Physics and Astronomy",
    "quant-ph": "Physics and Astronomy", "nlin": "Physics and Astronomy", "math-ph": "Mathematics", "math": "Mathematics",
    "cs": "Computer Science", "stat": "Mathematics", "eess": "Engineering", "econ": "Economics, Econometrics and Finance",
    "q-bio.NC": "Neuroscience", "q-bio": "Biochemistry, Genetics and Molecular Biology", "q-fin": "Economics, Econometrics and Finance",
}
# bioRxiv / medRxiv subject category -> field
SUBJECT_FIELD = {
    "neuroscience": "Neuroscience", "immunology": "Immunology and Microbiology", "microbiology": "Immunology and Microbiology",
    "pharmacology and toxicology": "Pharmacology, Toxicology and Pharmaceutics", "ecology": "Environmental Science",
    "plant biology": "Agricultural and Biological Sciences", "zoology": "Agricultural and Biological Sciences",
    "animal behavior and cognition": "Agricultural and Biological Sciences", "evolutionary biology": "Agricultural and Biological Sciences",
    "paleontology": "Earth and Planetary Sciences", "bioengineering": "Engineering", "scientific communication and education": "Social Sciences",
    "epidemiology": "Medicine", "infectious diseases": "Medicine", "public and global health": "Medicine", "psychiatry and clinical psychology": "Psychology",
    "nursing": "Nursing", "dentistry and oral medicine": "Dentistry",
}
# USPTO CPC section letter -> field (a patent's first CPC class)
CPC_FIELD = {"A": "Medicine", "B": "Engineering", "C": "Chemistry", "D": "Materials Science", "E": "Engineering", "F": "Engineering",
             "G": "Physics and Astronomy", "H": "Engineering", "Y": "Environmental Science"}
_WORDS = (  # last resort for a person's idea with no field given: a few words per field, first hit wins
    (("perovskite", "alloy", "crystal", "battery cathode", "polymer", "material", "graphene", "ceramic"), "Materials Science"),
    (("trial", "patients", "dose", "therapy", "clinical", "vaccine", "cancer"), "Medicine"),
    (("protein", "gene", "crispr", "genome", "enzyme", "cell", "rna", "dna", "binder"), "Biochemistry, Genetics and Molecular Biology"),
    (("neuron", "brain", "cognit"), "Neuroscience"),
    (("molecule", "synthesis", "catalyst", "reaction", "yield"), "Chemistry"),
    (("algorithm", "model", "benchmark", "llm", "neural network", "software", "sort", "compiler", "database"), "Computer Science"),
    (("solar", "grid", "fuel", "hydrogen", "energy"), "Energy"),
    (("climate", "soil", "ocean", "carbon capture"), "Environmental Science"),
    (("theorem", "conjecture", "proof"), "Mathematics"),
    (("robot", "circuit", "pcb", "sensor", "bridge", "engine"), "Engineering"),
    (("quantum", "particle", "galaxy", "laser", "optic"), "Physics and Astronomy"),
    (("crop", "plant", "livestock"), "Agricultural and Biological Sciences"),
)


class IdeaError(ValueError):
    pass


class Names:
    """Attribute access to the names Knos's idea records use (`K.field == "field"`): callers and tests name a key
    through these constants instead of repeating its spelling."""

    def __init__(self, words: str):
        for w in words.split():
            setattr(self, w.replace("-", "_"), w)


# every environment variable knos.ideas reads (keys are read only by the adapter that needs them, never logged)
ENVS = ("OPENALEX_API_KEY", "NCBI_API_KEY", "USPTO_ODP_API_KEY", "QLOO_API_KEY", "KNOS_WANTED_LIVE", "KNOS_CONTACT_EMAIL",
        "KNOS_IDEAS_RECORD", "KNOS_IDEAS_FIXTURES", "KNOS_MCP_TOOLS")
FIXTURES_ENV = ENVS[7]

# every key of a Claim record, of a plan, of an oracle's evidence and of a contract record, and the source names
K = Names("v id field statement origin kind by ids sources source mode read retraction retracted checked notices risk links "
          "year venue label hash trial status has_results phases conditions published_doi arxiv_category fixture_label patent "
          "doi pmid pmcid nct arxiv biorxiv medrxiv openalex epmc researcher title type updated-by corrected live fixture "
          "met why evidence_hash oracle stages stage1 stage2 stage3 pool scope terms terms_hash amount payout_fee work_s "
          "commitment commitment_hash buyer_pays total parts locked locked_total orders claim passed qc lean label confirmed "
          "audience next_route untrusted claims structuredContent isError name verified login person player agent literature "
          "crossref pubmed europepmc clinicaltrials uspto unread orcid github "
          "primary_topic authorships author display_name is_retracted protocolSection identificationModule nctId briefTitle "
          "statusModule overallStatus DOI mock steps tools payees payee")


def field(name: str | None = None, *, arxiv: str | None = None, subject: str | None = None, cpc: str | None = None,
          text: str = "") -> str:
    """The claim's field: the name given (one of FIELDS, any case), else from an arXiv category, a bioRxiv/medRxiv
    subject, a CPC class, else from words of the statement; "Multidisciplinary" when nothing says."""
    if name:
        got = _FOLD.get(name.strip().lower())
        if got is None:
            raise IdeaError(f"field: one of the {len(FIELDS)} fields (knos idea fields lists them), not {name!r}")
        return got
    if arxiv:
        for k in sorted(ARXIV_FIELD, key=len, reverse=True):
            if arxiv == k or arxiv.startswith(k + ".") or arxiv.startswith(k + "-") or arxiv.split(".")[0] == k:
                return ARXIV_FIELD[k]
    if subject:
        s = subject.strip().lower()
        if s in SUBJECT_FIELD:
            return SUBJECT_FIELD[s]
        if s:
            return "Biochemistry, Genetics and Molecular Biology"     # bioRxiv's other subjects are molecular/cell biology
    if cpc:
        return CPC_FIELD.get(cpc.strip()[:1].upper(), "Engineering")
    low = text.lower()
    for words, f in _WORDS:
        if any(w in low for w in words):
            return f
    return "Multidisciplinary"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(s) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", str(s or "")).split())


def claim_id(first_id: str | None, statement: str) -> str:
    return PREFIX + hashlib.sha256((first_id or ("statement:" + statement.strip().lower())).encode()).hexdigest()[:32]


def record_hash(c: dict) -> str:
    keep = {k: v for k, v in c.items() if k not in ("hash", "label")}
    keep["sources"] = [{k: v for k, v in s.items() if k != "read"} for s in c.get("sources", [])]
    keep["origin"] = {k: v for k, v in (c.get("origin") or {}).items() if k != "at"}
    if isinstance(keep.get("retraction"), dict):
        keep["retraction"] = {k: v for k, v in keep["retraction"].items() if k != "read"}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()


def claim(statement: str, *, field_name: str, kind: str, by=None, ids: dict | None = None, sources: list | None = None,
          retraction: dict | None = None, links: list | None = None, year: int | None = None, venue: str | None = None,
          extra: dict | None = None) -> dict:
    statement = _clean(statement)
    if not 8 <= len(statement) <= 2000:
        raise IdeaError("statement: one sentence of 8 to 2,000 characters")
    if kind not in KINDS:
        raise IdeaError(f"origin: one of {', '.join(KINDS)}")
    if field_name not in FIELDS and field_name != "Multidisciplinary":
        raise IdeaError(f"field: one of FIELDS, not {field_name!r}")
    ids = {k: v for k, v in (ids or {}).items() if v}
    sources = sources or []
    first = next((f"{s['source']}:{s['id']}" for s in sources if s.get("id")), None)
    first = next((f"doi:{ids['doi'].lower()}" for _ in [0] if ids.get("doi")), first)   # one paper read from two sources is one idea
    risk = []
    r = retraction or {"checked": False, "retracted": False, "notices": [], "via": None}
    for n in r.get("notices", []):
        t = {"retraction": "retracted", "correction": "corrected", "expression_of_concern": "expression-of-concern",
             "expression-of-concern": "expression-of-concern", "withdrawal": "retracted", "removal": "retracted"}.get(str(n.get("type")).lower())
        if t and t not in risk:
            risk.append(t)
    if r.get("retracted") and "retracted" not in risk:
        risk.append("retracted")
    modes = {s.get("mode") for s in sources}
    if "fixture" in modes:
        label = "FIXTURE: recorded or synthetic response, not a read made now (" + ", ".join(sorted(s["source"] for s in sources if s.get("mode") == "fixture")) + ")"
    elif sources:
        label = "LIVE: read from the official API at " + ", ".join(sorted({s.get("read", "")[:16] for s in sources}))
    else:
        label = "STATED by its author: no source read yet"
    c = {"v": V, "id": claim_id(first, statement), "field": field_name, "statement": statement,
         "origin": {"kind": kind, "by": by, "at": now()}, "ids": ids, "sources": sources, "retraction": r,
         "risk": risk, "links": links or [], "year": year, "venue": _clean(venue) or None, **(extra or {}), "label": label}
    c["hash"] = record_hash(c)
    return c


def check(c: dict) -> dict:
    """A Claim record from outside (a file, an agent, an MCP argument), refused unless well formed and unchanged."""
    if not isinstance(c, dict) or c.get("v") != V or not str(c.get("id", "")).startswith(PREFIX):
        raise IdeaError("not a Knos idea record (v1)")
    for k in ("field", "statement", "origin", "ids", "sources", "retraction", "risk", "hash"):
        if k not in c:
            raise IdeaError(f"the record has no {k}")
    if c["hash"] != record_hash(c):
        raise IdeaError("the record was changed after it was made (its hash does not match)")
    return c


def person(statement: str, *, field_name: str | None = None, by=None, kind: str = "person") -> dict:
    """An idea from a person, a player or an AI agent: stated, not yet read anywhere."""
    if kind not in ("person", "player", "agent"):
        raise IdeaError("kind: person, player or agent (literature comes from a source)")
    return claim(statement, field_name=field(field_name, text=statement), kind=kind, by=by)


# ---- the small, offline contract (V34DOG task #283): intake / orcid_ok / release_schedule -------------------------------
SOURCES = ("person", "player", "agent", "openalex", "arxiv", "pubmed", "europepmc", "biorxiv", "medrxiv", "crossref",
           "clinicaltrials", "patent")
_ORCID_RE = re.compile(r"^(?:https?://orcid\.org/|orcid:)?(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])/?$")


def orcid_ok(s) -> bool:
    """An ORCID iD, bare or as https://orcid.org/..., whose last character is its ISO 7064 11,2 check digit."""
    m = _ORCID_RE.match(str(s or "").strip())
    if not m:
        return False
    digits = m.group(1).replace("-", "").upper()
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    return digits[-1] == ("X" if check == 10 else str(check))


def _bare_orcid(s) -> str | None:
    m = _ORCID_RE.match(str(s or "").strip())
    return m.group(1).upper() if m else None


def release_schedule(total_units: int, percents) -> list[int]:
    """How a pull commitment of `total_units` is released stage by stage: one whole number per stage, summing exactly
    to the total, each within one unit of its share (largest remainder). Percents must sum to 100."""
    if isinstance(total_units, bool) or not isinstance(total_units, int) or total_units < 0:
        raise ValueError("total_units: a whole number, 0 or more")
    ps = [float(p) for p in percents]
    if not ps or any(p < 0 for p in ps) or abs(sum(ps) - 100.0) > 1e-9:
        raise ValueError("percents: one per stage, none negative, summing to 100")
    exact = [total_units * p / 100.0 for p in ps]
    out = [int(x) for x in exact]
    left = total_units - sum(out)
    for i in sorted(range(len(ps)), key=lambda i: (-(exact[i] - out[i]), i))[:left]:
        out[i] += 1
    return out


def intake(source: str, rec: dict) -> dict:
    """One idea in, from a source name and the record that source gives (no network): for person, player and agent
    `{"title", "field", "by"}` plus optional "orcid" and "github"; for a research source its own record (an OpenAlex
    work object, a Crossref work, a ClinicalTrials.gov study, a PubMed esummary row, an arXiv/bioRxiv entry as a dict,
    a USPTO application). Returns source, id, title, field, retracted, researcher (ORCID iDs and GitHub logins) and
    hash (sha256 of those, so it changes when the title changes)."""
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}: one of {', '.join(SOURCES)}")
    if not isinstance(rec, dict):
        raise ValueError("record: a JSON object")
    researcher: list[str] = []
    retracted = False
    if source in ("person", "player", "agent"):
        title = _clean(rec.get("title"))
        if not title:
            raise ValueError("a person's, player's or agent's idea needs a title")
        if rec.get("orcid") is not None:
            if not orcid_ok(rec["orcid"]):
                raise ValueError(f"{rec['orcid']}: not a valid ORCID iD (ISO 7064 11,2 check digit)")
            researcher.append(_bare_orcid(rec["orcid"]) or "")
        if rec.get("github"):
            gh = str(rec["github"]).strip().removeprefix("github:").removeprefix("@")
            if not re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$", gh):
                raise ValueError(f"{gh}: not a GitHub login")
            researcher.append(gh)
        given = _clean(rec.get("field"))
        fld = _FOLD.get(given.lower(), given) if given else field(text=title)     # one of FIELDS in its canonical name, else as given
        ident = claim_id(None, title)
        by = rec.get("by")
    elif source == "openalex":
        title = _clean(rec.get("title") or rec.get("display_name"))
        retracted = bool(rec.get("is_retracted"))
        for a in rec.get("authorships") or []:
            o = _bare_orcid(((a or {}).get("author") or {}).get("orcid"))
            if o:
                if not orcid_ok(o):
                    raise ValueError(f"{o}: not a valid ORCID iD")
                researcher.append(o)
        fname = (((rec.get("primary_topic") or {}).get("field")) or {}).get("display_name")
        fld = _FOLD.get(str(fname).lower(), field(text=title)) if fname else field(text=title)
        ident = str(rec.get("id") or "").rsplit("/", 1)[-1] or claim_id(None, title)
        by = None
    elif source == "crossref":
        w = rec.get("message", rec)
        title = _clean(" ".join(w.get("title") or []) if isinstance(w.get("title"), list) else w.get("title"))
        retracted = any(str(u.get("type", "")).lower() in ("retraction", "withdrawal", "removal") for u in w.get("updated-by") or []) \
            or title.upper().startswith("RETRACTED")
        researcher = [o for o in (_bare_orcid(a.get("ORCID")) for a in w.get("author") or []) if o]
        fld, ident, by = field(text=title), str(w.get("DOI") or "").lower() or claim_id(None, title), None
    elif source == "clinicaltrials":
        p = rec.get("protocolSection") or {}
        idm = p.get("identificationModule") or {}
        title = _clean(idm.get("briefTitle") or idm.get("officialTitle") or rec.get("title"))
        status = (p.get("statusModule") or {}).get("overallStatus")
        retracted = status == "WITHDRAWN"
        fld, ident, by = "Medicine", idm.get("nctId") or rec.get("id") or claim_id(None, title), None
    elif source == "pubmed":
        title = _clean(rec.get("title"))
        retracted = "retracted publication" in [str(t).lower() for t in rec.get("pubtype") or []]
        fld, ident, by = field(text=title), str(rec.get("uid") or rec.get("pmid") or claim_id(None, title)), None
    elif source == "europepmc":
        title = _clean(rec.get("title"))
        retracted = "retracted publication" in str(rec.get("pubType", "")).lower()
        fld, ident, by = field(text=title), str(rec.get("pmid") or rec.get("id") or claim_id(None, title)), None
    elif source == "arxiv":
        title = _clean(rec.get("title"))
        retracted = "withdrawn" in str(rec.get("comment", "")).lower()
        fld = field(arxiv=rec.get("primary_category") or rec.get("category") or "", text=title)
        ident, by = str(rec.get("id") or "").rsplit("/abs/", 1)[-1] or claim_id(None, title), None
    elif source in ("biorxiv", "medrxiv"):
        title = _clean(rec.get("title"))
        fld = field(subject=rec.get("category") or "", text=title)
        ident, by = str(rec.get("doi") or claim_id(None, title)), None
    else:  # patent: a USPTO ODP application (applicationMetaData merged or not)
        m = {**rec, **(rec.get("applicationMetaData") or {})}
        title = _clean(m.get("inventionTitle") or m.get("title"))
        cpc = (m.get("cpcClassificationBag") or [""])[0]
        fld = field(cpc=cpc, text=title) if cpc else field(text=title)
        ident, by = str(m.get("applicationNumberText") or claim_id(None, title)), None
    if not title:
        raise ValueError(f"the {source} record has no title")
    core = {"source": source, "id": ident, "title": title, "field": fld, "retracted": retracted, "researcher": researcher}
    return {**core, "by": by, "hash": hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()}


def merge(base: dict, other: dict) -> dict:
    """One idea read from two sources (same DOI): ids and sources joined, the retraction check of either kept."""
    ids = {**other.get("ids", {}), **base.get("ids", {})}
    srcs = base["sources"] + [s for s in other["sources"] if s not in base["sources"]]
    r = base["retraction"] if base["retraction"].get("checked") else other["retraction"]
    if other["retraction"].get("retracted"):
        r = other["retraction"]
    std = {"v", "id", "field", "statement", "origin", "ids", "sources", "retraction", "risk", "links", "year", "venue", "label", "hash"}
    extra = {**{k: v for k, v in other.items() if k not in std}, **{k: v for k, v in base.items() if k not in std}}
    return claim(base["statement"], field_name=base["field"], kind=base["origin"]["kind"], by=base["origin"].get("by"), ids=ids,
                 sources=srcs, retraction=r, links=list(dict.fromkeys(base["links"] + other["links"])), year=base.get("year") or other.get("year"),
                 venue=base.get("venue") or other.get("venue"), extra=extra)
