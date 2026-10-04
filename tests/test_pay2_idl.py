"""idl/knos_pay_v2.json (Shank format, written by hand: the program is native) against the second escrow's source and
client, beyond what tests/test_idl.py checks for every program (the address, the discriminants, what each builder of
the client sends and where each account is): every instruction's accounts and arguments as the headers of
programs-v2/knos_pay/src/lib.rs and order_terms.rs list them, the number of accounts each handler takes, every account
layout against the constants of state.rs, order_terms.rs and order_judge.rs and against what the client's readers
read, the error codes and bounds, the pins, and the audiences."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from knos.settle.v2 import order_auto, pay

ROOT = Path(__file__).resolve().parents[1]
IDL = json.loads((ROOT / "idl" / "knos_pay_v2.json").read_text(encoding="utf-8"))
SRC = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "programs-v2" / "knos_pay" / "src").glob("*.rs")}
LIB, STATE, TERMS_RS, JUDGE_RS = SRC["lib.rs"], SRC["state.rs"], SRC["order_terms.rs"], SRC["order_judge.rs"]
CLAIMS_RS = (ROOT / "programs-v2" / "knos_oidc" / "src" / "claims.rs").read_text(encoding="utf-8")
IDS = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text())

K = {n: Pubkey(bytes([i + 1]) * 32) for i, n in enumerate(["authority", "funder", "mint", "relayer", "wallet"])}
REPO, ISSUE, PAYEE, OWNER, AMOUNT = 987654321, 7, 1234567, 424242, 5_000_000
TERMS = pay.terms_json({"checks": [{"app": 15368, "name": "test"}], "mode": "merge", "v": 1})
WF_SHA = "c" * 40
BAL = pay.balance_pda(OWNER, K["authority"], K["mint"])
FIXED = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "i64": 8, "publicKey": 32}


def size(t) -> int | None:
    """Bytes a type takes; None for `bytes`, which is raw and runs to the end."""
    if isinstance(t, dict):
        inner, count = t["array"]
        return size(inner) * count
    return FIXED.get(t)


def encode(fields: list[dict], values: dict) -> bytes:
    out = b""
    for f in fields:
        v, n = values.get(f["name"], 0), size(f["type"])
        if isinstance(v, int):
            v = v.to_bytes(n, "little", signed=f["type"] == "i64")
        assert n is None or len(v) == n, f["name"]
        out += bytes(v)
    return out


def offsets(fields: list[dict]) -> dict[str, int]:
    out, at = {}, 0
    for f in fields:
        out[f["name"]] = at
        at += size(f["type"])
    return out


def layout(account: str) -> list[dict]:
    return next(a for a in IDL["accounts"] if a["name"] == account)["type"]["fields"]


def constants(source: str, prefix: str, kind: str = "usize") -> dict[str, int]:
    return {m.group(1): int(m.group(2).replace("_", "")) for m in re.finditer(rf"pub const ({prefix}\w+): {kind} = ([\d_]+);", source)}


def camel(name: str) -> str:
    head, *rest = name.split("_")
    # `as` is a word most languages keep for themselves: the IDL calls that account by what it holds
    return {"system": "systemProgram", "as": "assign"}.get(name, head + "".join(w.capitalize() for w in rest))


def u64s(values) -> bytes:
    return b"".join(v.to_bytes(8, "little") for v in values)


def a_job(**over) -> pay.Job:
    """A job as the client reads it from bytes laid out by the IDL."""
    v = {"state": 1, "kind": 1, "tokenProgram": 0, "repoId": REPO, "issue": ISSUE, "amount": AMOUNT, "ownerId": OWNER, "payeeId": PAYEE,
         "source": bytes(BAL), "refundTo": bytes(pay.baltok_pda(BAL)), "rentTo": bytes(K["relayer"]), "mint": bytes(K["mint"]), "wfSha": WF_SHA.encode()}
    v.update(over)
    return pay.read_job(encode(layout("Job"), v))


FROM_BALANCE = a_job()
FROM_WALLET = a_job(kind=0, tokenProgram=1, ownerId=0, source=bytes(K["funder"]), refundTo=bytes(K["funder"]), rentTo=bytes(K["funder"]))
T22 = pay.TOKEN_2022


def _accounts(text: str) -> list[dict]:
    """The account words a header line starts with: `name`, `name(s)`, `name(w)`, `name(s,w)`; `[a b]` are optional.
    Prose ends the list (a word that is not one of these, or a comma)."""
    out, optional = [], False
    for word in text.split():
        optional = optional or word.startswith("[")
        m = re.match(r"^([a-z][a-z_]*)(?:\(([sw,]+)\))?$", word.strip("[]"))
        if not m:
            break
        name, flags = m.groups()
        out.append({"name": camel(name), "isSigner": "s" in (flags or ""), "isMut": "w" in (flags or ""), **({"optional": True} if optional else {})})
    return out


def header() -> dict[str, dict]:
    """The instructions as the headers of lib.rs and order_terms.rs list them: `<tag> <Name>  <accounts in order>`
    (the list may run on to the next line), then `data:` and the arguments, on that line or the next."""
    out = {}
    for source in (LIB, TERMS_RS):
        lines = source.splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"^//!   (\d+) (\w+)(?: +(\S.*))?$", line)      # an instruction with no accounts is its tag and its name
            if not m:
                continue
            first, _, same_line = (m.group(3) or "").partition("data: ")
            following = lines[i + 1][3:].strip()
            accounts = _accounts(first) + _accounts(following.split(",")[0])
            # Release: after its fixed accounts, two for each payee its record names; the IDL lists the first payee's
            each = re.search(r", then for each recorded payee, in the record's order: (.+)$", following)
            accounts += _accounts(each.group(1)) if each else []
            data = same_line or (following[len("data: "):] if following.startswith("data: ") else "")
            args = []
            for arg in (data.split(", ") if data else []):
                kind = re.match(r"^.+? (\[.+\]|\w+)$", arg).group(1)
                array = re.match(r"^\[(\w+); (\d+)\]$", kind)
                # `[32]` is how order_terms.rs writes an address
                args.append({"array": [array.group(1), int(array.group(2))]} if array else "publicKey" if kind == "[32]" else kind)
            out[m.group(2)] = {"tag": int(m.group(1)), "accounts": accounts, "args": args}
    return out


# What order_terms.rs appends to three instructions of order_pay.rs, whose own header (lib.rs) lists them without it.
APPENDED = {"PayOrder": [{"name": "assign", "isSigner": False, "isMut": False}, {"name": "doneOrHb", "isSigner": False, "isMut": True, "optional": True}],
            "SettleOrder": [{"name": "assign", "isSigner": False, "isMut": False}],
            "RefundOrder": [{"name": "takerBind", "isSigner": False, "isMut": False, "optional": True},
                            {"name": "killToken", "isSigner": False, "isMut": True, "optional": True}]}
# The accounts the IDL lists once and the program takes once per payee (read after the handler's fixed accounts).
PER_PAYEE = {"PayOrder": 6, "SettleOrder": 6, "Release": 2}


def test_the_address_and_the_pins_are_the_second_deployments():
    assert IDL["metadata"] == {"origin": "shank", "address": IDS["knos_pay"]} and IDL["name"] == "knos_pay_v2"
    assert str(pay.PAY_ID) == IDS["knos_pay"] and str(pay.OIDC_ID) == IDS["knos_oidc"]
    assert pay.IDS == IDS                                    # the client's copy of the pinned values is the programs' file
    pins = dict(re.findall(r'pub const (\w+): Pubkey = pubkey!\("(\w+)"\);', LIB))
    assert pins == {"OIDC_ID": IDS["knos_oidc"], "FEE_OWNER": IDS["fee_owner"], "GUARDIAN": IDS["guardian"],
                    "USDC_DEVNET": str(pay.USDC_DEVNET), "USDC_MAINNET": str(pay.USDC_MAINNET)}
    assert f'pub const CLAIM_SHA: &[u8; 40] = b"{IDS["claim_sha"]}";' in LIB
    assert (str(pay.FEE_OWNER), str(pay.GUARDIAN)) == (IDS["fee_owner"], IDS["guardian"])
    tokens = dict(re.findall(r'pub const (\w+): Pubkey = pubkey!\("(\w+)"\);', SRC["token.rs"]))
    assert tokens == {"TOKEN": str(pay.TOKEN), "TOKEN_2022": str(pay.TOKEN_2022), "ATA_PROGRAM": str(pay.ATA_PROGRAM)}


def test_every_instruction_of_the_source_is_in_the_idl_with_its_accounts_and_arguments():
    """The header comments of lib.rs and order_terms.rs are the program's own account of itself; the dispatch has one
    arm per tag."""
    listed = header()
    arms = {int(m.group(1)) for m in re.finditer(r"^        (\d+) => \w+::\w+\(", LIB.split("pub fn process")[1], re.M)}
    got = {i["name"]: i["discriminant"]["value"] for i in IDL["instructions"]}
    # 0..11 are 2.0; 2.1 adds 12..27
    assert got == {name: h["tag"] for name, h in listed.items()} and set(got.values()) == arms == set(range(28))
    assert all(i["discriminant"]["type"] == "u8" for i in IDL["instructions"])
    for i in IDL["instructions"]:
        h = listed[i["name"]]
        want = h["accounts"] + APPENDED.get(i["name"], [])
        assert [{k: a[k] for k in ("name", "isSigner", "isMut")} for a in i["accounts"]] == [{k: a[k] for k in ("name", "isSigner", "isMut")} for a in want], i["name"]
        # optional: what a header brackets, what is appended only for some orders, and FundBalance's side account
        # (the header of lib.rs: "`balx` is passed (and then required) only once the Balance has a side account")
        optional = [a["name"] for a in want if a.get("optional")] + (["balx"] if i["name"] == "FundBalance" else [])
        assert [a["name"] for a in i["accounts"] if a.get("optional")] == optional, i["name"]
        assert [a["type"] for a in i["args"]] == h["args"], i["name"]
        # the handler takes exactly that many accounts
        fn = re.search(rf"^        {h['tag']} => (\w+)::(\w+)\(", LIB, re.M)
        body = SRC[fn.group(1) + ".rs"].split(f"pub fn {fn.group(2)}(")[1]
        # ...not counting an optional account (read after the others) and a payee's (read per payee)
        fixed = len([a for a in i["accounts"] if not a.get("optional")]) - PER_PAYEE.get(i["name"], 0)
        taken = re.search(r"let \[([^\]]+)\] = take\(accounts\)\?;", body.split("\n}")[0])
        assert len(taken.group(1).split(",")) == fixed if taken else fixed == 0, i["name"]
    # what is appended is what order_terms.rs says it reads after the accounts lib.rs lists, and where it reads it
    said = " ".join(line[3:].strip() for line in TERMS_RS.splitlines() if line.startswith("//!"))
    for sentence in ('PayOrder takes, after its payees\' accounts: one ["as", order, payee] per payee, in the payees\' order',
                     'then ["done", order, pr](w) for a STANDING order, or ["hb", order](w) for one with a holdback',
                     'SettleOrder takes ["as", order, payee] after its sixteen',
                     "RefundOrder takes, after its eight, the taker's bind and a token account of his wallet (w) when a kill fee is due"):
        assert sentence in said, sentence
    assert "const PER: usize = 5;" in TERMS_RS and "per.get(payees.len() * PER + k)" in TERMS_RS            # the assignments follow every payee's five
    assert TERMS_RS.count("per.get(n * PER + n)") == 2                                                      # then the marker, or the record
    assert "let [bind, dest] = take(accounts.get(8..)" in TERMS_RS and "let [tok, key, sys, used] = take(accounts.get(2..)" in TERMS_RS
    assert "let [wallet_acc, dest] = take(per.get(2 * k..)" in TERMS_RS and "let per = &accounts[13..];" in TERMS_RS
    # the numbers the IDL's sentences give
    text = json.dumps(IDL)
    assert "now + 7 days" in text and re.search(r"pub const NOTICE: i64 = 7 \* 86_400;", TERMS_RS) and pay.NOTICE == 7 * 86_400
    assert "the tip (0.05, or 0.30 when a token account was created here)" in text and (pay.TIP, pay.TIP_FIRST) == (50_000, 300_000)


def test_account_sizes_and_field_offsets_are_the_constants_of_the_source():
    lens = {**constants(STATE, ""), **constants(TERMS_RS, "")}
    sizes = {a["name"]: sum(size(f["type"]) for f in a["type"]["fields"]) for a in IDL["accounts"]}
    assert sizes == {"Balance": 160, "Job": 320, "Bind": 56, "Rep": 64, "Pair": 1, "Pause": 8, "Rate": 16, "BalX": 152, "Plan": 24, "Used": 41, "Order": 512,
                     "Hb": 240, "Done": 65, "As": 88, "Q": 106}
    assert sizes == {"Balance": lens["BALANCE_LEN"], "Job": lens["JOB_LEN"], "Bind": lens["BIND_LEN"], "Rep": lens["REP_LEN"], "Pair": lens["PAIR_LEN"],
                     "Pause": lens["PAUSE_LEN"], "Rate": lens["RATE_LEN"], "BalX": lens["BALX_LEN"], "Plan": lens["PLAN_LEN"], "Used": lens["USED_LEN"],
                     "Order": lens["ORDER_LEN"], "Hb": lens["HB_LEN"], "Done": lens["DONE_LEN"], "As": lens["AS_LEN"], "Q": lens["Q_LEN"]}
    assert {name for name in lens if name.endswith("_LEN")} == {"BALANCE_LEN", "JOB_LEN", "BIND_LEN", "REP_LEN", "PAIR_LEN", "PAUSE_LEN", "RATE_LEN",
                                                                "BALX_LEN", "PLAN_LEN", "USED_LEN", "ORDER_LEN", "HB_LEN", "DONE_LEN", "AS_LEN", "Q_LEN"}
    assert (pay.BALX_LEN, pay.PLAN_LEN, pay.ORDER_LEN) == (152, 24, 512)
    assert (pay.HB_LEN, pay.DONE_LEN, pay.AS_LEN, pay.USED_LEN) == (240, 65, 88, 41)
    # every account's docs give its length
    for a in IDL["accounts"]:
        assert f" {sizes[a['name']]} byte" in " ".join(a["docs"]), a["name"]
    assert (pay.JOB_LEN, pay.BALANCE_LEN, pay.BIND_LEN, pay.REP_LEN) == (320, 160, 56, 64)
    names = {
        "Job": {"J_STATE": "state", "J_MODE": "mode", "J_KIND": "kind", "J_BUMP": "bump", "J_TOKEN_PROGRAM": "tokenProgram", "J_FAUCET": "faucet",
                "J_REPO": "repoId", "J_ISSUE": "issue", "J_AMOUNT": "amount", "J_DEADLINE": "deadline", "J_HOLD_UNTIL": "holdUntil", "J_PAYEE": "payeeId",
                "J_FUNDER_ID": "funderId", "J_NOT_BEFORE": "notBefore", "J_OWNER_ID": "ownerId", "J_SOURCE": "source", "J_REFUND_TO": "refundTo",
                "J_RENT_TO": "rentTo", "J_MINT": "mint", "J_TERMS": "terms", "J_WF_REPO": "wfRepoHash", "J_WF_SHA": "wfSha"},
        "Balance": {"B_VERSION": "version", "B_BUMP": "bump", "B_FAUCET": "faucet", "B_X": "hasX", "B_OWNER_ID": "ownerId", "B_AUTHORITY": "authority", "B_MINT": "mint",
                    "B_CAP": "capPerJob", "B_LAST_IAT": "lastIat", "B_SPENDERS": "spenders", "B_SPENT": "spent"},
        "Bind": {"BD_VERSION": "version", "BD_BUMP": "bump", "BD_ORG": "org", "BD_ORG_IAT": "orgIat", "BD_USER": "userId", "BD_WALLET": "wallet", "BD_IAT": "iat"},
        "Rep": {"R_PAID": "paid", "R_FUNDERS": "funders", "R_TOTAL": "total", "R_TEST_PAID": "testPaid", "R_SELF_PAID": "selfPaid",
                "R_TEST_TOTAL": "testTotal", "R_FIRST": "first", "R_LAST": "last"},
        "BalX": {"X_VERSION": "version", "X_BUMP": "bump", "X_DAY_LIMIT": "dayLimit", "X_TOTAL_LIMIT": "totalLimit", "X_REPOS": "repos", "X_WF_SHA": "wfSha",
                 "X_DAY": "day", "X_DAY_SPENT": "daySpent", "X_TOTAL_SPENT": "totalSpent"},
        "Plan": {"P_VERSION": "version", "P_BUMP": "bump", "P_BPS": "feeBps", "P_OWNER": "ownerId", "P_EXPIRES": "expires"},
        "Order": {"O_VERSION": "version", "O_STATE": "state", "O_MODE": "mode", "O_KIND": "kind", "O_FLAGS": "flags", "O_BUMP": "bump", "O_DECIMALS": "decimals",
                  "O_RESERVE_DAYS": "reserveDays", "O_REPO": "repoId", "O_ISSUE": "issue", "O_SCOPE": "scope", "O_SEQ": "seq", "O_HOLDBACK_BPS": "holdbackBps",
                  "O_KILL_BPS": "killBps", "O_AMOUNT": "amount", "O_FEE": "fee", "O_RATE": "rate", "O_PAID": "paid", "O_DEADLINE": "deadline",
                  "O_NOT_BEFORE": "notBefore", "O_HOLD_UNTIL": "holdUntil", "O_WARRANTY_S": "warrantyS", "O_RESERVED_BY": "reservedBy",
                  "O_RESERVED_UNTIL": "reservedUntil", "O_CANCEL_AT": "cancelAt", "O_PAYEE": "payeeId", "O_FUNDER_ID": "funderId", "O_OWNER_ID": "ownerId",
                  "O_ARBITER_ID": "arbiterId", "O_JUDGE_REPO": "judgeRepoId", "O_SOURCE": "source", "O_REFUND_TO": "refundTo", "O_RENT_TO": "rentTo",
                  "O_MINT": "mint", "O_TERMS": "terms", "O_WF_REPO": "wfRepoHash", "O_WF_SHA": "wfSha", "O_FEE_BPS": "feeBps", "O_RESERVED": "reserved"},
        "Used": {"U_PAYER": "payer", "U_AFTER": "after"},
        # the accounts of an order's terms (order_terms.rs). H_ENTRIES is where the first of the four entries starts
        "Hb": {"H_VERSION": "version", "H_BUMP": "bump", "H_N": "n", "H_PAYER": "payer", "H_UNTIL": "until", "H_ENTRIES": "payeeId0"},
        "Done": {"D_PAYER": "payer", "D_ORDER": "order"},
        "As": {"A_VERSION": "version", "A_BUMP": "bump", "A_PAYEE": "payeeId", "A_ORDER": "order", "A_TO": "to", "A_SINCE": "since"},
        "Q": {"Q_BUMP": "bump", "Q_KIND": "kind", "Q_PAYER": "payer", "Q_ORDER": "order", "Q_SINCE": "since", "Q_ART": "artifact"},
    }
    prefix = {"Job": "J_", "Balance": "B_", "Bind": "BD_", "Rep": "R_", "BalX": "X_", "Plan": "P_", "Order": "O_", "Used": "U_", "Hb": "H_", "Done": "D_", "As": "A_", "Q": "Q_"}
    entry = constants(TERMS_RS, "H_")["H_ENTRY"]        # the size of one entry of a holdback's record, not an offset
    for account, fields in names.items():
        # a Bind's two bytes that only BindOrg writes are named where BindOrg is (order_judge.rs)
        consts = {**constants(STATE, prefix[account]), **constants(TERMS_RS, prefix[account]), **(constants(JUDGE_RS, "BD_") if account == "Bind" else {})}
        consts.pop("H_ENTRY", None)
        consts.pop("Q_LEN", None)                       # a quorum marker's length, which its prefix makes look like an offset
        assert set(fields) == set(consts), account
        at = offsets(layout(account))
        assert {c: at[f] for c, f in fields.items()} == consts, account
        named = set(fields.values()) | ({f"{part}{k}" for k in range(4) for part in ("payeeId", "wallet", "amount")} if account == "Hb" else set())
        first = {"Used": "used", "Done": "done"}.get(account)        # a marker's first byte is 1 (a used marker's: USED, or MINTED) and is no offset
        assert all(f.startswith("padding") or f == first for f in set(at) - named), account
    hb = offsets(layout("Hb"))
    assert [(hb[f"payeeId{k}"], hb[f"wallet{k}"], hb[f"amount{k}"]) for k in range(4)] == [(48 + entry * k, 56 + entry * k, 88 + entry * k) for k in range(4)]
    assert entry == 48 and "(payee id u64 @0, wallet [32] @8, amount u64 @40)" in TERMS_RS and pay.MAX_PAYEES == 4 == constants(LIB, "MAX_")["MAX_PAYEES"]
    assert offsets(layout("Used"))["used"] == offsets(layout("Done"))["done"] == 0 and "d[0] = as_;" in STATE and "d[0] = 1;" in TERMS_RS
    # every instruction that takes a token marks it, once: the ten that read one are the ten that call mark_used
    reads = {name for name, src in SRC.items() for _ in re.finditer(r"= (?:github|fund_token|fund_run|crate::fund::fund_run_order|crate::order_judge::token)\(", src)}
    marks = [name for name, src in SRC.items() for _ in re.finditer(r"^    +mark_used\(program_id, ", src, re.M)]
    assert len(marks) == 10 == len(pay.TOKEN_AT) and set(marks) == reads == {"fund.rs", "pay.rs", "order.rs", "order_pay.rs", "order_terms.rs", "order_judge.rs"}
    assert {k: v for k, v in constants(STATE, "", "u8").items() if k in ("USED", "MINTED")} == {"USED": 1, "MINTED": pay.MINTED} and pay.MINTED == 2
    # the times are signed: exactly the fields the source reads or writes as i64
    signed = {c for src in SRC.values() for pair in re.findall(r"i64_at\(&d, ([A-Z]\w+)\)|put_i64\(&mut d, ([A-Z]\w+),", src) for c in pair if c}
    assert signed == {"J_DEADLINE", "J_HOLD_UNTIL", "J_NOT_BEFORE", "B_LAST_IAT", "BD_IAT", "R_FIRST", "R_LAST", "X_DAY", "P_EXPIRES", "O_DEADLINE",
                      "O_NOT_BEFORE", "O_HOLD_UNTIL", "O_WARRANTY_S", "O_RESERVED_UNTIL", "O_CANCEL_AT", "U_AFTER", "H_UNTIL", "A_SINCE", "Q_SINCE"}
    for account, fields in names.items():
        assert {f["name"] for f in layout(account) if f["type"] == "i64"} == {fields[c] for c in signed if c in fields}, account
    for account in ("Pause", "Rate"):
        assert all(f["type"] == "i64" for f in layout(account))


def test_accounts_written_as_the_idl_says_are_read_by_the_client():
    """Each field gets its own value, the bytes are laid out by the IDL, and the Python readers find every value."""
    v = {"state": 3, "mode": 1, "kind": 1, "bump": 254, "tokenProgram": 1, "faucet": 1, "repoId": REPO, "issue": ISSUE, "amount": AMOUNT,
         "deadline": 1_790_000_100, "holdUntil": -5, "payeeId": PAYEE, "funderId": 555000, "notBefore": 1_790_000_000, "ownerId": OWNER,
         "source": bytes(BAL), "refundTo": bytes(K["wallet"]), "rentTo": bytes(K["relayer"]), "mint": bytes(K["mint"]), "terms": bytes(range(32)),
         "wfRepoHash": pay.wf_repo_hash("drexthealpha/Knos"), "wfSha": WF_SHA.encode()}
    assert pay.read_job(encode(layout("Job"), v)) == pay.Job(
        state="held", mode=1, from_balance=True, token_program=T22, faucet=True, repo_id=REPO, issue=ISSUE, amount=AMOUNT, deadline=1_790_000_100,
        hold_until=-5, payee_id=PAYEE, funder_id=555000, not_before=1_790_000_000, owner_id=OWNER, source=BAL, refund_to=K["wallet"],
        rent_to=K["relayer"], mint=K["mint"], terms=bytes(range(32)), wf_repo_hash=v["wfRepoHash"], wf_sha=WF_SHA)
    assert FROM_BALANCE.funder == OWNER and FROM_WALLET.funder == K["funder"] and not FROM_WALLET.from_balance and FROM_BALANCE.state == "open"
    b = {"version": 1, "bump": 253, "faucet": 1, "ownerId": OWNER, "authority": bytes(K["authority"]), "mint": bytes(K["mint"]), "capPerJob": 77,
         "lastIat": -3, "spenders": u64s([5, 0, 6, 0]), "spent": 99}
    assert pay.read_balance(encode(layout("Balance"), b)) == pay.Balance(faucet=True, owner_id=OWNER, authority=K["authority"], mint=K["mint"],
                                                                         cap_per_job=77, last_iat=-3, spenders=(5, 6), spent=99)
    assert pay.read_bind(encode(layout("Bind"), {"version": 1, "bump": 2, "userId": PAYEE, "wallet": bytes(K["wallet"]), "iat": 1_790_000_007})) == \
        pay.Bind(user_id=PAYEE, wallet=K["wallet"], iat=1_790_000_007)
    r = {"paid": 9, "funders": 4, "total": 77_000_000, "testPaid": 3, "selfPaid": 2, "testTotal": 5_000_000, "first": 1_790_000_001, "last": 1_790_000_002}
    assert pay.read_rep(encode(layout("Rep"), r)) == pay.Record(paid=9, funders=4, total=77_000_000, test_paid=3, self_paid=2, test_total=5_000_000,
                                                               first=1_790_000_001, last=1_790_000_002)
    assert pay.read_pause(encode(layout("Pause"), {"until": 1_790_000_300})) == 1_790_000_300 and pay.read_pause(None) == 0
    assert pay.read_rate(encode(layout("Rate"), {"lastUse": 1_790_000_500, "lastIat": 1_790_000_499})) == (1_790_000_500, 1_790_000_499)
    assert pay.read_rate(None) == pay.read_rate(bytes(8)) == (0, 0)
    # the readers take exactly these sizes, and a version they know
    for read, n in ((pay.read_job, 320), (pay.read_balance, 160), (pay.read_bind, 56)):
        good = bytes([1]) + bytes(n - 1)
        assert read(good) is not None and read(good + b"\0") is None and read(good[:-1]) is None and read(None) is None
    assert pay.read_balance(bytes(160)) is None and pay.read_bind(bytes(56)) is None
    assert pay.read_rep(bytes(65)) == pay.read_rep(None) == pay.Record(0, 0, 0, 0, 0, 0, 0, 0) and pay.read_pause(bytes(9)) == 0


def test_an_orders_accounts_written_as_the_idl_says_are_read_by_the_client():
    """The same for the accounts of 2.1: the order, a Balance's side account, a Plan, a holdback's record, an
    assignment and the two markers."""
    scope, order = pay.scope_of(REPO, ISSUE), pay.order_pda(pay.scope_of(REPO, ISSUE), BAL, 3)
    v = {"version": 2, "state": 4, "mode": 1, "kind": 1, "flags": pay.F_NEUTRAL | pay.F_TOKEN2022, "bump": 251, "decimals": 6, "reserveDays": 9, "repoId": REPO,
         "issue": ISSUE, "scope": scope, "seq": 3, "holdbackBps": 1000, "killBps": 500, "amount": AMOUNT, "fee": 400_000, "rate": 11, "paid": 12,
         "deadline": 1_790_000_100, "notBefore": 1_790_000_000, "holdUntil": -5, "warrantyS": 30 * 86_400, "reservedBy": 13, "reservedUntil": 1_790_000_050,
         "cancelAt": 1_790_000_040, "payeeId": PAYEE, "funderId": 555000, "ownerId": OWNER, "arbiterId": 77, "judgeRepoId": 31313131, "source": bytes(BAL),
         "refundTo": bytes(pay.baltok_pda(BAL)), "rentTo": bytes(K["relayer"]), "mint": bytes(K["mint"]), "terms": bytes(range(32)),
         "wfRepoHash": pay.wf_repo_hash("drexthealpha/Knos"), "wfSha": WF_SHA.encode(), "feeBps": 100}
    o = pay.read_order(encode(layout("Order"), v))
    assert o == pay.Order(
        state="warranty", mode=1, from_balance=True, flags=pay.F_NEUTRAL | pay.F_TOKEN2022, decimals=6, reserve_days=9, repo_id=REPO, issue=ISSUE, scope=scope,
        seq=3, holdback_bps=1000, kill_bps=500, amount=AMOUNT, fee=400_000, rate=11, paid=12, deadline=1_790_000_100, not_before=1_790_000_000, hold_until=-5,
        warranty_s=30 * 86_400, reserved_by=13, reserved_until=1_790_000_050, cancel_at=1_790_000_040, payee_id=PAYEE, funder_id=555000, owner_id=OWNER,
        arbiter_id=77, judge_repo_id=31313131, source=BAL, refund_to=pay.baltok_pda(BAL), rent_to=K["relayer"], mint=K["mint"], terms=bytes(range(32)),
        wf_repo_hash=v["wfRepoHash"], wf_sha=WF_SHA, fee_bps=100)
    assert o.address() == order and o.token_program == T22 and o.funder == OWNER and not o.faucet
    assert {pay.read_order(encode(layout("Order"), {**v, "state": n})).state for n in (1, 3)} == {"open", "held"}
    flags = constants(STATE, "F_", "u8")
    assert flags == {"F_FAUCET": pay.F_FAUCET, "F_PRIVATE": pay.F_PRIVATE, "F_NEUTRAL": pay.F_NEUTRAL, "F_STANDING": pay.F_STANDING, "F_TOKEN2022": pay.F_TOKEN2022,
                     "F_AUTO": order_auto.F_AUTO}
    assert "pub const F_QUORUM: u8 = 0xc0;" in STATE and order_auto.F_QUORUM == 0xC0 and order_auto.Q_LEN == constants(TERMS_RS, "Q_")["Q_LEN"]
    assert "flags: FAUCET 1, PRIVATE 2, NEUTRAL 4, STANDING 8, TOKEN2022 16" in " ".join(next(a for a in IDL["accounts"] if a["name"] == "Order")["docs"])
    assert constants(STATE, "", "u8") == {"OPEN": 1, "HELD": 3, "WARRANTY": 4, "USED": 1, "MINTED": 2, **flags} and pay.STATES == {1: "open", 3: "held", 4: "warranty"}
    x = {"version": 1, "bump": 250, "dayLimit": 30, "totalLimit": 70, "repos": u64s([REPO, 0, 5, 0, 0, 0, 0, 0]), "wfSha": WF_SHA.encode(), "day": 20_717,
         "daySpent": 7, "totalSpent": 9}
    assert pay.read_balx(encode(layout("BalX"), x)) == pay.BalanceX(day_limit=30, total_limit=70, repos=(REPO, 5), wf_sha=WF_SHA, day=20_717, day_spent=7, total_spent=9)
    assert pay.read_balx(encode(layout("BalX"), {**x, "wfSha": bytes(40)})).wf_sha == ""
    plan = pay.read_plan(encode(layout("Plan"), {"version": 1, "bump": 249, "feeBps": 100, "ownerId": OWNER, "expires": 1_790_000_600}))
    assert plan == pay.Plan(fee_bps=100, owner_id=OWNER, expires=1_790_000_600)
    assert (pay.plan_bps(plan, 1_790_000_599), pay.plan_bps(plan, 1_790_000_600), pay.plan_bps(None, 0)) == (100, pay.FEE_BPS, pay.FEE_BPS)
    # a holdback's record: only the entries it counts are read
    h = {"version": 1, "bump": 248, "n": 2, "payer": bytes(K["relayer"]), "until": 1_790_000_700, "payeeId0": PAYEE, "wallet0": bytes(K["wallet"]),
         "amount0": 350_000, "payeeId1": 9, "wallet1": bytes(K["funder"]), "amount1": 150_000, "payeeId2": 8, "wallet2": bytes(K["mint"]), "amount2": 1}
    assert pay.read_holdback(encode(layout("Hb"), h)) == pay.Holdback(payer=K["relayer"], until=1_790_000_700,
                                                                      payees=[(PAYEE, K["wallet"], 350_000), (9, K["funder"], 150_000)])
    a = encode(layout("As"), {"version": 1, "bump": 247, "payeeId": PAYEE, "order": bytes(order), "to": bytes(K["wallet"]), "since": 1_790_000_000})
    assert pay.read_assign(a) == pay.read_assign(a, o) == K["wallet"]
    later = pay.read_order(encode(layout("Order"), {**v, "notBefore": 1_790_000_001}))          # funded again at the same address
    assert pay.read_assign(a, later) is None and pay.payee_wallet(a, later, None, K["funder"]) == K["funder"] and pay.payee_wallet(a, o, None, K["funder"]) == K["wallet"]
    # the markers are told by their length, as CloseMarker tells them
    used = encode(layout("Used"), {"used": 1, "payer": bytes(K["relayer"]), "after": 1_790_009_000})
    done = encode(layout("Done"), {"done": 1, "payer": bytes(K["relayer"]), "order": bytes(order)})
    assert pay.read_marker(used) == (K["relayer"], 1_790_009_000) and pay.read_marker(done) == (K["relayer"], order)
    for read, good in ((pay.read_order, bytes([2]) + bytes(511)), (pay.read_balx, bytes([1]) + bytes(151)), (pay.read_plan, bytes([1]) + bytes(23)),
                       (pay.read_holdback, bytes([1]) + bytes(239)), (pay.read_assign, a), (pay.read_marker, used), (pay.read_marker, done)):
        assert read(good) is not None and read(good + b"\0") is None and read(good[:-1]) is None and read(None) is None
    assert pay.read_order(bytes(512)) is None and pay.read_holdback(bytes(240)) is None and pay.read_assign(bytes(88)) is None
    # a used marker can be closed this long after it was made: what state.rs adds to the clock, with the verifier's lateness
    late = int(re.search(r"pub const LATE: i64 = (\d+);", (ROOT / "programs-v2" / "knos_oidc" / "src" / "lib.rs").read_text(encoding="utf-8")).group(1))
    assert "saturating_add(TOKEN_AHEAD + TOKEN_LIFE + knos_oidc::LATE + 3600)" in STATE and pay.USED_KEEP == pay.TOKEN_AHEAD + pay.TOKEN_LIFE + late + 3600


def test_every_error_code_and_bound_of_the_source_is_the_clients():
    claims = set(constants(CLAIMS_RS, "E_", "u32").values())
    assert claims == {60, 61, 62, 63}
    # the escrow's own codes are 80..99; it passes on the claim reader's and, for a token whose key is no longer usable,
    # the three of knos-oidc's key rule. The client has plain words for every code that is not the claim reader's.
    stale_key = {76, 77, 78}
    own = set(constants(LIB, "E_", "u32").values())
    assert {e["code"] for e in IDL["errors"]} == own | claims | stale_key and own == set(range(80, 104))
    assert set(pay.ERRORS) == own | stale_key and all(text and text[0].islower() and not text.endswith(".") for text in pay.ERRORS.values())
    value = lambda name: eval(re.search(rf"pub const {name}: \w+ = ([\d_ *]+);", LIB).group(1).replace("_", ""), {})  # noqa: E731, S307 - digits and * only
    for name in ("FEE_BPS", "FEE_MIN", "MIN_AMOUNT", "MAX_AMOUNT", "MIN_WORK", "MAX_WORK", "HOLD", "FAUCET_CAP", "FUND_PERIOD", "CLOCK_SLACK", "PAUSE_MAX", "MAX_TERMS",
                 "TOKEN_AHEAD", "TOKEN_LIFE", "ORDER_FEE_MIN", "FEE_TIER_1", "FEE_TIER_2", "FEE_BPS_2", "FEE_BPS_3", "ORDER_MIN_AMOUNT", "TIP", "TIP_FIRST", "PLAN_BPS_MIN", "MAX_HOLDBACK_BPS",
                 "MAX_WARRANTY_DAYS", "MAX_KILL_BPS", "MAX_PAYEES"):
        assert value(name) == getattr(pay, name), name
    for amount in (0, 1, 49_999, 50_000, 1_000_000, 1_999_999, 2_000_000, 5_000_000, 123_456_789, 500_000_000):
        assert pay.fee_of(amount) == min(max(amount // 10_000 * 250 + amount % 10_000 * 250 // 10_000, 50_000), amount)
    # an order's fee is paid on top, in three marginal tiers: the owner's Plan rate (or 2.5%) of the first 1,000 whole
    # units, 1% from there to 50,000, 0.5% above; at least 0.40 and no maximum. The same sums as lib.rs's own test.
    part = lambda a, bps: a // 10_000 * bps + a % 10_000 * bps // 10_000  # noqa: E731 - bps_of
    one, edges = 1_000_000, (0, 1, 5, 16, 100, 999, 1_000, 1_001, 2_000, 49_999, 50_000, 50_001, 100_000, 1_000_000)
    for amount in [e * one + d for e in edges for d in (-1, 0, 1, 99, 100, 199, 200) if e * one + d >= 0]:
        for bps in (50, 100, 150, 250):
            first, second, third = min(amount, 1_000 * one), min(amount, 50_000 * one) - min(amount, 1_000 * one), amount - min(amount, 50_000 * one)
            assert pay.order_fee(amount, bps) == max(part(first, bps) + part(second, 100) + part(third, 50), 400_000), (amount, bps)
    table = [(5, 250, 0.4), (16, 250, 0.4), (100, 250, 2.5), (1_000, 250, 25), (2_000, 250, 35), (50_000, 250, 515), (100_000, 250, 765), (1_000_000, 250, 5_265),
             (1_000, 50, 5), (2_000, 50, 15), (50_000, 150, 505), (100_000, 50, 745)]
    for units, bps, fee in table:
        assert pay.order_fee(units * one, bps) == round(fee * one), (units, bps)
    assert (pay.order_fee(2_000 * 10 ** 9, 250, 9), pay.order_fee(200_000, 250, 2), pay.order_fee(100_000, 250, 0), pay.order_fee(60_000, 250, 0)) == (35 * 10 ** 9, 3_500, 765, 565)
    assert pay.MAX_AMOUNT == 100_000 * one and pay.order_fee(pay.MAX_AMOUNT) == 765 * one
    assert (pay.order_fee(5_000_000), pay.order_fee(16_000_040), pay.order_fee(500_000_000), pay.order_fee(2_000_000_000)) == (400_000, 400_001, 12_500_000, 35_000_000)
    assert (pay.order_fee(5 * 10 ** 9, decimals=9), pay.order_fee(500, decimals=2)) == (400_000_000, 40)


def test_audiences_and_terms_are_what_the_program_parses():
    address = K["wallet"]
    funding = pay.fund_audience(7, AMOUNT, pay.TESTS, pay.terms_hash(TERMS), BAL, 3600)
    assert funding == f"knos2:fund:7:5000000:1:{pay.terms_hash(TERMS).hex()}:3600:{BAL}" and pay.named_balance(funding) == BAL
    assert pay.fund_audience(7, AMOUNT, pay.MERGE, bytes(32), BAL).split(":")[6] == str(14 * 86_400)        # two weeks of work unless said
    assert pay.pay_audience(REPO, 7, PAYEE, "a" * 40, pay.terms_hash(TERMS), 0, address) == f"knos2:pay:{REPO}:7:{PAYEE}:{'a' * 40}:{pay.terms_hash(TERMS).hex()}:0:{address}"
    assert pay.pay_audience(REPO, 7, PAYEE, "a" * 40, pay.terms_hash(TERMS), 1).endswith(":1:-")
    assert pay.bind_audience(address) == f"knos2:bind:{address}"
    # the part counts the program splits on
    for audience, parts, reader in ((funding, 8, "fund_aud"), (pay.pay_audience(REPO, 7, PAYEE, "a" * 40, bytes(32), 0), 9, "pay_aud"),
                                    (pay.bind_audience(address), 3, "bind_aud")):
        assert len(audience.split(":")) == parts and f"parts::<{parts}>(aud)" in SRC["gh.rs"].split(f"pub fn {reader}(")[1].split("\n}")[0]
    # an order's audiences (knos3), and the part counts the program splits them on
    order, payees = pay.order_pda(pay.scope_of(REPO, ISSUE), BAL, 3), [(PAYEE, 7000, address), (9, 3000, None)]
    options = pay.opts(pay.F_NEUTRAL, holdback_bps=1000, warranty_days=30, kill_bps=500, reserve_days=9, rate=11, arbiter_id=77, judge_repo_id=31313131)
    assert len(options) == pay.OPTS_LEN == constants(SRC["order.rs"], "OPTS_")["OPTS_LEN"] == 48
    wallet_funding = next(i for i in IDL["instructions"] if i["name"] == "FundOrderWallet")["args"]          # the fixed part of its data, before the terms
    assert sum(size(a["type"]) or 0 for a in wallet_funding) == 157 and "if data.len() < 157 {" in SRC["order.rs"].split("pub fn fund_order_wallet(")[1]
    funding = pay.order_fund_audience(7, AMOUNT, pay.TESTS, pay.terms_hash(TERMS), BAL, 3600, 3, options)
    assert funding == f"knos3:fund:7:5000000:1:{pay.terms_hash(TERMS).hex()}:3600:{BAL}:3:{options.hex()}"
    paying = pay.order_pay_audience(order, "a" * 40, pay.terms_hash(TERMS), pay.TESTS, 12, payees)
    assert paying == f"knos3:pay:{order}:{'a' * 40}:{pay.terms_hash(TERMS).hex()}:1:12:{PAYEE}.7000.{address},9.3000.-" and pay.payees_of(paying) == payees
    assert pay.rule_audience(order, payees) == f"knos3:rule:{order}:{PAYEE}.7000.{address},9.3000.-" and pay.payees_of(pay.rule_audience(order, payees)) == payees
    assert pay.org_bind_audience(address) == f"knos3:bind:{address}" and pay.take_audience(order, PAYEE, 5) == f"knos3:take:{order}:{PAYEE}:5"
    assert pay.cancel_audience(order) == f"knos3:cancel:{order}" and pay.revert_audience(order, "b" * 40) == f"knos3:revert:{order}:{'b' * 40}"
    for audience, n, file, reader in ((funding, 10, "order.rs", "pub fn order_fund_aud("), (paying, 8, "order_pay.rs", "pub fn pay_order_aud("),
                                      (pay.rule_audience(order, payees), 4, "order_judge.rs", "pub fn audience("),
                                      (pay.org_bind_audience(address), 3, "order_judge.rs", "pub fn org_bind_aud("),
                                      (pay.take_audience(order, PAYEE, 5), 5, "order_terms.rs", "pub fn reserve("),
                                      (pay.cancel_audience(order), 3, "order_terms.rs", "pub fn cancel("),
                                      (pay.revert_audience(order, "b" * 40), 4, "order_terms.rs", "pub fn revert(")):
        body = SRC[file].split(reader)[1].split("\n}")[0]
        assert len(audience.split(":")) == n and (f"parts::<{n}>(aud)" in body or f"aud_of::<{n}>(&g.aud, b\"{audience.split(':')[1]}\"" in body), reader
    # a private order's fund token names neither its repository nor its issue: its terms are sha256(scope || terms hash)
    scope = pay.scope_of(REPO, ISSUE, bytes([9]) * 32)
    assert pay.private_fund_terms(scope, pay.terms_hash(TERMS)) == __import__("hashlib").sha256(scope + pay.terms_hash(TERMS)).digest()
    assert pay.scope_of(REPO, ISSUE) == __import__("hashlib").sha256(b"knos3:scope" + REPO.to_bytes(8, "little") + ISSUE.to_bytes(8, "little")).digest()
    assert 'hashv(&[b"knos3:scope", &repo.to_le_bytes(), &issue.to_le_bytes()])' in SRC["order.rs"]
    # what a refund owes a taker first, as order_terms::kill_fee has it
    killed = pay.read_order(encode(layout("Order"), {"version": 2, "state": 1, "killBps": 1000, "amount": 20_000_000, "reservedBy": 5, "reservedUntil": 100, "cancelAt": 50}))
    assert pay.kill_fee(killed) == 2_000_000 and "bps_of(o.amount, o.kill_bps as u64).min(o.amount - o.paid)" in TERMS_RS
    for change in ({"cancelAt": 0}, {"cancelAt": 101}, {"reservedBy": 0}, {"killBps": 0}, {"state": 3}):
        assert pay.kill_fee(pay.read_order(encode(layout("Order"), {"version": 2, "state": 1, "killBps": 1000, "amount": 20_000_000, "reservedBy": 5,
                                                                    "reservedUntil": 100, "cancelAt": 50, **change}))) == 0, change
    # canonical terms: sorted keys, no spaces, ASCII; the hash is sha256 of exactly those bytes
    assert pay.terms_json({"v": 1, "checks": [{"name": "tést", "app": 0}], "accept": ""}) == b'{"accept":"","checks":[{"app":0,"name":"t\\u00e9st"}],"v":1}'
    assert pay.terms_hash(b"{}").hex() == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    with pytest.raises(ValueError):
        pay.terms_json({"paths": ["x" * 600]})
    # where a proof pays: the bound wallet, else the address in the audience, else nowhere yet
    bound = pay.Bind(user_id=PAYEE, wallet=K["funder"], iat=1)
    with_address, without = pay.pay_audience(REPO, 7, PAYEE, "a" * 40, bytes(32), 0, address), pay.pay_audience(REPO, 7, PAYEE, "a" * 40, bytes(32), 0)
    assert [pay.destination(b, a) for b in (bound, None) for a in (with_address, without)] == [K["funder"], K["funder"], address, None]
    assert pay.funder_key(K["funder"]) == bytes(K["funder"]) and pay.funder_key(OWNER).hex() == __import__("hashlib").sha256(b"gh" + OWNER.to_bytes(8, "little")).hexdigest()


def test_raw_bytes_come_last_and_the_idl_says_how_the_program_can_change():
    for i in IDL["instructions"]:
        assert [a["type"] for a in i["args"]].count("bytes") <= 1 and all(a["type"] != "bytes" for a in i["args"][:-1])
    text = json.dumps(IDL)
    # what may be said of the second deployment, and the word that may not
    assert "Upgradeable only through a multisig with a public 48-hour delay, until an outside review." in IDL["docs"]
    assert "immutable" not in text.lower() and not re.search(r"\baudit", text, re.I)
