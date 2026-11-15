"""`knos budget set <agent> 5/day --chain tempo` and `knos budget set <agent> 20 --chain solana`: budgets the chain
enforces, even if the agent or Knos is compromised.

Keys:
  - the root money keys (Tempo budget account, Solana vault owner) are encrypted at rest (knos.keystore) and
    unlocked only by a passphrase typed at a terminal: an agent cannot unlock them;
  - each agent's own key (Tempo access key, Solana delegate) is a hot, owner-only file the agent signs with. It can
    spend only what the chain lets it: the Keychain limit per period on Tempo, the delegated amount on Solana.

Uninstalling Knos does not remove a limit: it lives on chain until `knos budget revoke`.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import keystore, paths

NETWORKS = {"tempo": ("moderato", "mainnet"), "solana": ("devnet", "mainnet", "localnet")}
TEMPO_TOKENS = {"moderato": {"pathUSD": "0x20c0000000000000000000000000000000000000",
                             "AlphaUSD": "0x20c0000000000000000000000000000000000001"},
                "mainnet": {"pathUSD": "0x20c0000000000000000000000000000000000000",
                            "USDC.e": "0x20C000000000000000000000b9537d11c60E8b50"}}


class BudgetError(Exception):
    pass


def root() -> Path:
    d = paths.home() / "budget"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path() -> Path:
    return root() / "chain.json"


def load_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(s: dict) -> None:
    keystore.write_private(state_path(), json.dumps(s, indent=1))


def parse_amount(text: str) -> tuple[float, int]:
    """'5/day' -> (5.0, 86400); '20' -> (20.0, 0). Periods: day, week, month (30 days)."""
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*(day|week|month))?\s*", text or "")
    if not m:
        raise BudgetError(f"not an amount: {text!r} (examples: 5/day, 20)")
    period = {"day": 86_400, "week": 7 * 86_400, "month": 30 * 86_400}.get(m.group(2) or "", 0)
    return float(m.group(1)), period


def _root_keystore(chain: str) -> Path:
    return root() / f"{chain}-root.keystore"


def _unlock_or_create(chain: str, network: str, make, ask=None, ask_new=None) -> bytes:
    p = _root_keystore(chain)
    if p.exists():
        pw = (ask or (lambda path, cl: keystore.ask(path, cl, f"{chain} budget passphrase: ")))(p, network)
        return keystore.load(p, pw)
    if make is None:
        raise BudgetError(f"no {chain} budget key on this machine: nothing to revoke")
    secret = make()
    pw = (ask_new or (lambda path, cl: keystore.ask(path, cl, f"New passphrase for the {chain} budget key: ",
                                                     confirm=True)))(p, network)
    keystore.save(p, secret, pw, label=f"knos {chain} budget root")
    return secret


def agent_key_path(agent: str, chain: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", agent)[:40]
    d = paths.home() / "wallets"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}-{chain}-limited.json"


# ---- Tempo -------------------------------------------------------------------------------------------------------

def tempo_set(agent: str, amount: float, period: int, network: str = "moderato", token_name: str = "pathUSD",
              ask=None, ask_new=None) -> dict:
    from eth_account import Account

    from . import tempo_keys as tk
    chain_id, url = tk.CHAINS[network]
    token = TEMPO_TOKENS[network][token_name]
    root_key = _unlock_or_create("tempo", network, lambda: bytes(Account.create().key), ask, ask_new)
    root_acct = Account.from_key(root_key)
    kp = agent_key_path(agent, "tempo")
    if kp.exists():
        agent_acct = Account.from_key(json.loads(kp.read_text(encoding="utf-8"))["key"])
    else:
        agent_acct = Account.create()
        keystore.write_private(kp, json.dumps({"key": agent_acct.key.hex(), "address": agent_acct.address,
                                               "root": root_acct.address, "network": network}))
    units = int(round(amount * 10 ** tk.DECIMALS))
    sent = tk.authorize(url, chain_id, root_key.hex(), agent_acct.address, token, units, period_s=period or 0)
    if not sent.ok:
        raise BudgetError(f"Tempo did not accept the key: {sent.status}. The budget account {root_acct.address} "
                          "must hold some of the token for fees.")
    s = load_state()
    s.setdefault("agents", {})[f"{agent}@tempo"] = {"chain": "tempo", "network": network, "token": token,
                                                    "root": root_acct.address, "key": agent_acct.address,
                                                    "amount": amount, "period": period, "tx": sent.tx,
                                                    "set_at": int(time.time())}
    save_state(s)
    return s["agents"][f"{agent}@tempo"]


def tempo_show(entry: dict) -> dict:
    from . import tempo_keys as tk
    _, url = tk.CHAINS[entry["network"]]
    left, ends = tk.remaining(url, entry["root"], entry["key"], entry["token"])
    return {"remaining": left / 10 ** tk.DECIMALS, "period_ends": ends}


def tempo_revoke(entry: dict, ask=None) -> str:
    from . import tempo_keys as tk
    chain_id, url = tk.CHAINS[entry["network"]]
    root_key = _unlock_or_create("tempo", entry["network"], None, ask)
    sent = tk.revoke(url, chain_id, root_key.hex(), entry["key"], entry["token"])
    if not sent.ok:
        raise BudgetError(f"not revoked: {sent.status}")
    return sent.tx


# ---- Solana ------------------------------------------------------------------------------------------------------

def _sol_url(network: str) -> str:
    from ..team import rpc
    return rpc.CLUSTERS[network]


def solana_set(agent: str, amount: float, network: str = "devnet", mint: str | None = None, decimals: int = 6,
               ask=None, ask_new=None) -> dict:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey

    from ..team import rpc
    from . import sol_budget as sb
    url = _sol_url(network)
    mint_pk = Pubkey.from_string(mint or sb.USDC.get(network, ""))
    owner = Keypair.from_bytes(_unlock_or_create("solana", network, lambda: bytes(Keypair()), ask, ask_new))
    kp = agent_key_path(agent, "solana")
    if kp.exists():
        agent_key = Keypair.from_bytes(bytes(json.loads(kp.read_text(encoding="utf-8"))["key"]))
    else:
        agent_key = Keypair()
        keystore.write_private(kp, json.dumps({"key": list(bytes(agent_key)), "address": str(agent_key.pubkey())}))
    s = load_state()
    entry = s.get("agents", {}).get(f"{agent}@solana")
    ixs = []
    if entry and entry.get("vault"):
        vault = Pubkey.from_string(entry["vault"])
        signers = []
    else:
        v = Keypair()
        vault = v.pubkey()
        ixs += sb.new_vault_ixs(url, owner.pubkey(), owner.pubkey(), v, mint_pk)
        signers = [v]
    units = int(round(amount * 10 ** decimals))
    ixs.append(sb.approve_checked(vault, mint_pk, agent_key.pubkey(), owner.pubkey(), units, decimals))
    try:
        sig = rpc.send(url, ixs, owner, signers)
    except rpc.RpcError as e:
        raise BudgetError(f"Solana did not accept it: {e}. The vault key {owner.pubkey()} needs a little SOL for "
                          "rent and fees.") from None
    entry = {"chain": "solana", "network": network, "mint": str(mint_pk), "decimals": decimals,
             "owner": str(owner.pubkey()), "vault": str(vault), "key": str(agent_key.pubkey()), "amount": amount,
             "tx": sig, "set_at": int(time.time())}
    s.setdefault("agents", {})[f"{agent}@solana"] = entry
    save_state(s)
    return entry


def solana_show(entry: dict) -> dict:
    from solders.pubkey import Pubkey

    from . import sol_budget as sb
    got = sb.status(_sol_url(entry["network"]), Pubkey.from_string(entry["vault"]))
    scale = 10 ** entry.get("decimals", 6)
    return {"remaining": got["delegated_amount"] / scale if got["delegate"] else 0.0,
            "vault_balance": got["amount"] / scale, "delegate": str(got["delegate"]) if got["delegate"] else None}


def solana_revoke(entry: dict, ask=None) -> str:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey

    from ..team import rpc
    from . import sol_budget as sb
    owner = Keypair.from_bytes(_unlock_or_create("solana", entry["network"], None, ask))
    return rpc.send(_sol_url(entry["network"]), [sb.revoke(Pubkey.from_string(entry["vault"]), owner.pubkey())],
                    owner)


def entries() -> dict:
    return load_state().get("agents", {})


def legacy_wallets_notice() -> str:
    """0.2 "budget wallets" (a funded key per agent) still work, but their cap is only as good as the balance."""
    try:
        from . import wallets
        if wallets.listed():
            return ("Note: this machine has 0.2 budget wallets (knos budget agents). Their limit is what you put in "
                    "them. Chain-enforced budgets: knos budget set <agent> 5/day --chain tempo")
    except Exception:  # noqa: BLE001
        pass
    return ""
