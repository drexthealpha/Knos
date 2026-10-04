"""idl/knos_oidc.json, idl/knos_pay.json, idl/knos_oidc_v2.json and idl/knos_pay_v2.json (Shank format, written by
hand: the programs are native) say what the Python client sends and what the programs' source defines: every
instruction's discriminant, accounts with their signer and writable flags, and arguments; every account layout; every
error code; the deployed addresses. knos_oidc_v2 and knos_pay_v2 are the second deployment (programs-v2, clients
knos.settle.v2.oidc and knos.settle.v2.pay); what is particular to the second escrow (its account layouts, its
readers, its bounds and audiences) is in tests/test_pay2_idl.py."""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from knos.settle import oidc, pay
from knos.settle.v2 import oidc as oidc2
from knos.settle.v2 import pay as pay2

ROOT = Path(__file__).resolve().parents[1]
# IDL file -> (the directory of its deployment, the crate in it, the Python client)
PROGRAMS = {"knos_oidc": ("programs", "knos_oidc", oidc), "knos_pay": ("programs", "knos_pay", pay),
            "knos_oidc_v2": ("programs-v2", "knos_oidc", oidc2), "knos_pay_v2": ("programs-v2", "knos_pay", pay2)}
IDL = {name: json.loads((ROOT / "idl" / f"{name}.json").read_text(encoding="utf-8")) for name in PROGRAMS}
SRC = {name: (ROOT / tree / crate / "src" / "lib.rs").read_text(encoding="utf-8") for name, (tree, crate, _) in PROGRAMS.items()}
# the second escrow lists the instructions of an order's terms (18..21, 24, 27) in the header of the file that holds them
ORDER_TERMS_RS = (ROOT / "programs-v2" / "knos_pay" / "src" / "order_terms.rs").read_text(encoding="utf-8")
CLAIMS_RS = (ROOT / "programs" / "knos_oidc" / "src" / "claims.rs").read_text(encoding="utf-8")

K = {n: Pubkey(bytes([i + 1]) * 32) for i, n in enumerate(["payer", "funder", "funder_token", "mint", "relayer", "address", "token_account",
                                                             "authority", "wallet", "guardian", "key"])}
REPO, ISSUE, AUTHOR, AMOUNT = 987654321, 7, 1234567, 5_000_000
N2048, N4096 = (1 << 2047) | 0x1234567, (1 << 4095) | 0x1234567   # odd numbers of the two key sizes: only the encoding matters
TID, CHECKS, WF_SHA = bytes(range(0xC0, 0xE0)), bytes(range(32)), "c" * 40
JWT = "eyJhbGciOiJSUzI1NiJ9." + "A" * 1000 + ".c2ln"
JOB = pay.job_pda(REPO, ISSUE, K["funder"])
ISSUER_URL = "https://oidc.ci.example.dev"       # an RS256 issuer that is neither GitHub nor GitLab

# the second escrow: a Balance of the owner's, a job funded from it and one funded by a wallet in a Token-2022 mint
OWNER, SPENDERS, T22 = 424242, [555000, 9], pay2.TOKEN_2022
TERMS = pay2.terms_json({"checks": [{"app": 15368, "name": "test"}], "mode": "merge", "v": 1})
BAL, FAUCET_BAL = pay2.balance_pda(OWNER, K["authority"], K["mint"]), pay2.faucet_balance_pda(OWNER)
JOB2, JOB2_OF_WALLET = pay2.job_pda(REPO, ISSUE, BAL), pay2.job_pda(REPO, ISSUE, K["funder"])
_JOB = dict(state="open", mode=0, faucet=False, repo_id=REPO, issue=ISSUE, amount=AMOUNT, deadline=0, hold_until=0, payee_id=AUTHOR, funder_id=0,
            not_before=0, mint=K["mint"], terms=bytes(32), wf_repo_hash=bytes(32), wf_sha=WF_SHA)
FROM_BALANCE = pay2.Job(from_balance=True, token_program=pay2.TOKEN, owner_id=OWNER, source=BAL, refund_to=pay2.baltok_pda(BAL), rent_to=K["relayer"], **_JOB)
FROM_WALLET = pay2.Job(from_balance=False, token_program=T22, owner_id=0, source=K["funder"], refund_to=K["funder"], rent_to=K["funder"], **_JOB)
PAYOUT = {"bind": pay2.bind_pda(AUTHOR), "destToken": pay2.ata(K["wallet"], K["mint"]), "rep": pay2.rep_pda(AUTHOR), "pair": pay2.pair_pda(AUTHOR, OWNER),
          "vault": pay2.vault_pda(K["mint"]), "feeToken": pay2.ata(pay2.FEE_OWNER, K["mint"]), "auth": pay2.auth_pda(), "rentTo": K["relayer"],
          "mint": K["mint"], "tokenProgram": pay2.TOKEN, "systemProgram": pay2.SYSTEM, "used": pay2.used_pda(bytes(32))}
# an order funded by a wallet, as the client reads it
_ORDER = bytearray(pay2.ORDER_LEN)
_ORDER[0:2] = bytes([2, 1])
for _at in (192, 224, 256):
    _ORDER[_at:_at + 32] = bytes(K["funder"])
_ORDER[288:320] = bytes(K["mint"])
_ORDER[152:160] = AUTHOR.to_bytes(8, "little")      # the payee a held order waits for
ORDER, ORD, OPTS = pay2.read_order(bytes(_ORDER)), pay2.order_pda(pay2.scope_of(REPO, ISSUE), K["funder"], 3), pay2.opts(pay2.F_NEUTRAL, kill_bps=500)
# the same order with a holdback (PayOrder then takes its record); in warranty with one payee recorded; cancelled while reserved (a kill fee is due)
_HELD_BACK, _KILLED = bytearray(_ORDER), bytearray(_ORDER)
_HELD_BACK[60:62] = (1000).to_bytes(2, "little")
_KILLED[62:64], _KILLED[64:72] = (500).to_bytes(2, "little"), AMOUNT.to_bytes(8, "little")
TAKER = 7654321                                     # reserved by him until 200, cancelled at 100
_KILLED[128:136], _KILLED[136:144], _KILLED[144:152] = TAKER.to_bytes(8, "little"), (200).to_bytes(8, "little"), (100).to_bytes(8, "little")
HELD_BACK, KILLED = pay2.read_order(bytes(_HELD_BACK)), pay2.read_order(bytes(_KILLED))
HB = pay2.Holdback(payer=K["relayer"], until=1_790_000_000, payees=[(AUTHOR, K["wallet"], 500_000)])
PAYOUT_22 = {**PAYOUT, "destToken": pay2.ata(K["wallet"], K["mint"], T22), "pair": pay2.pair_pda(AUTHOR, K["funder"]),
             "feeToken": pay2.ata(pay2.FEE_OWNER, K["mint"], T22), "rentTo": K["funder"], "tokenProgram": T22}
TOKEN_AND_KEY = {"relayer": K["relayer"], "key": K["key"]}


def u64s(values) -> bytes:
    return b"".join(v.to_bytes(8, "little") for v in values)


