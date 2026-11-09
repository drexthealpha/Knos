"""Pay after proof from any source: the client side of knos_pay 0.3.34 (programs-v2/knos_pay/src/{issuers,cs,orcid,order_proof}.rs).

Three ways an order is released besides a forge workflow:

* ATTESTED: the order pins a container image digest; a Google Confidential Space attestation token (RS256, issuer
  https://confidentialcomputing.googleapis.com) whose ``submods.container.image_digest`` is that digest and whose
  audience is ``proof_audience(...)`` pays it through PayOrder (knos.settle.v2.pay.pay_order_ix, unchanged).
* PANEL: the order pins m of n referee Ed25519 keys; each referee signs ``verdict_digest(...)``; PayOrderVerdict
  counts distinct signatures through Solana's Ed25519 precompile, records them below m and pays at m.
* ORCID: a researcher binds an ORCID iD to a wallet (BindOrcid) with an id_token whose nonce is
  ``knos3:bind:<wallet>``; proofs and verdicts then name the payee by iD.

Nothing here holds a key. Referee keys sign where they live; this module builds bytes and instructions.
"""
from __future__ import annotations

import hashlib

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from knos.settle.v2 import pay

CS_ISSUER = "https://confidentialcomputing.googleapis.com"   # its discovery document's "issuer", fetched 14 Oct 2026
ORCID_ISSUER = "https://orcid.org"                            # likewise
ED25519_ID = Pubkey.from_string("Ed25519SigVerify111111111111111111111111111")
INSTRUCTIONS = Pubkey.from_string("Sysvar1nstructions1111111111111111111111111")

FORGE, ATTESTED, PANEL = 0, 1, 2
O_JUDGE, O_PIN = 448, 456          # in the order account (order_proof.rs)
MAX_REFEREES = 10
VOTE_LEN = 80
OR_BASE = 10 ** 18                 # ORCID payee ids: OR_BASE + the iD's first fifteen digits
ORCID_LIFE = 86_400
TEST_ORCID_CLIENT = "APP-KNOSTEST00000001"   # the client id a testkeys build accepts (orcid.rs); a real build pins Knos's own


# -- ORCID ---------------------------------------------------------------------------------------------------------
def orcid_check(digits15: str) -> str:
    """ISO 7064 MOD 11-2, as ORCID documents its check character."""
    total = 0
    for c in digits15:
        total = (total + int(c)) * 2
    r = (12 - total % 11) % 11
    return "X" if r == 10 else str(r)


def orcid_id(orcid: str) -> int:
    """The payee id of an ORCID iD "dddd-dddd-dddd-dddC"; ValueError for a malformed iD or a wrong check character."""
    parts = orcid.split("-")
    if len(orcid) != 19 or len(parts) != 4 or not all(len(p) == 4 for p in parts):
        raise ValueError(f"not an ORCID iD: {orcid!r}")
    digits = "".join(parts)[:15]
    if not digits.isdigit() or orcid_check(digits) != orcid[-1]:
        raise ValueError(f"not an ORCID iD (check character): {orcid!r}")
    return OR_BASE + int(digits)


def orcid_of(payee_id: int) -> str | None:
    """The ORCID iD behind a payee id, or None when the id is not in the ORCID range."""
    if not OR_BASE <= payee_id < OR_BASE + 10 ** 15:
        return None
    d = f"{payee_id - OR_BASE:015d}"
    full = d + orcid_check(d)
    return "-".join(full[i:i + 4] for i in range(0, 16, 4))


def bind_nonce(wallet: Pubkey | str) -> str:
    """The nonce Knos's ORCID sign-in sends: ORCID returns it in the id_token, and BindOrcid binds that wallet."""
    return f"knos3:bind:{wallet}"


def bind_orcid_ix(relayer: Pubkey, id_token: Pubkey, key: Pubkey, orcid: str, used: Pubkey | str | bytes,
                  program: Pubkey = pay.PAY_ID) -> Instruction:
    """Bind (8) with an ORCID id_token. `id_token`: the knos-oidc token account of the verified ORCID id_token; `key` the key account it
    names; `used` the token's marker (pay.used_pda(jwt))."""
    marker = used if isinstance(used, Pubkey) else pay.used_pda(used, program)
    return Instruction(program, bytes([8]), [AccountMeta(relayer, True, True), AccountMeta(id_token, False, False), AccountMeta(key, False, False),
                                             AccountMeta(pay.bind_pda(orcid_id(orcid), program), False, True), AccountMeta(pay.SYSTEM, False, False),
                                             AccountMeta(marker, False, True)])


