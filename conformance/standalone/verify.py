#!/usr/bin/env python3
"""Check a Knos evidence archive with nothing but Python.

    python verify.py                  the folder this file is in (an unpacked archive)
    python verify.py ARCHIVE.zip      an archive, packed
    python verify.py FOLDER --strict  also fail on a note marked INCOMPLETE (a missing number) or UNSIGNED (a root or a log nobody signed)

This file is the whole verifier. It imports the Python standard library and nothing else, it opens no connection, and
it needs neither Knos, nor its website, nor a Solana node. Python 3.8 or later. It is written to be read: every check
is a few lines, in the order the report prints them.

What it checks again, from the archived bytes alone:
  1. every file is the one the manifest lists (SHA-256), and the evidence root is the root of those files;
  2. the log of events: every line canonical, every line's hash chained to the one before, every id the id of what
     the line says, a repeat counted once, no two claims under one id, every correction naming something;
  3. every acknowledgement in the log: the issuer's RS256 or ES256 signature against the archived keys, for exactly
     that head;
  4. the numbers each sender gave: a missing number is named, with the correction that explains it if one does;
  5. every month's statement of the log, made again from the log and compared byte for byte;
  6. every ledger: each evaluation's id, each batch's Merkle root (commitment formats 1 and 2), count, accepted
     count and value, the numbering of a month's batches, and the month's running hash;
  7. every signed token: its signature against the archived keys, and what it was signed for (a batch of an archived
     ledger, a file of the archive, a head of the log);
  8. every statement for accounts payable: its own hash, and every total from its lines;
  9. the terms: each file's bytes hash to the name it is kept under.

What it cannot check, and says so in its report: that the archived keys are the issuer's (compare their SHA-256 with a
copy another holder kept, or with the issuer's own document); that nothing was left out before the first archive was
made; what the chain holds (the report prints each running hash to compare with the chain's account). A receipt is
checked by hash; its judge's token is checked when the token itself is in the archive.

Exit code 0 when every check holds, 1 otherwise.
"""
import base64
import hashlib
import json
import os
import re
import sys
import zipfile

TYPE, VERSION = "knos.archive", 1
NOT_EVIDENCE = ("MANIFEST.json", "verify.py", "README.txt")       # what the evidence root does not cover
ZERO = "0" * 64
VERDICTS = ("accepted", "rejected", "insufficient_evidence", "disputed")
VERDICT_WORDS = {"accepted": "accepted", "rejected": "rejected", "insufficient_evidence": "insufficient evidence", "disputed": "disputed"}
LINE_STATES = ("agreed", "disputed", "duplicate", "insufficient_evidence")
KINDS = ("evaluation", "acceptance", "invoice_line", "settlement", "correction", "acknowledgement")
SOURCES = ("record", "batch", "settle", "shadow", "import")
COUNTED = KINDS[:4]
EVENT_KEYS = ["ack", "amount", "corrects", "deliverable", "evaluation", "evidence", "first", "id", "invoice_line", "kind", "month", "prev", "reason", "seq",
              "settlement", "source", "supplier", "unit", "verdict", "void"]
PREFIX = {"deliverable": "dlv", "evaluation": "evl", "invoice_line": "inv", "settlement": "stl"}
OWN = {"acceptance": "acc", "correction": "cor", "acknowledgement": "ack"}
HEX = set("0123456789abcdef")
PART = r"[A-Za-z0-9._-]{1,64}"
STREAM = r"(" + PART + ":" + PART + r":[0-9]{6})\.(0|[1-9][0-9]{0,18})"
SENT = re.compile(r"(?:batch|sent):" + STREAM + r"(?::.*)?", re.S)
GAP = re.compile(r"gap:" + STREAM)
JWT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def sha(*parts):
    return hashlib.sha256(b"".join(parts)).digest()


def hexsha(raw):
    return hashlib.sha256(raw).hexdigest()


