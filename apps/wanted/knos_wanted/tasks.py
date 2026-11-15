"""Open work a contributor (person or agent) can join: the Knos game's rounds on this server, judged and paid on devnet.

The game is `knos.game` (src/knos/game): a sealed task, players who submit code, a deterministic referee, a pot paid by
verdicts. This module fronts it for the web app:
  - when KNOS_GAME_DIR names an operator's open round, that round is listed;
  - otherwise (Render wipes /data) the server keeps ONE open DEMO round, seeded from the example task packaged in the
    image (examples/autoresearch) with a time budget sized for a free 0.1-CPU host, and reseeds it when it closes;
  - /api/task/submit: the contributor's first submission joins them as a player, later ones reuse that player (several
    attempts per round, the game's own per_round limit); the sealed referee answers at once, on this server;
  - a submission the referee SCORES earns a demo prize when the contributor gives a devnet wallet: a knos_pay PANEL
    order of test units FUNDED BY THE ROUND'S SPONSOR (Knos itself, from this server's own devnet test wallet: a
    sponsor funding a prize pot, not a buyer), pinned to the panel every new order pins (preorder.panel). With the FROST
    referee group configured, the referee's verdict is published at /api/prize/evidence and the prize is released only
    when 2 of the 3 referee hosts sign it after re-checking that page themselves (knos_wanted.referee); otherwise 2 of
    the server's 3 referee keys release it at once (devnet test money, labelled).
Open milestones are listed beside the round as evidence tasks.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import threading
from pathlib import Path

from . import escrow, preorder

TASK_README = "https://github.com/drexthealpha/Knos/blob/main/examples/autoresearch/README.md"
TASK_DIR = Path(__file__).resolve().parents[3] / "examples" / "autoresearch"      # the image ships it beside the app


def task_files() -> dict:
    """The round's README and baseline train.py as text, in the answer itself: an agent limited to Knos's tools (no web
    fetch) once wrote train.py blind, and every attempt failed in the sandbox with "shown": null."""
    out = {}
    for key, name in (("readme_text", "README.md"), ("baseline_source", "train.py")):
        f = TASK_DIR / name
        out[key] = f.read_text(encoding="utf-8") if f.is_file() else None
    return out
DEMO_TITLE = "Demo round: beat the sealed classifier (test money)"
DEMO_LABEL = ("DEMO ROUND, devnet test money: the repository's example task, seeded by this server so contributors "
              "always have one open round; the sealed referee judges every submission")
DEMO_BUDGET_S = 120          # per seeded run; the task's own 20 s is sized for a laptop, not a free 0.1-CPU host
PER_ROUND = 4
PRIZE_UNITS = 5              # test units for a scored attempt (knos_pay's order minimum)
SPONSOR = ("sponsor: Knos, the round's sponsor; its own devnet test wallet funds the prize pot (test money). A sponsor "
           "funding a prize is a real role, not a buyer")
PUBLIC_URL_ENV = "KNOS_WANTED_PUBLIC_URL"
_lock = threading.Lock()


def _status(root: Path) -> str | None:
    try:
        return json.loads((root / "game.json").read_text(encoding="utf-8")).get("status")
    except (OSError, ValueError):
        return None


def _open_demo() -> Path | None:
    """The newest open demo round this server already seeded (it survives a restart on the same state dir)."""
    rows = sorted(escrow._state_dir().glob("demo-game-*"), reverse=True)
    return next((r for r in rows if (r / "game.json").exists() and _status(r) != "closed"), None)


def _demo_task(stamp: str) -> Path:
    """The packaged task, copied with a time budget sized for this host; the sealed file is copied as it is (its sha256
    is what task.json commits to)."""
    dst = escrow._state_dir() / f"demo-task-{stamp}"
    shutil.copytree(TASK_DIR, dst, ignore=shutil.ignore_patterns("__pycache__"))
    spec = json.loads((dst / "task.json").read_text(encoding="utf-8"))
    spec["time_budget_s"] = max(int(spec.get("time_budget_s") or 0), DEMO_BUDGET_S)
    (dst / "task.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return dst


def ensure_round() -> str | None:
    """One open demo round at a time. Returns the id of a round it seeded, None when one is already open."""
    with _lock:
        base = Path(os.environ.get("KNOS_GAME_DIR") or "").expanduser()
        if str(base) not in ("", ".") and (base / "game.json").exists() and _status(base) != "closed":
            return None                                # an open round (the operator's, or the demo one): leave it
        kept = _open_demo()
        if kept is not None:
            os.environ["KNOS_GAME_DIR"] = str(kept)
            return None
        if not TASK_DIR.exists():
            return None                                # no packaged task: the page says so instead
        from knos.game.engine import Game
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
        root = escrow._state_dir() / f"demo-game-{stamp}"
        g = Game.create(root, _demo_task(stamp), title=DEMO_TITLE, field="ml-research", game_id=f"knos-demo-{stamp}",
                        rules={"rounds": 3, "per_round": PER_ROUND, "ladder_eta": 0.01, "max_refusals": 2, "identity_required": False})
        os.environ["KNOS_GAME_DIR"] = str(root)
        print(f"knos-demand-check: seeded the demo game round {g.s['id']} at {root} ({DEMO_LABEL})", flush=True)
        return g.s["id"]


def _tools():
    import importlib
    return importlib.import_module("knos.game.tools")


def available() -> tuple[bool, str]:
    base = Path(os.environ.get("KNOS_GAME_DIR") or "").expanduser()
    if str(base) in ("", ".") or not (base / "game.json").exists() or _status(base) == "closed":
        try:
            ensure_round()
        except Exception as e:  # noqa: BLE001
            return False, f"no open round: the demo round could not be seeded ({type(e).__name__})"
    if not os.environ.get("KNOS_GAME_DIR", "").strip():
        return False, "no open round on this server (no game folder and no packaged demo task)"
    try:
        _tools()
        return True, "ok"
    except Exception as e:  # noqa: BLE001
        return False, f"the game modules are not installed here ({type(e).__name__})"


def _budget() -> int | None:
    try:
        root = Path(os.environ["KNOS_GAME_DIR"])
        s = json.loads((root / "game.json").read_text(encoding="utf-8"))
        task = Path(s.get("task_dir") or s.get("task", {}).get("dir") or "")
        if task and (task / "task.json").exists():
            return int(json.loads((task / "task.json").read_text(encoding="utf-8")).get("time_budget_s") or 0) or None
    except (KeyError, OSError, ValueError):
        pass
    return None


def rounds() -> list[dict]:
    ok, why = available()
    if not ok:
        return []
    gt = _tools()
    try:
        st = gt.call("knos_game_state", {})
        board = gt.call("knos_game_board", {})
    except Exception:  # noqa: BLE001
        return []
    g = st.get("game") or st
    demo = str(g.get("id") or "").startswith("knos-demo-")
    return [{"id": g.get("id"), "title": g.get("title"),
             "label": DEMO_LABEL if demo else "Knos game round: code judged by the sealed referee; the pot pays by its "
             "verdicts on devnet (test money)", "demo": demo, "state": g.get("status") or st.get("status"),
             "round": g.get("round") or st.get("round"), "players": len(board.get("board") or board.get("rows") or []),
             "submit": {"file": "train.py", "what": "the whole train.py, changed so the sealed referee measures a higher "
                        "accuracy (for example: features 'square' and standardize True)",
                        "attempts_per_round": PER_ROUND, "time_budget_s": _budget() or DEMO_BUDGET_S,
                        "readme": TASK_README, "baseline": "https://github.com/drexthealpha/Knos/blob/main/examples/autoresearch/train.py",
                        **task_files(),
                        "prize": f"{PRIZE_UNITS} test units on devnet for a scored attempt, when you give a devnet wallet"}}]


def round_state() -> dict:
    """The open round as its public state says it: id, status, metric direction, the Ladder step and the baseline's
    shown score (what a referee-judged milestone's margin is measured from). Never a hidden score."""
    ok, why = available()
    if not ok:
        raise ValueError(why)
    st = _tools().call("knos_game_state", {})
    g = st.get("game") or st
    return {"id": g.get("id"), "status": g.get("status"), "direction": g.get("direction"), "metric": g.get("metric"),
            "eta": float((g.get("rules") or {}).get("ladder_eta") or 0.01), "baseline_shown": g.get("baseline_shown")}


def listing() -> dict:
    ok, why = available()
    ms = [{"claim_id": r.get("claim_id"), "idea": r.get("idea"), "commitment": r.get("commitment"), "units": r.get("units")}
          for r in preorder.all_public(20) if r.get("status") == "locked"]
    return {"rounds": rounds(), "why": None if ok else why, "milestones": ms,
            "note": "devnet test money; a round's attempts are judged by the game's sealed referee, a milestone by 2-of-3 referee signatures"}


def _players() -> Path:
    return escrow._state_dir() / "demo-players.json"


def _player_for(game_id: str, sub: str, name: str, kind: str, gt) -> tuple[str, str]:
    """The same contributor keeps one player per round: later attempts are that player's next attempts."""
    with _lock:
        try:
            book = json.loads(_players().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            book = {}
        k = hashlib.sha256(f"{game_id}|{sub}".encode()).hexdigest()
        if k in book:
            return book[k]["player"], book[k]["key"]
        joined = gt.call("knos_game_join", {"name": name, "kind": kind, "label": "web contributor"})
        book[k] = {"player": joined["player"], "key": joined["key"]}
        tmp = _players().with_suffix(".tmp")
        tmp.write_text(json.dumps(book), encoding="utf-8")
        os.replace(tmp, _players())
        return joined["player"], joined["key"]


def public_base(base: str | None = None) -> str:
    """The origin the referee hosts fetch a prize's evidence from: $KNOS_WANTED_PUBLIC_URL, else the request's origin,
    else https://<KNOS_WANTED_RP_ID>, else https://knos.onrender.com."""
    got = os.environ.get(PUBLIC_URL_ENV) or base or ("https://" + os.environ["KNOS_WANTED_RP_ID"] if os.environ.get("KNOS_WANTED_RP_ID") else "")
    return (got or "https://knos.onrender.com").rstrip("/")


def _prizes() -> Path:
    d = escrow._state_dir() / "prizes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prize_evidence(pid: str) -> bytes | None:
    """The public evidence page of one prize (the round's verdict and the commitment's claim id): what each referee
    host fetches and re-checks before it signs."""
    if not (isinstance(pid, str) and len(pid) == 16 and all(c in "0123456789abcdef" for c in pid)):
        return None
    f = _prizes() / f"{pid}.evidence.json"
    return f.read_bytes() if f.exists() else None


def load_prize(order: str) -> dict:
    return json.loads((_prizes() / f"{order}.json").read_text(encoding="utf-8"))


def save_prize(rec: dict) -> None:
    f = _prizes() / f"{rec['order']}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, default=str), encoding="utf-8")
    os.replace(tmp, f)


def _prize(game_id: str, verdict: dict, name: str, wallet: str, base: str | None = None) -> dict:
    """A scored attempt's demo prize: one knos_pay PANEL order of test units to the contributor's wallet, funded by the
    round's sponsor. The FROST referee group (when configured) releases it after 2 of 3 hosts re-check the published
    verdict; else 2 of the server's 3 referee keys sign over the referee's verdict (its sha256 is the evidence)."""
    from solders.pubkey import Pubkey

    from knos import ideas
    from knos.ideas import commit as C
    from knos.settle.v2 import pay
    try:
        Pubkey.from_string(wallet)
    except ValueError:
        return {"paid": False, "why": "payout wallet: a Solana address"}
    ok, why = preorder.ready()
    if not ok:
        return {"paid": False, "why": why}
    led = escrow.ledger()
    sponsor, pan, prog = escrow.demo_key(), preorder.panel(), preorder.program()
    mint = escrow.mint(led)
    claim = ideas.claim(f"Demo round {game_id}: prize for attempt {verdict.get('n')} by {name} (sha256 {str(verdict.get('sha256'))[:16]})",
                        field_name="Computer Science", kind="person", by={"app": "knos demand check", "round": game_id})
    tok = pay.ata(sponsor.pubkey(), mint)
    pre = [pay.create_ata_ix(sponsor.pubkey(), w, mint) for w in (sponsor.pubkey(), Pubkey.from_string(wallet)) if led.account(pay.ata(w, mint)) is None]
    if pre:
        led.send(pre, sponsor)
    need = PRIZE_UNITS * escrow.UNIT + pay.order_fee(PRIZE_UNITS * escrow.UNIT)
    if escrow._token_units(led, tok) < need:
        led.send([escrow._mint_to_ix(mint, tok, sponsor.pubkey(), -(-need // escrow.UNIT))], sponsor)
    doc = C.commit(claim, units=PRIZE_UNITS, price=1, payee=C.parse_payee(wallet), funder=sponsor, funder_token=tok, mint=mint, led=led,
                   stages=[("referee_pass", 10_000)], stage_work_s=[7 * 86_400], panel=pan,
                   program=prog, unlisted_panel=True)
    st = doc["orders"]["stage1"]
    pid = doc["commitment_hash"][:16]
    out = {"units": PRIZE_UNITS, "to": wallet, "order": st["order"], "lock": st["signature"], "funded_by": SPONSOR,
           "label": "demo prize, devnet test money, funded by the round's sponsor"}
    if pan[0] == 1:
        # the FROST referee group: publish the verdict as the evidence page, then 2 of the 3 hosts check it and sign
        from . import referee
        page = json.dumps({"kind": "knos-demo-round-verdict", "claim": claim["id"], "round": game_id, "verdict": verdict},
                          sort_keys=True, default=str).encode()
        (_prizes() / f"{pid}.evidence.json").write_bytes(page)
        url = f"{public_base(base)}/api/prize/evidence?id={pid}"
        rec = {"kind": "prize", "order": st["order"], "doc": doc, "round": game_id, "to": wallet, "status": "locked",
               "evidence_url": url, "signatures": {"lock": st["signature"]}}
        save_prize(rec)
        sig = referee.start(rec, url, led, kind="prize")
        rec["referee_session"] = {"id": sig["session"], "github": sig["github"]}
        save_prize(rec)
        return {**out, "paid": False, "status": "signing", "session": sig["session"], "evidence": url, "needs": sig["needs"],
                "explorer": [escrow.explorer(st["signature"])] if st["signature"] else []}
    review = escrow._state_dir() / f"prize-{pid}.verdict.json"
    review.write_text(json.dumps(verdict, sort_keys=True, default=str), encoding="utf-8")
    refs = preorder.referees()
    recs = [C.sign(doc, "stage1", r, led, passed=True, review=review) for r in refs[:2]]
    got = C.release(doc, "stage1", recs, preorder.relayer(), led)
    return {**out, "paid": got["status"] == "released", "release": [s["signature"] for s in got["sent"]],
            "explorer": [escrow.explorer(s) for s in [st["signature"], *[x["signature"] for x in got["sent"]]] if s]}


def submit(round_id: str, name: str, code: str, who: str, sub: str | None = None, wallet: str | None = None,
           base: str | None = None) -> dict:
    """Submit one attempt to the open round (the contributor's player is reused across attempts); the referee answers
    at once. A scored attempt with a payout wallet is paid its demo prize on devnet."""
    ok, why = available()
    if not ok:
        raise ValueError(why)
    if not (isinstance(code, str) and 10 <= len(code) <= 100_000):
        raise ValueError("train.py: the whole file, 10 to 100,000 characters")
    gt = _tools()
    game_id = (gt.call("knos_game_state", {}).get("game") or {}).get("id") or round_id
    name = (" ".join(str(name or "").split()) or "contributor")[:40]
    player, key = _player_for(str(game_id), sub or who, name, "agent" if "agent" in who else "human", gt)
    got = gt.call("knos_game_submit", {"player": player, "key": key, "file": code})   # the tool reads "file"
    result = {k: got.get(k) for k in ("n", "round", "decision", "shown", "reasons", "rules", "sha256", "said", "moved")}
    if result.get("decision") != "scored":            # why "shown" is null, in the log (the reasons name no key)
        print(f"knos referee: round {game_id} attempt {result.get('n')} {result.get('decision')}: "
              f"{'; '.join(str(r) for r in (result.get('reasons') or []))[:300]}", flush=True)
    out = {"name": name, "round": game_id, "result": result, "submitted_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
           "note": "judged by the round's sealed referee on this server (devnet test money)"}
    if wallet and got.get("decision") == "scored":
        try:
            out["prize"] = _prize(str(game_id), {**result, "name": name}, name, wallet.strip(), base)
        except Exception as e:  # noqa: BLE001 - the verdict stands; the prize says why it did not pay
            out["prize"] = {"paid": False, "why": f"the prize could not be paid ({type(e).__name__})"}
    return out