# -- payees and audiences ----------------------------------------------------------------------------------------------
def payees_text(payees) -> str:
    """`payees`: 1..=4 of (GitHub id or ORCID iD, basis points, address or None)."""
    return ",".join(f"{i}.{bps}.{a if a is not None else '-'}" for i, bps, a in payees)


def payee_id(p: int | str) -> int:
    return orcid_id(p) if isinstance(p, str) else int(p)


def proof_audience(order: Pubkey, evidence: bytes, terms: bytes, payees) -> str:
    """What a Confidential Space judge asks its launcher to put in the token's audience (at most 512 bytes)."""
    aud = f"knos3:proof:{order}:{evidence.hex()}:{terms.hex()}:{payees_text(payees)}"
    if len(aud.encode()) > 512:
        raise ValueError("a Confidential Space audience is at most 512 bytes")
    return aud


def cs_claims(image_digest: bytes, aud: str, iat: int, life: int = 3600, **over) -> dict:
    """The claims of a Confidential Space token as Google documents them (token-claims reference, read 14 Oct 2026).
    For tests with a TEST issuer key only: Google signs the real ones."""
    c = {"aud": aud, "iss": CS_ISSUER, "iat": iat, "nbf": iat, "exp": iat + life, "sub": "https://www.googleapis.com/compute/v1/projects/p/zones/z/instances/1",
         "eat_nonce": ["knos-test-nonce-0001"], "secboot": True, "oemid": 11129, "hwmodel": "GCP_INTEL_TDX", "swname": "CONFIDENTIAL_SPACE",
         "swversion": ["20260900"], "dbgstat": "disabled-since-boot",
         "submods": {"confidential_space": {"support_attributes": ["LATEST", "STABLE", "USABLE"]},
                     "container": {"image_reference": "us-docker.pkg.dev/knos-test/judges/judge:1", "image_digest": "sha256:" + image_digest.hex(),
                                   "restart_policy": "Never", "image_id": "sha256:" + "0" * 64, "env": {}, "args": ["/judge"]},
                     "gce": {"zone": "us-central1-a", "project_id": "knos-test", "project_number": "1", "instance_name": "judge", "instance_id": "1"}},
         "google_service_accounts": ["judge@knos-test.iam.gserviceaccount.com"]}
    c.update(over)
    return c


def orcid_claims(orcid: str, client: str, wallet: Pubkey | str, iat: int, **over) -> dict:
    """The claims of an ORCID id_token as ORCID's guide shows them. For tests with a TEST issuer key only."""
    c = {"aud": client, "sub": orcid, "auth_time": iat - 10, "iss": ORCID_ISSUER, "exp": iat + ORCID_LIFE, "iat": iat,
         "nonce": bind_nonce(wallet), "jti": f"orcid-test-{iat}"}
    c.update(over)
    return c


# -- orders that pin a judge -----------------------------------------------------------------------------------------
def panel_bytes(m: int, keys: list[bytes]) -> bytes:
    if not 1 <= m <= len(keys) <= MAX_REFEREES or len(set(keys)) != len(keys) or any(len(k) != 32 for k in keys):
        raise ValueError("a panel is 1 <= m <= n <= 10 distinct 32-byte keys")
    return bytes([m, len(keys)]) + b"".join(keys)


def panel_pin(m: int, keys: list[bytes]) -> bytes:
    return hashlib.sha256(b"knos3:panel" + panel_bytes(m, keys)).digest()


def judge_of(data: bytes | None) -> tuple[int, bytes] | None:
    """(judge kind, pin) of an order account: FORGE for every order of an earlier build."""
    if not data or len(data) != pay.ORDER_LEN:
        return None
    return data[O_JUDGE], bytes(data[O_PIN:O_PIN + 32])