def canon(obj):
    """The one way a line is written: keys sorted, no spaces, ASCII."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def evidence_root(listed):
    """The one hash two holders compare: SHA-256 of the canonical JSON of {name: sha256} over the evidence files."""
    return hexsha(canon({k: v for k, v in listed.items() if k not in NOT_EVIDENCE}).encode())


# -- ids ------------------------------------------------------------------------------------------------------------------
def tagged(tag, kind, parts, prefix):
    h = hashlib.sha256(tag + kind.encode() + b"\x00")
    for p in parts:
        b = str(p).encode("utf-8")
        h.update(len(b).to_bytes(4, "big") + b)
    return prefix + "_" + h.hexdigest()[:24]


def an_id(kind, *parts):
    return tagged(b"knos.id.v1\x00", kind, parts, PREFIX[kind])


def own_id(kind, *parts):
    return tagged(b"knos.event.v1\x00", kind, parts, OWN[kind])


def kind_of(text):
    head, _, tail = text.partition("_")
    for kind, prefix in PREFIX.items():
        if head == prefix and len(tail) == 24 and set(tail) <= HEX:
            return kind
    return None


# -- signatures -----------------------------------------------------------------------------------------------------------
SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")      # DigestInfo of SHA-256 (RFC 8017, 9.2)
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF      # the curve P-256 (FIPS 186-4, D.1.2.3)
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296, 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def rs256(signed, sig, n, e=65537):
    """RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017, 8.2.2): the signature to the power e is exactly the padded hash."""
    k = (n.bit_length() + 7) // 8
    if len(sig) != k or k < 11 + len(SHA256_INFO) + 32:
        return False
    want = b"\x00\x01" + b"\xff" * (k - 3 - len(SHA256_INFO) - 32) + b"\x00" + SHA256_INFO + hashlib.sha256(signed).digest()
    return pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big") == want


def inv(a, m):
    return pow(a, m - 2, m)                 # m is prime: Fermat. No negative exponent, so Python 3.7 reads it too.


def ec_add(a, b):
    if a is None or b is None:
        return a or b
    if a[0] == b[0] and (a[1] + b[1]) % P == 0:
        return None
    m = (3 * a[0] * a[0] - 3) * inv(2 * a[1], P) % P if a == b else (b[1] - a[1]) * inv(b[0] - a[0], P) % P
    x = (m * m - a[0] - b[0]) % P
    return x, (m * (a[0] - x) - a[1]) % P


def ec_mul(k, point):
    out = None
    while k:
        if k & 1:
            out = ec_add(out, point)
        point, k = ec_add(point, point), k >> 1
    return out


def es256(signed, sig, x, y):
    """ECDSA over P-256 with SHA-256 (FIPS 186-4, 6.4), the signature as r || s, 32 bytes each (RFC 7518, 3.4)."""
    if len(sig) != 64 or not (0 <= x < P and 0 <= y < P) or (y * y - (x * x * x - 3 * x + B)) % P:
        return False
    r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    if not (0 < r < N and 0 < s < N):
        return False
    w = inv(s, N)
    got = ec_add(ec_mul(int.from_bytes(hashlib.sha256(signed).digest(), "big") * w % N, G), ec_mul(r * w % N, (x, y)))
    return got is not None and got[0] % N == r


def read_token(token, jwks):
    """(header, claims, why not signed or None). The signature is checked against the archived keys with the token's
    key id and algorithm. A token's expiry is not held against it: an archive is read long after it."""
    token = token.strip()
    try:
        h64, c64, s64 = token.split(".")
        head, claims, sig = json.loads(unb64(h64)), json.loads(unb64(c64)), unb64(s64)
        assert isinstance(head, dict) and isinstance(claims, dict)
    except Exception:
        return {}, {}, "it is not a signed token (three parts, the first two JSON)"
    signed, alg, kid = (h64 + "." + c64).encode(), head.get("alg"), head.get("kid")
    keys = [k for k in jwks.get("keys", []) if isinstance(k, dict) and k.get("kid") == kid]
    if not keys:
        return head, claims, "no archived key has its key id %r" % (kid,)
    for k in keys:
        try:
            if alg == "RS256" and k.get("kty") == "RSA" and rs256(signed, sig, int.from_bytes(unb64(k["n"]), "big"), int.from_bytes(unb64(k["e"]), "big")):
                return head, claims, None
            if alg == "ES256" and k.get("kty") == "EC" and k.get("crv") == "P-256" and \
                    es256(signed, sig, int.from_bytes(unb64(k["x"]), "big"), int.from_bytes(unb64(k["y"]), "big")):
                return head, claims, None
        except Exception:
            continue
    if alg not in ("RS256", "ES256"):
        return head, claims, "its algorithm %r is not one this file checks (RS256, ES256)" % (alg,)
    return head, claims, "it does not carry the signature of the archived key %r: the token or the keys were changed" % (kid,)


# -- the log of events ----------------------------------------------------------------------------------------------------
def event_problem(o):
    """Why this object is not one event, or None. The id must be the id of what the event says it is."""
    if not isinstance(o, dict) or sorted(o) != EVENT_KEYS:
        return "an event has exactly these fields: " + ", ".join(EVENT_KEYS)
    text = ("corrects", "deliverable", "evaluation", "evidence", "id", "invoice_line", "kind", "prev", "reason", "settlement", "source", "supplier", "unit", "verdict")
    if not all(isinstance(o[k], str) for k in text) or o["void"] not in (0, 1) or isinstance(o["void"], bool):
        return "an event's fields are text, and void is 1 or 0"
    for k in ("amount", "first", "month", "seq"):
        if isinstance(o[k], bool) or not (isinstance(o[k], int) or (o[k] is None and k in ("amount", "first"))):
            return "an event's %s is a whole number" % k
    if o["kind"] not in KINDS or o["source"] not in SOURCES or (o["verdict"] and o["verdict"] not in VERDICTS):
        return "its kind, its source or its verdict is not one this format has"
    for name in PREFIX:
        if o[name] and kind_of(o[name]) != name:
            return "%r is not the id of a %s" % (o[name], name.replace("_", " "))
    if o["month"] and not (190001 <= o["month"] <= 999912 and 1 <= o["month"] % 100 <= 12):
        return "%s is not a month" % o["month"]
    if o["amount"] is not None and (not o["unit"] or o["amount"] < 0):
        return "an amount is a whole number, zero or more, and names its unit"
    kind, a = o["kind"], o["ack"]
    if kind != "correction" and (o["corrects"] or o["void"] or o["reason"]):
        return "only a correction names another event, voids one or gives a reason"
    if (kind == "acknowledgement") != (a is not None):
        return "an acknowledgement, and nothing else, carries a signed token"
    if kind == "evaluation" and (o["id"] != o["evaluation"] or not o["deliverable"] or not o["verdict"]):
        return "an evaluation's id is its evaluation id, and it names its deliverable and its verdict"
    if kind == "acceptance" and (not o["deliverable"] or o["id"] != own_id("acceptance", o["deliverable"]) or o["verdict"] != "accepted"):
        return "an acceptance names its deliverable, takes its id from it, and its verdict is accepted"
    if kind == "invoice_line" and o["id"] != o["invoice_line"]:
        return "an invoice line's id is its invoice line id"
    if kind == "settlement" and (o["id"] != o["settlement"] or not o["deliverable"] or o["amount"] is None):
        return "a settlement's id is its settlement id, and it names its deliverable and its amount"
    if kind == "correction":
        if not o["corrects"] or o["id"] != own_id("correction", o["corrects"], o["verdict"], "" if o["amount"] is None else o["amount"], o["unit"], o["void"], o["reason"]):
            return "a correction names what it corrects and takes its id from what it changes"
        if not (o["void"] or o["verdict"] or o["amount"] is not None):
            return "a correction says what changes: a verdict, an amount, or that the event is void"
        if o["corrects"].startswith("gap:") and not (GAP.fullmatch(o["corrects"]) and o["void"] and o["reason"].strip() and not o["verdict"] and o["amount"] is None):
            return "a correction of a missing number names it, is void, gives its reason and changes nothing else"
    if kind == "acknowledgement":
        if not isinstance(a, dict) or sorted(a) != ["head", "party", "token", "upto"] or not isinstance(a["token"], str) or not isinstance(a["head"], str) \
                or type(a["upto"]) is not int or type(a["party"]) is not int:
            return "an acknowledgement carries head, party, token and upto"
        if o["id"] != own_id("acknowledgement", a["party"], a["upto"], a["head"]):
            return "an acknowledgement takes its id from the party and the head it signed"
    return None


