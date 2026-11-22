"""Research in the valley of death: a landmark result -> a research card -> the demand check on the product it enables.

    card = research_card("10.1126/science.aam8743")         # DOI, arXiv id, PubMed id, OpenAlex id (W...), uspto:<number>
    card["product"]          the product phrase the demand check runs on (the maker may edit it)
    flags = why_never_crossed(card, report)                   # after the demand check, from the card's own sources

The paper is read through Knos's own source readers (knos.ideas.sources: OpenAlex, Crossref, arXiv, PubMed / Europe
PMC; patents through the USPTO path, a labelled FIXTURE without a USPTO key). Citations, topics, keywords and the
abstract come from OpenAlex; the retraction check from Crossref (`updated-by`) and OpenAlex `is_retracted`; Nobel
recognition from data/nobel.toml (each row cites its nobelprize.org press release). Nothing here is written by a
language model: the "proven result" is a sentence of the abstract chosen by a fixed rule and quoted with its source.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
try:
    import tomllib
except ImportError:  # Python 3.10: the same parser, as Knos itself reads TOML (src/knos/judge.py)
    import tomli as tomllib  # type: ignore[no-redef]
from pathlib import Path

NOBEL_FILE = Path(__file__).parent / "data" / "nobel.toml"
OA_SELECT = "id,doi,title,publication_year,cited_by_count,abstract_inverted_index,keywords,topics,concepts,is_retracted"
RESULT_RE = re.compile(r"\b(we (show|demonstrate|report|find|found|observe|observed|present|describe|identify|identified)|"
                       r"here,? we|this (shows|demonstrates|establishes)|our results)\b", re.I)
REGULATED_FIELDS = {"Medicine", "Pharmacology, Toxicology and Pharmaceutics", "Immunology and Microbiology", "Neuroscience",
                    "Nursing", "Dentistry", "Health Professions", "Veterinary", "Biochemistry, Genetics and Molecular Biology"}
REGULATED_WORDS = ("clinical", "therapy", "therapeutic", "drug", "patient", "disease", "vaccine", "diagnos", "medical", "food safety")
# Topic / keyword -> the product a result enables (checked in order; the first match wins; else a generic phrase).
PRODUCT_MAP = (
    (("water harvesting", "atmospheric water", "metal-organic framework"), "a device that harvests drinking water from air"),
    (("regulatory t", "foxp3", "immune tolerance"), "a regulatory T cell therapy for autoimmune disease"),
    (("attosecond", "high harmonic"), "a laser blood test that identifies disease molecules"),
    (("perovskite",), "perovskite solar panels"), (("graphene",), "graphene based consumer electronics"),
    (("crispr", "cas9"), "a gene editing therapy"), (("lithium", "battery"), "a longer lasting battery"),
    (("microbiome", "probiotic"), "a probiotic supplement"), (("sleep",), "a sleep improving device"),
)
REGULATORS = {"fda.gov": "FDA (US)", "ema.europa.eu": "EMA (EU)", "nafdac.gov.ng": "NAFDAC (Nigeria)",
              "mhra.gov.uk": "MHRA (UK)", "gov.uk/government/organisations/medicines-and-healthcare": "MHRA (UK)",
              "pmda.go.jp": "PMDA (Japan)"}
REGULATOR_WORDS = {"FDA": "FDA (US)", "EMA": "EMA (EU)", "NAFDAC": "NAFDAC (Nigeria)", "MHRA": "MHRA (UK)", "PMDA": "PMDA (Japan)"}


def regulator_of(evidence: dict | None) -> str | None:
    """The regulator a "no product yet" source cites, from its URL's domain or its quoted words."""
    if not evidence:
        return None
    url = str(evidence.get("url") or "").lower()
    for dom, name in REGULATORS.items():
        if dom in url:
            return name
    said = str(evidence.get("said") or "")
    for word, name in REGULATOR_WORDS.items():
        if re.search(rf"\b{word}\b", said):
            return name
    return None


YEARS_STUCK = 5            # years since publication before a cited result with no product counts as stuck
TOP_CITED = 1000           # OpenAlex cited_by_count at or above this: top-cited


class ResearchError(ValueError):
    pass


def nobel_rows() -> list[dict]:
    return tomllib.loads(NOBEL_FILE.read_text(encoding="utf-8")).get("paper", [])


def nobel_for(doi: str | None) -> dict | None:
    d = (doi or "").lower()
    return next((r for r in nobel_rows() if r["doi"].lower() == d), None) if d else None


def abstract(inv: dict | None) -> str:
    if not isinstance(inv, dict):
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)