ORDER_PAYOUT = {"order": ORD, "ov": pay2.ov_pda(ORD), "tipToken": pay2.ata(K["relayer"], K["mint"]), "feeToken": pay2.ata(pay2.FEE_OWNER, K["mint"]),
                "auth": pay2.auth_pda(), "rentTo": K["funder"], "mint": K["mint"], "tokenProgram": pay2.TOKEN, "systemProgram": pay2.SYSTEM,
                "ataProgram": pay2.ATA_PROGRAM, "bind": pay2.bind_pda(AUTHOR), "wallet": K["wallet"], "destToken": pay2.ata(K["wallet"], K["mint"]),
                "rep": pay2.rep_pda(AUTHOR), "pair": pay2.pair_pda(AUTHOR, K["funder"]), "assign": pay2.assign_pda(ORD, AUTHOR)}
ORDER_AND_HB = {"order": ORD, "ov": pay2.ov_pda(ORD), "hb": pay2.hb_pda(ORD), "auth": pay2.auth_pda(), "rentTo": K["funder"], "hbPayer": K["relayer"],
                "mint": K["mint"], "tokenProgram": pay2.TOKEN}

# builder -> (IDL instruction, the instructions it builds, how many of the IDL's optional accounts they carry,
#             the arguments the data must decode to[, the address each account must be, under the IDL's name for it])
CASES = {
    "knos_oidc": {
        "write_ixs": ("Write", lambda: oidc.write_ixs(K["payer"], TID, JWT), 0,
                      [{"id": TID, "total": len(JWT), "offset": off, "chunk": JWT.encode()[off:off + oidc.CHUNK]} for off in (0, oidc.CHUNK)]),
        "step_ix": ("Step", lambda: [oidc.step_ix(K["payer"], TID, oidc.key_pda(oidc.GITHUB, N2048), 8)], 0, [{"id": TID, "squarings": 8}]),
        "close_ix": ("Close", lambda: [oidc.close_ix(K["payer"], TID)], 0, [{"id": TID}]),
        "register_key_ix": ("RegisterKey", lambda: [oidc.register_key_ix(K["payer"], oidc.GITHUB, N2048), oidc.register_key_ix(K["payer"], oidc.GITLAB, N4096)], 0,
                            [{"issuer": 0, "n": oidc.modulus_bytes(N2048)}, {"issuer": 1, "n": oidc.modulus_bytes(N4096)}]),
        "register_key_ix (attested)": ("RegisterKey", lambda: [oidc.register_key_ix(K["payer"], oidc.GITHUB, N2048, K["token_account"])], 1,
                                       [{"issuer": 0, "n": oidc.modulus_bytes(N2048)}]),
        "key_params_ix": ("KeyParams", lambda: [oidc.key_params_ix(K["payer"], oidc.GITHUB, N2048)], 0,
                          [{"n0inv": oidc.key_params(N2048)[0], "r2": oidc.key_params(N2048)[1]}]),
    },
    "knos_oidc_v2": {
        "write_ixs": ("Write", lambda: oidc2.write_ixs(K["payer"], TID, JWT), 0,
                      [{"id": TID, "total": len(JWT), "offset": off, "chunk": JWT.encode()[off:off + oidc2.CHUNK]} for off in (0, oidc2.CHUNK)]),
        "step_ix": ("Step", lambda: [oidc2.step_ix(K["payer"], TID, oidc2.key_pda(oidc2.GITHUB, N2048), 4)], 0, [{"id": TID, "squarings": 4}]),
        "close_ix": ("Close", lambda: [oidc2.close_ix(K["payer"], TID)], 0, [{"id": TID}]),
        "register_key_ix": ("RegisterKey", lambda: [oidc2.register_key_ix(K["payer"], oidc2.GITHUB, N2048), oidc2.register_key_ix(K["payer"], oidc2.GITLAB, N4096)], 0,
                            [{"issuer": 0, "n": oidc2.modulus_bytes(N2048)}, {"issuer": 1, "n": oidc2.modulus_bytes(N4096)}]),
        "register_key_ix (attested)": ("RegisterKey", lambda: [oidc2.register_key_ix(K["payer"], oidc2.GITLAB, N4096, K["token_account"], K["key"])], 2,
                                       [{"issuer": 1, "n": oidc2.modulus_bytes(N4096)}],
                                       [{"payer": K["payer"], "key": oidc2.key_pda(oidc2.GITLAB, N4096), "systemProgram": oidc2.SYSTEM, "attest": K["token_account"],
                                         "attestKey": K["key"]}]),
        "key_params_ix": ("KeyParams", lambda: [oidc2.key_params_ix(K["payer"], oidc2.GITLAB, N4096)], 0,
                          [{"n0inv": oidc2.key_params(N4096)[0], "r2": oidc2.key_params(N4096)[1]}]),
        "refresh_ix": ("Refresh", lambda: [oidc2.refresh_ix(K["payer"], oidc2.GITHUB, N2048, K["token_account"], K["key"])], 0, [{}],
                       [{"payer": K["payer"], "key": oidc2.key_pda(oidc2.GITHUB, N2048), "attest": K["token_account"], "attestKey": K["key"]}]),
        "register_issuer_key_ix": ("RegisterIssuerKey", lambda: [oidc2.register_issuer_key_ix(K["payer"], ISSUER_URL, N4096, K["token_account"], K["key"])], 0,
                                   [{"urlLen": len(ISSUER_URL), "urlAndN": ISSUER_URL.encode() + oidc2.modulus_bytes(N4096)}],
                                   [{"payer": K["payer"], "key": oidc2.key_pda(ISSUER_URL, N4096), "issuer": oidc2.iss_pda(ISSUER_URL),
                                     "systemProgram": oidc2.SYSTEM, "attest": K["token_account"], "attestKey": K["key"]}]),
        "register_private_key_ix": ("RegisterPrivateKey", lambda: [oidc2.register_private_key_ix(K["wallet"], ISSUER_URL, N2048)], 0,
                                    [{"urlLen": len(ISSUER_URL), "urlAndN": ISSUER_URL.encode() + oidc2.modulus_bytes(N2048)}],
                                    [{"registrant": K["wallet"], "key": oidc2.key_pda(ISSUER_URL, N2048, registrant=K["wallet"]), "systemProgram": oidc2.SYSTEM}]),
        "approve_ix": ("Approve", lambda: [oidc2.approve_ix(oidc2.GUARDIAN, oidc2.GITLAB, N4096)], 0, [{}]),
        "revoke_ix": ("Revoke", lambda: [oidc2.revoke_ix(oidc2.GUARDIAN, oidc2.GITHUB, N2048)], 0, [{}]),
    },
    "knos_pay": {
        "fund_ix": ("Fund", lambda: [pay.fund_ix(K["funder"], K["funder_token"], K["mint"], REPO, ISSUE, AMOUNT, "drexthealpha/Knos", WF_SHA,
                                                 mode=pay.TESTS, checks=CHECKS, work_s=7 * 86_400, review_s=86_400)], 0,
                    [{"repoId": REPO, "issue": ISSUE, "amount": AMOUNT, "work": 7 * 86_400, "review": 86_400, "mode": pay.TESTS, "checks": CHECKS,
                      "wfRepoHash": pay.wf_repo_hash("drexthealpha/Knos"), "wfSha": WF_SHA.encode()}]),
        "fund_with_token_ix": ("FundWithToken", lambda: [pay.fund_with_token_ix(K["relayer"], K["token_account"], REPO, ISSUE)], 0, [{}]),
        "pay_ix": ("Pay", lambda: [pay.pay_ix(K["relayer"], K["token_account"], JOB, AUTHOR, K["mint"], K["funder"])], 0, [{}]),
        "settle_ix": ("Settle", lambda: [pay.settle_ix(K["relayer"], JOB, AUTHOR, K["mint"], K["funder"])], 0, [{}]),
        "veto_ix": ("Veto", lambda: [pay.veto_ix(K["funder"], JOB)], 0, [{}]),
        "veto_ix (token)": ("Veto", lambda: [pay.veto_ix(K["relayer"], pay.job_pda(REPO, ISSUE), K["token_account"])], 1, [{}]),
        "refund_ix": ("Refund", lambda: [pay.refund_ix(K["relayer"], JOB, K["mint"], K["funder_token"], K["funder"])], 0, [{}]),
        "claim_ix": ("Claim", lambda: [pay.claim_ix(K["relayer"], K["token_account"], AUTHOR, K["mint"], K["address"])], 0, [{}]),
        "init_faucet_ix": ("InitFaucet", lambda: [pay.init_faucet_ix(K["payer"])], 0, [{}]),
    },
    "knos_pay_v2": {
        "open_balance_ix": ("OpenBalance", lambda: [pay2.open_balance_ix(K["authority"], OWNER, K["mint"], cap=AMOUNT, spenders=SPENDERS)], 0,
                            [{"ownerId": OWNER, "cap": AMOUNT, "spenders": u64s(SPENDERS + [0, 0])}],
                            [{"authority": K["authority"], "balance": BAL, "baltok": pay2.baltok_pda(BAL), "mint": K["mint"], "auth": pay2.auth_pda(),
                              "tokenProgram": pay2.TOKEN, "systemProgram": pay2.SYSTEM}]),
        "set_balance_ix": ("SetBalance", lambda: [pay2.set_balance_ix(K["authority"], BAL, cap=AMOUNT, spenders=SPENDERS)], 0,
                           [{"cap": AMOUNT, "spenders": u64s(SPENDERS + [0, 0])}], [{"authority": K["authority"], "balance": BAL}]),
        "withdraw_ix": ("Withdraw", lambda: [pay2.withdraw_ix(K["authority"], BAL, K["mint"], AMOUNT), pay2.withdraw_ix(K["authority"], BAL, K["mint"], 0, K["address"], T22)], 0,
                        [{"amount": AMOUNT}, {"amount": 0}],
                        [{"authority": K["authority"], "balance": BAL, "baltok": pay2.baltok_pda(BAL), "destToken": dest, "mint": K["mint"],
                          "auth": pay2.auth_pda(), "tokenProgram": program} for dest, program in ((pay2.ata(K["authority"], K["mint"]), pay2.TOKEN), (K["address"], T22))]),
        "fund_balance_ix": ("FundBalance", lambda: [pay2.fund_balance_ix(K["relayer"], K["token_account"], K["key"], BAL, K["mint"], REPO, ISSUE, TERMS, used=bytes(32))], 0,
                            [{"terms": TERMS}],
                            [{**TOKEN_AND_KEY, "fundToken": K["token_account"], "balance": BAL, "baltok": pay2.baltok_pda(BAL), "job": JOB2,
                              "vault": pay2.vault_pda(K["mint"]), "mint": K["mint"], "auth": pay2.auth_pda(), "tokenProgram": pay2.TOKEN,
                              "systemProgram": pay2.SYSTEM, "pause": pay2.pause_pda(), "used": pay2.used_pda(bytes(32))}]),
        "fund_balance_ix (a Balance with a side account)": ("FundBalance", lambda: [pay2.fund_balance_ix(
            K["relayer"], K["token_account"], K["key"], BAL, K["mint"], REPO, ISSUE, TERMS, balx=True, used=bytes(32))], 1, [{"terms": TERMS}]),
        # 2.1: work orders
        "version_ix": ("Version", lambda: [pay2.version_ix()], 0, [{}]),
        "set_balance_x_ix": ("SetBalanceX", lambda: [pay2.set_balance_x_ix(K["authority"], BAL, 30, 70, [REPO], WF_SHA)], 0,
                             [{"dayLimit": 30, "totalLimit": 70, "repos": u64s([REPO] + [0] * 7), "wfSha": WF_SHA.encode()}],
                             [{"authority": K["authority"], "balance": BAL, "balx": pay2.balx_pda(BAL), "systemProgram": pay2.SYSTEM}]),
        "set_plan_ix": ("SetPlan", lambda: [pay2.set_plan_ix(K["guardian"], K["relayer"], OWNER, 100, 1_800_000_000)], 0,
                        [{"ownerId": OWNER, "feeBps": 100, "expires": 1_800_000_000}],
                        [{"feeOwner": K["guardian"], "payer": K["relayer"], "plan": pay2.plan_pda(OWNER), "systemProgram": pay2.SYSTEM}]),
        "fund_order_wallet_ix": ("FundOrderWallet", lambda: [pay2.fund_order_wallet_ix(
            K["funder"], K["funder_token"], K["mint"], REPO, ISSUE, AMOUNT, "drexthealpha/Knos", WF_SHA, TERMS, pay2.TESTS, 7 * 86_400, 3, OPTS)], 0,
            [{"issue": ISSUE, "repoId": REPO, "amount": AMOUNT, "mode": pay2.TESTS, "work": 7 * 86_400, "seq": 3, "opts": OPTS,
              "wfRepo": pay2.wf_repo_hash("drexthealpha/Knos"), "wfSha": WF_SHA.encode(), "terms": TERMS}],
            [{"funder": K["funder"], "order": ORD, "ov": pay2.ov_pda(ORD), "funderToken": K["funder_token"], "mint": K["mint"], "auth": pay2.auth_pda(),
              "tokenProgram": pay2.TOKEN, "systemProgram": pay2.SYSTEM, "pause": pay2.pause_pda()}]),
        "fund_order_balance_ix": ("FundOrderBalance", lambda: [pay2.fund_order_balance_ix(
            K["relayer"], K["token_account"], K["key"], BAL, K["mint"], OWNER, REPO, ISSUE, TERMS, bytes(32), 3)], 0, [{"terms": TERMS}],
            [{**TOKEN_AND_KEY, "fundToken": K["token_account"], "balance": BAL, "baltok": pay2.baltok_pda(BAL), "balx": pay2.balx_pda(BAL),
              "plan": pay2.plan_pda(OWNER), "order": pay2.order_pda(pay2.scope_of(REPO, ISSUE), BAL, 3),
              "ov": pay2.ov_pda(pay2.order_pda(pay2.scope_of(REPO, ISSUE), BAL, 3)), "used": pay2.used_pda(bytes(32)), "mint": K["mint"],
              "auth": pay2.auth_pda(), "tokenProgram": pay2.TOKEN, "systemProgram": pay2.SYSTEM, "pause": pay2.pause_pda()}]),
        "fund_private_order_balance_ix": ("FundOrderBalance", lambda: [pay2.fund_private_order_balance_ix(
            K["relayer"], K["token_account"], K["key"], BAL, K["mint"], OWNER, bytes([5]) * 32, bytes([6]) * 32, bytes(32), 3)], 0,
            [{"terms": bytes([5]) * 32 + bytes([6]) * 32}],
            [{**TOKEN_AND_KEY, "fundToken": K["token_account"], "balance": BAL, "baltok": pay2.baltok_pda(BAL), "balx": pay2.balx_pda(BAL),
              "plan": pay2.plan_pda(OWNER), "order": pay2.order_pda(bytes([5]) * 32, BAL, 3), "ov": pay2.ov_pda(pay2.order_pda(bytes([5]) * 32, BAL, 3)),
              "used": pay2.used_pda(bytes(32)), "mint": K["mint"], "auth": pay2.auth_pda(), "tokenProgram": pay2.TOKEN, "systemProgram": pay2.SYSTEM,
              "pause": pay2.pause_pda()}]),
        "bind_org_ix": ("BindOrg", lambda: [pay2.bind_org_ix(K["relayer"], K["token_account"], K["key"], OWNER, used=bytes(32))], 0, [{}],
                        [{**TOKEN_AND_KEY, "bindToken": K["token_account"], "bind": pay2.bind_pda(OWNER), "systemProgram": pay2.SYSTEM, "used": pay2.used_pda(bytes(32))}]),
        "pay_order_ix": ("PayOrder", lambda: [pay2.pay_order_ix(K["relayer"], K["token_account"], K["key"], ORD, ORDER, [(AUTHOR, K["wallet"])], used=bytes(32))], 0, [{}],
                         [{**TOKEN_AND_KEY, "payToken": K["token_account"], **ORDER_PAYOUT, "used": pay2.used_pda(bytes(32))}]),
        "pay_order_ix (an order with a holdback)": ("PayOrder", lambda: [
            pay2.pay_order_ix(K["relayer"], K["token_account"], K["key"], ORD, HELD_BACK, [(AUTHOR, K["wallet"])], used=bytes(32))], 1, [{}],
            [{**TOKEN_AND_KEY, "payToken": K["token_account"], **ORDER_PAYOUT, "used": pay2.used_pda(bytes(32)), "doneOrHb": pay2.hb_pda(ORD)}]),
        "release_ix": ("Release", lambda: [pay2.release_ix(K["relayer"], ORD, ORDER, HB)], 0, [{}],
                       [{"relayer": K["relayer"], **ORDER_AND_HB, "tipToken": pay2.ata(K["relayer"], K["mint"]), "feeToken": pay2.ata(pay2.FEE_OWNER, K["mint"]),
                         "systemProgram": pay2.SYSTEM, "ataProgram": pay2.ATA_PROGRAM, "wallet": K["wallet"], "destToken": pay2.ata(K["wallet"], K["mint"])}]),
        "revert_ix": ("Revert", lambda: [pay2.revert_ix(K["relayer"], K["token_account"], K["key"], ORD, ORDER, HB, used=bytes(32))], 0, [{}],
                      [{**TOKEN_AND_KEY, "revertToken": K["token_account"], **ORDER_AND_HB, "refundToken": pay2.ata(K["funder"], K["mint"]), "systemProgram": pay2.SYSTEM,
                        "used": pay2.used_pda(bytes(32))}]),
        "reserve_ix": ("Reserve", lambda: [pay2.reserve_ix(K["relayer"], K["token_account"], K["key"], ORD, used=bytes(32))], 0, [{}],
                       [{**TOKEN_AND_KEY, "takeToken": K["token_account"], "order": ORD, "systemProgram": pay2.SYSTEM, "used": pay2.used_pda(bytes(32))}]),
        "cancel_ix": ("Cancel", lambda: [pay2.cancel_ix(K["funder"], ORD)], 0, [{}], [{"signer": K["funder"], "order": ORD}]),
        "cancel_ix (a Balance's order: a token)": ("Cancel", lambda: [pay2.cancel_ix(K["relayer"], ORD, K["token_account"], K["key"], used=bytes(32))], 4, [{}],
                                                    [{"signer": K["relayer"], "order": ORD, "cancelToken": K["token_account"], "key": K["key"], "systemProgram": pay2.SYSTEM,
                                                      "used": pay2.used_pda(bytes(32))}]),
        "assign_ix": ("Assign", lambda: [pay2.assign_ix(K["wallet"], ORD, AUTHOR, K["address"])], 0, [{"payeeId": AUTHOR, "to": bytes(K["address"])}],
                      [{"signer": K["wallet"], "order": ORD, "bind": pay2.bind_pda(AUTHOR), "assign": pay2.assign_pda(ORD, AUTHOR), "systemProgram": pay2.SYSTEM}]),
        "close_marker_ix": ("CloseMarker", lambda: [pay2.close_marker_ix(pay2.done_pda(ORD, 12), K["relayer"], ORD),
                                                    pay2.close_marker_ix(pay2.used_pda(bytes(32)), K["relayer"])], 0, [{}, {}],
                            [{"marker": pay2.done_pda(ORD, 12), "rentTo": K["relayer"], "order": ORD},
                             {"marker": pay2.used_pda(bytes(32)), "rentTo": K["relayer"], "order": pay2.SYSTEM}]),
        "settle_order_ix": ("SettleOrder", lambda: [pay2.settle_order_ix(K["relayer"], ORD, ORDER, K["wallet"])], 0, [{}], [{"relayer": K["relayer"], **ORDER_PAYOUT}]),
        "refund_order_ix": ("RefundOrder", lambda: [pay2.refund_order_ix(K["relayer"], ORD, ORDER)], 0, [{}],
                            [{"relayer": K["relayer"], "order": ORD, "ov": pay2.ov_pda(ORD), "refundToken": pay2.ata(K["funder"], K["mint"]),
                              "auth": pay2.auth_pda(), "rentTo": K["funder"], "mint": K["mint"], "tokenProgram": pay2.TOKEN}]),
        "refund_order_ix (a kill fee is due)": ("RefundOrder", lambda: [pay2.refund_order_ix(K["relayer"], ORD, KILLED, kill_token=K["address"])], 2, [{}],
                                                [{"relayer": K["relayer"], "order": ORD, "ov": pay2.ov_pda(ORD), "refundToken": pay2.ata(K["funder"], K["mint"]),
                                                  "auth": pay2.auth_pda(), "rentTo": K["funder"], "mint": K["mint"], "tokenProgram": pay2.TOKEN,
                                                  "takerBind": pay2.bind_pda(TAKER), "killToken": K["address"]}]),
        "top_up_ix": ("TopUp", lambda: [pay2.top_up_ix(K["funder"], ORD, ORDER, AMOUNT)], 0, [{"add": AMOUNT}],
                      [{"signer": K["funder"], "order": ORD, "ov": pay2.ov_pda(ORD), "fromToken": pay2.ata(K["funder"], K["mint"]), "balance": K["funder"],
                        "mint": K["mint"], "auth": pay2.auth_pda(), "tokenProgram": pay2.TOKEN, "pause": pay2.pause_pda()}]),
        "fund_wallet_ix": ("FundWallet", lambda: [pay2.fund_wallet_ix(K["funder"], K["funder_token"], K["mint"], REPO, ISSUE, AMOUNT, "drexthealpha/Knos", WF_SHA, TERMS,
                                                                     mode=pay2.TESTS, work_s=7 * 86_400, token_program=T22)], 0,
                           [{"repoId": REPO, "issue": ISSUE, "amount": AMOUNT, "work": 7 * 86_400, "mode": pay2.TESTS,
                             "wfRepoHash": pay2.wf_repo_hash("drexthealpha/Knos"), "wfSha": WF_SHA.encode(), "terms": TERMS}],
                           [{"funder": K["funder"], "job": JOB2_OF_WALLET, "funderToken": K["funder_token"], "vault": pay2.vault_pda(K["mint"]), "mint": K["mint"],
                             "auth": pay2.auth_pda(), "tokenProgram": T22, "systemProgram": pay2.SYSTEM, "pause": pay2.pause_pda()}]),
        # a Balance's job; a wallet's job in a Token-2022 mint; no wallet known, so the job will be held and the vault stands in for the destination
        "pay_ix": ("Pay", lambda: [pay2.pay_ix(K["relayer"], K["token_account"], K["key"], JOB2, FROM_BALANCE, AUTHOR, K["wallet"], used=bytes(32)),
                                   pay2.pay_ix(K["relayer"], K["token_account"], K["key"], JOB2_OF_WALLET, FROM_WALLET, AUTHOR, K["wallet"], used=bytes(32)),
                                   pay2.pay_ix(K["relayer"], K["token_account"], K["key"], JOB2, FROM_BALANCE, AUTHOR, None, used=bytes(32))], 0, [{}, {}, {}],
                   [{**TOKEN_AND_KEY, "payToken": K["token_account"], "job": JOB2, **PAYOUT},
                    {**TOKEN_AND_KEY, "payToken": K["token_account"], "job": JOB2_OF_WALLET, **PAYOUT_22},
                    {**TOKEN_AND_KEY, "payToken": K["token_account"], "job": JOB2, **PAYOUT, "destToken": pay2.vault_pda(K["mint"])}]),
        "settle_ix": ("Settle", lambda: [pay2.settle_ix(K["relayer"], JOB2, FROM_BALANCE, K["wallet"])], 0, [{}], [{"relayer": K["relayer"], "job": JOB2, **PAYOUT}]),
        "refund_ix": ("Refund", lambda: [pay2.refund_ix(K["relayer"], JOB2, FROM_BALANCE), pay2.refund_ix(K["relayer"], JOB2_OF_WALLET, FROM_WALLET)], 0, [{}, {}],
                      [{"relayer": K["relayer"], "job": JOB2, "vault": pay2.vault_pda(K["mint"]), "refundToken": pay2.baltok_pda(BAL), "auth": pay2.auth_pda(),
                        "rentTo": K["relayer"], "mint": K["mint"], "tokenProgram": pay2.TOKEN},
                       {"relayer": K["relayer"], "job": JOB2_OF_WALLET, "vault": pay2.vault_pda(K["mint"]), "refundToken": pay2.ata(K["funder"], K["mint"], T22),
                        "auth": pay2.auth_pda(), "rentTo": K["funder"], "mint": K["mint"], "tokenProgram": T22}]),
        "bind_ix": ("Bind", lambda: [pay2.bind_ix(K["relayer"], K["token_account"], K["key"], AUTHOR, used=bytes(32))], 0, [{}],
                    [{**TOKEN_AND_KEY, "bindToken": K["token_account"], "bind": pay2.bind_pda(AUTHOR), "systemProgram": pay2.SYSTEM, "used": pay2.used_pda(bytes(32))}]),
        "pause_ix": ("Pause", lambda: [pay2.pause_ix(K["guardian"], K["relayer"], 3600)], 0, [{"seconds": 3600}],
                     [{"guardian": K["guardian"], "payer": K["relayer"], "pause": pay2.pause_pda(), "systemProgram": pay2.SYSTEM}]),
        "init_faucet_ix": ("InitFaucet", lambda: [pay2.init_faucet_ix(K["relayer"])], 0, [{}],
                           [{"payer": K["relayer"], "mint": pay2.faucet_mint(), "auth": pay2.auth_pda(), "tokenProgram": pay2.TOKEN, "systemProgram": pay2.SYSTEM}]),
        "faucet_open_ix": ("FaucetOpen", lambda: [pay2.faucet_open_ix(K["relayer"], K["token_account"], K["key"], OWNER, REPO, used=bytes(32))], 0, [{}],
                           [{**TOKEN_AND_KEY, "fundToken": K["token_account"], "balance": FAUCET_BAL, "baltok": pay2.baltok_pda(FAUCET_BAL),
                             "mint": pay2.faucet_mint(), "auth": pay2.auth_pda(), "tokenProgram": pay2.TOKEN, "systemProgram": pay2.SYSTEM,
                             "rate": pay2.rate_pda(REPO), "used": pay2.used_pda(bytes(32))}]),
    },
}
NOT_THE_PROGRAMS = {"create_ata_ix"}   # an instruction of the associated token account program, not of knos-pay
MODULES = {name: client for name, (_, _, client) in PROGRAMS.items()}
FIXED = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "i64": 8, "publicKey": 32}