def stated(o):
    """What an event says, apart from how it came: two arrivals of one id must agree on this."""
    return (o["kind"], o["deliverable"], "" if o["kind"] == "acceptance" else o["evaluation"], o["invoice_line"], o["settlement"], o["verdict"], o["amount"],
            o["unit"], o["supplier"], o["corrects"], o["void"], o["reason"], canon(o["ack"]) if o["ack"] else "")


class Log:
    def __init__(self):
        self.events, self.hashes, self.first, self.fixes, self.acks = [], [], {}, {}, []
        self.by_deliverable, self.by_month = {}, {}

    @property
    def head(self):
        return self.hashes[-1] if self.hashes else ZERO

    def state(self, e):
        """(verdict, amount, unit, void) of a counted event after every correction that names it, in order."""
        verdict, amount, unit, void = e["verdict"], e["amount"], e["unit"], False
        for n in self.fixes.get(e["id"], ()):
            c = self.events[n]
            void, verdict = bool(c["void"]), c["verdict"] or verdict
            if c["amount"] is not None:
                amount, unit = c["amount"], c["unit"]
        return verdict, amount, unit, void

    def verdict_of(self, deliverable):
        said, amount, unit = set(), None, ""
        for n in self.by_deliverable.get(deliverable, ()):
            e = self.events[n]
            if e["first"] is not None or e["kind"] not in ("evaluation", "acceptance"):
                continue
            v, a, u, void = self.state(e)
            if void:
                continue
            if e["kind"] == "acceptance":
                return v, a, u
            said.add(v)
            if v == "accepted" and amount is None and a is not None:
                amount, unit = a, u
        for v in ("disputed", "accepted", "rejected"):
            if v in said:
                return v, (amount if v == "accepted" else None), (unit if v == "accepted" else "")
        return "insufficient_evidence", None, ""

    def acknowledged(self):
        out = {}
        for n in self.acks:
            a = self.events[n]["ack"]
            out[str(a["party"])] = max(out.get(str(a["party"]), -1), a["upto"])
        return out


def read_log(text, jwks, bad):
    """The log, read once from its first line. Everything wrong with it goes to `bad`, in words."""
    log = Log()
    for n, line in enumerate(x for x in text.split("\n") if x):
        try:
            o = json.loads(line)
        except ValueError:
            o = None
        why = event_problem(o)
        if why and (not isinstance(o, dict) or sorted(o) != EVENT_KEYS or why.startswith("an event's")):
            bad("the log, line %d: %s. Nothing after it was read." % (n, why))
            break
        if canon(o) != line:
            bad("the log, line %d is not written in the canonical form: it was edited." % n)
        if o["seq"] != n or o["prev"] != log.head:
            bad("the log, line %d does not follow the line before it: a line was removed, reordered or edited." % n)
        if why:
            bad("the log, line %d: %s." % (n, why))
        counted = log.first.get(o["id"])
        if o["first"] != counted:
            bad("the log, line %d names the wrong line as the one that counts for %s." % (n, o["id"]))
        elif counted is not None and stated(log.events[counted]) != stated(o):
            bad("the log, lines %d and %d carry the id %s and say different things." % (counted, n, o["id"]))
        if o["kind"] == "correction" and not why and not GAP.fullmatch(o["corrects"]) and \
                (o["corrects"] not in log.first or log.events[log.first[o["corrects"]]]["kind"] not in COUNTED):
            bad("the log, line %d corrects %s, which no earlier line is." % (n, o["corrects"]))
        if o["kind"] == "acknowledgement" and not why:
            a = o["ack"]
            _head, claims, unsigned = read_token(a["token"], jwks)
            p = str(claims.get("aud", "")).split(":")
            if unsigned:
                bad("the log, line %d: the acknowledgement's token: %s." % (n, unsigned))
            elif p != ["knosm", "ack", str(a["party"]), str(a["upto"]), a["head"]] or str(claims.get("repository_owner_id")) != str(a["party"]):
                bad("the log, line %d: the token was signed for another party or another head than the line says." % n)
            elif not 0 <= a["upto"] < n or log.hashes[a["upto"]] != a["head"]:
                bad("the log, line %d: owner %s acknowledged lines 0 to %s with a head that line no longer has: the acknowledged range was changed." % (n, a["party"], a["upto"]))
        log.events.append(o)
        log.hashes.append(hexsha(line.encode("utf-8")))
        log.first.setdefault(o["id"], n)
        if o["deliverable"]:
            log.by_deliverable.setdefault(o["deliverable"], []).append(n)
        if o["month"]:
            log.by_month.setdefault(o["month"], []).append(n)
        if o["first"] is None and o["kind"] == "correction":
            log.fixes.setdefault(o["corrects"], []).append(n)
        if o["first"] is None and o["kind"] == "acknowledgement" and not why:
            log.acks.append(n)
    return log


