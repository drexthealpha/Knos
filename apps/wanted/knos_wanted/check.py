"""Knos's demand check on Qloo's REST API: an idea in plain words -> Qloo evidence -> a decision made by code.

    report = demand_check("A smart water bottle that reminds you to drink", place="Lagos")
    report["decision"]   {"verdict": "OPEN" | "REFUSE" | "CANNOT_DECIDE", "reasons": [...], "target_units", "reserve_units"}

The Qloo calls (every number in the report names the call that produced it, by its index in report["calls"]):
  /search (+ /entities)   the closest existing products of the idea's kind; the leader = most relevant, then most popular
  /v2/tags                the idea's own taste tags (tag search on its content words, tags of that kind)
  /v2/insights urn:demographics   WHO: age and gender affinity of the matched products (at the place, when given)
  /v2/insights urn:heatmap + urn:entity:place   WHERE: the areas and named places where that taste clusters
  /v2/audiences + /v2/insights signal.demographics.audiences   WHO BUYS: candidate segments (50 a page), each scored by
                          its lift on the products nearest this taste; the spending-habit segments set the price tier
  /v2/trending            weekly population percentile of the leader (Qloo's series ends ~24 Jul 2026: "data through")
  /v2/analysis/compare    the idea's other matches (a) vs the leader (b): shared taste tags = overlap; else the share
                          of the leader's nearest products that are also nearest this taste (one more /v2/insights call)

The DECISION is deterministic code over those numbers (RULES below; why each threshold: docs/reference/DEMAND_CHECK.md).
No language model decides. Without Qloo (no key, the budget spent, an essential call failing) the verdict is
CANNOT_DECIDE "cannot decide: no Qloo evidence". Pre-orders never open on mock, synthetic or missing data.
Directional demand evidence, not a sales forecast; aggregate taste, not a prediction about one person.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .qloo_rest import LIVE_LABEL, Client, QlooError


V = 2
KIND = "knos-demand-check"
FRAMING = "Directional demand evidence, not a sales forecast."
AGGREGATE = "aggregate taste, not a prediction about one person"
NO_EVIDENCE = "cannot decide: no Qloo evidence"
NOTHING_CLOSE = "Qloo knows nothing close to"    # the only refusal for a new idea: no Qloo tag shares a content word with it
OWNED = "an existing product already owns this"
SERVED = "the incumbent already serves this taste"
DATA_END = "2026-07-24"     # the newest week in Qloo's /v2/trending series (measured 16 Oct 2026)
TREND_NOTE = f"Qloo's trend data ends {DATA_END} and shows no movement for these; not counted"
TREND_TYPES = {"urn:entity:brand", "urn:entity:artist", "urn:entity:movie", "urn:entity:person", "urn:entity:podcast",
               "urn:entity:tv_show", "urn:entity:actor"}
DEFAULT_PLACE = "United States"
# The market's country code, for scoping Qloo's geography (launch cities never leave the chosen market).
COUNTRIES = {"united states": "US", "usa": "US", "us": "US", "united kingdom": "GB", "uk": "GB", "nigeria": "NG",
             "germany": "DE", "france": "FR", "japan": "JP", "canada": "CA", "australia": "AU", "india": "IN",
             "brazil": "BR", "south korea": "KR", "korea": "KR", "spain": "ES", "italy": "IT", "mexico": "MX"}


def market_country(place: str | None) -> str | None:
    return COUNTRIES.get((place or DEFAULT_PLACE).strip().lower())
# Qloo's kit (docs/SAFE_USE.md): no inference of sensitive traits. Political and belief segments are never asked for,
# and a segment named for a religion, an ethnicity, a sexual orientation, health or politics is never shown or sized.
AUDIENCE_TYPES = ("communities", "global_issues", "hobbies_and_interests", "investing_interests", "leisure", "life_stage",
                  "professional_area", "spending_habits")
AUDIENCE_TYPES = tuple("urn:audience:" + t for t in AUDIENCE_TYPES)
SENSITIVE_TYPES = ("urn:audience:political_preferences", "urn:audience:lifestyle_preferences_beliefs")
SENSITIVE_SEGMENT = re.compile(
    r"\b(aapi|asian|black(?! friday)|african|latin[oax]|latine|hispanic|indigenous|native american|arab|jewish|juda\w*|muslim|islam\w*|christian\w*|catholic|"
    r"belief\w*|bible\w*|torah|quran|ethnic\w*|racial|"
    r"protestant|evangelical|mormon|hindu\w*|buddhis\w*|sikh|religio\w*|faith\w*|church\w*|spiritual\w*|atheis\w*|lgbt\w*|queer|"
    r"gay|lesbian|bisexual|transgender|politic\w*|conservative\w*|liberal(?! arts)\w*|progressive\w*|democrat\w*|republican\w*|"
    r"health\w*|disab\w*|chronic|illness\w*|pregnan\w*|immigra\w*)\b", re.I)


def safe_segment(a: dict) -> bool:
    """A segment Knos may show and size: not of a sensitive type, not named for a sensitive trait."""
    ids, name = [str(a.get(k) or "") for k in ("id", "entity_id", "type")], f"{a.get('name') or ''} {a.get('disambiguation') or ''}"
    return not any(i.startswith(SENSITIVE_TYPES) for i in ids) and not SENSITIVE_SEGMENT.search(name)


def scrub(rep: dict) -> dict:
    """The report with every segment named for a sensitive trait taken out of what the card shows (a card kept from
    before its name was known to be sensitive is shown without it); the decision it holds stays as it was made."""
    out = dict(rep)
    vs = out.get("versus")
    if isinstance(vs, dict) and "audience" in str(vs.get("method") or ""):      # segments; taste tags are not people
        out["versus"] = {**vs, **{k: [x for x in vs[k] if not SENSITIVE_SEGMENT.search(str(x))]
                                  for k in ("whitespace", "shared", "leader_only") if isinstance(vs.get(k), list)}}
    for k in ("audiences", "who_wants", "named_audience"):
        if isinstance(out.get(k), list):
            out[k] = [x for x in out[k] if not isinstance(x, dict) or safe_segment(x)]
    return out
NEUTRAL = 0.5          # Qloo's audience affinity when it has no signal: the list comes back flat at exactly 0.5

# The kind of product, from the idea's nouns, in this priority order (a "podcast about video games" is a podcast).
KINDS = (("urn:entity:podcast", ("podcast",)), ("urn:entity:tv_show", ("tv show", "tv series", "sitcom", "web series")),
         ("urn:entity:movie", ("film", "movie", "documentary")), ("urn:entity:book", ("book", "novel", "cookbook")),
         ("urn:entity:videogame", ("video game", "videogame", "mobile game", "game", "gaming")),
         ("urn:entity:place", ("restaurant", "cafe", "coffee shop", "coffee bar", "bar", "pub", "bakery", "hotel", "gym",
                               "salon", "venue", "bistro", "diner", "food truck", "brewery", "club", "festival", "music festival",
                               "concert hall", "theater", "theatre", "museum", "karaoke", "arcade", "food hall", "night market")),
         ("urn:entity:artist", ("band", "album", "singer", "rapper", "musician")))
NOT_KIND = ("board game", "card game", "game night", "games night")
# Words that carry no product meaning: grammar, pitch words, and the words of an instruction to this app.
STOP = set("""a an and or but the of for to in on at by with from into onto over under about above after before as is are
was were be been being it its this that these those there here which who whom whose what when where why how all any each
every some such no not nor only own same so than too very can could will would shall should may might must do does did
done have has had having i me my we our ours you your yours he she they them their his her him one two three new brand
like just really also get gets make makes made use uses using used way ways thing things people person someone anyone
everyone idea ideas product products service services startup company business app apps platform tool tools solution
solutions market markets customer customers user users buyer buyers seller sell sells buy buys selling buying
demand target reserve release funds fund money price prices order orders preorder preorders decision decide rules rule
ignore previous instruction instructions system prompt set open close verified overwhelming guaranteed exactly clone
copy version invented invent call called named name similar better best cheaper cheap first ever kind sort type lot
lots great good amazing awesome cool nice perfect ultimate premium simple easy smart now today tomorrow please brand-new
let lets without within measure measures read reads
all-new""".split())
# Audience words in the idea, and the Qloo demographic key they name.
AUDIENCE = {"student": ("age", "24_and_younger"), "students": ("age", "24_and_younger"), "teen": ("age", "24_and_younger"),
            "teens": ("age", "24_and_younger"), "teenagers": ("age", "24_and_younger"), "gen z": ("age", "24_and_younger"),
            "young": ("age", "24_and_younger"), "millennials": ("age", "30_to_34"), "parents": ("age", "35_to_44"),
            "moms": ("gender", "female"), "mums": ("gender", "female"), "dads": ("gender", "male"),
            "kids": ("age", "35_to_44"), "children": ("age", "35_to_44"), "seniors": ("age", "55_and_older"),
            "retirees": ("age", "55_and_older"), "elderly": ("age", "55_and_older"), "older": ("age", "55_and_older"),
            "women": ("gender", "female"), "woman": ("gender", "female"), "female": ("gender", "female"),
            "girls": ("gender", "female"), "men": ("gender", "male"), "male": ("gender", "male"), "guys": ("gender", "male")}
CLONE_PHRASES = ("exactly like", "just like", "clone of", "copy of", "same as", "identical to", "knockoff of",
                 "knock-off of", "rip-off of", "replica of", "a version of")

# The decision rules. Every threshold is here, read by decide() and printed in the report.
RULES = {
    "relevance": "a Qloo product counts only when its name shares 2 content words with the idea, or 1 in its name and 1 more "
                 "in its description or tags, or 3 anywhere in its name, description and tags (content words: the idea minus filler, "
                 "pitch, instruction and kind words such as podcast); "
                 "none -> a new idea, answered from the Qloo tags that share a content word with it (OPEN on its own taste, "
                 "else not yet); no such tag -> REFUSE '" + NOTHING_CLOSE + " <its words>'",
    "clone": "the leader's name is in the idea together with a clone phrase ('exactly like', 'clone of', ...) or is "
             "the idea's whole subject -> REFUSE " + OWNED,
    "informative_affinity": 0.55,     # a product or place counts as informative above Qloo's neutral 0.5 by this margin
    "min_scored_segments": 3,         # audience segments whose lift Qloo answered live (documented calls, sweep 22 section 4)
    "price_lift": 0.005,              # premium minus budget spending-segment lift above this -> premium, below minus this -> budget
    "served_overlap": 0.85,           # overlap with the leader at or above this -> REFUSE on its own (a me-too)
    "owned_overlap": 0.6,             # overlap with the leader at or above this ...
    "owned_popularity": 0.95,         # ... while the leader's Qloo popularity is at or above this -> REFUSE (owned)
    "unknown_leader_popularity": 0.9,  # no leader comparison possible and the leader is this popular -> REFUSE (owned)
    "min_compare_tags": 3,            # tag overlap is computed only when both sides have this many tags
    "contradiction": -0.3,            # the idea names an audience whose Qloo affinity is at or below this -> REFUSE;
                                      # between this and 0 it halves the target
    "falling_delta": -0.02,           # trend percentile change at or below: REFUSE (falling); a flat or missing series
    "rising_delta": 0.02,             # counts neither for nor against
    "group_confirmed": 1.2,           # the idea names a buyer group (a /v2/audiences segment) whose lift on this taste ranks in
    "group_refuted": 0.6,             # the top half of the scored segments -> target x 1.2; named but lower or unread -> x 0.6
    "adjacent_affinity": 0.94,        # a recommended product (/v2/insights of the idea's kind) at or above this affinity
                                      # (top-10 recommendations measured 0.93-0.955 on 16 Oct 2026: 0.94 keeps the strongest),
    "adjacent_many": 5,               # not already matched, is adjacent demand: >= 5 -> target x 1.2,
    "adjacent_many_factor": 1.2,
    "adjacent_few": 1,                # <= 1 -> target x 0.8, else x 1
    "adjacent_few_factor": 0.8,
    "base_units": 100,
    "units_formula": "target = round10(base x (1 + 2 x strength) x (1 - overlap/2) x audience_factor x trend_factor), "
                     "strength = (mean affinity of the 10 products nearest the taste - 0.5) x 2, clamped to [0, 1], "
                     "trend_factor 1.25 rising else 1, "
                     "audience_factor = 0.5 when the named audience leans mildly away (else 1) x the buyer-group factor x the "
                     "recommendations factor (see group_* and adjacent_*), clamped to [20, 1000]; "
                     "reserve = ceil(target x (0.3 + 0.2 x overlap)) units pre-ordered before the maker is paid",
}


def _norm(w: str) -> str:
    w = w.lower()
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W\d_][\w\-]{1,}", (text or "").lower())        # any alphabet: "cómics" stays one word


def content_words(idea: str, place: str | None = None) -> list[str]:
    drop = set(tokens(place or "")) | {w for w in AUDIENCE}
    out: list[str] = []
    for w in tokens(idea):
        if len(w) < 3 or w in STOP or w in drop or _norm(w) in out:
            continue
        out.append(_norm(w))
    return out


def _place_nouns() -> frozenset[str]:
    from pathlib import Path

    import knos
    p = Path(knos.__file__).with_name("place_nouns.txt")
    return frozenset(w.strip().lower() for w in p.read_text(encoding="utf-8").splitlines() if w.strip() and not w.startswith("#"))


PLACE_NOUNS = _place_nouns()
_HEAD_END = re.compile(r"\b(?:for|with|in|near|on|at|like|to|from|that|which|who|where|and)\b|[,;:!?.()$]")


def head_noun(idea: str) -> str:
    """The idea's last noun before what qualifies it: "a board game cafe with vegan snacks for students" -> "cafe"."""
    chunk = _HEAD_END.split(f" {idea.lower()} ", 1)[0]
    words = re.findall(r"[a-zà-ÿ]+", chunk)
    return words[-1] if words else ""