def size(t) -> int | None:
    """Bytes a type takes; None for `bytes`, which is raw and runs to the end."""
    if isinstance(t, dict):
        inner, count = t["array"]
        return size(inner) * count
    return FIXED.get(t)


def decode(fields: list[dict], data: bytes) -> dict:
    """`data` read as the IDL says: the fields in order, little-endian, no padding."""
    out, at = {}, 0
    for f in fields:
        n = size(f["type"])
        raw = data[at:] if n is None else data[at:at + n]
        assert len(raw) == (len(data) - at if n is None else n), f"{f['name']}: data too short"
        at += len(raw)
        out[f["name"]] = int.from_bytes(raw, "little", signed=f["type"] == "i64") if f["type"] in ("u8", "u16", "u32", "u64", "i64") else bytes(raw)
    assert at == len(data), "bytes left over"
    return out


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
        at += size(f["type"]) or 0
    return out


def layout(program: str, account: str) -> list[dict]:
    return next(a for a in IDL[program]["accounts"] if a["name"] == account)["type"]["fields"]


def constants(source: str, prefix: str, kind: str = "usize") -> dict[str, int]:
    return {m.group(1): int(m.group(2).replace("_", "")) for m in re.finditer(rf"pub const ({prefix}\w+): {kind} = ([\d_]+);", source)}