def gaps(log):
    """Every number a sender gave that is not in the log: (stream, number, the line that explains it or None, who
    acknowledged that line)."""
    seen, told = {}, {}
    for n, e in enumerate(log.events):
        m = SENT.fullmatch(e["evidence"]) if e["kind"] in COUNTED else None
        g = GAP.fullmatch(e["corrects"]) if e["kind"] == "correction" and e["first"] is None else None
        if m:
            seen.setdefault(m.group(1), set()).add(int(m.group(2)))
        elif g:
            told[(g.group(1), int(g.group(2)))] = n
            seen.setdefault(g.group(1), set())
    acked, out = log.acknowledged(), []
    for stream in sorted(seen):
        top = max(list(seen[stream]) + [k for s, k in told if s == stream] + [-1])
        for number in range(top + 1):
            if number not in seen[stream]:
                line = told.get((stream, number))
                out.append((stream, number, line, sorted(p for p, upto in acked.items() if line is not None and upto >= line)))
    return out


def log_statement(log, month):
    """One month of the log as `knos events statement` writes it: the same log gives the same bytes."""
    evals, lines, accepted, money, repeats, voided, fixes = {v: 0 for v in VERDICTS}, [], set(), {}, 0, 0, []

    def add(unit, what, amount):
        if amount is not None and unit:
            money.setdefault(unit, {k: 0 for k in ("billed",) + LINE_STATES + ("settled",)})[what] += amount

    for n in log.by_month.get(month, ()):
        e = log.events[n]
        if e["first"] is not None:
            repeats += 1
            continue
        if e["kind"] == "correction":
            fixes.append(n)
            continue
        if e["kind"] == "acknowledgement":
            continue
        verdict, amount, unit, void = log.state(e)
        if void:
            voided += 1
        elif e["kind"] == "evaluation":
            evals[verdict] += 1
        elif e["kind"] == "acceptance":
            if verdict == "accepted":
                accepted.add(e["deliverable"])
        elif e["kind"] == "settlement":
            add(unit, "settled", amount)
        else:
            dlv = e["deliverable"]
            earlier = next((k for k in log.by_deliverable.get(dlv, ()) if k < n and log.events[k]["kind"] == "invoice_line" and log.events[k]["first"] is None
                            and not log.state(log.events[k])[3]), None) if dlv else None
            state, why = "insufficient_evidence", "the line names no deliverable" if not dlv else "nothing accepted or rejected this deliverable"
            if earlier is not None:
                state, why = "duplicate", "line %d already bills this deliverable (%s)" % (earlier, log.events[earlier]["id"])
            elif dlv:
                v, agreed_amount, agreed_unit = log.verdict_of(dlv)
                if v == "accepted" and amount is not None and agreed_amount is not None and (amount, unit) != (agreed_amount, agreed_unit):
                    state, why = "disputed", "billed %s %s, accepted at %s %s" % (amount, unit, agreed_amount, agreed_unit)
                elif v == "accepted":
                    state, why = "agreed", ""
                elif v in ("rejected", "disputed"):
                    state, why = "disputed", "the deliverable is " + VERDICT_WORDS[v]
            add(unit, "billed", amount)
            add(unit, state, amount)
            lines.append({"amount": amount, "deliverable": dlv, "id": e["id"], "line": n, "state": state, "supplier": e["supplier"], "unit": unit, "why": why})
    acked = log.acknowledged()
    last = max(log.by_month.get(month, [-1]))
    st = {"type": "knos.events-statement", "version": 1, "month": month, "supplier": "", "head": log.head, "events": len(log.events), "evaluations": evals,
          "accepted_deliverables": len(accepted), "invoice_lines": lines, "line_states": {s: sum(1 for x in lines if x["state"] == s) for s in LINE_STATES},
          "amounts": dict(sorted(money.items())), "repeats_not_counted": repeats, "voided": voided, "corrections": fixes,
          "acknowledged": {"upto": dict(sorted(acked.items())), "covers_month": sorted(p for p, upto in acked.items() if upto >= last >= 0)}}
    st["sha256"] = hexsha(canon(st).encode())
    return st


# -- a ledger file --------------------------------------------------------------------------------------------------------
def split(n):
    return 1 << ((n - 1).bit_length() - 1)


def tree(hashes, node):
    """RFC 6962's shape: split at the largest power of two below the number of leaves."""
    if len(hashes) == 1:
        return hashes[0]
    k = split(len(hashes))
    return node(tree(hashes[:k], node), tree(hashes[k:], node))