def kind_of(idea: str) -> str:
    """A place (urn:entity:place) when the idea's last noun is in src/knos/place_nouns.txt; else the kind its nouns name
    (podcast, show, film, book, video game, artist); else a brand. /search asks a place idea and a brand idea as both
    kinds and keeps the better match (gather)."""
    if head_noun(idea) in PLACE_NOUNS:
        return "urn:entity:place"
    low = f" {idea.lower()} "
    for nk in NOT_KIND:
        low = low.replace(nk, " ")
    for t, words in KINDS:
        if t != "urn:entity:place" and any(re.search(rf"\b{re.escape(w)}s?\b", low) for w in words):
            return t
    return "urn:entity:brand"


def kind_words() -> set[str]:
    """The one-word kind names, dropped from the search query ("podcast"); a multi-word kind ("night market", "food
    truck") is never split into single words, which took "night", "food" or "coffee" out of every query."""
    return {_norm(w) for _, ws in KINDS for w in ws if " " not in w}


def audience_named(idea: str) -> list[tuple[str, str, str]]:
    low = f" {idea.lower()} "
    return [(w, *AUDIENCE[w]) for w in AUDIENCE if re.search(rf"\b{re.escape(w)}\b", low)]


class _Run:
    """One check's Qloo calls, numbered so every figure can cite its source. A failed call is retried once without
    the optional parts (location, tags); its error is kept short (never Qloo's raw answer)."""

    OPTIONAL = ("signal.location.query", "signal.interests.tags", "filter.location.query", "output.heatmap.boundary", "sort_by",
                "offset", "filter.tags", "operator.filter.tags")
    # Qloo ignores a filter the entity type does not take, silently (docs.qloo.com/reference/parameters, the Entity Type
    # Parameter Guide): such a parameter is dropped here and the call says so, instead of looking applied
    PLACE_ONLY = ("filter.price_level.", "filter.hotel_class.", "filter.properties.business_rating.", "filter.external.resy.",
                  "filter.external.tripadvisor.")
    ENTITY_ONLY = ("filter.popularity.", "filter.external.exists", "filter.parents.types")
    # filters that can empty a result: when they do, the call is made once more without them and says it broadened
    NARROWING = ("filter.popularity.", "filter.price_level.", "filter.hotel_class.", "filter.properties.business_rating.",
                 "filter.external.exists", "filter.tags", "operator.filter.tags")

    @classmethod
    def guide(cls, params: dict) -> tuple[dict, list[str]]:
        t = str(params.get("filter.type") or "")
        drop = [k for k in params if (k.startswith(cls.PLACE_ONLY) and t != "urn:entity:place")
                or (k.startswith(cls.ENTITY_ONLY) and not t.startswith("urn:entity:"))]
        return {k: v for k, v in params.items() if k not in drop}, drop

    def __init__(self, client: Client, on_call=None):
        self.c = client
        self.calls: list[dict] = []
        self.on_call = on_call or (lambda c: None)       # the agent streams each call to the page as it happens
        self._inflight: dict = {}                          # prefetched questions still being answered: key -> Future
        self.deadline: float | None = None                 # time.monotonic() past which only essential questions wait
        self._numbering = threading.Lock()                 # parts of a report ask at once; each call keeps one number

    def prefetch(self, calls: list[tuple[str, dict]]) -> None:
        """Ask independent questions at once (R21): the answers land in the client's cache, so the calls that follow,
        made in order and numbered as always, are answered from it. A failure here is only a cache miss later."""
        from concurrent.futures import ThreadPoolExecutor

        def one(path, p):
            try:
                self.c.get(path, p)
            except Exception as e:  # noqa: BLE001 - get() goes straight to its lighter question
                return e
            return None
        ex = ThreadPoolExecutor(max_workers=len(calls) or 1)
        for path, params in calls:                         # sent at once; get() waits for its own, never asks twice
            p = self.guide(params)[0] if path == "/v2/insights" else params
            self._inflight[_key(path, p)] = ex.submit(one, path, p)
        ex.shutdown(wait=False)

    def _add(self, rec: dict) -> dict:
        with self._numbering:
            rec = {"n": len(self.calls) + 1, **rec}
            self.calls.append(rec)
        self.on_call(rec)
        return rec

    def get(self, path: str, params: dict, what: str, broaden: bool = True, wait_s: float | None = None,
            _broadened: bool = False) -> tuple[dict | None, int | None]:
        """One numbered call. A prefetched question is waited for (up to `wait_s` seconds when given: a call that decides
        nothing need not hold up the verdict), then read from the cache. A prefetched question that failed is not asked
        again: its lighter form goes next. Each call records how long it held the report up (ms), waits included."""
        t0 = time.perf_counter()
        params, dropped = self.guide(params) if path == "/v2/insights" else (params, [])
        fut = self._inflight.pop(_key(path, params), None)
        failed = None
        # the check's time budget (CHECK_BUDGET_S): past it, a question that is not essential is left out, said so
        left = None if self.deadline is None or what.startswith(ESSENTIAL) else self.deadline - time.monotonic()
        if left is not None:
            wait_s = max(0.2, left) if wait_s is None else max(0.2, min(wait_s, left))
            if fut is None and left <= 0:
                self._add({"call": f"GET {path}", "what": what, "params": params, "ms": 0,
                           "error": f"left out: the check's {CHECK_BUDGET_S:g} s budget was spent before it was asked"})
                return None, None
        if fut is not None:
            try:
                failed = fut.result(timeout=wait_s)
            except Exception:  # noqa: BLE001 - concurrent.futures.TimeoutError: not answered within wait_s
                if wait_s is not None and not fut.done():
                    self._add({"call": f"GET {path}", "what": what, "params": params, "ms": _ms(t0),
                               "error": f"Qloo had not answered within {wait_s:g} s; left out of this report"})
                    return None, None
        if dropped:
            what += f" (not sent: {', '.join(dropped)}, which Qloo ignores for {params.get('filter.type')})"
        tries = [params]
        keep = ("filter.location.query",) if path == "/v2/insights" and params.get("filter.type") == "urn:heatmap" else ()
        light = {k: v for k, v in params.items() if k not in self.OPTIONAL or k in keep}
        if light != params and wait_s is None:             # a call that decides nothing gets no second, slower try
            tries.append(light)
        err = None
        for p in tries:
            if p is params and failed is not None:
                err = failed
                continue
            try:
                got = self.c.get(path, p)
            except QlooError as e:
                err = e
                continue
            rec = self._add({"call": got["source"]["call"], "what": what, "params": got["source"]["params"],
                             "cached": got["source"]["cached"], "at": got["source"]["at"], "ms": _ms(t0), "body_digest": _digest(got["body"]),
                             **({"surface": got["source"]["surface"]} if got["source"].get("surface") else {}),
                             **({"note": "retried without location/tags after Qloo refused them"} if p is not params else {})})
            narrow = [k for k in p if k.startswith(self.NARROWING)]
            if broaden and narrow and not _results(got["body"]) and not _broadened:
                # empty under the narrowing filters: broaden once, and say so
                return self.get(path, {k: v for k, v in p.items() if k not in narrow}, what + f" (broadened: nothing with {', '.join(narrow)})",
                                _broadened=True)
            return got["body"], rec["n"]
        m = re.search(r"HTTP (\d{3})", str(err))
        code = m.group(1) if m else ""
        short = ("Qloo refused this server's API key (HTTP %s): no Qloo data was used" % code if code in ("401", "403") else
                 "Qloo's rate limit for this key was reached (HTTP 429): Knos waits as long as Qloo asks before asking again" if code == "429" else
                 f"Qloo could not answer this part (HTTP {code})" if code else
                 "Qloo's monthly call budget is spent" if "budget" in str(err) else
                 "not sent: " + str(err).split("not sent: ", 1)[1][:160] if "not sent: " in str(err) else
                 "Qloo did not answer in time" if "did not answer" in str(err) else "Qloo could not be reached")
        self._add({"call": f"GET {path}", "what": what, "params": params, "ms": _ms(t0), "error": short})
        return None, None


def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def _digest(body) -> str:
    """A short, human summary of a Qloo answer (names and scores, never the whole body)."""
    r = (body or {}).get("results") if isinstance(body, dict) else None
    if isinstance(r, list):
        return f"{len(r)} results: " + ", ".join(str(x.get("name")) for x in r[:4])
    if isinstance(r, dict):
        for k in ("entities", "tags", "audiences", "heatmap", "trending", "demographics"):
            v = r.get(k)
            if isinstance(v, list):
                names = [str(x.get("name") or x.get("date") or (x.get("location") or {}).get("geohash") or "") for x in v[:4]]
                return f"{len(v)} {k}" + (": " + ", ".join(n for n in names if n) if any(names) else "")
        if "a" in r or "b" in r:
            return f"compare: {len(r.get('a') or [])} tags on the idea's side, {len(r.get('b') or [])} on the leader's"
    return "answer received"


def _results(body) -> list:
    r = (body or {}).get("results")
    return r if isinstance(r, list) else []


# Words that name a product's form, not what it is: a match that shares only these with the idea is not that product
# ("a vegan ramen subscription box" is not an outdoor-gear subscription box).
FORM_WORDS = {_norm(w) for w in ("box", "boxes", "kit", "kits", "subscription", "subscriptions", "app", "apps", "brand", "brands",
                                  "service", "services", "set", "sets", "pack", "packs", "club", "clubs", "shop", "shops", "store",
                                  "stores", "company", "product", "products", "line", "delivery", "platform", "online", "series")}