@pytest.mark.parametrize("program", list(IDL))
def test_the_address_is_the_deployed_program(program):
    tree, crate, _ = PROGRAMS[program]
    ids = json.loads((ROOT / tree / "program_ids.json").read_text())
    assert IDL[program]["metadata"] == {"origin": "shank", "address": ids[crate]}
    assert IDL[program]["name"] == program
    assert len({idl["metadata"]["address"] for idl in IDL.values()}) == len(IDL)


@pytest.mark.parametrize("program", list(IDL))
def test_every_instruction_of_the_source_is_in_the_idl(program):
    """The header comment of lib.rs lists each instruction as `<tag> <Name>`; the dispatch has one arm per tag."""
    headers = SRC[program] + (ORDER_TERMS_RS if program == "knos_pay_v2" else "")
    listed = {m.group(2): int(m.group(1)) for m in re.finditer(r"^//!   (\d+) (\w+)(?: |$)", headers, re.M)}
    # an arm is a block, or (the second escrow) a call into the module that holds the instruction
    arms = {int(m.group(1)) for m in re.finditer(r"^        (\d+) => (?:\{|\w+::\w+\()", SRC[program].split("pub fn process")[1], re.M)}
    got = {i["name"]: i["discriminant"]["value"] for i in IDL[program]["instructions"]}
    assert got == listed and set(got.values()) == arms == set(range(len(got)))
    assert [i["discriminant"]["value"] for i in IDL[program]["instructions"]] == list(range(len(got)))       # in the order of their tags
    assert all(i["discriminant"]["type"] == "u8" for i in IDL[program]["instructions"])