def root1(ids, keys):
    """Commitment format 1: leaf = sha256(0x00 || evaluation id), node = sha256(0x01 || left || right), over the ids
    in ascending order, then one leaf sha256(0x02 || sha256(line)) for each correction line. No leaves: sha256 of nothing."""
    leaves = [sha(b"\x00", i) for i in sorted(set(ids))] + [sha(b"\x02", k) for k in sorted(set(keys))]
    return tree(leaves, lambda a, b: sha(b"\x01", a, b)) if leaves else sha()


def event_bytes(fields):
    """Commitment format 2: the canonical bytes of one evaluation. The tag, the format (2), the number of fields (18),
    then each field as its length (u32 big-endian) and its UTF-8 bytes."""
    out = [b"knos.event\x00", bytes([2, len(fields)])]
    for x in fields:
        raw = x.encode("utf-8")
        out += [len(raw).to_bytes(4, "big"), raw]
    return b"".join(out)


def root2(events, keys):
    """Commitment format 2: each leaf is the hash of the whole event, and the number of leaves is inside the root."""
    leaves = [sha(b"knos.leaf.2\x00", event_bytes(f)) for _i, f in sorted(events)] + [sha(b"knos.fix.2\x00", k) for k in sorted(set(keys))]
    top = tree(leaves, lambda a, b: sha(b"knos.node.2\x00", a, b)) if leaves else b""
    return sha(b"knos.root.2\x00", len(leaves).to_bytes(4, "big"), top)


def evaluation(o, month, seq):
    """(the 32-byte id, the 18 texts format 2 hashes, accepted, rate) of one ledger line, or raises ValueError."""
    order, artifact, policy, milestone, rate = o["order"], o["artifact"], o["policy"], o["milestone"], o["rate"]
    if not (isinstance(order, str) and len(order) == 64 and set(order) <= HEX and isinstance(policy, str) and len(policy) == 64 and set(policy) <= HEX
            and isinstance(artifact, str) and len(artifact) == 40 and set(artifact) <= HEX and o["accepted"] in (0, 1)
            and all(type(o[k]) is int and o[k] >= 0 for k in ("milestone", "rate", "buyer", "seller"))):
        raise ValueError("its fields are not an evaluation's")
    key = sha(bytes.fromhex(order), artifact.encode(), bytes.fromhex(policy), milestone.to_bytes(4, "little"))
    dlv = an_id("deliverable", order, milestone)
    evl = an_id("evaluation", dlv, artifact, policy, o.get("evaluator", ""), o.get("run", ""))
    stands = o.get("verdict") or ("accepted" if o["accepted"] else "rejected")
    if stands not in VERDICTS or (stands == "accepted") != bool(o["accepted"]):
        raise ValueError("its verdict and its accepted flag disagree")
    if o.get("id", key.hex()) != key.hex() or o.get("dlv", dlv) != dlv or o.get("evl", evl) != evl \
            or o.get("deliverable", sha(bytes.fromhex(order), milestone.to_bytes(4, "little")).hex()) != sha(bytes.fromhex(order), milestone.to_bytes(4, "little")).hex():
        raise ValueError("an id it carries is not the id of its own order, artifact, policy and milestone")
    fields = (dlv, evl, o.get("inv", ""), o.get("stl", ""), stands, str(rate), o.get("currency", ""), str(o["buyer"]), str(o["seller"]), order, str(milestone),
              policy, artifact, o.get("evidence", ""), o.get("evaluator", ""), o.get("run", ""), "%06d" % month, str(seq))
    return key, fields, bool(o["accepted"]), rate