def _cat_stem(w: str) -> str:
    w = w.lower()
    for a, b in (("ies", "y"), ("es", ""), ("s", "")):
        if w.endswith(a) and len(w) > len(a) + 3:
            return w[: -len(a)] + b
    return w


def _cat_stems(text) -> list[str]:
    return [_cat_stem(w) for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(w) >= 3]


def category_word(idea: str, tags: list[dict]) -> str | None:
    """What the idea is, in one word: its last word that also names one of the Qloo tags resolved for it (/v2/tags)."""
    in_tags = {w for t in tags or [] for w in _cat_stems(t.get("name"))}
    words = [w for w in _cat_stems(idea) if w not in STOP_STEMS]
    inside = [w for w in words if w in in_tags]
    return inside[-1] if inside else None


STOP_STEMS = {"for", "the", "and", "with", "brand", "kit", "app", "that", "your", "from"}


def entity_tied(m: dict, idea: str, tags: list[dict]) -> bool:
    """A match for the idea only when the entity shares a Qloo tag with the idea's tags, or names its category."""
    ids = {t.get("id") for t in tags or [] if t.get("id")}
    if ids & set(m.get("tag_ids") or []):
        return True
    cat = category_word(idea, tags)
    return cat is None or cat in _cat_stems(f"{m.get('name') or ''} {m.get('about') or ''}")


def retie(rep: dict) -> dict:
    """A kept report with the match rule applied (tied): a match that fails it moves to the unrelated, its id leaves
    the cities' "because", and when the matches change the report is decided again by the same code."""
    idea, tags = str(rep.get("idea") or ""), rep.get("tags") or []
    keep = [m for m in rep.get("matches") or [] if entity_tied(m, idea, tags)]
    if len(keep) == len(rep.get("matches") or []):
        return rep
    gone = [m for m in rep["matches"] if m not in keep]
    out = {**rep, "matches": keep,
           "unrelated": list(rep.get("unrelated") or [])       # the dropped ones last: the refusal names the nearest results first
           + [{"name": m.get("name"), "why": "shares no Qloo tag with the idea and does not name what it is"} for m in gone]}
    ids = {m.get("id") for m in keep}
    lead = rep.get("leader") if isinstance(rep.get("leader"), dict) and rep["leader"].get("id") in ids else None
    out["leader"] = lead or (max(keep, key=lambda m: len(m.get("matched_words") or []) + 2 * len(m.get("name_words") or []) + (m.get("popularity") or 0)) if keep else None)
    out["cities"] = [{**c, "because": [i for i in c.get("because") or [] if i in ids]} for c in rep.get("cities") or []]
    names = {m.get("name") for m in gone}
    old = rep.get("leader") if isinstance(rep.get("leader"), dict) else None
    if old and old.get("id") not in ids:                     # what was measured against a dropped leader goes with it
        out["versus"], out["trend"] = None, None
    out["ladder"] = [b for b in rep.get("ladder") or [] if b.get("name") not in names]
    g = rep.get("grounding")
    if isinstance(g, dict) and isinstance(g.get("comparables"), list):
        out["grounding"] = {**g, "comparables": [c for c in g["comparables"] if c not in names]}
    out["decision"] = decide(out, True, idea)
    return out


def _ent(r: dict, src: int, words: list[str]) -> dict:
    p = r.get("properties") or {}
    geo = p.get("geocode") or {}
    where = ", ".join(str(x) for x in (geo.get("name"), geo.get("admin1_region"), geo.get("country_code")) if x) or p.get("address") or ""
    tag_names = " ".join(str(t.get("name") or "") for t in (r.get("tags") or [])[:40] if isinstance(t, dict))
    name_t = {_norm(p) for w in tokens(r.get("name") or "") for p in [w, *w.split("-")] if p}
    all_t = name_t | {_norm(w) for w in tokens(f"{p.get('short_description') or p.get('description') or ''} {tag_names}")}
    name_hits = sorted(name_t & set(words))
    hits = sorted(all_t & set(words))
    return {"name": r.get("name"), "id": r.get("entity_id"), "type": (r.get("types") or [None])[0], "popularity": r.get("popularity"),
            "about": (p.get("short_description") or p.get("description") or "")[:240], "located": str(where)[:120],
            "address": str(p.get("address") or "")[:160], "matched_words": hits, "name_words": name_hits,
            "relevant": bool(set(hits) - FORM_WORDS) and (len(name_hits) >= 2 or (len(name_hits) >= 1 and len(hits) >= 2) or len(hits) >= 3),
            "tag_ids": [t.get("id") for t in (r.get("tags") or [])[:40] if isinstance(t, dict) and t.get("id")], "src": src}


def _dedupe(ms: list[dict]) -> list[dict]:
    seen, out = set(), []
    for m in ms:
        k = re.sub(r"[^a-z0-9]", "", (m.get("name") or "").lower())
        if m.get("id") in seen or k in seen:
            continue
        seen.update({m.get("id"), k})
        out.append(m)
    return out


def _in_place(m: dict, place: str | None) -> bool:
    if not place:
        return True
    hay = f"{m.get('located')} {m.get('address')}".lower()
    return any(t in hay for t in tokens(place) if len(t) > 2)


def _trend(run: _Run, ent: dict | None, today: dt.date) -> dict:
    """The leader's weekly population percentile over the newest 26 weeks Qloo has (one window back if empty)."""
    if not ent or ent.get("type") not in TREND_TYPES:
        return {"direction": "no movement", "why": TREND_NOTE, "counted": False}
    for back in (0, 1, 2):
        end = today - dt.timedelta(weeks=12 * back)
        start = end - dt.timedelta(weeks=12)
        body, src = run.get("/v2/trending", {"filter.type": ent["type"], "signal.interests.entities": ent["id"],
                                             "filter.start_date": start.isoformat(), "filter.end_date": end.isoformat(), "take": 50},
                            f"weekly trend of {ent['name']}")
        if src is None:
            return {"direction": "unknown", "why": "Qloo's trend call failed", "counted": False}
        pts = sorted(((p.get("date"), p.get("population_percentile"), p.get("population_rank_velocity") or 0)
                      for p in ((body or {}).get("results") or {}).get("trending") or []
                      if isinstance(p.get("population_percentile"), (int, float))), key=lambda x: x[0] or "")
        if not pts:
            continue
        delta = round(pts[-1][1] - pts[0][1], 4)
        moved = len({round(p[1], 6) for p in pts}) > 1 or any(p[2] for p in pts)
        row = {"entity": ent["name"], "from": pts[0][0], "to": pts[-1][0], "data_through": pts[-1][0], "weeks": len(pts),
               "start_percentile": round(pts[0][1], 4), "end_percentile": round(pts[-1][1], 4), "delta": delta, "src": src}
        if not moved:
            return {**row, "direction": "no movement", "counted": False,
                    "why": TREND_NOTE.replace(DATA_END, pts[-1][0])}
        d = "rising" if delta >= RULES["rising_delta"] else "falling" if delta <= RULES["falling_delta"] else "flat"
        return {**row, "direction": d, "counted": d != "flat"}
    return {"direction": "no movement", "why": TREND_NOTE, "counted": False}


