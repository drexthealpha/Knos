"""The steps of scripts/deploy_v2.sh that are transactions of the two programs, not calls of the solana command.

    python scripts/deploy_v2.py [--rpc URL] [--payer FILE] <step>

    cluster         which cluster the endpoint is: devnet, testnet, mainnet-beta or local
    hash FILE       the executable hash of a program file, as solana-verify prints it
    id NAME         the pinned address of knos_oidc, knos_pay, knos_meter, knos_passkey or upgrade_gate
    program NAME    a program (one of those names, or an address) as the chain has it: "absent", or
                    "<executable hash> <upgrade authority, or none>"
    buffer ADDRESS  a program buffer as the chain has it: "absent", or "<executable hash> <its authority, or none>"
    room NAME       how many bytes of program the data account of NAME can hold: a build larger than that cannot be
                    upgraded to until the account is extended
    extend NAME N   the upgradeable loader's ExtendProgram: N more bytes for NAME's data account, their rent paid by the
                    fee payer. It changes no code, and anyone may send it while the cluster has not activated
                    ExtendProgramChecked (devnet on 4 October 2026: `solana feature status` lists it inactive); once that
                    is active only the upgrade authority can extend, which here is the upgrade vault. Exit 6 when the
                    cluster refuses it
    gate NAME FILE [TOKEN]   whether the upgrade gate holds a record that GitHub built FILE for NAME. With TOKEN (a file
                    holding the token program.yml asked GitHub for, audience gate:<program>:<hash>), a missing record
                    is written. With --wait SECONDS a record that is not there yet is waited for (program.yml's gate
                    job and a relayer write it). Exit 0 recorded, 3 the gate is not deployed here, 4 no record
    rc-ids OIDC PAY OUT   write the staging ids file a client reads through KNOS_PROGRAM_IDS
    schedule OUT FILE...  join what `governance.mjs upgrade propose --out` wrote for each program into the one file
                    scripts/schedule_upgrade.sh reads, and print when the upgrades can be executed
    stale [--replace] NAME=HASH...   the upgrade proposals that can still run and would deploy another build of NAME than
                    HASH (this build's executable hash), one per line: "<index> <program> <its build's hash> <Squads status>".
                    Without --replace, exit 5 and say so when there is one: nothing may be proposed beside it. With
                    --replace they are listed for scripts/deploy_v2.sh to withdraw (node scripts/governance.mjs cancel)
    kept NAME=HASH  the buffer of the newest proposal that can still run and carries exactly this build of NAME, or
                    nothing: deploy_v2.sh proposes with that buffer, so governance.mjs continues that proposal
                    and never makes a second one for the same build
    summary-new     one line about knos_meter, knos_passkey and upgrade_gate. Exit 1 unless all three are deployed
                    and held by the upgrade vault
    faucet          InitFaucet: the escrow's test-USDC mint
    keys            RegisterKey and KeyParams for each of GitHub's four genesis keys
    fee-account     the fee owner's token account for the faucet's mint
    addresses       every address of the deployment, each with what it is
    transactions C  every transaction on chain that touches one of those addresses, oldest first (C: the cluster the
                    cluster step printed, for explorer links)
    summary         one line: what is on chain now. Exit 1 unless the deployment is complete

Each step reads the chain first and sends only what is missing, so each can be run again after a failure. The four
genesis keys are the keys of GitHub's key set as committed on 2 Oct 2026 (tests/fixtures) whose sha256 is a GENESIS
constant of programs-v2/knos_oidc/src/pins.rs: the program takes exactly those without an attestation. A key lives 30
days from the day it is registered; after that the rotate workflow's Refresh keeps it alive.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from oidc_pins import genesis  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from knos import chain  # noqa: E402
from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import gate, oidc, pay, relay  # noqa: E402

JWKS = ROOT / "tests" / "fixtures" / "github_jwks_2026-10-02.json"
PINS = ROOT / "programs-v2" / "knos_oidc" / "src" / "pins.rs"
CLUSTERS = {"EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG": "devnet", "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY": "testnet",
            "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d": "mainnet-beta"}


NEW = ("knos_meter", "knos_passkey", "upgrade_gate")         # what 0.3.13 deploys for the first time
UPGRADED = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")     # what --propose proposes: every program the upgrade vault holds
LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"


def program_id(name: str) -> str:
    """The address of a program: its pinned one by name (a staging file named by KNOS_PROGRAM_IDS replaces the four it
    may), or the address itself."""
    if name == "upgrade_gate":
        return str(gate.GATE_ID)
    if name in pay.IDS and name.startswith("knos_"):
        return pay.IDS[name]
    try:
        return str(Pubkey.from_string(name))
    except ValueError:
        raise SystemExit(f"{name} is neither a program of this deployment (knos_oidc, knos_pay, knos_meter, knos_passkey, upgrade_gate) nor an address") from None


def when(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def genesis_keys(jwks: dict | None = None, pins: str | None = None) -> list[tuple[str, int]]:
    """(kid, modulus) of each GitHub key the second deployment's verifier takes without an attestation."""
    want = {h for issuer, h in genesis(PINS.read_text(encoding="utf-8") if pins is None else pins) if issuer == oidc.GITHUB}
    have = {oidc.key_hash(n).hex(): (kid, n) for kid, n in oidc.jwks_keys(json.loads(JWKS.read_text(encoding="utf-8")) if jwks is None else jwks)}
    missing = sorted(want - set(have))
    if missing:
        raise SystemExit(f"refused: {JWKS.name} has no key whose sha256 is {', '.join(missing)}, a GENESIS constant of pins.rs. Nothing was sent.")
    return [have[h] for h in sorted(want)]