def read_ledger(name, text, bad):
    """Every batch of a ledger file, recomputed from its lines: [(header, format 1 or 2, ok)]. Problems go to `bad`."""
    batches, cur, fixed = [], None, set()

    def finish(b):
        if b is None:
            return
        h, where = b["h"], "%s, batch %s of %s" % (name, b["h"]["seq"], b["h"]["month"])
        ids = [k for k, _f, _a, _r in b["evals"]]
        uniq = {k: (f, a, r) for k, f, a, r in b["evals"]}
        if len(uniq) != len(ids):
            bad("%s: an evaluation is written twice." % where)
        fmt = h.get("format", 1)
        root = (root1(uniq, b["keys"]) if fmt == 1 else root2([(k, v[0]) for k, v in uniq.items()], b["keys"])).hex()
        got = (len(uniq), sum(1 for v in uniq.values() if v[1]), sum(v[2] for v in uniq.values() if v[1]))
        if root != h["root"]:
            bad("%s: the lines give root %s in format %d, the header says %s: a line was changed, added or removed." % (where, root, fmt, h["root"]))
        if got != (h["count"], h["accepted"], h["value"]):
            bad("%s: the lines give count %d, accepted %d, value %d; the header says %s, %s, %s." % ((where,) + got + (h["count"], h["accepted"], h["value"])))
        if any((v[0][7], v[0][8]) != (str(h["buyer"]), str(h["seller"])) for v in uniq.values()):
            bad("%s: an evaluation is of another buyer or seller than the header's." % where)
        b["root2"] = root2([(k, v[0]) for k, v in uniq.items()], b["keys"]).hex()
        b["ids"] = set(uniq)
        batches.append(b)

    closed = False
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            o = json.loads(raw)
            assert isinstance(o, dict)
            if "batch" in o:
                h = o["batch"]
                assert all(type(h[k]) is int and h[k] >= 0 for k in ("accepted", "buyer", "count", "month", "seller", "seq", "value")) and h.get("format", 2) == 2
                assert isinstance(h["root"], str) and len(h["root"]) == 64 and set(h["root"]) <= HEX
                if "supersedes" in h:
                    old = [b for b in batches + ([cur] if cur else []) if "%s.%s:%s" % (b["h"]["month"], b["h"]["seq"], b["h"]["root"]) == h["supersedes"]]
                    finish(cur)
                    cur, closed = None, True
                    if len(old) != 1 or old[0].get("root2") != h["root"]:
                        bad("%s, line %d: the batch that supersedes %s does not commit to that batch's lines in format 2." % (name, n, h["supersedes"]))
                    continue
                finish(cur)
                cur, closed = {"h": h, "evals": [], "keys": [], "at": n}, False
                continue
            assert cur is not None and not closed
            if "correction" in o:
                if canon(o) != raw.strip():
                    bad("%s, line %d: a correction is not written in the canonical form." % (name, n))
                c = o["correction"]
                cur["keys"].append(sha(raw.strip().encode()))
                fixed.add((str(c.get("batch")), str(c.get("id"))))
                continue
            cur["evals"].append(evaluation(o, cur["h"]["month"], cur["h"]["seq"]))
        except Exception as why:
            bad("%s, line %d cannot be read as a ledger line (%s). Nothing after it was read." % (name, n, why or "it is not one"))
            break
    finish(cur)
    months, where = {}, {}
    for b in batches:
        months.setdefault(b["h"]["month"], []).append(b)
        for k in b["ids"]:
            where.setdefault(k, []).append("%s.%s" % (b["h"]["month"], b["h"]["seq"]))
    for k, at in sorted(where.items()):
        if len(at) > 1 and not any((x, k.hex()) in fixed for x in at):
            bad("%s: evaluation %s is in batches %s and no correction says which is the repeat: it is counted twice." % (name, k.hex(), ", ".join(at)))
    chains = {}
    for m, mine in sorted(months.items()):
        mine.sort(key=lambda b: b["h"]["seq"])
        if [b["h"]["seq"] for b in mine] != list(range(len(mine))):
            bad("%s, month %s: its batches are numbered %s, not 0 to %d: one is missing or repeated." % (name, m, [b["h"]["seq"] for b in mine], len(mine) - 1))
        chain = bytes(32)
        for b in mine:
            h = b["h"]
            chain = sha(chain, bytes.fromhex(h["root"]), *(int(h[k]).to_bytes(8, "little") for k in ("seq", "count", "accepted", "value")))
        chains[m] = chain.hex()
    return batches, chains


# -- a statement for accounts payable -------------------------------------------------------------------------------------
def units(amount, scale):
    if not amount:
        return 0
    whole, _, part = amount.lstrip("-").partition(".")
    return (-1 if amount.startswith("-") else 1) * int(whole + part.ljust(scale, "0")[:scale])


def amount_of(value, scale):
    whole, part = divmod(abs(value), 10 ** scale)
    text = ("%0*d" % (scale, part)).rstrip("0") if scale else ""
    return ("-" if value < 0 else "") + str(whole) + "." + text.ljust(2, "0")