@pytest.mark.parametrize("program", list(IDL))
def test_every_builder_of_the_client_is_checked(program):
    builders = {n for n, f in inspect.getmembers(MODULES[program], inspect.isfunction)
                if n.endswith(("_ix", "_ixs")) and f.__module__ == MODULES[program].__name__} - NOT_THE_PROGRAMS
    assert builders == {name.split(" ")[0] for name in CASES[program]}
    assert {c[0] for c in CASES[program].values()} == {i["name"] for i in IDL[program]["instructions"]}
    # an instruction with optional accounts is built both without and with them
    for i in IDL[program]["instructions"]:
        optional = sum(1 for a in i["accounts"] if a.get("optional"))
        assert {c[2] for c in CASES[program].values() if c[0] == i["name"]} == ({0, optional} if optional else {0})


@pytest.mark.parametrize("program,case", [(p, c) for p in CASES for c in CASES[p]])
def test_the_client_builds_what_the_idl_says(program, case):
    name, build, optional, want_args, *where = CASES[program][case]
    idl = next(i for i in IDL[program]["instructions"] if i["name"] == name)
    ixs = build()
    assert len(ixs) == len(want_args) and all(len(w) == len(ixs) for w in where)
    for k, (ix, want) in enumerate(zip(ixs, want_args)):
        data = bytes(ix.data)
        assert str(ix.program_id) == IDL[program]["metadata"]["address"]
        assert data[0] == idl["discriminant"]["value"]
        required = [a for a in idl["accounts"] if not a.get("optional")]
        accounts = required + [a for a in idl["accounts"] if a.get("optional")][:optional]
        assert len(ix.accounts) == len(accounts), [a["name"] for a in accounts]
        for meta, a in zip(ix.accounts, accounts):
            assert (meta.is_signer, meta.is_writable) == (a["isSigner"], a["isMut"]), a["name"]
            # where the case says it: the account the IDL gives this name is at the address the name means
            assert not where or meta.pubkey == where[0][k][a["name"]], a["name"]
        # optional accounts come last: the program reads them only after the others
        assert all(a.get("optional") for a in idl["accounts"][len(required):])
        assert decode(idl["args"], data[1:]) == want