def program_state(ledger, name: str) -> tuple[str, str | None] | None:
    """(executable hash, upgrade authority or None) of a program as the chain has it; None when it is not deployed."""
    def account(address: str):
        data = ledger.account(Pubkey.from_string(address))
        return None if data is None else ("", data)
    deployed, authority, elf = mc.program_data(account, program_id(name))
    return (mc.elf_hash(elf), authority) if deployed else None


def room(ledger, name: str) -> int | None:
    """How many bytes of program the data account of `name` holds room for; None when it is not deployed. The loader
    refuses an Upgrade whose buffer is larger."""
    data = ledger.account(mc.programdata_address(program_id(name)))
    return None if data is None or len(data) < mc.PROGRAMDATA_HEADER else len(data) - mc.PROGRAMDATA_HEADER


def extend_ix(program: str, payer: Pubkey, more: int):
    """The upgradeable loader's ExtendProgram (variant 6, additional_bytes u32): programdata(w) program(w) system
    payer(s,w). The payer pays the rent of the bytes added."""
    from solders.instruction import AccountMeta, Instruction
    if not 0 < more < 2 ** 32:
        raise SystemExit(f"refused: a program is extended by 1 to {2 ** 32 - 1} bytes, not by {more}.")
    return Instruction(Pubkey.from_string(LOADER), (6).to_bytes(4, "little") + more.to_bytes(4, "little"),
                       [AccountMeta(mc.programdata_address(program), False, True), AccountMeta(Pubkey.from_string(program), False, True),
                        AccountMeta(Pubkey.from_string("11111111111111111111111111111111"), False, False), AccountMeta(payer, True, True)])


def buffer_state(ledger, address: str) -> tuple[str, str | None] | None:
    """(executable hash, authority or None) of a program buffer; None when the account is not one. A buffer that is
    half written has the hash of what is there so far, which is not the build's."""
    data = ledger.account(Pubkey.from_string(address))
    if not data or len(data) < gate.BUFFER_HEADER or data[:4] != (1).to_bytes(4, "little"):
        return None
    return mc.elf_hash(data[gate.BUFFER_HEADER:]), (str(Pubkey.from_bytes(data[5:37])) if data[4] == 1 else None)


