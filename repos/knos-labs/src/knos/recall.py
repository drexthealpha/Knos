"""No-LLM conversational recall on top of the public sibyl_memory_client API.

    index(client, sessions)            store past chat sessions as Sibyl entities
    index_turn(client, ...)            store one turn (Knos's session reader: answer.point)
    retrieve(client, question, k=10)   -> list of entity bodies (dicts), best first

Used by the MCP `search` tool, `knos.sdk.Knos.recall`, and the reference worker's memory of its own past jobs.
LongMemEval_s, held-out 370 questions: 96.8% top-10 (docs/BENCH.md).

`sessions` is an iterable of dicts {"id": str, "date": str, "turns": [{"role", "content"}, ...]}.
Every returned body has "session", "date", "text".

Index (write time, deterministic):
  * category "round": one entity per user message + the assistant reply that follows it
    (body: session, date, text) -- the same row as the 0.3.1 baseline.
  * category "pref":  the sentences of a user message that state a preference / habit /
    plan / possession ("I prefer", "I love", "I've been", "my favourite", ...). Small.
  Separate user-turn entities were tried and dropped: they push a 115k-token history past
  the 5 MB free-tier store cap. The user-only signal is computed at read time instead.

Retrieve (read time, no LLM, deterministic):
  1. Content terms of the question (stopwords + conversational filler removed).
  2. OR-of-terms: one single-term Sibyl FTS5 search per term (porter-stemmed index = the
     inverted index; hit count = document frequency). From the returned round bodies three
     BM25 rankings are computed: whole round, user part only, assistant part only.
  3. Sibyl's own search(question) ranking (the baseline) is fused in.
  4. Advice / recommendation questions also rank the "pref" rows.
  5. Channels are fused by weighted reciprocal rank at SESSION level; the k slots go to k
     different past sessions (best row of each), so one long session cannot fill the list.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter

# ----------------------------------------------------------------------------- tunables
CFG = {
    "w_round": 1.0,      # OR-BM25 over whole round text
    "w_user": 1.5,       # OR-BM25 over the user part of the round
    "w_asst": 0.0,       # OR-BM25 over the assistant part of the round
    "w_native": 0.5,     # Sibyl native search(question)
    "w_pref": 1.0,       # pref rows (advice questions only)
    "w_pref_all": 0.0,   # pref rows on every question
    "rrf_k": 60.0,
    "per_session": 1,    # max rows returned per session
    "k1": 1.2, "b": 0.75,
    "max_terms": 16,
    "native_limit": 50,
    "pool": 200,
    "pref_slots": 0,     # slots reserved for top pref-channel sessions on advice questions
    "bigram_bonus": 0.0,
    "filler": True,
    "agg": "rrf",        # rrf | max
}

_WORD = re.compile(r"[a-z0-9]+")

STOP = frozenset("""
a about above after again against all also am an and any are aren as at be because been before
being below between both but by can cannot could couldn did didn do does doesn doing don down during
each few for from further had hadn has hasn have haven having he her here hers herself him himself his
how i if in into is isn it its itself just let ll me more most mustn my myself no nor not now of off on
once only or other ought our ours ourselves out over own re same shan she should shouldn so some such
than that the their theirs them themselves then there these they this those through to too under until
up ve very was wasn we were weren what when where which while who whom why will with won would wouldn
you your yours yourself yourselves s t d m o y ain ma
""".split())
# Conversational filler of "remind me what we discussed" questions: matches everywhere.
FILLER = frozenset("""
remind remember recall previous previously earlier last conversation conversations chat chats talked
talk discussed discussion mentioned mention told tell said say asked ask wondering wonder wanted want
going back looking follow following confirm sure thing things know think thought get got
please thanks thank help would also again something someone way lot really actually
specifically exactly kind sort us can could currently recently just
""".split())

ADVICE = re.compile(
    r"\b(suggest|suggestions?|recommend|recommendations?|tips?|advice|ideas?|any (good|other)|"
    r"what should|should i|thinking of|thinking about|help me|can you (give|find|share)|"
    r"looking for|what (are|is) (some|a good)|how can i|how do i|what (can|could) i|worth|"
    r"good idea|anything|planning|plan)\b", re.I)

PREF_PAT = re.compile(
    r"\b(i (really |absolutely |usually |always |often |generally |mostly |also |still |do |"
    r"especially |particularly |definitely |recently |just )?(prefer|like|love|enjoy|hate|dislike|"
    r"adore|can't stand|am into|am interested|am a fan|am trying|am looking|have been|started|"
    r"usually|always|never|tend to|want to|plan to|am planning|am thinking|used to|got|bought|made|"
    r"tried|use|own|have|had|went|visited|am|was)|i'(m|ve|d)|"
    r"my (favou?rite|go-to|usual|own|current|new|old|previous|last|first|recent))\b", re.I)

_SENT = re.compile(r"(?<=[.!?])\s+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


_STEMS: dict = {}


def _stem(t: str) -> str:
    s = _STEMS.get(t)
    if s is None:
        if len(_STEMS) > 200000:
            _STEMS.clear()
        s = _STEMS[t] = _stem_raw(t)
    return s


def _stem_raw(t: str) -> str:
    """Crude suffix strip, used only to count term frequency inside bodies that Sibyl's
    porter-stemmed FTS5 index already matched."""
    for suf in ("ational", "ization", "fulness", "iveness", "ations", "ation", "ments", "ment",
                "ings", "ing", "ies", "ied", "edly", "ed", "ers", "er", "ly", "es", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def query_terms(question: str) -> list[str]:
    toks = _tokens(question)
    drop = STOP | FILLER if CFG["filler"] else STOP
    out = [t for t in dict.fromkeys(toks) if t not in drop and len(t) > 1]
    if not out:
        out = [t for t in dict.fromkeys(toks) if t not in STOP] or list(dict.fromkeys(toks))
    return out[: CFG["max_terms"]]


# ----------------------------------------------------------------------------- index
def pref_text(user_msg: str) -> str:
    sents = [s.strip() for s in _SENT.split(user_msg) if s.strip()]
    return " ".join(s for s in sents if PREF_PAT.search(s))[:1200]


def index(client, sessions) -> int:
    """Store sessions as Sibyl entities. Returns the number of entities written."""
    n = 0
    for s in sessions:
        sid, date, turns = s["id"], s.get("date", ""), s["turns"]
        i = r = 0
        while i < len(turns):
            turn = turns[i]
            nxt = turns[i + 1] if i + 1 < len(turns) and turns[i + 1]["role"] == "assistant" else None
            text = f"[{date}] {turn['role']}: {turn['content']}" + (f"\nassistant: {nxt['content']}" if nxt else "")
            client.set_entity("round", f"{sid}#{r}", {"session": sid, "date": date, "text": text}); n += 1
            if turn["role"] == "user":
                p = pref_text(turn["content"])
                if p:
                    client.set_entity("pref", f"{sid}#{r}", {"session": sid, "date": date,
                                                             "text": f"[{date}] user: {p}"}); n += 1
            r += 1
            i += 2 if nxt else 1
    return n


def index_turn(client, session: str, n: int, date: str, role: str, text: str, where: str = "") -> int:
    """Store one thing said in a session (what Knos's session reader yields) as a round, plus its preference sentences
    when a person said it. Upserted by name, so reading the same turn again writes nothing new."""
    body = {"session": session, "date": date, "text": f"[{date}] {role}: {text}", "where": where}
    client.set_entity("round", f"{session}#{n}", body)
    wrote = 1
    if role == "user":
        p = pref_text(text)
        if p:
            client.set_entity("pref", f"{session}#{n}", {**body, "text": f"[{date}] user: {p}"})
            wrote += 1
    return wrote


# ----------------------------------------------------------------------------- retrieve
def _body(row):
    b = row.get("body") if isinstance(row, dict) else None
    if isinstance(b, str):
        try:
            b = json.loads(b)
        except Exception:
            b = {}
    return b if isinstance(b, dict) else {}


def _split_round(text):
    i = text.find("\nassistant: ")
    return (text, "") if i < 0 else (text[:i], text[i:])


def _hits(client, terms, category):
    """name -> {"body", "parts": {field: stemmed tokens}} for rows containing any term."""
    hits, rows_by_term = {}, {}
    for t in terms:
        rows = client.search_entities(t, limit=10000, category=category)
        rows_by_term[t] = [r.get("name") for r in rows]
        for row in rows:
            name = row.get("name")
            if name in hits:
                continue
            body = _body(row)
            u, a = _split_round(body.get("text", ""))
            pu = [_stem(x) for x in _tokens(u)]
            pa = [_stem(x) for x in _tokens(a)]
            cu, ca = Counter(pu), Counter(pa)
            hits[name] = {"body": body, "seq": pu + pa, "matched": set(),
                          "parts": {"user": (cu, len(pu)), "asst": (ca, len(pa)),
                                    "all": (cu + ca, len(pu) + len(pa))}}
    for t, names in rows_by_term.items():
        for n in names:
            hits[n]["matched"].add(t)
    return hits, rows_by_term


def _bm25(hits, terms, field, n_docs):
    k1, b = CFG["k1"], CFG["b"]
    st = {t: _stem(t) for t in terms}
    tf = {}
    df = {t: 0 for t in terms}
    for name, h in hits.items():
        cnt = h["parts"][field][0]
        d = {}
        for t in terms:
            c = cnt.get(st[t], 0)
            if not c and field == "all" and t in h["matched"]:
                c = 1   # Sibyl's porter index matched it; the crude stem missed the form
            if c:
                d[t] = c
                df[t] += 1
        if d:
            tf[name] = d
    if not tf:
        return []
    N = max(n_docs, max(df.values()) + 1)
    lens = {n: max(1, hits[n]["parts"][field][1]) for n in hits}
    avgdl = sum(lens.values()) / len(lens)
    idf = {t: math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5)) for t in terms}
    pairs = [(st[terms[i]], st[terms[i + 1]]) for i in range(len(terms) - 1)]
    out = []
    for name, d in tf.items():
        dl = lens[name]
        s = sum(idf[t] * c * (k1 + 1) / (c + k1 * (1 - b + b * dl / avgdl)) for t, c in d.items())
        if CFG["bigram_bonus"] and len(d) > 1:
            toks = hits[name]["seq"]
            joined = " " + " ".join(toks) + " "
            for x, y in pairs:
                if f" {x} {y} " in joined:
                    s += CFG["bigram_bonus"]
        out.append((s, name))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out[: CFG["pool"]]


_ndocs = {}


def _count(client, category):
    key = (id(client), category)
    if key not in _ndocs:
        _ndocs[key] = len(client.list_entities(category=category, limit=10000))
    return _ndocs[key]


def retrieve(client, question: str, k: int = 10) -> list[dict]:
    terms = query_terms(question)
    rk = CFG["rrf_k"]
    fused = {}   # session -> {"score": float, "rows": [(score, body)]}

    def add(bodies, weight):
        for rank, body in enumerate(bodies):
            sid = body.get("session")
            if sid is None:
                continue
            sc = weight / (rk + rank + 1)
            e = fused.setdefault(sid, {"score": 0.0, "rows": [], "best": 0.0})
            e["score"] += sc
            e["best"] = max(e["best"], sc)
            e["rows"].append((sc, body))

    n_round = _count(client, "round")
    hits, _ = _hits(client, terms, "round")
    for field, w in (("all", CFG["w_round"]), ("user", CFG["w_user"]), ("asst", CFG["w_asst"])):
        if w:
            add([hits[n]["body"] for _, n in _bm25(hits, terms, field, n_round)], w)
    if CFG["w_native"]:
        add([_body(r) for r in client.search(question, limit=CFG["native_limit"])
             if r.get("category") in (None, "round")], CFG["w_native"])
    advice = bool(ADVICE.search(question))
    wp = CFG["w_pref_all"] + (CFG["w_pref"] if advice else 0.0)
    pref_sessions = []
    if wp:
        phits, _ = _hits(client, terms, "pref")
        prows = [phits[n]["body"] for _, n in _bm25(phits, terms, "all", _count(client, "pref"))]
        add(prows, wp)
        for b in prows:
            if b.get("session") not in pref_sessions:
                pref_sessions.append(b.get("session"))

    key = (lambda kv: -kv[1]["score"]) if CFG["agg"] == "rrf" else (lambda kv: (-kv[1]["best"], -kv[1]["score"]))
    order = [sid for sid, _ in sorted(fused.items(), key=key)]
    if advice and pref_sessions and CFG["pref_slots"]:
        head = order[: k - CFG["pref_slots"]]
        for sid in pref_sessions:
            if len(head) >= k:
                break
            if sid not in head:
                head.append(sid)
        order = head + [s for s in order if s not in head]

    out = []
    per = CFG["per_session"]
    for sid in order:
        seen, taken = set(), 0
        for _, body in sorted(fused[sid]["rows"], key=lambda x: -x[0]):
            t = body.get("text", "")
            if t in seen:
                continue
            seen.add(t)
            out.append({"session": body.get("session"), "date": body.get("date"), "text": t,
                        "where": body.get("where", "")})
            taken += 1
            if taken >= per or len(out) >= k:
                break
        if len(out) >= k:
            break
    if len(out) < k and per < k:   # fewer sessions than k: fill with extra rows
        have = {o["text"] for o in out}
        for sid in order:
            for _, body in sorted(fused[sid]["rows"], key=lambda x: -x[0]):
                if len(out) >= k:
                    break
                if body.get("text", "") not in have:
                    have.add(body.get("text", ""))
                    out.append({"session": body.get("session"), "date": body.get("date"), "text": body.get("text", ""),
                                "where": body.get("where", "")})
    return out[:k]