def topic_id(topic: str | bytes) -> int:
    """A judged order's `repo_id`: a nonzero number of at most 18 digits named by the idea it funds (not a repository)."""
    b = topic.encode() if isinstance(topic, str) else topic
    return int.from_bytes(hashlib.sha256(b"knos3:topic" + b).digest()[:8], "little") % (10 ** 18 - 1) + 1


def judged_opts(kind: int, grace: bool = False) -> bytes:
    """The 48 option bytes of a judged order: byte 35 is the judge (1 ATTESTED, 2 PANEL), byte 33 the grace."""
    o = bytearray(pay.opts(grace=grace))
    o[35] = kind
    return bytes(o)


def fund_order_judged_ix(funder: Pubkey, funder_token: Pubkey, mint: Pubkey, topic: int, issue: int, amount: int, terms: bytes, *,
                         image_digest: bytes | None = None, panel: tuple[int, list[bytes]] | None = None, work_s: int = 14 * 86_400, seq: int = 0,
                         grace: bool = False, token_program: Pubkey = pay.TOKEN, program: Pubkey = pay.PAY_ID) -> Instruction:
    """FundOrderWallet (15) of an order judged by a container image (`image_digest`, 32 bytes) or by a referee panel
    (`panel` = (m, keys); only its hash goes on chain, so the client checks it). `topic` (topic_id) and `issue` name
    the order's scope; `terms`: the terms JSON (logged, its hash stored). Mode 1; workflows commit forty '0'."""
    if (image_digest is None) == (panel is None):
        raise ValueError("an order pins an image or a panel")
    if topic == 0:
        raise ValueError("a judged order's topic id is not 0")
    if image_digest is not None:
        kind, pin = ATTESTED, image_digest
    else:
        assert panel is not None        # exactly one of the two is given (checked above)
        kind, pin = PANEL, panel_pin(*panel)
    if len(pin) != 32:
        raise ValueError("an image digest is 32 bytes")
    order = pay.order_pda(pay.scope_of(topic, issue), funder, seq, program)
    data = (b"\x0f" + issue.to_bytes(8, "little") + topic.to_bytes(8, "little") + amount.to_bytes(8, "little") + b"\x01"
            + work_s.to_bytes(8, "little", signed=True) + seq.to_bytes(4, "little") + judged_opts(kind, grace) + pin + b"0" * 40 + terms)
    return Instruction(program, data,
                       [AccountMeta(funder, True, True), AccountMeta(order, False, True), AccountMeta(pay.ov_pda(order, program), False, True),
                        AccountMeta(funder_token, False, True), AccountMeta(mint, False, False), AccountMeta(pay.auth_pda(program), False, False),
                        AccountMeta(token_program, False, False), AccountMeta(pay.SYSTEM, False, False), AccountMeta(pay.pause_pda(program), False, False)])


def verdict_digest(order: Pubkey, o: pay.Order, evidence: bytes, payees, program: Pubkey = pay.PAY_ID) -> bytes:
    """What each referee signs (Ed25519, the 32 bytes themselves): sha256("knos3:verdict" || program || order ||
    stamp i64 LE || terms hash || evidence || payees text), or "FAIL" in the payees' place for a FAIL verdict. The
    stamp changes with every funding of the address."""
    text = FAIL if payees in ("FAIL", FAIL) else payees_text(payees).encode()
    return hashlib.sha256(b"knos3:verdict" + bytes(program) + bytes(order) + o.stamp.to_bytes(8, "little", signed=True) + o.terms + evidence + text).digest()


FAIL = b"FAIL"     # what the referees sign in the payees' place for a FAIL verdict (order_proof.rs FAIL)


def vote_pda(order: Pubkey, digest: bytes, program: Pubkey = pay.PAY_ID) -> Pubkey:
    return Pubkey.find_program_address([b"vd", bytes(order), digest], program)[0]


def read_vote(data: bytes | None) -> dict | None:
    if not data or len(data) != VOTE_LEN:
        return None
    return {"payer": Pubkey.from_bytes(data[0:32]), "order": Pubkey.from_bytes(data[32:64]), "inc": int.from_bytes(data[64:72], "little"),
            "bits": int.from_bytes(data[72:76], "little")}