def gate_record(ledger, name: str, elf: bytes, payer: Keypair | None = None, jwt: str | None = None, say=print) -> int:
    """0 when the upgrade gate holds a record that GitHub built these bytes for the program, 3 when the gate is not
    deployed on this cluster, 4 when it is and holds no record. With a token and a payer, a missing record is written
    first: the token is verified on chain by knos-oidc, then handed to the gate."""
    program, h = Pubkey.from_string(program_id(name)), gate.executable_hash(elf)
    at = gate.record_pda(program, h)
    if program_state(ledger, "upgrade_gate") is None:
        say(f"  upgrade gate: not deployed on this cluster ({gate.GATE_ID}), so no record of {name}'s build can exist")
        return 3
    rec = gate.read_record(ledger.account(at))
    if rec is None and jwt and payer is not None:
        done = relay.verify_only(ledger, payer, jwt)
        if not done.get("ok"):
            say(f"  upgrade gate: the token for {name} could not be verified on chain ({done.get('error') or done}). No record was written")
            return 4
        key = oidc.read_token(ledger.account(Pubkey.from_string(done["account"]))).key
        say(f"  upgrade gate: record written: {ledger.send([gate.record_ix(payer.pubkey(), Pubkey.from_string(done['account']), key, program, h)], payer)}")
        rec = gate.read_record(ledger.account(at))
    if rec is None or rec.executable != h:
        say(f"  upgrade gate: NO record that GitHub built {h.hex()} for {name} ({at} does not exist)")
        return 4
    say(f"  upgrade gate: GitHub's runner built {h.hex()} for {name} from commit {rec.sha} (run {rec.run_id}, record {at})")
    return 0


def gate_awaited(ledger, name: str, elf: bytes, payer: Keypair | None = None, jwt: str | None = None, wait: float = 0, every: float = 15, say=print,
                 sleep=time.sleep, clock=time.monotonic) -> int:
    """`gate_record`, asked again every `every` seconds for up to `wait` seconds while the gate is there and the record
    is not: program.yml's gate job asks GitHub for the token after the verified builds, and a relayer carries it, so a
    record of a build that was just pushed is still on its way. Says once that it waits, and at the end what is so."""
    said: list[str] = []
    rc = gate_record(ledger, name, elf, payer, jwt, said.append)
    end = clock() + wait
    if rc == 4 and wait > 0:
        say(f"  upgrade gate: no record of this build of {name} yet. Waiting up to {round(wait)} seconds for it: program.yml's gate job has GitHub sign "
            f"the hash of each build it makes on main or a release tag ({gate.WORKFLOW}), and a relayer carries that to the gate. Asking every {round(every)} seconds")
    while rc == 4 and clock() < end:
        sleep(min(every, max(0.0, end - clock())))
        said.clear()
        try:
            rc = gate_record(ledger, name, elf, say=said.append)
        except (OSError, chain.RpcError) as why:    # the cluster did not answer this once: asked again
            said.append(f"  upgrade gate: the cluster did not answer ({type(why).__name__}); NO record that GitHub built this build of {name} was read")
    for line in said:
        say(line)
    return rc


def rc_ids(oidc_id: str, pay_id: str) -> dict:
    """The staging ids file: the pinned file with the two staging programs in place of the real ones, and a line that
    says what it is. Every other value is the pinned one: the programs' own constants cannot be staged."""
    for address in (oidc_id, pay_id):
        Pubkey.from_string(address)
    pinned = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    if oidc_id == pinned["knos_oidc"] or pay_id == pinned["knos_pay"] or oidc_id == pay_id:
        raise SystemExit("refused: a staging program must have an address of its own, not a pinned one. Nothing was written.")
    return {**pinned, "knos_oidc": oidc_id, "knos_pay": pay_id,
            "staging": "A STAGING deployment (scripts/deploy_v2.sh --rc): the 2.1 builds under ids of their own, for rehearsal. Not the pinned programs."}


