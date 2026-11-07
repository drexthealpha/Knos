"""Open signals: free, keyless public sources, each named as its own source and never mixed into Qloo's answers.

    coords(name, country)   a place's latitude and longitude from Wikidata (P625), for a city Qloo named without them

Every call has a short timeout and fails to nothing (the caller says what is missing); answers are kept in memory, so
one city is looked up once per process.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
import urllib.parse
import urllib.request

UA = "Knos/0.4 (https://github.com/drexthealpha/Knos; demand check, open signals)"
WIKIDATA = "https://www.wikidata.org/w/api.php"
_cache: dict[tuple[str, str], tuple[float, float] | None] = {}
_lock = threading.Lock()


def _get(url: str, timeout: float = 4.0) -> dict | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=timeout) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def coords(name: str, country: str | None = None) -> tuple[float, float] | None:
    """Latitude and longitude of the first Wikidata item for this place name that has coordinates (P625)."""
    key = (str(name or "").strip(), str(country or "").upper())
    if not key[0]:
        return None
    with _lock:
        if key in _cache:
            return _cache[key]
    found = _search(key[0])
    got = None
    if found:
        ents = (_get(f"{WIKIDATA}?action=wbgetentities&format=json&props=claims&ids={'|'.join(found[:5])}") or {}).get("entities") or {}
        for qid in found[:5]:
            for c in ((ents.get(qid) or {}).get("claims") or {}).get("P625") or []:
                v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
                if isinstance(v.get("latitude"), (int, float)) and isinstance(v.get("longitude"), (int, float)):
                    got = (round(float(v["latitude"]), 4), round(float(v["longitude"]), 4))
                    break
            if got:
                break
    with _lock:
        _cache[key] = got
    return got


def _search(name: str) -> list[str]:
    q = urllib.parse.urlencode({"action": "wbsearchentities", "format": "json", "language": "en", "type": "item", "limit": 5, "search": name})
    return [x["id"] for x in ((_get(f"{WIKIDATA}?{q}") or {}).get("search") or []) if isinstance(x, dict) and x.get("id")]


# ---- the no-Qloo baseline ----------------------- --------------------------------------------------------------------
# Six keyless public sources answer for an idea: how much people read about it (Wikimedia pageviews), how much the news
# writes about it (GDELT), how much builders post about it (Hacker News), how much research there is (OpenAlex), what
# the concept is (Wikidata) and what the launch country earns (World Bank). What they cannot say, they leave empty:
# none of them says who the buyers are or in which cities, so the baseline names no audience and no city.
RULES = {
    "attention": "a source counts as attention when Wikipedia's article on the idea's subject has at least 100 views a day "
                 "(last 60 days), GDELT counts at least 50 news articles in 3 months, Hacker News at least 5 stories in 2 "
                 "years, or OpenAlex at least 200 works since 2023",
    "verdict": "OPEN when at least 2 of those 4 count, REFUSE when the subject was found and fewer count, CANNOT_DECIDE when no "
               "source answered",
    "price_tier": "the launch country's GDP per person (World Bank): mid at 20,000 US dollars or more, budget below; the "
                  "open sources give no venue prices, so never premium or luxury",
    "audience": "none: no open source here says who buys",
    "cities": "none: no open source here says where",
}
STOP = set("a an the for to of and or with that which who your you my our in on at by from into about this these those is are "
           "be it its as app apps service platform tool kit device system based new smart small home".split())
SINCE = "2023-01-01"


def phrase(idea: str) -> str:
    words = [w for w in re.findall(r"[^\W_][\w-]*", (idea or "").lower()) if w not in STOP]
    return " ".join(words[:2])           # the subject: two words find more than four (Hacker News, GDELT match them all)


def _wikipedia(q: str) -> dict:
    found = (_get("https://en.wikipedia.org/w/rest.php/v1/search/page?" + urllib.parse.urlencode({"q": q, "limit": 1})) or {}).get("pages") or []
    if not found:
        return {"source": "Wikimedia pageviews", "answered": False}
    title = found[0].get("key") or found[0].get("title")
    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=59)
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
           f"{urllib.parse.quote(str(title), safe='')}/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    items = (_get(url) or {}).get("items") or []
    per_day = round(sum(i.get("views", 0) for i in items) / max(1, len(items)), 1) if items else 0.0
    qid = None
    props = _get("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "query", "prop": "pageprops", "titles": title, "format": "json"})) or {}
    for p in ((props.get("query") or {}).get("pages") or {}).values():
        qid = (p.get("pageprops") or {}).get("wikibase_item")
    return {"source": "Wikimedia pageviews", "answered": True, "article": title, "views_per_day": per_day, "counts": per_day >= 100,
            "link": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(str(title))}", "wikidata": qid}


_gdelt_lock, _gdelt_last = threading.Lock(), [0.0]


def _gdelt(q: str) -> dict:
    """GDELT answers one request in 5 seconds per address: calls wait their turn."""
    query = f'"{q}"' if " " in q else q
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode({"query": query, "mode": "timelinevolraw", "format": "json", "timespan": "3months"})
    got = None
    for _ in range(1):
        with _gdelt_lock:
            time.sleep(max(0.0, _gdelt_last[0] + 5.5 - time.time()))
            got = _get(url, timeout=12)
            _gdelt_last[0] = time.time()
        if got is not None:
            break
    if got is None:
        return {"source": "GDELT news", "answered": False}
    series = (got.get("timeline") or [{}])[0].get("data") or [] if got.get("timeline") else []
    n = int(sum(int(x.get("value") or 0) for x in series))
    return {"source": "GDELT news", "answered": True, "articles_3_months": n, "counts": n >= 50,
            "link": "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode({"query": query, "mode": "artlist", "timespan": "3months"})}


def _hn(q: str) -> dict:
    since = int(time.time()) - 2 * 365 * 86400
    got = _get("https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({"query": q, "tags": "story", "numericFilters": f"created_at_i>{since}", "hitsPerPage": 0}))
    if got is None:
        return {"source": "Hacker News", "answered": False}
    n = int(got.get("nbHits") or 0)
    return {"source": "Hacker News", "answered": True, "stories_2_years": n, "counts": n >= 5,
            "link": "https://hn.algolia.com/?" + urllib.parse.urlencode({"query": q, "type": "story"})}


def _openalex(q: str) -> dict:
    got = _get("https://api.openalex.org/works?" + urllib.parse.urlencode({"search": q, "filter": f"from_publication_date:{SINCE}", "per-page": 1}))
    if got is None:
        return {"source": "OpenAlex", "answered": False}
    n = int((got.get("meta") or {}).get("count") or 0)
    return {"source": "OpenAlex", "answered": True, "works_since_2023": n, "counts": n >= 200,
            "link": "https://openalex.org/works?" + urllib.parse.urlencode({"search": q, "filter": f"from_publication_date:{SINCE}"})}


def _worldbank(country: str) -> dict:
    got = _get(f"https://api.worldbank.org/v2/country/{urllib.parse.quote(country)}/indicator/NY.GDP.PCAP.CD?format=json&mrnev=1")
    row = (got[1][0] if isinstance(got, list) and len(got) > 1 and got[1] else None) or {}
    v = row.get("value")
    if not isinstance(v, (int, float)):
        return {"source": "World Bank", "answered": False}
    return {"source": "World Bank", "answered": True, "country": country, "gdp_per_person_usd": round(v), "year": row.get("date"),
            "link": f"https://data.worldbank.org/indicator/NY.GDP.PCAP.CD?locations={country}"}


def _wikidata(qid: str | None) -> dict:
    if not qid:
        return {"source": "Wikidata", "answered": False}
    ents = (_get(f"{WIKIDATA}?action=wbgetentities&format=json&props=labels|descriptions&languages=en&ids={qid}") or {}).get("entities") or {}
    e = ents.get(qid) or {}
    return {"source": "Wikidata", "answered": bool(e), "id": qid, "label": ((e.get("labels") or {}).get("en") or {}).get("value"),
            "about": ((e.get("descriptions") or {}).get("en") or {}).get("value"), "link": f"https://www.wikidata.org/wiki/{qid}"}


def baseline(idea: str, country: str = "US") -> dict:
    """The demand answer from open signals only, each source with what it said and its link; no key, no Qloo."""
    from concurrent.futures import ThreadPoolExecutor
    q = phrase(idea)
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(f, a) for f, a in ((_wikipedia, q), (_gdelt, q), (_hn, q), (_openalex, q), (_worldbank, country))]
        wiki, gdelt, hn, oa, wb = (f.result() for f in futures)
    wd = _wikidata(wiki.get("wikidata"))
    attention = [s for s in (wiki, gdelt, hn, oa) if s.get("answered")]
    n = sum(1 for s in attention if s.get("counts"))
    verdict = "CANNOT_DECIDE" if not attention else "OPEN" if n >= 2 else "REFUSE"
    tier = None if not wb.get("answered") else ("mid" if wb["gdp_per_person_usd"] >= 20000 else "budget")
    return {"source": "open signals (Wikimedia, GDELT, Hacker News, OpenAlex, World Bank, Wikidata; keyless)", "idea": idea, "phrase": q,
            "verdict": verdict, "attention_counted": n, "audience": None, "cities": [], "price_tier": tier,
            "signals": [wiki, gdelt, hn, oa, wb, wd], "rules": RULES}


_answers: dict[str, tuple[float, dict]] = {}
ROWS = {"Wikimedia pageviews": ("Wikipedia", "views_per_day", "views a day (last 60 days)"),
        "GDELT news": ("News", "articles_3_months", "articles in 3 months (GDELT)"),
        "Hacker News": ("Hacker News", "stories_2_years", "stories in 2 years"),
        "OpenAlex": ("Research papers", "works_since_2023", "since 2023 (OpenAlex)")}


def held_for(idea: str) -> dict:
    """Money already put down on this idea here: locked pre-orders and funder money, in test dollars (6 decimals)."""
    from . import preorder
    key, units, n = " ".join((idea or "").lower().split()), 0, 0
    for r in preorder.all_public(200):
        if " ".join(str(r.get("idea") or "").lower().split()) == key and r.get("status") == "locked":
            units += int(r.get("units") or 0) * int(r.get("unit_price") or 0)
            n += 1
    return {"usd": round(units / 1_000_000, 2), "count": n}


def fallback(idea: str, country: str = "US") -> dict:
    """A4: the demand answer when Qloo gives nothing (no key, an error, HTTP 429, an empty answer): the open signals plus
    money already put down, in plain rows, with one line naming the sources used. Kept 10 minutes per idea."""
    k = f"{country}|{' '.join((idea or '').lower().split())}"
    got = _answers.get(k)
    if got and time.time() - got[0] < 600:
        return got[1]
    b = baseline(idea, country)
    rows, used = [], []
    for s in b["signals"]:
        name, field, unit = ROWS.get(s.get("source"), (None, None, None))
        if name and s.get("answered"):
            rows.append({"name": name, "value": round(s.get(field) or 0), "unit": unit, "link": s.get("link"), "counts": bool(s.get("counts"))})
            used.append({"News": "GDELT news", "Research papers": "OpenAlex"}.get(name, name))
    held = held_for(idea)
    rows.append({"name": "Money down", "value": held["usd"], "unit": f"test money, {held['count']} pre-orders here", "counts": held["usd"] > 0})
    used.append("pre-orders here")
    n = sum(1 for r in rows if r["counts"])
    verdict = "OPEN" if n >= 2 else "REFUSE" if len(used) > 1 else "CANNOT_DECIDE"
    out = {"verdict": verdict, "rows": rows, "counted": n, "phrase": b["phrase"],
           "line": "Sources: " + ", ".join(used) + ".",
           "head": {"OPEN": "People want this", "REFUSE": "Little interest found yet", "CANNOT_DECIDE": "No signal yet"}[verdict],
           "rule": "People want it when 2 of these pass: Wikipedia 100 views a day, news 50 articles, "
                   "Hacker News 5 stories, 200 research papers, any money down."}
    _answers[k] = (time.time(), out)
    return out


def online() -> bool:
    """The hosted app (Render sets RENDER) or KNOS_OPEN_SIGNALS=on: the open sources are reachable; tests stay offline."""
    import os
    return os.environ.get("KNOS_OPEN_SIGNALS") == "on" or (bool(os.environ.get("RENDER")) and os.environ.get("KNOS_OPEN_SIGNALS") != "off")


def needs_fallback(rep: dict) -> bool:
    """Qloo gave nothing usable: no key, an error or HTTP 429 with no real answer kept, or an empty answer."""
    if not online() or rep.get("kind") == "which_one" or rep.get("without_qloo") or rep.get("stale") or rep.get("nearest"):
        return False
    d = rep.get("decision") or {}
    return bool(rep.get("queued") or rep.get("qloo_down") or d.get("verdict") == "CANNOT_DECIDE"
                or (not rep.get("matches") and not rep.get("tags") and "decision" in rep))


def prefetch(idea: str, country: str = "US") -> None:
    """Start the fallback's lookups beside the Qloo step when Qloo cannot answer, so the answer is ready when it ends."""
    k = f"{country}|{' '.join((idea or '').lower().split())}"
    if online() and k not in _answers:
        threading.Thread(target=lambda: fallback(idea, country), daemon=True).start()