def ed25519_ix(signatures: list[tuple[bytes, bytes]], message: bytes) -> Instruction:
    """One Ed25519 precompile instruction verifying each (public key, signature) over `message`, every part in its
    own data (instruction index 0xFFFF), the message once. The program counts only entries laid out this way."""
    n = len(signatures)
    head = 2 + 14 * n
    body, offsets = b"", b""
    msg_at = head + 96 * n
    for k, (key, sig) in enumerate(signatures):
        sig_at, key_at = head + 96 * k, head + 96 * k + 64
        body += sig + key
        offsets += b"".join(v.to_bytes(2, "little") for v in (sig_at, 0xFFFF, key_at, 0xFFFF, msg_at, len(message), 0xFFFF))
    return Instruction(ED25519_ID, bytes([n, 0]) + offsets + body + message, [])


def pay_order_proof_ix(relayer: Pubkey, cs_token: Pubkey, key: Pubkey, order: Pubkey, o: pay.Order, payees, used, wallets=None,
                       tip_token: Pubkey | None = None, program: Pubkey = pay.PAY_ID) -> Instruction:
    """PayOrder (17) of an ATTESTED order: the Confidential Space token account and its key in the token's place."""
    ws = wallets or [a for _, _, a in payees]
    return pay.pay_order_ix(relayer, cs_token, key, order, o, [(payee_id(p), w) for (p, _, _), w in zip(payees, ws)], tip_token, program, used=used)


def pay_order_verdict_ix(relayer: Pubkey, order: Pubkey, o: pay.Order, m: int, keys: list[bytes], evidence: bytes, payees,
                         wallets=None, tip_token: Pubkey | None = None, program: Pubkey = pay.PAY_ID, fee_token: Pubkey | None = None) -> Instruction:
    """PayOrder (17) WITH data: a referee panel's PASS. `payees` as payees_text takes them (ids may be ORCID iDs);
    `wallets`: per payee the wallet it will be paid at (pay.order_destination), default the address it carries. The
    token's place holds the instructions sysvar, the key's the verdict's tally; `used` is not read (the system
    program stands there). Put the referees' ed25519_ix in the same transaction."""
    digest = verdict_digest(order, o, evidence, payees, program)
    ws = wallets or [a for _, _, a in payees]
    per = [m_ for (p, _, _), w in zip(payees, ws) for m_ in pay._payee_accounts(o, payee_id(p), w, None, program)]
    asg = [AccountMeta(pay.assign_pda(order, payee_id(p), program), False, False) for p, _, _ in payees]
    return Instruction(program, b"\x11" + panel_bytes(m, keys) + evidence + payees_text(payees).encode(),
                       [AccountMeta(relayer, True, True), AccountMeta(INSTRUCTIONS, False, False), AccountMeta(vote_pda(order, digest, program), False, True),
                        *pay._order_common(relayer, order, o, tip_token, program, fee_token), AccountMeta(pay.SYSTEM, False, False), *per, *asg])


def refund_order_verdict_ix(relayer: Pubkey, order: Pubkey, o: pay.Order, m: int, keys: list[bytes], evidence: bytes, refund_token: Pubkey | None = None,
                            program: Pubkey = pay.PAY_ID) -> Instruction:
    """RefundOrder (22) WITH data: m referees signed verdict_digest(order, o, evidence, "FAIL"); everything the order
    holds goes back to the funding wallet now. Put the referees' ed25519_ix in the same transaction."""
    digest = verdict_digest(order, o, evidence, "FAIL", program)
    dest = refund_token if refund_token is not None else pay.ata(o.refund_to, o.mint, o.token_program)
    return Instruction(program, b"\x16" + panel_bytes(m, keys) + evidence,
                       [AccountMeta(relayer, True, True), AccountMeta(order, False, True), AccountMeta(pay.ov_pda(order, program), False, True),
                        AccountMeta(dest, False, True), AccountMeta(pay.auth_pda(program), False, False), AccountMeta(o.rent_to, False, True),
                        AccountMeta(o.mint, False, False), AccountMeta(o.token_program, False, False), AccountMeta(INSTRUCTIONS, False, False),
                        AccountMeta(pay.SYSTEM, False, False), AccountMeta(vote_pda(order, digest, program), False, True)])