def schedule(parts: list[dict], rpc: str, wait: int = 600) -> dict:
    """What scripts/schedule_upgrade.sh reads: each proposal, and the one time at which all of them can be executed (the
    latest of their times) plus `wait` seconds, so the run does not start on the very second the time lock ends."""
    if not parts:
        raise SystemExit("refused: no proposal was given, so there is nothing to schedule.")
    waiting = [p for p in parts if not p.get("executable_from")]
    if waiting:
        raise SystemExit("refused: " + ", ".join(f"proposal {p.get('index')} ({p.get('program')})" for p in waiting) + " is not approved yet, so its 48 hours "
                         "have not started. Another member approves with: node scripts/governance.mjs approve upgrade <index> --member FILE. Then run --propose again.")
    last = max(int(p["executable_from"]) for p in parts)
    return {"rpc": rpc, "executable_from": last, "executable_from_utc": when(last), "run_at": last + wait, "run_at_utc": when(last + wait),
            "proposals": sorted(({k: p[k] for k in ("program", "address", "buffer", "hash", "index", "approved_at", "executable_from")} for p in parts),
                                key=lambda p: int(p["index"]))}


def older(entries: list[dict], builds: dict[str, str]) -> list[dict]:
    """The upgrade proposals that can still run and would deploy another build than this one, lowest index first.
    `entries`: scripts/upgrade_feed.py's (its `pending` is a draft, an active or an approved proposal above the
    multisig's stale index). `builds`: this build's executable hash by program name. A proposal whose buffer cannot be
    read is not known to be this build, so it counts."""
    return sorted((e for e in entries if e["status"] == "pending" and e["program"] in builds and e.get("build_hash") != builds[e["program"]]),
                  key=lambda e: int(e["index"]))


def replace_plan(entries: list[dict], builds: dict[str, str], replace: bool) -> tuple[list[dict], str | None]:
    """(the proposals to withdraw before this build is proposed, the refusal). Without `replace` an older proposal
    that can still run is a refusal and nothing is withdrawn: two approved proposals for one program would both
    execute, and the later execution wins whatever was meant. With it, each is listed to be withdrawn first."""
    found = older(entries, builds)
    if not found or replace:
        return found, None
    said = "; ".join(f"proposal {e['index']} ({e['program']}, build {e.get('build_hash') or 'unknown: its buffer cannot be read'}, "
                     + (f"approved: it can be executed from {when(e['earliest_execution'])}" if e.get("earliest_execution") else f"{e['squads_status'].lower()}: it can still be approved")
                     + ")" for e in found)
    return [], (f"refused: {said} would deploy another build than this one. Nothing was proposed. To withdraw "
                f"{'it' if len(found) == 1 else 'them'} and propose this build in {'its' if len(found) == 1 else 'their'} place, pass --replace: "
                "bash scripts/deploy_v2.sh --propose --replace")


def kept(entries: list[dict], name: str, build: str) -> str | None:
    """The buffer of the newest proposal that can still run and would deploy exactly `build` of `name`; None when
    there is none. It is this build's own proposal, made by an earlier run (perhaps from another buffer file)."""
    mine = [e for e in entries if e["status"] == "pending" and e["program"] == name and e.get("build_hash") == build]
    return max(mine, key=lambda e: int(e["index"]))["buffer"] if mine else None


def builds_of(pairs: list[str]) -> dict[str, str]:
    """{program: executable hash} from NAME=HASH arguments."""
    out = dict(p.split("=", 1) for p in pairs if "=" in p)
    bad = [p for p in pairs if "=" not in p] + [n for n, h in out.items() if n not in UPGRADED or len(h) != 64]
    if bad or not out:
        raise SystemExit(f"stale takes NAME=HASH for programs among {', '.join(UPGRADED)} (got {' '.join(pairs) or 'nothing'})")
    return out


def summary_new(ledger) -> tuple[bool, str]:
    """(complete, one line) for the programs 0.3.13 deploys for the first time."""
    vault, ok, said = pay.IDS["upgrade_authority"], True, []
    for name in NEW:
        state = program_state(ledger, name)
        ok &= state is not None and state[1] == vault
        said.append(f"{name} {program_id(name)} is not deployed" if state is None else
                    f"{name} {program_id(name)} runs the build {state[0]}, and its upgrade authority is "
                    + ("the upgrade vault " + vault if state[1] == vault else f"{state[1] or 'none'}, NOT the upgrade vault {vault}"))
    return ok, "on chain now: " + "; ".join(said) + "."