def test_fund_data_is_the_145_bytes_the_program_requires():
    fund = next(i for i in IDL["knos_pay"]["instructions"] if i["name"] == "Fund")
    assert sum(size(a["type"]) for a in fund["args"]) == 145 and "rest.len() != 145" in SRC["knos_pay"]
    for name in ("FundWithToken", "Pay", "Settle", "Veto", "Refund", "Claim", "InitFaucet"):
        assert next(i for i in IDL["knos_pay"]["instructions"] if i["name"] == name)["args"] == []


def test_account_sizes_are_the_ones_the_programs_and_the_readers_use():
    lens = constants(SRC["knos_pay"], "")
    sizes = {a["name"]: sum(size(f["type"]) for f in a["type"]["fields"]) for a in IDL["knos_pay"]["accounts"]}
    assert sizes == {"Job": 256, "Due": 48, "Rep": 32, "Rate": 16}
    assert sizes == {"Job": lens["JOB_LEN"], "Due": lens["DUE_LEN"], "Rep": lens["REP_LEN"], "Rate": lens["RATE_LEN"]}
    # the Python readers take exactly these sizes and nothing else
    assert pay.read_job(bytes(256)) is not None and pay.read_job(bytes(255)) is None and pay.read_job(bytes(257)) is None
    due = (5).to_bytes(8, "little") + bytes(40)
    assert pay.read_due(due) == 5 and pay.read_due(due + b"\0") == 0 and pay.read_due(due[:-1]) == 0
    rep = (3).to_bytes(4, "little") + bytes(28)
    assert pay.read_rep(rep).paid_jobs == 3 and pay.read_rep(rep + b"\0").paid_jobs == 0
    # knos-oidc's accounts are a fixed header, then bytes
    t, k = constants(SRC["knos_oidc"], "T_"), constants(SRC["knos_oidc"], "K_")
    assert sum(size(f["type"]) or 0 for f in layout("knos_oidc", "Token")) == t["T_JWT"] == oidc.T_JWT == 626
    assert sum(size(f["type"]) or 0 for f in layout("knos_oidc", "Key")) == k["K_HDR"] == 8
    assert [f["name"] for f in layout("knos_oidc", "Token") if size(f["type"]) is None] == ["jwt"]
    # the second deployment: the same token account; the key's header grew from 8 bytes to 40
    t2, k2 = constants(SRC["knos_oidc_v2"], "T_"), constants(SRC["knos_oidc_v2"], "K_")
    assert layout("knos_oidc_v2", "Token") == layout("knos_oidc", "Token") and t2 == t and oidc2.T_JWT == 626
    assert sum(size(f["type"]) or 0 for f in layout("knos_oidc_v2", "Key")) == k2["K_HDR"] == oidc2.K_HDR == 40
    assert [f["name"] for f in layout("knos_oidc_v2", "Key") if size(f["type"]) is None] == ["nAndR2"]
    for limbs in (64, 128):
        key = bytes([1, 0, limbs]) + bytes(37 + 8 * limbs)
        assert oidc2.read_key(key).bits == 32 * limbs and oidc2.read_key(key + b"\0") is None and oidc2.read_key(key[:-1]) is None


def test_field_offsets_are_the_constants_of_the_source():
    j = constants(SRC["knos_pay"], "J_")
    names = {"J_STATE": "state", "J_MODE": "mode", "J_KIND": "kind", "J_REPO": "repoId", "J_ISSUE": "issue", "J_AMOUNT": "amount",
             "J_DEADLINE": "deadline", "J_REVIEW": "review", "J_PAY_AFTER": "payAfter", "J_AUTHOR": "authorId", "J_FUNDER_ID": "funderId",
             "J_NOT_BEFORE": "notBefore", "J_VETOES": "vetoes", "J_FUNDER": "funder", "J_MINT": "mint", "J_CHECKS": "checks",
             "J_WF_REPO": "wfRepoHash", "J_WF_SHA": "wfSha"}
    assert set(names) == set(j)
    at = offsets(layout("knos_pay", "Job"))
    assert {c: at[f] for c, f in names.items()} == j
    assert set(at) - set(names.values()) == {"padding0", "padding1"}
    # the times are signed: the fields the source reads or writes as i64, and no others
    signed = {names[c] for pair in re.findall(r"i64_at\(&d, (J_\w+)\)|put_i64\(&mut d, (J_\w+),", SRC["knos_pay"]) for c in pair if c}
    assert signed == {"deadline", "review", "payAfter", "notBefore"} == {f["name"] for f in layout("knos_pay", "Job") if f["type"] == "i64"}
    assert [f["type"] for f in layout("knos_pay", "Rate")] == ["i64", "i64"]
    assert {f["name"] for f in layout("knos_oidc", "Token") if f["type"] == "i64"} == {"exp"} and "exp: i64" in SRC["knos_oidc"]
    t = constants(SRC["knos_oidc"], "T_")
    names = {"T_STAGE": "stage", "T_ISSUER": "issuer", "T_DONE": "squaringsDone", "T_LIMBS": "limbs", "T_LEN": "jwtLen", "T_POFF": "payloadOff",
             "T_PLEN": "payloadLen", "T_EXP": "exp", "T_KEY": "key", "T_PAYER": "payer", "T_ID": "id", "T_X": "x", "T_JWT": "jwt"}
    assert set(names) == set(t)
    at = offsets(layout("knos_oidc", "Token"))
    assert {c: at[f] for c, f in names.items()} == t and set(at) == set(names.values())
    # the second deployment's key header: every K_ constant of the source is the offset of an IDL field
    k = constants(SRC["knos_oidc_v2"], "K_")
    names = {"K_STATE": "state", "K_ISSUER": "issuer", "K_LIMBS": "limbs", "K_BUMP": "bump", "K_N0INV": "n0inv", "K_ACTIVE": "activeAt",
             "K_EXPIRES": "expiresAt", "K_FLAGS": "flags", "K_HDR": "nAndR2"}
    assert set(names) == set(k)
    at = offsets(layout("knos_oidc_v2", "Key"))
    assert {c: at[f] for c, f in names.items()} == k and set(at) - set(names.values()) == {"padding"}
    signed = {names[c] for pair in re.findall(r"i64_at\(&d, (K_\w+)\)|put_i64\(&mut d, (K_\w+),", SRC["knos_oidc_v2"]) for c in pair if c}
    assert signed == {"activeAt", "expiresAt"} == {f["name"] for f in layout("knos_oidc_v2", "Key") if f["type"] == "i64"}
    flags = constants(SRC["knos_oidc_v2"], "F_", "u8")
    assert flags == {"F_APPROVED": oidc2.APPROVED, "F_REVOKED": oidc2.REVOKED, "F_GENESIS": oidc2.GENESIS, "F_PRIVATE": oidc2.PRIVATE_FLAG} == {
        "F_APPROVED": 1, "F_REVOKED": 2, "F_GENESIS": 4, "F_PRIVATE": 8}
    assert "flags: 1 approved by the guardian, 2 revoked, 4 genesis" in " ".join(next(a for a in IDL["knos_oidc_v2"]["accounts"] if a["name"] == "Key")["docs"])