def check_ap_statement(name, st, log_lines, bad):
    """A `knos-statement`: its own SHA-256 (of its canonical bytes with that field empty) and every total from its lines."""
    again = hexsha((json.dumps(dict(st, sha256=""), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8", "surrogatepass"))
    if again != st.get("sha256"):
        bad("%s: its sha256 is not its own: it was changed after it was made." % name)
    lines, scale = st.get("lines", []), st.get("scale", 2)
    priced = all(ln.get("amount") for ln in lines)
    want = {"billed": {"lines": len(lines), "amount": amount_of(sum(units(ln["amount"], scale) for ln in lines), scale) if priced else ""}}
    for state in LINE_STATES:
        mine = [ln for ln in lines if ln.get("state") == state]
        want[state] = {"lines": len(mine), "amount": amount_of(sum(units(ln["amount"], scale) for ln in mine), scale) if priced else ""}
    if st.get("totals") != want:
        bad("%s: its totals are not the totals of its lines (the lines give %s)." % (name, canon(want)))
    from_log = 0
    if st.get("source") == "events" and log_lines is not None:
        for ln in lines:
            if ln.get("evidence_sha256") not in log_lines:
                bad("%s, line %s: the event it rests on is not a line of the archived log." % (name, ln.get("line")))
            else:
                from_log += 1
    return len(lines), from_log


def check_meter_statement(name, st, ledger_ids, bad):
    """A `knos.meter-statement`: its counts add up, its fee is the fee of its count, and its lines are in an archived ledger."""
    if sum(st.get("verdicts", {}).values()) != st.get("evaluations") or st.get("evaluations") != len(st.get("lines", [])):
        bad("%s: its verdicts or its lines do not add up to its evaluations." % name)
    m = st.get("meter", {})
    if m.get("fee") != max(0, st.get("evaluations", 0) - m.get("free", 0)) * m.get("rate", 0):
        bad("%s: its fee is not (evaluations - free) x rate." % name)
    if sorted(x["ids"]["deliverable"] for x in st.get("lines", []) if x.get("billed")) != st.get("billed_deliverables"):
        bad("%s: its billed deliverables are not the ones its lines bill." % name)
    missing = [x["id"] for x in st.get("lines", []) if x.get("id") not in ledger_ids]
    if missing and ledger_ids:
        bad("%s: %d of its lines are in no archived ledger (first: %s)." % (name, len(missing), missing[0]))


# -- the whole archive ----------------------------------------------------------------------------------------------------
def check(files):
    """(what was checked, what is only noted, what does not hold): three lists of sentences, from the bytes alone.
    `files`: name -> bytes."""
    done, notes, problems = [], [], []
    bad = problems.append
    try:
        manifest = json.loads(files["MANIFEST.json"])
        listed = manifest["files"]
        assert manifest["type"] == TYPE and manifest["version"] == VERSION and isinstance(listed, dict)
    except Exception:
        return done, notes, ["This is not a Knos evidence archive, version 1: it has no MANIFEST.json of one."]
    for name in sorted(set(listed) | (set(files) - {"MANIFEST.json"})):
        if name not in files:
            bad("%s is listed in the manifest and is not in the archive." % name)
        elif name not in listed:
            bad("%s is in the archive and the manifest does not list it." % name)
        elif hexsha(files[name]) != listed[name]:
            bad("%s is not the file the manifest lists (its SHA-256 differs): it was changed after the archive was made." % name)
    if manifest.get("evidence_root") != evidence_root(listed):
        bad("The manifest's evidence root is not the root of the files it lists.")
    if problems:
        return done, notes, problems
    done.append("every file is the one the manifest lists (%d files); evidence root %s" % (len(listed), manifest["evidence_root"]))

    def text_of(name):
        return files[name].decode("utf-8")

    def json_of(name):
        try:
            return json.loads(text_of(name))
        except (ValueError, UnicodeDecodeError):
            bad("%s is not JSON." % name)
            return None

    jwks = json_of("keys/jwks.json") if "keys/jwks.json" in files else {"keys": []}
    jwks = jwks if isinstance(jwks, dict) else {"keys": []}
    keys = manifest.get("keys") or {}
    if "keys/jwks.json" in files:
        if keys.get("sha256") != listed["keys/jwks.json"]:
            bad("The manifest's record of the keys names another file than keys/jwks.json.")
        notes.append("the %d archived issuer keys (SHA-256 %s) were read on %s from %s: that they are the issuer's is not something this archive can show; "
                     "compare that hash with a copy another holder kept" % (len(jwks.get("keys", [])), listed["keys/jwks.json"], keys.get("read"), keys.get("from")))

    # the log of events, its acknowledgements, its numbers and its statements
    log, log_lines = None, None
    if "events/log.jsonl" in files:
        before = len(problems)
        log = read_log(text_of("events/log.jsonl"), jwks, bad)
        log_lines = set(log.hashes)
        if manifest.get("head") != log.head:
            bad("The log's head is %s and the manifest says %s: lines were removed from the end, or added." % (log.head, manifest.get("head")))
        if len(problems) == before:
            done.append("the log of events holds: %d lines, each chained to the one before, each id the id of what the line says; head %s" % (len(log.events), log.head))
            acked = log.acknowledged()
            if acked:
                done.append("acknowledged with the issuer's signature, checked against the archived keys: " +
                            ", ".join("owner %s up to line %d" % (p, n) for p, n in sorted(acked.items())))
            else:
                notes.append("UNSIGNED: nobody has acknowledged the log: until a second party signs a head, it is one party's file")
        missing = gaps(log)
        for stream, number, line, who in missing:
            if line is None:
                notes.append("INCOMPLETE: number %d of %s never arrived and nothing explains it" % (number, stream))
            elif not who:
                notes.append("INCOMPLETE: number %d of %s never arrived; line %d says why (%s) and nobody has acknowledged that line" % (number, stream, line, log.events[line]["reason"]))
            else:
                done.append("number %d of %s never arrived: line %d says why (%s), acknowledged by owner %s" % (number, stream, line, log.events[line]["reason"], ", ".join(who)))
        if not missing:
            done.append("no number a sender gave is missing below the highest that arrived (a sender's last numbers cannot be known from the log)")
        made = 0
        for month in sorted(log.by_month):
            name = "statements/events-%d.json" % month
            if files.get(name) != (canon(log_statement(log, month)) + "\n").encode():
                bad("%s is not the statement the log gives for that month: it is missing, or it or the log was changed." % name)
            made += 1
        if made and len(problems) == before:
            done.append("%d monthly statements of the log were made again from the log: the same bytes" % made)

    # the ledgers
    batches, ledger_ids = {}, set()
    for name in sorted(n for n in files if n.startswith("ledgers/")):
        before = len(problems)
        try:
            got, chains = read_ledger(name, text_of(name), bad)
        except UnicodeDecodeError:
            bad("%s is not text." % name)
            continue
        for b in got:
            h = b["h"]
            batches[(h["buyer"], h["seller"], h["month"], h["seq"], h["count"], h["accepted"], h["value"], h["root"])] = [name, False]
            ledger_ids |= {k.hex() for k in b["ids"]}
        if len(problems) == before:
            done.append("%s recomputes: %d batches, every evaluation id, root, count and value; running hash %s" % (
                name, len(got), "; ".join("%s: %s" % (m, c) for m, c in sorted(chains.items())) or "none"))
            notes.append("compare the running hash of %s with the chain's Ledger account for that buyer, seller and month: this file asks no chain" % name)

    # the signed tokens
    by_hash, signed_files = {v: k for k, v in listed.items()}, set()
    token_names = sorted(n for n in files if n.startswith("tokens/"))
    for name in token_names:
        token = files[name].decode("ascii", "replace").strip()
        if name != "tokens/%s.jwt" % hexsha(token.encode()):
            bad("%s is not kept under the SHA-256 of its token." % name)
        _head, claims, unsigned = read_token(token, jwks)
        if unsigned:
            bad("%s: %s." % (name, unsigned))
            continue
        aud, short = str(claims.get("aud", "")), name[:23] + "..."
        p = aud.split(":")
        said = "%s carries the signature of the archived key, issued by %s at %s" % (short, claims.get("iss"), claims.get("iat"))
        if p[:2] in (["knosm", "batch"], ["knosm", "claim"]) and len(p) == 10:
            try:
                hit = batches.get(tuple(int(x) for x in p[2:9]) + (p[9],))
            except ValueError:
                hit = None
            if hit is None:
                bad("%s was signed for a batch that no archived ledger holds (%s)." % (name, aud))
            else:
                hit[1] = True
                done.append("%s, for batch %s of %s in %s: its root, count, accepted count and value are the ones signed" % (said, p[5], p[4], hit[0]))
        elif p[:2] == ["knosm", "close"] and len(p) == 6:
            if p[5] in by_hash:
                signed_files.add(by_hash[p[5]])
                done.append("%s, by owner %s, for the close record %s" % (said, claims.get("repository_owner_id"), by_hash[p[5]]))
            else:
                bad("%s was signed for a close record that is not in the archive (%s)." % (name, aud))
        else:
            done.append("%s, for the audience %s" % (said, aud))
    unsigned_batches = sorted("%s.%s of %s" % (k[2], k[3], v[0]) for k, v in batches.items() if not v[1])
    if unsigned_batches:
        notes.append("UNSIGNED: %d batches carry no signed token in this archive, so their roots are checked by hash only and are the holder's word: %s" % (
            len(unsigned_batches), ", ".join(unsigned_batches)))

    # receipts: by hash; the judge's token when it is here
    for name in sorted(n for n in files if n.startswith("receipts/")):
        want = sorted(set(re.findall(r'"token_sha256"\s*:\s*"([0-9a-f]{64})"', files[name].decode("utf-8", "replace"))))
        here = [h for h in want if "tokens/%s.jwt" % h in files]
        if want and len(here) == len(want):
            done.append("%s: the token it rests on is in the archive and its signature was checked above" % name)
        else:
            notes.append("%s is checked by hash only: %s" % (name, "the token it rests on is not in the archive" if want else "it names no token"))

    # statements
    for name in sorted(n for n in files if n.startswith("statements/") and not n.startswith("statements/events-")):
        st = json_of(name)
        before = len(problems)
        try:
            if isinstance(st, dict) and st.get("kind") == "knos-statement":
                n, from_log = check_ap_statement(name, st, log_lines, bad)
            elif isinstance(st, dict) and st.get("type") == "knos.meter-statement":
                check_meter_statement(name, st, ledger_ids, bad)
        except Exception:
            bad("%s cannot be read as the statement it says it is." % name)
            continue
        if isinstance(st, dict) and st.get("kind") == "knos-statement":
            if len(problems) == before:
                done.append("%s: its hash is its own and its totals are the totals of its %d lines" % (name, n) +
                            (" (%d of them rest on lines of the archived log)" % from_log if from_log else ""))
        elif isinstance(st, dict) and st.get("type") == "knos.meter-statement":
            if len(problems) == before:
                done.append("%s: its counts add up, its fee is the fee of its count, and its lines are in an archived ledger" % name)
        elif isinstance(st, dict) and st.get("type") == "knos.events-statement":
            bad("%s is a statement of the log under a name the log's statements do not have." % name)
        elif st is not None:
            notes.append("%s is not a statement this file knows: checked by hash only" % name)

    # the terms, by hash
    terms = sorted(n for n in files if n.startswith("terms/"))
    for name in terms:
        if name.split("/", 1)[1].split(".")[0] != hexsha(files[name]):
            bad("%s: its bytes do not hash to the name it is kept under." % name)
    if terms and not any(p.startswith("terms/") for p in problems):
        done.append("%d terms files hash to the names they are kept under" % len(terms))
    for name in sorted(n for n in files if n.startswith(("other/", "closes/")) and n not in signed_files):
        notes.append("%s is checked by hash only" % name)
    return done, notes, problems


def files_of(path):
    """name -> bytes, from a packed archive or an unpacked one."""
    if os.path.isdir(path):
        out = {}
        for folder, _dirs, names in os.walk(path):
            for name in names:
                full = os.path.join(folder, name)
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                if not rel.startswith("__pycache__/"):
                    with open(full, "rb") as f:
                        out[rel] = f.read()
        return out
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist() if not i.filename.endswith("/")}


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if "--help" in argv or "-h" in argv or len(args) > 1:
        print(__doc__)
        return 0 if len(args) <= 1 else 2
    path = args[0] if args else os.path.dirname(os.path.abspath(__file__))
    try:
        files = files_of(path)
    except (OSError, zipfile.BadZipFile) as why:
        print("Cannot read %s: %s" % (path, why))
        return 2
    done, notes, problems = check(files)
    for line in done:
        print("checked: " + line + ".")
    for line in notes:
        print("note: " + line + ".")
    for line in problems:
        print("DOES NOT HOLD: " + line)
    weak = [x for x in notes if x.startswith(("INCOMPLETE", "UNSIGNED"))] if "--strict" in argv else []
    failed = bool(problems) or bool(weak)
    print(("NOT VERIFIED: %d problems" % len(problems) + (", %d notes marked INCOMPLETE or UNSIGNED (--strict)" % len(weak) if "--strict" in argv else "")) if failed
          else "VERIFIED: %d checks hold, %d notes. No network, no Knos." % (len(done), len(notes)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