def init_faucet(ledger, payer: Keypair, say=print) -> Pubkey:
    mint = pay.faucet_mint()
    if ledger.account(mint) is None:
        say(f"  InitFaucet: {ledger.send([pay.init_faucet_ix(payer.pubkey())], payer)}")
    else:
        say("  the faucet mint exists already")
    return mint


def register_keys(ledger, payer: Keypair, keys: list[tuple[str, int]], say=print) -> list[oidc.Key]:
    """Every key registered (RegisterKey) and ready (KeyParams). Returns each key as the chain has it afterwards."""
    out = []
    for kid, n in keys:
        address = oidc.key_pda(oidc.GITHUB, n)
        if oidc.read_key(ledger.account(address)) is None:
            say(f"  RegisterKey {kid}: {ledger.send([oidc.register_key_ix(payer.pubkey(), oidc.GITHUB, n)], payer)}")
        if oidc.read_key(ledger.account(address)).state == 0:
            say(f"  KeyParams {kid}: {ledger.send([oidc.key_params_ix(payer.pubkey(), oidc.GITHUB, n)], payer)}")
        key = oidc.read_key(ledger.account(address))
        say(f"  key {kid} ({address}): ready, verifies until {when(key.expires_at)}")
        out.append(key)
    return out


def fee_account(ledger, payer: Keypair, say=print) -> Pubkey:
    mint = pay.faucet_mint()
    account = pay.ata(pay.FEE_OWNER, mint)
    if ledger.account(account) is None:
        say(f"  the fee owner's token account: {ledger.send([pay.create_ata_ix(payer.pubkey(), pay.FEE_OWNER, mint)], payer)}")
    else:
        say("  the fee owner's token account exists already")
    return account


def summary(ledger, keys: list[tuple[str, int]]) -> tuple[bool, str]:
    """(complete, one line that says what is on chain now)."""
    vault, ok, said = pay.IDS["upgrade_authority"], True, []
    for name in ("knos_oidc", "knos_pay"):
        state = program_state(ledger, name)
        ok &= state is not None and state[1] == vault
        said.append(f"{name} {pay.IDS[name]} is not deployed" if state is None else
                    f"{name} {pay.IDS[name]} runs the build {state[0]}, and its upgrade authority is "
                    + ("the upgrade vault " + vault if state[1] == vault else f"{state[1] or 'none'}, NOT the upgrade vault {vault}"))
    mint, now = pay.faucet_mint(), ledger.now()
    have_mint, have_fee = ledger.account(mint) is not None, ledger.account(pay.ata(pay.FEE_OWNER, mint)) is not None
    said.append(f"the faucet mint {mint} " + ("exists" if have_mint else "does not exist"))
    usable = [k for k in (oidc.read_key(ledger.account(oidc.key_pda(oidc.GITHUB, n))) for _kid, n in keys) if oidc.key_usable(k, now)[0]]
    said.append(f"{len(usable)} of GitHub's {len(keys)} genesis keys verify" + (f" (the first expires {when(min(k.expires_at for k in usable))})" if usable else ""))
    said.append("the fee owner's token account " + ("exists" if have_fee else "does not exist"))
    ok &= have_mint and have_fee and len(usable) == len(keys)
    return ok, "on chain now: " + "; ".join(said) + "."


def addresses(keys: list[tuple[str, int]]) -> list[tuple[str, str]]:
    """(what it is, its address) for everything the deployment is made of."""
    ids, mint = pay.IDS, pay.faucet_mint()
    out = []
    for name in ("knos_oidc", "knos_pay"):
        out += [(f"{name} program", ids[name]), (f"{name} program data (its bytes and upgrade authority)", str(mc.programdata_address(ids[name])))]
    out += [("upgrade multisig (Squads v4, time lock 172800 s)", ids["upgrade_multisig"]), ("upgrade vault (the programs' upgrade authority)", ids["upgrade_authority"]),
            ("guardian multisig (Squads v4, time lock 0)", ids["guardian_multisig"]), ("guardian vault (the GUARDIAN both programs name)", ids["guardian"]),
            ("test-USDC mint of the faucet", str(mint)), ("fee owner", ids["fee_owner"]), ("fee owner's token account", str(pay.ata(pay.FEE_OWNER, mint))),
            ("pause account of knos_pay", str(pay.pause_pda()))]
    out += [(f"GitHub key {kid[:8]}", str(oidc.key_pda(oidc.GITHUB, n))) for kid, n in keys]
    return out