def test_accounts_written_as_the_idl_says_are_read_by_the_client():
    """Each field gets its own value, the bytes are laid out by the IDL, and the Python readers find every value."""
    v = {"state": 2, "mode": 1, "kind": 1, "repoId": REPO, "issue": ISSUE, "amount": AMOUNT, "deadline": 1_790_000_100, "review": 86_400,
         "payAfter": -5, "authorId": AUTHOR, "funderId": 424242, "notBefore": 1_790_000_000, "vetoes": 3, "funder": bytes(K["funder"]),
         "mint": bytes(K["mint"]), "checks": CHECKS, "wfRepoHash": pay.wf_repo_hash("drexthealpha/Knos"), "wfSha": WF_SHA.encode()}
    job = pay.read_job(encode(layout("knos_pay", "Job"), v))
    assert job == pay.Job(state="proven", mode=1, token_funded=True, repo_id=REPO, issue=ISSUE, amount=AMOUNT, deadline=1_790_000_100,
                          review=86_400, pay_after=-5, author_id=AUTHOR, funder_id=424242, not_before=1_790_000_000, vetoes=3,
                          funder=K["funder"], mint=K["mint"], checks=CHECKS, wf_repo_hash=v["wfRepoHash"], wf_sha=WF_SHA)
    assert pay.read_due(encode(layout("knos_pay", "Due"), {"amount": 4_875_000, "userId": AUTHOR, "mint": bytes(K["mint"])})) == 4_875_000
    rep = pay.read_rep(encode(layout("knos_pay", "Rep"), {"paidJobs": 9, "vetoed": 1, "totalPaid": 77_000_000, "repositories": 4, "lastRepo": REPO}))
    assert rep == pay.Record(paid_jobs=9, total_paid=77_000_000, repositories=4)
    payload = b'{"aud":"x"}'
    tok = oidc.read_token(encode(layout("knos_oidc", "Token"), {
        "stage": 2, "issuer": 1, "squaringsDone": 16, "limbs": 64, "jwtLen": 40, "payloadOff": 626 + 4, "payloadLen": len(payload), "exp": 1_790_000_300,
        "key": bytes(K["address"]), "payer": bytes(K["payer"]), "id": TID, "x": bytes(512), "jwt": b"head" + payload + bytes(25)}))
    assert (tok.verified, tok.issuer, tok.done, tok.exp, tok.key, tok.payer, tok.payload) == (True, 1, 16, 1_790_000_300, K["address"], K["payer"], payload)
    # the second deployment: the same token bytes read the same, and a key account's header
    assert oidc2.read_token(encode(layout("knos_oidc_v2", "Token"), {
        "stage": 2, "issuer": 1, "squaringsDone": 16, "limbs": 64, "jwtLen": 40, "payloadOff": 626 + 4, "payloadLen": len(payload), "exp": 1_790_000_300,
        "key": bytes(K["address"]), "payer": bytes(K["payer"]), "id": TID, "x": bytes(512), "jwt": b"head" + payload + bytes(25)})) == tok
    header = {"state": 1, "issuer": 1, "limbs": 128, "bump": 254, "n0inv": 0xDEADBEEF, "activeAt": 1_790_086_400, "expiresAt": -7, "padding": bytes(15),
              "nAndR2": bytes(1024)}
    for flags, (approved, revoked, genesis) in ((0, (False, False, False)), (1, (True, False, False)), (2, (False, True, False)),
                                                (4, (False, False, True)), (5, (True, False, True)), (7, (True, True, True))):
        assert oidc2.read_key(encode(layout("knos_oidc_v2", "Key"), {**header, "flags": flags})) == oidc2.Key(
            state=1, issuer=1, bits=4096, active_at=1_790_086_400, expires_at=-7, approved=approved, revoked=revoked, genesis=genesis)
    # a key of any other issuer, and a private key: 64 more bytes after R^2, the issuer's hash and the registrant
    ih = oidc2.issuer_hash(ISSUER_URL)
    other = encode(layout("knos_oidc_v2", "Key"), {**header, "issuer": oidc2.OTHER, "flags": 1, "nAndR2": bytes(1024) + ih + bytes(32)})
    assert oidc2.read_key(other) == oidc2.Key(state=1, issuer=2, bits=4096, active_at=1_790_086_400, expires_at=-7, approved=True, revoked=False,
                                              genesis=False, issuer_hash=ih)
    assert oidc2.read_key(other[:-64]) is None and oidc2.read_key(encode(layout("knos_oidc_v2", "Key"), {**header, "nAndR2": bytes(1024 + 64)})) is None
    private = encode(layout("knos_oidc_v2", "Key"), {**header, "issuer": oidc2.PRIVATE, "flags": oidc2.PRIVATE_FLAG, "nAndR2": bytes(1024) + ih + bytes(K["wallet"])})
    assert oidc2.read_key(private) == oidc2.Key(state=1, issuer=3, bits=4096, active_at=1_790_086_400, expires_at=-7, approved=False, revoked=False,
                                                genesis=False, issuer_hash=ih, private=True, registrant=K["wallet"])
    assert oidc2.key_usable(oidc2.read_key(private[:16] + (2 ** 62).to_bytes(8, "little") + private[24:]), 1_790_086_400) == (True, "")   # no approval asked
    # the token accounts they verify carry the same two values where the running power was
    marked = encode(layout("knos_oidc_v2", "Token"), {
        "stage": 2, "issuer": 3, "squaringsDone": 16, "limbs": 64, "jwtLen": 40, "payloadOff": 626 + 4, "payloadLen": len(payload), "exp": 1_790_000_300,
        "key": bytes(K["address"]), "payer": bytes(K["payer"]), "id": TID, "x": ih + bytes(K["wallet"]) + bytes(448), "jwt": b"head" + payload + bytes(25)})
    assert oidc2.token_issuer(marked) == (ih, K["wallet"]) and oidc2.read_token(marked).issuer == oidc2.PRIVATE
    assert oidc2.token_issuer(bytes([2, 2]) + marked[2:]) == (ih, K["wallet"]) and oidc2.token_issuer(bytes([2, 1]) + marked[2:]) is None
    assert oidc2.read_iss(encode(layout("knos_oidc_v2", "Issuer"), {"state": 3, "bump": 255, "zero": 0, "urlLen": len(ISSUER_URL), "url": ISSUER_URL.encode()})) == ISSUER_URL