def _stem(w: str) -> str:
    w = w.lower()
    for suf in ("ers", "er", "ing", "ism", "ists", "ist", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


GROUP_GENERIC = {"with", "young", "and", "professional", "enthusiast", "enthusiasts", "issues", "interests", "politically",
                 "health", "beauty", "home", "art", "arts"}


AUDIENCE_TAKE = 50          # /v2/audiences takes 1 to 50 a page (Qloo's docs); a second page only when the named group is not on the first
SEGMENTS_SCORED = 4         # segments whose lift is read for one check (one /v2/insights call each), besides the named group
NEAREST = 10                # the products nearest the taste whose affinity the lift is measured on
SPENDING = "urn:audience:spending_habits"
SEARCH_WORDS = 3            # the idea's content words searched by name in /v2/audiences (filter.query), one call each
FLAT_LIFT = 0.0005          # scored segments whose lifts all lie within this are flat: shown, never counted as who buys


def _named_stems(idea: str) -> set[str]:
    low = f" {idea.lower()} "
    named = low.split(" for ", 1)[1] if " for " in low else ""         # the buyers are named after "for": "... for runners"
    return {_stem(w) for w in tokens(named) if len(w) > 3 and w not in STOP}


def _seg_list(run: _Run, types: list[str], what: str, page: int = 1) -> tuple[list[dict], int | None]:
    body, src = run.get("/v2/audiences", {"filter.audience.types": ",".join(types), "take": AUDIENCE_TAKE, "page": page}, what)
    return [{"name": str(a.get("name") or ""), "id": a.get("id") or a.get("entity_id"), "type": a.get("parent_type") or a.get("type")}
            for a in (((body or {}).get("results") or {}).get("audiences") or []) if safe_segment(a) and (a.get("id") or a.get("entity_id"))], src


def _segments(run: _Run, idea: str, kind: str, via: list[str], key: str, words: list[str], tags: list[dict],
              spending: bool = True) -> dict:
    """Who buys and the price tier, from Qloo's documented audience calls only (sweep 22 section 4: the ranked-segment
    value filter.type=urn:entity:audience is deprecated and the hackathon API answers it HTTP 400).
    1. Candidate segments: GET /v2/audiences, the non-sensitive types, 50 a page.
    2. The baseline: /v2/insights of the idea's kind with this taste as the signal (the matched products, or the top
       products of its tags), its NEAREST products and their affinity.
    3. One call per segment: the same question with signal.demographics.audiences=<segment> at weight high, its results
       pinned to those products (filter.results.entities). Lift = their mean affinity with the segment minus without it.
    A refused call is missing evidence, never counted. Measured 29 Oct 2026: Qloo answers the lift only with an interest
    signal beside the audience (an audience alone gives every product the same 0.765), and leaves the signal's own
    products out of the results, so the lift is read on the products nearest them."""
    out: dict = {"rows": [], "taste": None, "group": None, "spending": [], "src": None}
    if not via:
        return out
    types = [t for t in AUDIENCE_TYPES if t not in SENSITIVE_TYPES and t != SPENDING]
    q0 = {"filter.type": kind, key: ",".join(via), "take": NEAREST}
    named = [w for w in words if len(w) > 3][:SEARCH_WORDS]          # the idea's own words, searched by name (filter.query)

    def q_named(w):
        return {"filter.audience.types": ",".join(types), "filter.query": w, "take": AUDIENCE_TAKE, "page": 1}
    run.prefetch([("/v2/audiences", {"filter.audience.types": ",".join(types), "take": AUDIENCE_TAKE, "page": 1}), ("/v2/insights", q0)]
                 + [("/v2/audiences", q_named(w)) for w in named]
                 + ([("/v2/audiences", {"filter.audience.types": SPENDING, "take": AUDIENCE_TAKE, "page": 1})] if spending else []))
    by_name: list[dict] = []
    for w in named:
        body, _sn = run.get("/v2/audiences", q_named(w), f"audience segments: Qloo's segments named like '{w}'", broaden=False)
        by_name += [{"name": str(a.get("name") or ""), "id": a.get("id") or a.get("entity_id"), "type": a.get("parent_type") or a.get("type")}
                    for a in (((body or {}).get("results") or {}).get("audiences") or []) if safe_segment(a) and (a.get("id") or a.get("entity_id"))]
    segs, s_list = _seg_list(run, types, "audience segments: Qloo's segment list (non-sensitive types, 50 a page)")
    stems = _named_stems(idea)
    group = None
    for page in (1, 2):
        group = next((a for a in segs if {_stem(w) for w in tokens(a["name"]) if w not in GROUP_GENERIC} & stems), None) if stems else None
        if group or not stems or page == 2 or len(segs) < AUDIENCE_TAKE:
            break
        more, _s = _seg_list(run, types, "audience segments: Qloo's segment list, page 2 (the named buyer group)", page=2)
        segs += more
    body, s0 = run.get("/v2/insights", q0, f"audience segments: the {NEAREST} products nearest this taste (the lift's baseline)")
    near = {e.get("entity_id"): (e.get("query") or {}).get("affinity") for e in (((body or {}).get("results") or {}).get("entities") or [])
            if e.get("entity_id") and isinstance((e.get("query") or {}).get("affinity"), (int, float))}
    if s0 is None or not near:
        return out
    out["taste"] = {"mean_affinity": round(sum(near.values()) / len(near), 4), "products": len(near), "src": s0}
    out["near_ids"] = list(near)
    idea_words = set(words) | {w for t in tags for w in _path_words(t.get("id"))}
    own = [a for a in by_name + segs if ({_norm(w) for w in tokens(a["name"])} | _path_words(a["id"])) & idea_words]
    pick = list({a["id"]: a for a in ([group] if group else []) + own + segs}.values())[:SEGMENTS_SCORED + (1 if group else 0)]
    spend_segs = _seg_list(run, [SPENDING], "audience segments: Qloo's spending-habit segments (the price tier)")[0] if spending else []
    prem = next((a for n in PREMIUM for a in spend_segs if a["name"] == n), None)
    budg = next((a for n in BUDGET for a in spend_segs if a["name"] == n), None)
    spend = [a for a in (prem, budg) if a]
    pinned = {**q0, "filter.results.entities": ",".join(near)}

    def q(a):
        return {**pinned, "signal.demographics.audiences": a["id"], "signal.demographics.audiences.weight": "high"}
    run.prefetch([("/v2/insights", q(a)) for a in pick + spend])

    def lift(a, what):
        b, s = run.get("/v2/insights", q(a), what, broaden=False)
        got = {e.get("entity_id"): (e.get("query") or {}).get("affinity") for e in (((b or {}).get("results") or {}).get("entities") or [])}
        both = [k for k in near if isinstance(got.get(k), (int, float))]
        return (round(sum(got[k] - near[k] for k in both) / len(both), 4) if both else None), s, len(both)
    for a in pick:
        v, s, n = lift(a, f"audience segments: lift of {a['name']} on this taste")
        if v is not None:
            out["rows"].append({"name": a["name"], "id": a["id"], "type": a.get("type"), "lift": v, "products": n, "src": s})
    for a in spend:
        v, s, n = lift(a, f"audience segments: lift of {a['name']} (spending habits, the price tier)")
        if v is not None:
            out["spending"].append({"name": a["name"], "id": a["id"], "lift": v, "premium": a is prem, "src": s})
    out["rows"].sort(key=lambda r: -r["lift"])
    lifts = [r["lift"] for r in out["rows"]]
    if len(lifts) >= 2 and max(lifts) - min(lifts) < FLAT_LIFT:      # Qloo's audience signal moved every segment alike
        out["flat"] = round(lifts[0], 4)
        for r in out["rows"]:
            r["flat"] = True
    if group:
        hit = next((r for r in out["rows"] if r["id"] == group["id"]), None)
        rank = out["rows"].index(hit) + 1 if hit else None
        ok = hit is not None and rank is not None and rank <= max(1, len(out["rows"]) // 2)
        out["group"] = {"segment": group["name"], "id": group["id"], "lift": hit["lift"] if hit else None, "rank": rank,
                        "of": len(out["rows"]), "status": "confirmed" if ok else "refuted", "src": hit["src"] if hit else s_list}
    out["src"] = s0
    return out


def _recommend(run: _Run, kind: str, signal: dict, known: set, tags: list[dict] | None = None) -> dict | None:
    """Qloo's recommendations for this taste (/v2/insights filter.type = the idea's kind), kept to the idea's own taste
    tags: products next to the idea. Strong neighbours (affinity >= rules) that are not already matched are adjacent
    demand. With no taste tag to keep them in the idea's domain, they are not asked for and move nothing (unscoped,
    the same brands came back for a kombucha and a handbag)."""
    if not tags:
        return None
    thin = {"backfill.cross_domain.take": "5"} if len(known) < 3 else {}    # thin matches: cross-domain backfill, not a refusal
    scope = {"filter.tags": ",".join(t["id"] for t in tags[:3]), "operator.filter.tags": "union"}
    weight = {"signal.demographics.audiences.weight": "medium"} if signal.get("signal.demographics.audiences") else {}
    body, src = run.get("/v2/insights", {"filter.type": kind, "take": 10, "feature.explainability": "true", "bias.trends": "high",
                                         "filter.popularity.min": "0.2", **weight, **thin, **scope, **signal},
                        "recommendations: what this audience also likes, in the idea's taste tags (popularity at least 0.2, bias.trends high"
                                         + (", cross-domain backfill)" if thin else ")"))
    if src is None:
        return None
    rows = [{"name": e.get("name"), "id": e.get("entity_id"), "affinity": (e.get("query") or {}).get("affinity"), "popularity": e.get("popularity")}
            for e in (((body or {}).get("results") or {}).get("entities") or [])[:10]]
    adj = [r for r in rows if r["id"] not in known and isinstance(r["affinity"], (int, float)) and r["affinity"] >= RULES["adjacent_affinity"]]
    return {"items": rows, "adjacent": [r["name"] for r in adj], "strong": len(adj), "src": src}


# words of a Qloo id path that say nothing about the idea ("urn:audience:hobbies_and_interests:sneakerheads")
PATH_GENERIC = {"urn", "tag", "audience", "qloo", "keyword", "genre", "category", "subtype", "and", "the", "of", "interest",
                "hobbie", "hobby", "lifestyle", "preference", "communitie", "community", "global", "issue", "investing", "entity"}


def _path_words(urn) -> set[str]:
    return {_norm(w) for w in re.split(r"[:_\-./]+", str(urn or "").lower()) if len(w) > 2} - PATH_GENERIC


def tied(row: dict, words: list[str], tags: list[dict]) -> bool:
    """A segment shown under "Who wants it" must share a word, or a Qloo tag path word, with its idea: its name's words or
    its id's path against the idea's content words and the paths of the idea's own Qloo tags."""
    idea = set(words) | {w for t in tags for w in _path_words(t.get("id"))}
    own = {_norm(w) for w in tokens(row.get("name") or "")} | _path_words(row.get("id"))
    return bool(own & idea)


def _tag_tops(run: _Run, tags: list[dict], ents: list[dict], kind: str = "urn:entity:brand") -> list[dict]:
    """The products that carry this taste: the idea's matched ones, and for each of its own taste tags the tag's top
    products in the idea's kind (/v2/insights filter.tags), so an idea no product matches still reaches the people of
    its taste. Each keeps what ties it to the idea (the product itself, or the tag it came through)."""
    tags = [t for t in tags if t.get("id")]
    run.prefetch([("/v2/insights", {"filter.type": kind, "filter.tags": t["id"], "take": 2}) for t in tags])
    asks = [{"name": m.get("name"), "id": m["id"], "tie": {"kind": "product", "name": m.get("name"), "id": m["id"]}} for m in ents if m and m.get("id")]
    known = {a["id"] for a in asks}
    for t in tags:
        body, _ = run.get("/v2/insights", {"filter.type": kind, "filter.tags": t["id"], "take": 2},
                          f"who wants it: the top products of the tag {t.get('name')}", broaden=False)
        for e in (((body or {}).get("results") or {}).get("entities") or [])[:2]:
            if e.get("entity_id") and e["entity_id"] not in known:
                known.add(e["entity_id"])
                asks.append({"name": e.get("name"), "id": e["entity_id"],
                             "tie": {"kind": "tag", "name": t.get("name"), "id": t["id"], "via": e.get("name"), "via_id": e["entity_id"]}})
    return asks[:6]


def _who_wants(seg: dict, tops: list[dict]) -> list[dict]:
    """"Who wants it": the scored segments (_segments) with the highest lift, each tied to the products the lift was read
    through. Shown only; the verdict reads the segments through decide()."""
    tie = (tops[0]["tie"] if len(tops) == 1 else {"kind": "products", "name": ", ".join(str(a["name"]) for a in tops[:3]),
                                                   "id": ",".join(a["id"] for a in tops[:3])}) if tops else None
    return [{**r, "tie": tie} for r in (seg.get("rows") or [])[:6]]


ALSO_LOVE = (("music", "urn:entity:artist"), ("film", "urn:entity:movie"))


def _flat(items: list[dict]) -> bool:
    """Every answer at one affinity: Qloo's fallback for a signal it could not use, not this taste's."""
    return len(items) > 1 and len({x.get("affinity") for x in items}) == 1


def _also_love_q(ents: list[str], key: str, take: int = 4) -> list[tuple[str, dict]]:
    return [("/v2/insights", {"filter.type": t, "take": take, key: ",".join(ents)}) for _, t in ALSO_LOVE] if ents else []


def _launch_q(ents: list[str], place: str | None, key: str) -> list[tuple[str, dict]]:
    loc = place or DEFAULT_PLACE
    cc = market_country(loc)
    sig = {key: ",".join(ents)}
    return [("/v2/insights", {"filter.type": "urn:entity:destination", "take": 8, **({"filter.geocode.country_code": cc} if cc else {"filter.location.query": loc}), **sig}),
            ("/v2/insights", {"filter.type": "urn:heatmap", "filter.location.query": loc, "take": 5, **sig})]


def _also_love(run: _Run, ents: list[str], via: str, take: int = 4, key: str = "signal.interests.entities") -> dict | None:
    """What the people of this taste also love, in two other Qloo domains (artists and films, /v2/insights with
    signal.interests.entities, or .tags when no product carries the taste): shown only, the verdict does not read it."""
    if not ents:
        return None
    sig = {key: ",".join(ents)}
    run.prefetch([("/v2/insights", {"filter.type": t, "take": take, **sig}) for _, t in ALSO_LOVE])
    out = []
    for domain, t in ALSO_LOVE:
        body, n = run.get("/v2/insights", {"filter.type": t, "take": take, **sig}, f"also loved: {domain} ({t}) of the people of this taste", broaden=False)
        items = [{"name": e.get("name"), "affinity": (e.get("query") or {}).get("affinity")}
                 for e in (((body or {}).get("results") or {}).get("entities") or [])[:take] if e.get("name")]
        if items and not _flat(items):
            out.append({"domain": domain, "items": items, "src": n})
    return {"via": via, "domains": out} if out else None


def _launch(run: _Run, ents: list[str], place: str | None, key: str = "signal.interests.entities") -> dict | None:
    """Where to launch when no product matched the idea: Qloo's destinations and heatmap for the top products of its
    taste tags (the same calls as for a matched product, with that signal). Shown only; the verdict does not read it."""
    loc = place or DEFAULT_PLACE
    cc = market_country(loc)
    sig = {key: ",".join(ents)}
    q10 = {"filter.type": "urn:entity:destination", "take": 8, **({"filter.geocode.country_code": cc} if cc else {"filter.location.query": loc}), **sig}
    q7 = {"filter.type": "urn:heatmap", "filter.location.query": loc, "take": 5, **sig}
    run.prefetch([("/v2/insights", q10), ("/v2/insights", q7)])
    body, s10 = run.get("/v2/insights", q10, f"launch cities in {loc}, from the top products of the idea's taste tags", broaden=False)
    cities = []
    for r in (((body or {}).get("results") or {}).get("entities") or []):
        geo = (r.get("properties") or {}).get("geocode") or {}
        if (cc and geo.get("country_code") and geo["country_code"] != cc) or len(cities) >= 5:
            continue
        at = r.get("location") or {}
        lat, lon = at.get("lat", at.get("latitude")), at.get("lon", at.get("longitude"))
        ok = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        cities.append({"name": r.get("name"), "country": geo.get("country_code"), "affinity": (r.get("query") or {}).get("affinity"),
                       "lat": lat if ok else None, "lon": lon if ok else None, "src": s10})
    from . import open_signals
    for c in [c for c in cities if c["lat"] is None]:
        got = open_signals.coords(c["name"], c.get("country"))
        if got:
            c.update(lat=got[0], lon=got[1], coords_from="Wikidata")
    body, s7 = run.get("/v2/insights", q7, f"where: map points in {loc}, from the top products of the idea's taste tags", wait_s=MAP_WAIT_S)
    where = [{"lat": (h.get("location") or {}).get("latitude"), "lon": (h.get("location") or {}).get("longitude"),
              "affinity": (h.get("query") or {}).get("affinity"), "src": s7}
             for h in (((body or {}).get("results") or {}).get("heatmap") or [])[:HEAT_CELLS]]
    if _flat(cities):
        cities = []
    return {"cities": cities, "where": where, "via": "the top products of its taste tags"} if cities or where else None


def _tag_map_q(tag: str, place: str | None) -> dict:
    return {"filter.type": "urn:heatmap", "filter.location.query": place or DEFAULT_PLACE, "take": 5, "signal.interests.tags": tag}


def _tag_map(run: _Run, tag: str, place: str | None) -> list[dict]:
    """Qloo's heatmap for the idea's top matched tag, when the idea itself brought no cells."""
    q = _tag_map_q(tag, place)
    body, s7 = run.get("/v2/insights", q, f"where: map points for the top matched tag {tag}", wait_s=MAP_WAIT_S)
    return [{"lat": (h.get("location") or {}).get("latitude"), "lon": (h.get("location") or {}).get("longitude"),
             "affinity": (h.get("query") or {}).get("affinity"), "src": s7}
            for h in (((body or {}).get("results") or {}).get("heatmap") or [])[:HEAT_CELLS]]


def _new_idea(run: _Run, ev: dict, idea: str, kind: str, place: str | None, words: list[str], verdict_only: bool) -> dict:
    """A new idea has no existing product, so it is answered from its own taste (N1), never refused for being new:
    1. the Qloo tags that share a content word with it (gather's /v2/tags search);
    2. /v2/insights of its kind with those tags as signal.interests.tags (and signal.location.query when a place is
       given): the products or places Qloo ties to that taste, each with its affinity;
    3. who buys: Qloo's demographics and the audience lift (_segments) on those products;
    4. where to launch (the full card): the destinations, heatmap and named places of that taste.
    With no tag sharing a word, decide() says "Qloo knows nothing close to <words>"."""
    tags = [t for t in ev["tags"] if t.get("id")][:3]
    if not tags:
        return ev
    q_t = {"filter.type": kind, "signal.interests.tags": ",".join(t["id"] for t in tags), "take": NEAREST,
           **({"signal.location.query": place} if place else {})}
    body, s_t = run.get("/v2/insights", q_t, f"the idea's own taste: {kind.split(':')[-1]}s Qloo ties to the tags "
                        + ", ".join(str(t["name"]) for t in tags), broaden=False)
    items = []
    for e in (((body or {}).get("results") or {}).get("entities") or []):
        if not e.get("entity_id"):
            continue
        geo = (e.get("properties") or {}).get("geocode") or {}
        items.append({"name": e.get("name"), "id": e["entity_id"], "affinity": (e.get("query") or {}).get("affinity"),
                      "area": ", ".join(str(x) for x in (geo.get("name"), geo.get("admin1_region")) if x) or None,
                      "price_level": (e.get("properties") or {}).get("price_level"), "src": s_t})
    ev["taste_answer"] = {"kind": kind, "tags": [{"name": t["name"], "id": t["id"], "src": t.get("src")} for t in tags],
                          "items": items[:6], "src": s_t}
    via, key, said = [x["id"] for x in items[:3]], "signal.interests.entities", "the products nearest its taste tags"
    if not via:
        via, key, said = [t["id"] for t in tags], "signal.interests.tags", "its taste tags"
    loc = place or DEFAULT_PLACE
    q_who = {"filter.type": "urn:demographics", key: ",".join(via), **({"signal.location.query": place} if place else {})}
    run.prefetch([("/v2/insights", q_who)])
    seg = _segments(run, idea, kind, via, key, words, ev["tags"], spending=not verdict_only)
    body, s5 = run.get("/v2/insights", q_who, "who: age and gender affinity of the people of this taste")
    demo = ((body or {}).get("results") or {}).get("demographics") or []
    q = ((demo[0] or {}).get("query") or {}) if demo else {}
    if q.get("age") or q.get("gender"):
        age, gender = q.get("age") or {}, q.get("gender") or {}
        ev["who"] = {"age": age, "gender": gender, "top_age": max(age, key=age.get) if age else None,
                     "top_gender": max(gender, key=gender.get) if gender else None, "src": s5}
    ev["audiences"] = [{**r, "tied": tied(r, words, ev["tags"])} for r in seg["rows"][:6]]
    ev["taste"], ev["spending"], ev["buyer_group"] = seg["taste"], seg["spending"], seg["group"]
    ev["near_ids"] = seg.get("near_ids") or []
    ev["place"] = loc
    if kind == "urn:entity:place":
        ev["places"] = [{"name": x["name"], "area": x["area"] or "", "price_level": x["price_level"], "src": s_t} for x in items[:5]]
    if verdict_only:
        return ev
    tops = [{"name": x["name"], "id": x["id"], "tie": {"kind": "tag", "name": tags[0]["name"], "id": tags[0]["id"],
                                                        "via": x["name"], "via_id": x["id"]}} for x in items[:3]]
    ev["who_wants"] = _who_wants(seg, tops)
    run.prefetch(_also_love_q(via, key) + _launch_q(via, place, key))
    ev["also_love"] = _also_love(run, via, said, key=key)
    ev["launch"] = _launch(run, via, place, key=key)
    ev["price"] = price_tier(ev["spending"], [x["price_level"] for x in items])
    return ev


# a demand check's time budget: past it, a question that is not essential is left out, said so. Off: at 8 s, 20 cold
# ideas after a redeploy came back with a p95 of 10.60 s (from 15.87 s) but only 6 of 20 with heatmap cells (from 12),
# so most first checks lost their launch city; a launch city is worth the seconds
CHECK_BUDGET_S: float | None = None
HEAT_CELLS = 50           # the heatmap cells read (the cache keeps Qloo's first 50): metros.py needs 3 in one metro
MAP_WAIT_S = 8.0          # how long the check waits, at the end, for Qloo's heatmap (the slowest answer): the verdict reads
                          # none of it, but the launch city and the pre-order target do (metros.py); at 2 s a cold cache lost it


def _key(path: str, params: dict) -> str:
    return path + "?" + json.dumps(params, sort_keys=True, default=str)


def gather(run: _Run, idea: str, place: str | None, leader: str | None, today: dt.date, exclude: set[str],
           verdict_only: bool = False) -> dict:
    ev: dict = {"product_type": None, "words": [], "matches": [], "unrelated": [], "excluded": [], "leader": None, "tags": [],
                "who": None, "where": [], "places": [], "audiences": [], "who_wants": [], "also_love": None, "launch": None, "trend": None, "versus": None, "named_audience": [], "buyer_group": None, "recommended": None, "cities": [], "price": None, "persona": [], "persona_all": [], "ladder": [], "tag_families": []}
    words = content_words(idea, place)
    ev["words"], ev["named_audience"] = words, [{"word": w, "dimension": d, "key": k} for w, d, k in audience_named(idea)]
    if not words:
        return ev
    kind = ev["product_type"] = kind_of(idea)
    drop = kind_words() | {_norm(w) for w in PLACE_NOUNS}
    q_words = [w for w in words if w not in drop] or words
    rel = q_words
    both = kind in ("urn:entity:place", "urn:entity:brand")           # a place or a brand idea is searched as both kinds
    other = ("urn:entity:brand" if kind == "urn:entity:place" else "urn:entity:place") if both else None

    def q_search(k):
        return {"query": " ".join(q_words[:5]) + (f" {place}" if place and k == "urn:entity:place" else ""), "types": k, "take": 12, "sort_by": "match"}
    q_tags = {"filter.query": " ".join(q_words[:6]), "feature.semantic_search": "true", "feature.typo_tolerance": "true", "take": 8}
    run.prefetch([("/v2/tags", q_tags)] + ([("/search", q_search(other))] if other else []))   # asked with the search
    body, src = run.get("/search", q_search(kind), "closest existing products")
    if src is None:
        return ev
    found = _dedupe([_ent(r, src, rel) for r in _results(body) if r.get("entity_id")])
    if other:
        b_o, s_o = run.get("/search", q_search(other), f"closest existing products, asked as a {other.split(':')[-1]}", broaden=False)
        alt = _dedupe([_ent(r, s_o, rel) for r in _results(b_o) if r.get("entity_id")]) if s_o else []
        if sum(m["relevant"] for m in alt) > sum(m["relevant"] for m in found):          # the better match decides the kind
            kind, found, body, src = other, alt, b_o, s_o
            ev["product_type"] = kind
            ev["kind_switched"] = {"from": kind_of(idea), "to": kind, "why": "more relevant matches as this kind"}
    query = q_search(kind)["query"]
    q_fams = {"filter.parents.types": kind, "take": 10}
    # Qloo's text search reads a long query as one phrase: when nothing relevant comes back, ask again with the idea's
    # word pairs (at most 2 more calls), keeping only what passes the same relevance gate.
    if not any(m["relevant"] for m in found) and len(_results(body)) >= 12:     # the next page of the same answer first
        b2, s2 = run.get("/search", {"query": query, "types": kind, "take": 12, "page": 2, "sort_by": "match"},   # Qloo documents page, not offset
                         "closest existing products (the next 12)")
        found = _dedupe(found + [_ent(r, s2, rel) for r in _results(b2) if r.get("entity_id")]) if s2 else found
    if not any(m["relevant"] for m in found) and len(q_words) > 2:
        for pair in (q_words[:2], q_words[-2:]):
            b2, s2 = run.get("/search", {"query": " ".join(pair), "types": kind, "take": 12}, "closest existing products (word pair)")
            found = _dedupe(found + [_ent(r, s2, rel) for r in _results(b2) if r.get("entity_id")]) if s2 else found
            if any(m["relevant"] for m in found):
                break
    if kind == "urn:entity:place" and place:
        found = [m for m in found if _in_place(m, place)]
    ev["excluded"] = [m for m in found if m["id"] in exclude]
    found = [m for m in found if m["id"] not in exclude]
    # the idea's own tags first: a match must share one with it, or name what the idea is (tied)
    body, s4 = run.get("/v2/tags", q_tags, "taste tags: semantic search (typo-tolerant) of the product phrase")
    if body is not None:
        for t in ((body or {}).get("results") or {}).get("tags") or []:
            if t.get("id") and t["id"] not in {x["id"] for x in ev["tags"]} and {_norm(x) for x in tokens(t.get("name"))} & set(words):
                ev["tags"].append({"name": t.get("name"), "id": t["id"], "popularity": t.get("popularity"), "src": s4})
    ev["matches"] = [m for m in found if m["relevant"] and entity_tied(m, idea, ev["tags"])][:6]
    ev["unrelated"] = ([{"name": m["name"], "why": "shares too few content words with the idea"} for m in found if not m["relevant"]]
                       + [{"name": m["name"], "why": "shares no Qloo tag with the idea and does not name what it is"}
                          for m in found if m["relevant"] and not entity_tied(m, idea, ev["tags"])])[:6]
    lead = None
    if leader:
        body, s2 = run.get("/search", {"query": leader[:80], "types": kind, "take": 1}, "the named market leader")
        got = [_ent(r, s2, rel) for r in _results(body) if r.get("entity_id")]
        lead = got[0] if got else None
    if lead is None and ev["matches"]:
        lead = max(ev["matches"], key=lambda m: len(m["matched_words"]) + 2 * len(m["name_words"]) + (m.get("popularity") or 0))
    near = [m for m in ev["matches"] if lead is None or m["id"] != lead["id"]][:3]
    ev["leader"] = lead
    if not verdict_only:                             # shown on the full card only
        fams, _sf = run.get("/v2/tags/types", q_fams, f"tag families Qloo keeps for {kind.split(':')[-1]}s")
        ev["tag_families"] = [t.get("type") for t in ((fams or {}).get("results") or {}).get("tag_types") or []][:8]
    sig_ents = [m["id"] for m in near] or ([lead["id"]] if lead else [])
    # every question that needs only the matched products (or, with none, the top tag's map for the retry) goes out now,
    # before "who wants it": the verdict waits on the slowest of them, not on their sum
    if sig_ents:
        signal = {"signal.interests.entities": ",".join(sig_ents), **({"signal.location.query": place} if place else {})}
        loc = place or DEFAULT_PLACE
        ents_only = {"signal.interests.entities": signal["signal.interests.entities"]}
        cc = market_country(loc)
        q10 = {"filter.type": "urn:entity:destination", "take": 8, "feature.explainability": "true",
               **({"filter.geocode.country_code": cc} if cc else {"filter.location.query": loc}), **ents_only}
        hotel = {"filter.hotel_class.min": "3"} if {"hotel", "hotels", "resort", "stay"} & set(words) else {}
        q6 = {"filter.type": "urn:entity:place", **({"filter.geocode.country_code": cc} if cc else {"filter.location.query": loc}), "take": 5, "filter.properties.business_rating.min": "3.5",
              "filter.external.exists": "tripadvisor", **hotel, **ents_only,
              # the idea's taste tags, any of them (union), so a place matches on one: broadened away when they empty it
              **({"filter.tags": ",".join(t["id"] for t in ev["tags"][:3]), "operator.filter.tags": "union"} if ev["tags"] else {})}
        q7 = {"filter.type": "urn:heatmap", "filter.location.query": loc, "take": 5, **ents_only}     # Qloo's API refuses output.heatmap.boundary (400)
        q11 = {"filter.type": "urn:tag", "diversify.by": "subtype", "diversify.take": "2", "take": 8, **signal}
        q6_broad = {k: v for k, v in q6.items() if not k.startswith(run.NARROWING)}            # its broadened retry, ready too
        # every question that needs only the matched products, at once: the first verdict waits on the slowest of them,
        # not on their sum; the in-order calls below are then answered from the cache, numbered as always
        run.prefetch([("/v2/insights", {"filter.type": "urn:demographics", **signal}), ("/v2/insights", q6), ("/v2/insights", q6_broad),
                      ("/v2/insights", q7), ("/v2/insights", q11), ("/v2/insights", q10)])
        run.prefetch(_also_love_q(sig_ents, "signal.interests.entities"))
    elif ev["tags"]:
        run.prefetch([("/v2/insights", _tag_map_q(ev["tags"][0]["id"], place))])
    if not sig_ents:                                 # no existing product matches: answered from the idea's own taste (N1)
        return _new_idea(run, ev, idea, kind, place, words, verdict_only)
    # the verdict card (verdict_only) reads none of who-wants-it, also-loved, the map or the launch: they come with the full card
    mine = [m for m in (near or ([lead] if lead else []))][:2]
    tops = _tag_tops(run, ev["tags"][:3], mine, kind) if not verdict_only else \
        [{"name": m.get("name"), "id": m["id"], "tie": {"kind": "product", "name": m.get("name"), "id": m["id"]}} for m in mine]
    via, key, said = sig_ents, "signal.interests.entities", "the products it matched"
    seg = _segments(run, idea, kind, via, key, words, ev["tags"], spending=not verdict_only)   # who buys and the price tier
    ev["audiences"] = [{**r, "tied": tied(r, words, ev["tags"])} for r in seg["rows"][:6]]
    ev["taste"], ev["spending"], ev["buyer_group"] = seg["taste"], seg["spending"], seg["group"]
    ev["near_ids"] = seg.get("near_ids") or []
    ev["who_wants"] = [] if verdict_only else _who_wants(seg, tops)
    ev["also_love"] = None if verdict_only else _also_love(run, via, said, key=key)
    body, s5 = run.get("/v2/insights", {"filter.type": "urn:demographics", **signal}, "who: age and gender affinity")
    demo = ((body or {}).get("results") or {}).get("demographics") or []
    q = ((demo[0] or {}).get("query") or {}) if demo else {}
    if q.get("age") or q.get("gender"):
        age, gender = q.get("age") or {}, q.get("gender") or {}
        ev["who"] = {"age": age, "gender": gender, "top_age": max(age, key=age.get) if age else None,
                     "top_gender": max(gender, key=gender.get) if gender else None, "src": s5}
    signal_before = dict(signal)
    if ev["buyer_group"] and ev["buyer_group"].get("id"):
        signal = {**signal, "signal.demographics.audiences": ev["buyer_group"]["id"]}       # the named group steers the later calls
    ev["place"] = loc
    seen = {m["id"] for m in ev["matches"]} | ({lead["id"]} if lead else set())

    def places():
        body, s6 = run.get("/v2/insights", q6, f"where: named places in {loc} where this taste clusters (rated 3.5+, on Tripadvisor)")
        for r in (((body or {}).get("results") or {}).get("entities") or []):
            p = r.get("properties") or {}
            geo = p.get("geocode") or {}
            if len(ev["places"]) >= 5 or (cc and geo.get("country_code") and geo["country_code"] != cc):
                continue                       # named places stay inside the chosen market, as the launch cities do
            area = ", ".join(str(x) for x in (geo.get("name"), geo.get("admin2_region") or geo.get("admin1_region")) if x)
            ev["places"].append({"name": r.get("name"), "area": area or str(p.get("address") or "")[:80], "price_level": p.get("price_level"),
                                 "affinity": (r.get("query") or {}).get("affinity"), "src": s6})

    def persona():
        body, s11 = run.get("/v2/insights", q11, "taste persona: this taste's tags, one or two per family (diversify.by=subtype)")
        tail = kind.split(":")[-1]
        rows11 = [{"name": t.get("name"), "family": t.get("subtype"), "src": s11,
                   "on_kind": tail in str(t.get("subtype") or "") or bool({_norm(x) for x in tokens(t.get("name"))} & set(words))}
                  for t in (((body or {}).get("results") or {}).get("tags") or [])[:8]
                  if safe_segment({"name": t.get("name"), "type": t.get("subtype")})]        # no identity-like tag (SAFE_USE)
        ev["persona"] = [r for r in rows11 if r["on_kind"]] or rows11[:2]     # cross-domain noise stays out of the headline
        ev["persona_all"] = rows11

    def cities():
        body, s10 = run.get("/v2/insights", q10, f"launch cities: destinations in {loc} where this taste is strongest")
        for r in (((body or {}).get("results") or {}).get("entities") or []):
            geo = (r.get("properties") or {}).get("geocode") or {}
            if cc and geo.get("country_code") and geo["country_code"] != cc:
                continue                       # the launch cities stay inside the chosen market
            why = ((r.get("query") or {}).get("explainability") or {}).get("signal.interests.entities") or []
            if len(ev["cities"]) < 5:
                at = r.get("location") or {}
                lat, lon = at.get("lat", at.get("latitude")), at.get("lon", at.get("longitude"))
                ok = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                ev["cities"].append({"name": r.get("name"), "country": geo.get("country_code"), "affinity": (r.get("query") or {}).get("affinity"),
                                     "lat": lat if ok else None, "lon": lon if ok else None, "coords_from": "Qloo" if ok else None,
                                     "because": [x.get("entity_id") for x in why][:3], "src": s10})

        # a launch city Qloo named without coordinates is put on the map from Wikidata, while the other parts are still
        # being asked; the card names the source (an open signal: it decides nothing)
        from . import open_signals
        missing = [c for c in ev["cities"] if c.get("lat") is None]
        with ThreadPoolExecutor(max_workers=5) as ex:
            for c, got in zip(missing, ex.map(lambda c: open_signals.coords(c["name"], c.get("country")), missing)):
                if got:
                    c.update(lat=got[0], lon=got[1], coords_from="Wikidata")

    def ladder():
        if len(ev["matches"]) < 2:
            return
        ladder_ids = ",".join(m["id"] for m in ev["matches"][:6])
        body, s12 = run.get("/v2/insights", {"filter.type": kind, "filter.results.entities": ladder_ids, "take": 6, **signal_before},
                            "brand ladder: the matched products ranked against this taste (filter.results.entities)")
        ev["ladder"] = sorted([{"name": e.get("name"), "affinity": (e.get("query") or {}).get("affinity"), "popularity": e.get("popularity"),
                                "src": s12} for e in (((body or {}).get("results") or {}).get("entities") or [])],
                              key=lambda r: -(r["affinity"] or 0))

    def recommended():
        ev["recommended"] = _recommend(run, kind, signal, seen, ev["tags"])

    def trend():
        ev["trend"] = _trend(run, lead, today)

    def versus():
        if lead:
            ev["versus"] = _versus(run, near, lead, signal, ev.get("near_ids") or [], kind)
    # the independent parts, at once (each its own Qloo calls; the call list is numbered as each answer lands)
    with ThreadPoolExecutor(max_workers=7) as ex:
        for f in [ex.submit(x) for x in ((recommended, trend, versus) if verdict_only else (places, persona, cities, ladder, recommended, trend, versus))]:
            f.result()
    ev["price"] = price_tier(ev.get("spending") or [], [p_.get("price_level") for p_ in ev["places"]])
    # the verdict reads no `where` (the brief's launch terms do) and Qloo's heatmap is its slowest answer: read last,
    # so its wait overlaps everything above (it was asked at the start, with the other independent questions)
    if verdict_only:
        return ev
    body, s7 = run.get("/v2/insights", q7, f"where: map points in {loc}", wait_s=MAP_WAIT_S)
    for h in (((body or {}).get("results") or {}).get("heatmap") or [])[:HEAT_CELLS]:
        lc, hq = h.get("location") or {}, h.get("query") or {}
        ev["where"].append({"lat": lc.get("latitude"), "lon": lc.get("longitude"), "affinity": hq.get("affinity"), "src": s7})
    return ev


def _versus(run: _Run, near: list[dict], lead: dict, signal: dict, mine_near: list[str], kind: str = "urn:entity:brand") -> dict | None:
    """Overlap with the leader: shared taste tags when both sides have enough, else the share of the leader's nearest
    products that are also nearest this taste (/v2/insights of the idea's kind, NEAREST each).
    Needs at least one matched product besides the leader (else there is nothing to compare: None)."""
    if not near:
        return None
    if near:
        body, s8 = run.get("/v2/analysis/compare", {"a.signal.interests.entities": ",".join(e["id"] for e in near),
                                                    "b.signal.interests.entities": lead["id"], "take": 30}, "the idea's other matches vs the leader")
        r = (body or {}).get("results") or {}

        def names(lst):
            return {str(t.get("name")): t for t in (lst or []) if isinstance(t, dict) and t.get("name")}
        a, b = names(r.get("a")), names(r.get("b"))
        if s8 is not None and min(len(a), len(b)) >= RULES["min_compare_tags"]:
            shared = set(a) & set(b)
            return {"leader": lead["name"], "method": "shared taste tags (compare)", "overlap": round(len(shared) / min(len(a), len(b)), 3),
                    "shared": sorted(shared)[:8], "whitespace": sorted(set(a) - set(b))[:8], "leader_only": sorted(set(b) - set(a))[:8],
                    "sizes": [len(a), len(b)], "src": s8}
    if len(mine_near) < RULES["min_compare_tags"]:
        return None
    body, s9 = run.get("/v2/insights", {"filter.type": kind, "signal.interests.entities": lead["id"], "take": NEAREST},
                       f"the leader's ({lead['name']}) {NEAREST} nearest products", broaden=False)
    rows = {e.get("entity_id"): e.get("name") for e in (((body or {}).get("results") or {}).get("entities") or []) if e.get("entity_id")}
    if s9 is None or len(rows) < RULES["min_compare_tags"]:
        return None
    mine, theirs = set(mine_near), set(rows)
    shared = mine & theirs
    return {"leader": lead["name"], "method": "shared nearest products (Qloo has too few tags to compare)",
            "overlap": round(len(shared) / min(len(mine), len(theirs)), 3), "shared": sorted(str(rows[k]) for k in shared)[:8],
            "whitespace": [], "leader_only": sorted(str(rows[k]) for k in theirs - mine)[:8], "sizes": [len(mine), len(theirs)], "src": s9}


def _clone(idea: str, lead: dict | None, words: list[str]) -> str | None:
    if not lead or not lead.get("name"):
        return None
    low = idea.lower()
    name = re.sub(r"\s*\(.*?\)\s*", " ", lead["name"]).strip().lower()
    if len(name) < 3 or not re.search(rf"\b{re.escape(name)}\b", low):
        return None
    rest = [w for w in words if w not in {_norm(x) for x in tokens(name)} and w not in kind_words()]
    if any(p in low for p in CLONE_PHRASES) or len(rest) <= 1:
        return f"{OWNED}: the idea is {lead['name']} itself (popularity {lead.get('popularity') or 0:.2f})"
    return None


def _scored(ev: dict) -> list[dict]:
    """The audience segments that count: a lift Qloo answered, and lifts that separate the segments (never flat)."""
    return [a for a in ev.get("audiences") or [] if isinstance(a.get("lift"), (int, float)) and not a.get("flat")]


def _thin(ev: dict, info: list[dict], taste: dict) -> str:
    rows = [a for a in ev.get("audiences") or [] if isinstance(a.get("lift"), (int, float))]
    flat = f"; Qloo's audience signal moved all {len(rows)} scored segments alike (lift {rows[0]['lift']:+.4f}), so none counts"         if rows and all(a.get("flat") for a in rows) else ""
    return (f"audience too thin: {len(info)} audience segments separated by Qloo (needs {RULES['min_scored_segments']})" + flat
            + ("" if ev.get("who") else "; no demographic signal") + ("" if taste else "; no products near this taste"))


def decide(ev: dict, live: bool, idea: str = "") -> dict:
    """The decision, by code. `live` is False when an essential input is not real Qloo data: then nothing opens."""
    none = {"target_units": None, "reserve_units": None}
    if not live:
        return {"verdict": "CANNOT_DECIDE", "reasons": [NO_EVIDENCE], **none}
    if not ev["matches"] and not ev.get("tags"):
        why = (f"{NOTHING_CLOSE} {', '.join(ev['words'][:6])}" if ev["words"] else f"{NOTHING_CLOSE} these words (no content words)")
        if ev.get("unrelated"):
            why += f"; Qloo's nearest results share too few of its content words: {', '.join(u['name'] for u in ev['unrelated'][:3])}"
        return {"verdict": "REFUSE", "reasons": [why], **none}
    if not ev["matches"]:
        return _decide_new(ev)
    reasons = []
    lead, vs = ev["leader"], ev["versus"]
    c = _clone(idea, lead, ev["words"])
    if c:
        reasons.append(c)
    elif vs is None and lead and (lead.get("popularity") or 0) >= RULES["unknown_leader_popularity"]:
        reasons.append(f"{OWNED}: no comparison with {lead['name']} was possible and it is very popular "
                       f"({lead['popularity']:.2f} >= {RULES['unknown_leader_popularity']})")
    elif vs is None:
        reasons.append("no leader comparison possible: Qloo has too little on this space to show room next to "
                       f"{lead['name'] if lead else 'a leader'}")
    elif vs["overlap"] >= RULES["served_overlap"]:
        reasons.append(f"{SERVED}: {lead['name']} shares {vs['overlap']:.0%} of this taste ({vs['method']}, "
                       f">= {RULES['served_overlap']:.0%}), whatever its popularity")
    elif vs["overlap"] >= RULES["owned_overlap"] and (lead.get("popularity") or 0) >= RULES["owned_popularity"]:
        reasons.append(f"{OWNED}: {lead['name']} (popularity {lead['popularity']:.2f}) shares {vs['overlap']:.0%} "
                       f"({vs['method']}, >= {RULES['owned_overlap']:.0%})")
    info = _scored(ev)
    taste = ev.get("taste") or {}
    if len(info) < RULES["min_scored_segments"] or not ev["who"] or not taste:
        reasons.append(_thin(ev, info, taste))
    factor_a = 1.0
    for na in ev["named_audience"]:
        v = ((ev["who"] or {}).get(na["dimension"]) or {}).get(na["key"])
        if isinstance(v, (int, float)) and v <= RULES["contradiction"]:
            reasons.append(f"Qloo contradicts the stated audience: '{na['word']}' ({na['key'].replace('_', ' ')}) scores {v:+.2f} "
                           f"(<= {RULES['contradiction']})")
        elif isinstance(v, (int, float)) and v < 0:
            factor_a = 0.5
    t = ev["trend"] or {}
    if t.get("direction") == "falling":
        reasons.append(f"falling trend: {t['entity']} percentile {t['start_percentile']} -> {t['end_percentile']} "
                       f"(data through {t['data_through']})")
    if reasons:
        return {"verdict": "REFUSE", "reasons": reasons, **none}
    overlap = vs["overlap"]
    strength = round(max(0.0, min(1.0, (taste["mean_affinity"] - NEUTRAL) * 2)), 4)
    factor_t = 1.25 if t.get("direction") == "rising" else 1.0
    bg, rec = ev.get("buyer_group"), ev.get("recommended")
    factor_g = (RULES["group_confirmed"] if bg["status"] == "confirmed" else RULES["group_refuted"]) if bg else 1.0
    factor_r = 1.0
    if rec is not None:
        factor_r = RULES["adjacent_many_factor"] if rec["strong"] >= RULES["adjacent_many"] else RULES["adjacent_few_factor"] if rec["strong"] <= RULES["adjacent_few"] else 1.0
    factor_a = round(factor_a * factor_g * factor_r, 4)
    raw = RULES["base_units"] * (1 + 2 * strength) * (1 - overlap / 2) * factor_a * factor_t
    target = int(min(1000, max(20, round(raw / 10) * 10)))
    reserve = int(math.ceil(round(target * (0.3 + 0.2 * overlap), 6)))
    why = [f"{len(ev['matches'])} Qloo products match the idea's words ({', '.join(ev['matches'][0]['matched_words'][:4])})",
           f"audience: {len(info)} segments scored, highest lift {info[0]['name']} {info[0]['lift']:+.4f}; taste strength "
           f"{strength:.2f} (mean affinity {taste['mean_affinity']:.3f} of the {taste['products']} products nearest it)",
           f"vs {vs['leader']}: overlap {overlap:.0%} ({vs['method']}); room: {', '.join(vs['whitespace'][:3]) or 'none named'}",
           (f"trend: {t.get('direction')} (data through {t.get('data_through')})" if t.get("counted") else f"trend: {t.get('why') or TREND_NOTE}")]
    if any(isinstance(((ev["who"] or {}).get(na["dimension"]) or {}).get(na["key"]), (int, float)) and
           ((ev["who"] or {}).get(na["dimension"]) or {}).get(na["key"]) < 0 for na in ev["named_audience"]):
        why.append("the stated audience leans mildly away in Qloo's demographics: target halved")
    if bg:
        why.append(f"buyer group '{bg['segment']}' (/v2/audiences) {bg['status']} by its lift on this taste"
                   + (f" (rank {bg['rank']} of {bg['of']} scored, lift {bg['lift']:+.4f})" if bg.get("rank") else " (no lift read)")
                   + f": target x {factor_g}")
    if rec is not None and factor_r != 1.0:
        why.append(f"recommendations: {rec['strong']} strong adjacent products ({', '.join(rec['adjacent'][:3]) or 'none'}): target x {factor_r}")
    return {"verdict": "OPEN", "reasons": why, "target_units": target, "reserve_units": reserve,
            "formula": f"round10({RULES['base_units']} x (1 + 2 x {strength:.3f}) x (1 - {overlap:.3f}/2) x {factor_a} x {factor_t}) = {target}; "
                       f"reserve ceil({target} x (0.3 + 0.2 x {overlap:.3f})) = {reserve}"}


def _decide_new(ev: dict) -> dict:
    """A new idea (no existing product, N1): OPEN on its own taste when Qloo ties products or places to its tags, scores
    at least min_scored_segments audience segments live and answers its demographics; else not yet, with what is
    missing. No leader to compare against, so the overlap is 0 and the reserve its floor."""
    none = {"target_units": None, "reserve_units": None}
    ta, taste = ev.get("taste_answer") or {}, ev.get("taste") or {}
    info = _scored(ev)
    tags = ", ".join(str(t["name"]) for t in (ta.get("tags") or ev.get("tags") or [])[:3])
    reasons = []
    if not ta.get("items"):
        reasons.append(f"Qloo ties no {str(ta.get('kind') or 'product').split(':')[-1]}s to its taste tags ({tags}) yet")
    if len(info) < RULES["min_scored_segments"] or not ev.get("who") or not taste:
        reasons.append(_thin(ev, info, taste))
    if reasons:
        return {"verdict": "REFUSE", "reasons": [f"a new idea, read through its taste tags ({tags})"] + reasons, **none}
    strength = round(max(0.0, min(1.0, (taste["mean_affinity"] - NEUTRAL) * 2)), 4)
    bg = ev.get("buyer_group")
    factor_g = (RULES["group_confirmed"] if bg["status"] == "confirmed" else RULES["group_refuted"]) if bg else 1.0
    raw = RULES["base_units"] * (1 + 2 * strength) * factor_g
    target = int(min(1000, max(20, round(raw / 10) * 10)))
    reserve = int(math.ceil(round(target * 0.3, 6)))
    why = [f"a new idea: no existing product in Qloo yet, answered from its taste tags ({tags}): "
           f"{', '.join(str(x['name']) for x in ta['items'][:3])}",
           f"audience: {len(info)} segments scored, highest lift {info[0]['name']} {info[0]['lift']:+.4f}; taste strength "
           f"{strength:.2f} (mean affinity {taste['mean_affinity']:.3f} of the {taste['products']} products nearest it)",
           "no leader to compare against: overlap 0"]
    if bg:
        why.append(f"buyer group '{bg['segment']}' (/v2/audiences) {bg['status']} by its lift on this taste: target x {factor_g}")
    return {"verdict": "OPEN", "reasons": why, "target_units": target, "reserve_units": reserve, "new_idea": True,
            "formula": f"round10({RULES['base_units']} x (1 + 2 x {strength:.3f}) x {factor_g}) = {target}; reserve ceil({target} x 0.3) = {reserve}"}


def report_hash(rep: dict) -> str:
    keep = {k: v for k, v in rep.items() if k not in ("hash", "calls", "made", "fees")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()


ESSENTIAL = ("closest existing products", "who:")    # a refused audience call is missing evidence, not counted (sweep 22 s4)


PREMIUM = ("Gourmand Fine Dining", "Boutique Hotels", "High Fashion", "Watch Collecting", "Art Collectibles", "Angel Start Up Investing",
           "Wine Enthusiast", "Real Estate")
BUDGET = ("Discount Shoppers",)
TIERS = {"budget": 1, "mid": 2, "premium": 4}       # test units per pre-ordered unit (devnet test money; a scale, not a price)


def price_tier(spending: list[dict], venue_levels: list | None = None) -> dict | None:
    """The price tier from Qloo's spending-habit segments scored the same way as the audience (_segments: their lift on
    this taste): a premium segment's lift minus Discount Shoppers'. Above +price_lift -> premium, below -price_lift ->
    budget, else mid. Without both lifts, the places' median price_level (1-4) decides: 3-4 premium, 1 budget, 2 mid.
    The tier sets the pre-order's unit price in test units (TIERS)."""
    lv = sorted(v for v in (venue_levels or []) if isinstance(v, (int, float)))
    venue = lv[len(lv) // 2] if lv else None            # the venues' median price_level (1-4), the price cross-check
    prem = [s for s in spending if s.get("premium") and isinstance(s.get("lift"), (int, float))]
    budg = [s for s in spending if not s.get("premium") and isinstance(s.get("lift"), (int, float))]
    if prem and budg:
        score = round(prem[0]["lift"] - budg[0]["lift"], 4)
        tier = "premium" if score > RULES["price_lift"] else "budget" if score < -RULES["price_lift"] else "mid"
        how, src = f"spending-habit segments: {prem[0]['name']} minus {budg[0]['name']} lift", prem[0].get("src")
    elif venue is not None:
        score, tier, how, src = None, "premium" if venue >= 3 else "budget" if venue <= 1 else "mid", "the places' median price level", None
    else:
        return None
    return {"tier": tier, "unit_price": TIERS[tier], "score": score, "from": how, "segments_seen": [s["name"] for s in prem + budg],
            "venue_price_level": venue, "venue_check": (None if venue is None or score is None else
            "agrees" if (venue >= 3) == (tier == "premium") or venue == 2 else "differs"), "src": src}


EFFECTS = (("closest existing products", "relevance gate and the market leader"), ("the named market leader", "the leader to compare against"),
           ("details of", "popularity of the leader (owned-space rule)"), ("taste tags", "the idea's taste tags (shown, not counted)"),
           ("who:", "sets WHO: the age and gender to target; checks a named audience"),
           ("where: named places", "sets WHERE: named places in the launch area"), ("where: map points", "sets WHERE: map hot spots"),
           ("audience segments", "WHO BUYS: the audience gate (3 segments scored live), the taste strength and the PRICE TIER (spending-habit segments)"),
           ("the named buyer group", "confirms or refutes the buyer group named after 'for': target x1.2 / x0.6"),
           ("launch cities", "sets WHERE: the launch cities"), ("recommendations", "adjacent demand: target x1.2 / x0.8; the brand ladder"),
           ("weekly trend", "rising or falling (not counted when Qloo's series does not move)"),
           ("the idea's other matches vs the leader", "overlap with the leader: owned/served gates, the reserve, the unserved audience"),
           ("the leader's", "overlap with the leader (audience method): owned/served gates, the reserve, the unserved audience"))


def annotate(rep: dict) -> None:
    for c in rep.get("calls") or []:
        c["effect"] = next((e for k, e in EFFECTS if c["what"].startswith(k)), "evidence")
        c["out"] = c.get("error") or c.get("body_digest") or ""


CHECKS_AT_ONCE = 3               # demand checks run at the same time; the next waits (each holds its Qloo answers)
_checks = threading.BoundedSemaphore(CHECKS_AT_ONCE)
running = [0]
_running_lock = threading.Lock()


def demand_check(idea: str, place: str | None = None, leader: str | None = None, client: Client | None = None,
                 today: dt.date | None = None, exclude: list[str] | None = None, on_call=None, options: dict | None = None,
                 stage: str | None = None, only_cache: str | None = None) -> dict:
    """One demand check (_demand_check), CHECKS_AT_ONCE at a time: six at once ran the free instance (512 MB) out of
    memory in champion runs of 24 Oct 2026; the seventh visitor waits seconds instead of every visitor getting a 502.
    Each check sees the shared client through its own CheckBudget (qloo_rest.PER_CHECK live calls at most);
    `only_cache` (a reason, e.g. the visitor's hourly cap) answers it from the private cache only."""
    from .qloo_rest import CheckBudget
    budget = client if isinstance(client, CheckBudget) else CheckBudget(client or Client(), only_cache=only_cache)
    with _checks:
        with _running_lock:
            running[0] += 1
        try:
            rep = _demand_check(idea, place, leader, budget, today, exclude, on_call, options, stage)
            rep["qloo_request"] = {"req": budget.req, "sent": budget.sent, **({"cache_only": only_cache} if only_cache else {})}
            if stage != "verdict":                    # the verdict card and its full card are one check
                from . import usage
                usage.bump(checks=1, briefs=1 if rep.get("brief") else 0)
            return rep
        finally:
            with _running_lock:
                running[0] -= 1


def _demand_check(idea: str, place: str | None = None, leader: str | None = None, client: Client | None = None,
                  today: dt.date | None = None, exclude: list[str] | None = None, on_call=None, options: dict | None = None,
                  stage: str | None = None) -> dict:
    """stage "verdict": only what the verdict card shows (verdict, matched product, audience), as soon as it is ready;
    the questions for the map, also-loved and the launch are already sent, and the full check reads their answers."""
    verdict_only = stage == "verdict"
    from knos import qloo_families

    from . import families
    opts = qloo_families.options(options)          # the families' options (knos.qloo_families): refused when unknown or malformed
    idea = " ".join(str(idea or "").split())
    if not 8 <= len(idea) <= 500:
        raise ValueError("describe the idea in 8 to 500 characters")
    place = (" ".join(str(place).split())[:60] or None) if place else None
    leader = (" ".join(str(leader).split())[:80] or None) if leader else None
    client = client or Client()
    today = today or dt.datetime.now(dt.timezone.utc).date()
    run = _Run(client, on_call)
    run.deadline = time.monotonic() + CHECK_BUDGET_S if CHECK_BUDGET_S else None
    ok, why = client.ready()
    empty = {"product_type": None, "words": content_words(idea, place), "matches": [], "unrelated": [], "excluded": [], "leader": None,
             "tags": [], "who": None, "where": [], "places": [], "audiences": [], "who_wants": [], "also_love": None, "launch": None, "trend": None, "versus": None, "named_audience": [], "buyer_group": None, "recommended": None, "cities": [], "price": None, "persona": [], "persona_all": [], "ladder": [], "tag_families": []}
    ev = gather(run, idea, place, leader, today, set(exclude or []), verdict_only) if ok else empty
    if ok and opts and not verdict_only:                                # F1-F8: each asked-for family's own calls, numbered with the rest
        ev["families"] = families.answer(run, ev, idea, place, opts)
    failed = [c for c in run.calls if c.get("error") and c["what"].startswith(ESSENTIAL)]
    missing = [c for c in run.calls if c.get("error") and c not in failed]
    live = ok and bool(run.calls) and not failed
    if ok and not run.calls:      # no content word: nothing to ask Qloo; that is a refusal, not missing evidence
        live = True
    decision = decide(ev, live, idea)
    if not ok:
        decision["reasons"].append(why)
    elif failed and "HTTP 429" in str(failed[0].get("error") or ""):      # Qloo's limit: one plain sentence, the whole reason
        from . import qloo_status
        decision["reasons"] = [qloo_status.limit_line() or "Qloo is limiting requests right now (HTTP 429), so it has not answered this idea."]
    elif failed:
        decision["reasons"].append(f"{failed[0]['what']}: {failed[0]['error']}")
    for c in missing:
        if "HTTP 429" not in str(c.get("error") or ""):
            decision["reasons"].append(f"missing evidence (not counted): {c['what']}: {c['error']}")
    good = [c for c in run.calls if not c.get("error")]
    label = (LIVE_LABEL + ("; partial: some calls failed" if failed or missing else "")) if good else "NO QLOO EVIDENCE"
    limits = ("Qloo states no prices, no market sizes, no B2B and no medical demand; the only price signals are venue "
              "price levels (1-4) and spending-habit segments. Pre-orders and per-use payments are how willingness to pay is proven here.")
    rep = {"v": V, "kind": KIND, "limits": limits, "idea": idea, "place": place, "leader_named": leader, "label": label,
           "framing": FRAMING, "aggregate": AGGREGATE, **ev, "decision": decision, "rules": RULES, "calls": run.calls,
           "made": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "day": today.isoformat()}
    d = rep["decision"]
    if d.get("verdict") == "OPEN":            # Qloo's evidence SETS the campaign: who, where, the price, the target and the reserve
        pr = ev.get("price") or {"tier": "mid", "unit_price": TIERS["mid"]}
        vs = ev.get("versus") or {}
        d["plan"] = {"who": {"age": (ev.get("who") or {}).get("top_age"), "gender": (ev.get("who") or {}).get("top_gender"),
                             "segments": [a["name"] for a in (ev.get("audiences") or []) if a.get("tied")][:4]
                                         or [a["name"] for a in (ev.get("audiences") or [])][:3]},
                     "where": [c["name"] + (f" ({c['country']})" if c.get("country") else "") for c in ev.get("cities") or []][:4],
                     "tier": pr["tier"], "unit_price": pr["unit_price"], "target_units": d["target_units"], "reserve_units": d["reserve_units"],
                     "escrow_target": d["target_units"] * pr["unit_price"], "escrow_reserve": d["reserve_units"] * pr["unit_price"],
                     "unserved_audience": vs.get("whitespace", [])[:5],
                     "persona": [x["name"] for x in ev.get("persona") or []][:6],
                     "ladder": [{k: r[k] for k in ("name", "affinity", "popularity")} for r in ev.get("ladder") or []][:6],
                     "venue_price_level": pr.get("venue_price_level"), "venue_check": pr.get("venue_check")}
    from . import metros                           # Qloo sets the money terms: launch city, pre-order target, refund rule
    cells = ev.get("where") or (ev.get("launch") or {}).get("where") or []
    if ok and not verdict_only and (not cells or metros.flat(cells)) and ev.get("tags"):    # no map: asked once more, by the top matched tag
        cells = _tag_map(run, ev["tags"][0]["id"], place)
        ev["where_by_tag"] = {"tag": ev["tags"][0]["name"], "cells": len(cells)}
    matched = bool(rep.get("matches"))             # no product matched: nothing to launch, so no city and no map line
    rep["terms"] = None if verdict_only or not matched else metros.terms(cells)
    rep["no_map"] = None if rep["terms"] or verdict_only or not matched else metros.NO_MAP
    rep["brief"] = metros.brief(idea, rep["terms"], [x["name"] for x in ev.get("persona") or [] if x.get("name")]) if rep["terms"] else None
    rep["stage"] = "verdict" if verdict_only else "full"
    rep["options"] = opts
    rep["grounding"] = families.grounding(rep)
    annotate(rep)
    rep["hash"] = report_hash(rep)
    return rep