def transactions(url: str, found: list[tuple[str, str]], cluster: str = "") -> list[str]:
    """One line per transaction on chain that touches one of the addresses, oldest first: when, its signature, whether it
    worked, which of the addresses it touched, and (on a public cluster) where to read it."""
    seen: dict[str, tuple[int, int, bool, list[str]]] = {}
    for what, address in found:
        # 60 s a call: a fork asks mainnet-beta's endpoint about an address it has no history of, which can take 10 s
        for row in chain.call(url, "getSignaturesForAddress", [address, {"limit": 200, "commitment": "confirmed"}], timeout=60) or []:
            seen.setdefault(row["signature"], (row["slot"], row.get("blockTime") or 0, row["err"] is None, []))[3].append(what)
    suffix = {"devnet": "?cluster=devnet", "testnet": "?cluster=testnet", "mainnet-beta": ""}.get(cluster)
    out = []
    for sig, (slot, at, ok, touched) in sorted(seen.items(), key=lambda kv: (kv[1][0], kv[0])):
        link = f"  https://explorer.solana.com/tx/{sig}{suffix}" if suffix is not None else ""
        out.append(f"{when(at) if at else f'slot {slot}'}  {sig}  {'ok' if ok else 'FAILED'}  touches {', '.join(touched)}{link}")
    return out


