"""Knos's published referee registry (config/referees.yaml) and the panel rule every client tool applies.

THE TRUST MODEL, plainly: on chain a PANEL order (the knos_pay panel test build) pays whatever m of its pinned keys sign. The chain
does not read the oracle and does not know who holds the keys. So whoever holds the panel keys decides the money. Knos's
client tools therefore accept a panel only when every key is in the published registry and none is the funder's or a
payee's own key. Anything else needs an explicit `unlisted_panel=True` (`--unlisted-panel` on a command line), and the
output then carries UNLISTED_LABEL.

`unlisted_panel`:
  False  refuse an unlisted panel (PanelError)                           what the command-line tools pass by default
  True   accept it, labelled                                               --unlisted-panel
  None   (library default, for callers written before the registry) accept it with a warning and the label
A panel holding the funder's or a payee's key is refused unless unlisted_panel is True, whatever else is said.

The registry file is the file KNOS_REFEREES names, else config/referees.yaml in the repository, else the wheel's copy
(knos/_config/referees.yaml). It is read with PyYAML when that is installed, else with the small reader below (the
file's own shape: a `referees:` list of flat `key: value` entries), so a plain `pip install knos` reads it too.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path

UNLISTED_LABEL = ("UNLISTED PANEL: not drawn from Knos's published referee registry (config/referees.yaml); whoever holds "
                  "these keys decides the money")
SELF_LABEL = "UNLISTED PANEL: the panel holds the funder's or a payee's own key"
_ROOT = Path(__file__).resolve().parents[3]


class PanelError(ValueError):
    """A panel a Knos client tool will not use: one sentence."""


def registry_path() -> Path:
    given = os.environ.get("KNOS_REFEREES")
    if given:
        return Path(given)
    tree = _ROOT / "config" / "referees.yaml"
    wheel = Path(__file__).resolve().parents[1] / "_config" / "referees.yaml"
    return tree if tree.is_file() or not wheel.is_file() else wheel


def _scalar(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return int(v) if v.isdigit() else {"true": True, "false": False}.get(v.lower(), v)


def _parse(text: str) -> dict:
    """The registry's shape without PyYAML: top-level `name: value` lines and one `referees:` list of flat entries."""
    doc: dict = {}
    entries: list[dict] | None = None
    for raw in text.splitlines():
        line = raw.split(" #")[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if not raw.startswith((" ", "-")):
            name, _, value = line.partition(":")
            entries = [] if name.strip() == "referees" else None
            doc[name.strip()] = entries if entries is not None else _scalar(value)
            continue
        if entries is None:
            continue
        body = line.strip()
        if body.startswith("- "):
            entries.append({})
            body = body[2:]
        if entries and ":" in body:
            name, _, value = body.partition(":")
            entries[-1][name.strip()] = _scalar(value)
    return doc


def load(path: Path | None = None) -> list[dict]:
    """The registry's entries: {key (base58), name, label, test}. An absent file is an empty registry."""
    p = path or registry_path()
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        doc = _parse(text)
    else:
        doc = yaml.safe_load(text) or {}
    out = []
    for e in doc.get("referees") or []:
        out.append({"key": str(e["key"]), "name": str(e.get("name", "")), "label": str(e.get("label", "")), "test": bool(e.get("test", False))})
    return out


def _b(k) -> bytes:
    """A key as 32 bytes: bytes, a solders Pubkey or base58 text."""
    if isinstance(k, (bytes, bytearray, memoryview)):
        return bytes(k)
    if isinstance(k, str):
        from solders.pubkey import Pubkey
        return bytes(Pubkey.from_string(k))
    return bytes(k)


def registered(path: Path | None = None) -> dict[bytes, dict]:
    return {_b(e["key"]): e for e in load(path)}


def panel_rule(keys, *, funder=None, payees=(), unlisted_panel: bool | None = None, path: Path | None = None) -> str:
    """'' for a panel drawn from the registry with no party's own key; the label to print for an unlisted panel that
    may be used; PanelError for one that may not (see the module documentation). `payees`: their wallets (or
    (id, bps, wallet) triples, as a verdict names them)."""
    panel = [_b(k) for k in keys]
    own = {_b(funder)} if funder is not None else set()
    for p in payees or ():
        w = p[2] if isinstance(p, (tuple, list)) and len(p) == 3 else p
        if w is not None:
            own.add(_b(w))
    if own & set(panel):
        if unlisted_panel is not True:
            raise PanelError("the panel holds the funder's or a payee's own key: that party would judge itself "
                             "(pass --unlisted-panel to use it anyway; the output says UNLISTED PANEL)")
        return SELF_LABEL
    reg = registered(path)
    outside = [k for k in panel if k not in reg]
    if not outside:
        return ""
    if unlisted_panel is False:
        raise PanelError(f"{len(outside)} of the panel's {len(panel)} keys are not in Knos's referee registry "
                         f"({registry_path()}): pass --unlisted-panel to use them anyway (the output says UNLISTED PANEL)")
    if unlisted_panel is None:
        warnings.warn(UNLISTED_LABEL, stacklevel=2)
    return UNLISTED_LABEL


def labelled(out: dict, label: str) -> dict:
    """`out` with the panel label when there is one."""
    if label:
        out = {**out, "panel": label}
    return out