def proven_result(title: str, abstract_text: str) -> tuple[str, str]:
    """(sentence, where): the first abstract sentence stating a result (fixed phrases), else the abstract's last
    sentence, else the title."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", abstract_text or "") if len(s.strip()) > 30]
    hit = next((s for s in sents if RESULT_RE.search(s)), None)
    if hit:
        return hit[:400], "abstract (first sentence stating a result)"
    if sents:
        return sents[-1][:400], "abstract (last sentence)"
    return title, "title (no abstract available)"


def product_phrase(text: str, nobel: dict | None) -> tuple[str, str]:
    if nobel and nobel.get("enables"):
        return nobel["enables"], f"the use named by the landmark table's source ({nobel['url']})"
    low = text.lower()
    for keys, phrase in PRODUCT_MAP:
        if any(k in low for k in keys):
            return phrase, "Knos's topic-to-product table (research.PRODUCT_MAP) on the paper's topics and keywords"
    words = [w for w in re.findall(r"[a-z][a-z\-]{3,}", low) if w not in ("with", "from", "that", "this", "using", "based")][:3]
    return "a product based on " + " ".join(words), "generic phrase from the paper's first topic words: edit it"


def research_card(ref: str, fetcher=None, product: str | None = None, today: dt.date | None = None) -> dict:
    from knos.ideas import IdeaError, sources
    from knos.ideas.http import FetchError
    ref = (ref or "").strip()
    if ref.lower().startswith("patent:"):
        ref = "uspto:" + ref[7:]
    if not 3 <= len(ref) <= 200:
        raise ResearchError("paste a DOI, arXiv id, PubMed id, OpenAlex id (W...) or uspto:<patent number>")
    f = fetcher or sources.Fetcher()
    try:
        c = sources.get(ref, f)
    except (IdeaError, FetchError) as e:
        raise ResearchError(f"could not read {ref}: {str(e)[:200]}") from None
    ids = c.get("ids") or {}
    work, oa_url = {}, None
    if ids.get("doi") or ids.get("openalex"):
        path = f"works/{ids['openalex']}" if ids.get("openalex") else f"works/doi:{ids['doi']}"
        oa_url = sources._oa_url(path, {"select": OA_SELECT})
        try:
            work, _ = f.json(oa_url)
        except FetchError:
            work = {}
    abs_text = abstract(work.get("abstract_inverted_index"))
    sentence, where = proven_result(c["statement"], abs_text)
    topics = [t.get("display_name") for t in (work.get("topics") or [])[:3] if t.get("display_name")]
    keywords = [k.get("display_name") for k in (work.get("keywords") or [])[:5] if k.get("display_name")]
    concepts = [k.get("display_name") for k in (work.get("concepts") or [])[:5] if k.get("display_name")]
    row = nobel_for(ids.get("doi"))
    nobel = row if row and row.get("nobel", True) else None
    phrase, phrase_why = product_phrase(" ".join([c["statement"], *topics, *keywords, *concepts]), row)
    retr = c.get("retraction") or {}
    today = today or dt.datetime.now(dt.timezone.utc).date()
    oa_link = (work.get("id") or "").replace("https://openalex.org/", "https://api.openalex.org/works/") or None
    card = {"v": 1, "kind": "knos-research-card", "ref": ref, "title": c["statement"], "field": c.get("field"),
            "topic": c.get("topic"), "topics": topics, "keywords": keywords, "year": c.get("year") or work.get("publication_year"),
            "venue": c.get("venue"), "ids": ids, "links": c.get("links"), "label": c.get("label"),
            "proven_result": {"quote": sentence, "where": where, "source": f"https://doi.org/{ids['doi']}" if ids.get("doi") else (c.get("links") or [None])[0]},
            "cited_by_count": work.get("cited_by_count"), "cited_source": oa_link,
            "retraction": {"retracted": bool(retr.get("retracted") or work.get("is_retracted")), "checked": bool(retr.get("checked")),
                           "via": retr.get("via") or ("OpenAlex is_retracted" if work else None), "notices": retr.get("notices") or []},
            "nobel": nobel, "regulator": regulator_of({"said": row["said"], "url": row["url"]} if row else None),
            "no_product_evidence": ({"said": row["said"], "url": row["url"], "products_on_market": row.get("products_on_market")} if row else None),
            "product": (product or "").strip()[:200] or phrase, "product_source": "edited by the maker" if product else phrase_why,
            "suggested_product": phrase, "day": today.isoformat()}
    card["hash"] = hashlib.sha256(json.dumps({k: v for k, v in card.items() if k not in ("day",)}, sort_keys=True, default=str).encode()).hexdigest()
    return card


def why_never_crossed(card: dict, report: dict, today: dt.date | None = None) -> list[dict]:
    """The three walls, each a flag with its evidence, or 'no evidence'. Nothing is asserted without a source."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    out = []
    year, cited = card.get("year"), card.get("cited_by_count")
    years = today.year - year if isinstance(year, int) else None
    none = card.get("no_product_evidence") or {}
    proven = bool(card.get("nobel")) or (isinstance(cited, int) and cited >= TOP_CITED)
    if years is not None and years >= YEARS_STUCK and proven and none.get("url"):
        out.append({"wall": "money before proof", "flag": True,
                    "evidence": f"{years} years since publication, " + (f"Nobel {card['nobel']['prize']} {card['nobel']['year']}" if card.get("nobel") else f"{cited} citations (OpenAlex)")
                    + f", and no product yet for '{card['product']}' ({none['url']})"})
    else:
        out.append({"wall": "money before proof", "flag": False, "evidence": "no evidence (needs >= 5 years and Nobel or >= 1,000 citations, and a source saying no product is on sale)"})
    text = " ".join([card.get("field") or "", card.get("topic") or "", *card.get("topics", []), card.get("product") or ""]).lower()
    word = next((w for w in REGULATED_WORDS if w in text), None)
    named = card.get("regulator")
    reg = named is not None or card.get("field") in REGULATED_FIELDS or word is not None
    why = (f"the 'no product yet' source cites the regulator {named} ({(card.get('no_product_evidence') or {}).get('url')})" if named
           else f"OpenAlex field '{card.get('field')}' is clinical or regulated" if card.get("field") in REGULATED_FIELDS
           else f"the topic or product names '{word}' (OpenAlex topic '{card.get('topic')}', product '{card.get('product')}')")
    out.append({"wall": "slow judges", "flag": reg,
                "evidence": (f"{why}: such products need clinical or regulatory approval before sale"
                             if reg else "no evidence (OpenAlex field and topics are not clinical or regulated)")})
    out.append({"wall": "failed attempts", "flag": False, "evidence": "no evidence"})
    return out