def retrying(step, tries: int = 4, pause: float = 5.0, say=print):
    """Runs a step, and again (up to `tries` times) when the cluster did not answer in time: a public endpoint at its rate limit
    or a fork reading an account for the first time does that. Safe because a step reads the chain first and sends only what
    is missing. A refusal by a program (its answer comes with its logs) is not asked again."""
    for n in range(1, tries + 1):
        try:
            return step()
        except (TimeoutError, OSError, chain.RpcError) as why:
            if n == tries or (isinstance(why, chain.RpcError) and isinstance(why.data, dict) and why.data.get("logs")):
                raise
            say(f"  no answer from the cluster ({why}); the chain is read again and what is missing sent, in {pause:g} seconds (try {n + 1} of {tries})")
            time.sleep(pause)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rpc", default="https://api.devnet.solana.com")
    ap.add_argument("--payer", type=Path, help="the fee payer's keypair file")
    ap.add_argument("--wait", type=float, default=0, help="gate: seconds to wait for a record that is not there yet")
    ap.add_argument("--replace", action="store_true", help="stale: list the older proposals to withdraw instead of refusing")
    ap.add_argument("step", choices=["cluster", "hash", "id", "program", "buffer", "gate", "rc-ids", "schedule", "stale", "kept", "room", "extend", "faucet", "keys", "fee-account",
                                     "addresses", "transactions", "summary", "summary-new"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("more", nargs="*")
    a = ap.parse_args(argv)
    if a.step == "hash":
        print(mc.elf_hash(Path(a.arg).read_bytes()))
        return 0
    if a.step == "id":
        print(program_id(a.arg))
        return 0
    if a.step == "rc-ids":
        out = Path(a.more[1])
        out.write_text(json.dumps(rc_ids(a.arg, a.more[0]), indent=2) + "\n", encoding="utf-8")
        print(f"  wrote {out}: knos_oidc {a.arg}, knos_pay {a.more[0]} (staging)")
        return 0
    if a.step == "schedule":
        plan = schedule([json.loads(Path(f).read_text(encoding="utf-8")) for f in a.more], a.rpc)
        Path(a.arg).write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        n = len(plan["proposals"])
        print(f"  {'the upgrade' if n == 1 else f'all {n} upgrades'} can be executed from {plan['executable_from_utc']}; the scheduler runs "
              f"{'it' if n == 1 else 'them'} at {plan['run_at_utc']} ({a.arg})")
        return 0
    if a.step in ("stale", "kept"):
        import upgrade_feed                                     # the one reader of the multisig's proposals and their buffers
        builds = builds_of([a.arg, *a.more] if a.arg else [])
        ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
        _ms, got = retrying(lambda: upgrade_feed.entries(mc._rpc(a.rpc), ids), say=lambda line: print(line, file=sys.stderr))   # stdout is the list
        if a.step == "kept":
            if len(builds) != 1:
                raise SystemExit("kept takes one NAME=HASH")
            (name, build), = builds.items()
            print(kept([vars(e) for e in got], name, build) or "")
            return 0
        withdraw, refusal = replace_plan([vars(e) for e in got], builds, a.replace)
        if refusal:
            print(refusal, file=sys.stderr)
            return 5
        for e in withdraw:
            print(f"{e['index']} {e['program']} {e.get('build_hash') or 'unknown'} {e['squads_status']}")
        return 0
    ledger = chain.Ledger(a.rpc)
    if a.step == "cluster":
        print(CLUSTERS.get(chain.call(a.rpc, "getGenesisHash", []), "local"))
        return 0
    if a.step in ("program", "buffer"):
        state = program_state(ledger, a.arg) if a.step == "program" else buffer_state(ledger, a.arg)
        print("absent" if state is None else f"{state[0]} {state[1] or 'none'}")
        return 0
    if a.step == "room":
        have = room(ledger, a.arg)
        print("absent" if have is None else have)
        return 0
    if a.step == "extend":
        payer = Keypair.from_bytes(bytes(json.loads(a.payer.read_text(encoding="utf-8"))))
        before, more = room(ledger, a.arg), int(a.more[0])
        try:
            sig = ledger.send([extend_ix(program_id(a.arg), payer.pubkey(), more)], payer)
        except chain.RpcError as why:
            print(f"  the cluster refused to extend {a.arg} by {more} bytes: {str(why)[:300]}", file=sys.stderr)
            return 6
        print(f"  {a.arg}: its data account holds room for {room(ledger, a.arg)} bytes of program now (before: {before}): {sig}")
        return 0
    if a.step == "gate":
        jwt = Path(a.more[1]).read_text(encoding="utf-8").strip() if len(a.more) > 1 else None
        payer = Keypair.from_bytes(bytes(json.loads(a.payer.read_text(encoding="utf-8")))) if jwt and a.payer else None
        return retrying(lambda: gate_awaited(ledger, a.arg, Path(a.more[0]).read_bytes(), payer, jwt, a.wait))
    if a.step == "summary-new":
        ok, line = summary_new(ledger)
        print(line)
        return 0 if ok else 1
    if a.step in ("addresses", "transactions"):
        found = addresses(genesis_keys())
        if a.step == "addresses":
            width = max(len(what) for what, _ in found)
            print("\n".join(f"  {what.ljust(width)}  {address}" for what, address in found))
        else:
            lines = retrying(lambda: transactions(a.rpc, found, (a.arg or "").split(" ")[0]))
            print("\n".join(f"  {line}" for line in lines) if lines else "  none yet")
        return 0
    if a.step == "summary":
        ok, line = summary(ledger, genesis_keys())
        print(line)
        return 0 if ok else 1
    payer = Keypair.from_bytes(bytes(json.loads(a.payer.read_text(encoding="utf-8"))))
    if a.step == "faucet":
        retrying(lambda: init_faucet(ledger, payer))
    elif a.step == "keys":
        retrying(lambda: register_keys(ledger, payer, genesis_keys()))
    else:
        retrying(lambda: fee_account(ledger, payer))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (chain.RpcError, TimeoutError, OSError) as why:
        print(f"failed: {why}. Run the same command again: each step continues where it stopped.", file=sys.stderr)
        raise SystemExit(1) from None