def test_every_error_code_of_the_source_is_in_the_idl():
    claims = set(constants(CLAIMS_RS, "E_", "u32").values())
    assert claims == {60, 61, 62, 63}
    # knos-pay reads claims with knos-oidc's reader; the second escrow also refuses a token whose key is no longer usable
    # with the code knos-oidc's own rule (key_usable) gives
    theirs = constants(SRC["knos_oidc_v2"], "E_", "u32")
    stale_key = {theirs[name] for name in re.findall(r"Err\((E_\w+)\)", SRC["knos_oidc_v2"].split("pub fn key_usable(")[1].split("\n}")[0])}
    assert stale_key == {76, 77, 78}
    assert "knos_oidc::key_usable(" in (ROOT / "programs-v2" / "knos_pay" / "src" / "gh.rs").read_text(encoding="utf-8")
    for program, extra in (("knos_oidc", claims), ("knos_pay", claims), ("knos_oidc_v2", claims), ("knos_pay_v2", claims | stale_key)):
        errors = IDL[program]["errors"]
        codes = [e["code"] for e in errors]
        assert set(codes) == set(constants(SRC[program], "E_", "u32").values()) | extra
        assert codes == sorted(set(codes)) and len({e["name"] for e in errors}) == len(errors) and all(e["msg"] for e in errors)
    assert set(pay.ERRORS) <= {e["code"] for e in IDL["knos_pay"]["errors"]}
    assert set(pay2.ERRORS) == {e["code"] for e in IDL["knos_pay_v2"]["errors"]} - claims
    # the escrow's own codes are all in lib.rs: no other file of it defines one
    for path in (ROOT / "programs-v2" / "knos_pay" / "src").glob("*.rs"):
        assert path.name == "lib.rs" or not constants(path.read_text(encoding="utf-8"), "E_", "u32"), path.name
    # a code the second escrow passes on has the name the second verifier's IDL gives it
    named = {e["code"]: e["name"] for e in IDL["knos_oidc_v2"]["errors"]}
    assert {e["code"]: e["name"] for e in IDL["knos_pay_v2"]["errors"] if e["code"] < 80} == {c: named[c] for c in claims | stale_key}
    # the second verifier keeps every code of the first with its name, and adds four
    first, second = ({e["code"]: e["name"] for e in IDL[p]["errors"]} for p in ("knos_oidc", "knos_oidc_v2"))
    assert {c: n for c, n in second.items() if c in first} == first
    assert {c: n for c, n in second.items() if c not in first} == {76: "KeyNotActive", 77: "KeyExpired", 78: "KeyRevoked", 79: "NotGuardian"}


def test_the_second_verifier_keeps_the_first_ones_token_instructions_byte_for_byte():
    """Write, Step, Close, RegisterKey and KeyParams have the same discriminant, accounts and arguments in both IDLs
    (another program's client sends them to either deployment), and the new instructions come after them."""
    first, second = ({i["name"]: i for i in IDL[p]["instructions"]} for p in ("knos_oidc", "knos_oidc_v2"))
    wire = lambda i: ([(a["name"], a["isMut"], a["isSigner"], a.get("optional", False)) for a in i["accounts"]], i["args"], i["discriminant"])  # noqa: E731
    assert list(second)[:len(first)] == list(first) == ["Write", "Step", "Close", "RegisterKey", "KeyParams"]
    for name in first:
        accounts, args, tag = wire(second[name])
        # RegisterKey also takes the key account that verified the attestation, after the first deployment's accounts
        added = [("attestKey", False, False, True)] if name == "RegisterKey" else []
        assert (accounts[:len(accounts) - len(added)], args, tag) == wire(first[name]) and accounts[len(accounts) - len(added):] == added, name
    assert [(n, second[n]["discriminant"]["value"], second[n]["args"]) for n in list(second)[len(first):]] == [
        ("Refresh", 5, []), ("Approve", 6, []), ("Revoke", 7, []), ("RegisterIssuerKey", 8, [{"name": "urlLen", "type": "u8"}, {"name": "urlAndN", "type": "bytes"}]),
        ("RegisterPrivateKey", 9, [{"name": "urlLen", "type": "u8"}, {"name": "urlAndN", "type": "bytes"}])]
    # and the Python client of the second deployment builds them with the first one's builders
    p = K["payer"]
    for a, b in ((oidc2.write_ixs(p, TID, JWT)[0], oidc.write_ixs(p, TID, JWT, program=oidc2.OIDC_ID)[0]),
                 (oidc2.step_ix(p, TID, K["address"], 3), oidc.step_ix(p, TID, K["address"], 3, program=oidc2.OIDC_ID)),
                 (oidc2.close_ix(p, TID), oidc.close_ix(p, TID, program=oidc2.OIDC_ID)),
                 (oidc2.register_key_ix(p, 1, N4096, K["token_account"]), oidc.register_key_ix(p, 1, N4096, K["token_account"], program=oidc2.OIDC_ID)),
                 (oidc2.key_params_ix(p, 0, N2048), oidc.key_params_ix(p, 0, N2048, program=oidc2.OIDC_ID))):
        assert (a.program_id, bytes(a.data), a.accounts) == (b.program_id, bytes(b.data), b.accounts)
    assert oidc2.step_plan(4096) == oidc.step_plan(4096) == [2, 3, 3, 3, 4, 1] and oidc2.step_plan(2048) == [8, 8]
    # the plan the IDLs and the sources' header comments give is the one the clients send
    for text in (" ".join(first["Step"]["docs"]), " ".join(second["Step"]["docs"]), SRC["knos_oidc_v2"]):
        assert "Step(2), Step(3) three times, Step(4), Step(1)" in " ".join(text.replace("//!", " ").split())


def test_the_idl_has_the_shape_shank_writes():
    for idl in IDL.values():
        assert set(idl) == {"version", "name", "docs", "instructions", "accounts", "errors", "metadata"}
        for i in idl["instructions"]:
            assert set(i) == {"name", "docs", "accounts", "args", "discriminant"}
            assert all({"name", "isMut", "isSigner"} <= set(a) <= {"name", "isMut", "isSigner", "desc", "optional"} for a in i["accounts"])
            assert all(set(a) == {"name", "type"} for a in i["args"])
            assert len({a["name"] for a in i["accounts"]}) == len(i["accounts"])
        for a in idl["accounts"]:
            assert a["type"]["kind"] == "struct" and all(set(f) == {"name", "type"} for f in a["type"]["fields"])
        types = [x["type"] for i in idl["instructions"] for x in i["args"]] + [f["type"] for a in idl["accounts"] for f in a["type"]["fields"]]
        assert all(t == "bytes" or size(t) for t in types)
