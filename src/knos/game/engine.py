"""One Knos game: a sealed goal, many attempts at once, by humans and AI scientists, judged by the same referee.

    g = Game.create(root, task_dir, title="...", field="ml-research", rules={...})   seal the goal (Record: claim)
    pid = g.join("ada", kind="human")                    a player: a person, an AI agent, or a scripted one (labelled)
    g.submit(pid, {"train.py": text})                    one attempt: the referee judges it now, on sealed data
    g.board()                                            the public leaderboard (Ladder scores; never a hidden one)
    g.close_round()                                      next round (each round allows `per_round` attempts a player)
    g.finish()                                           the verdicts: each player's best attempt on the SECOND sealed
                                                         set (used once, here), ranked; the pot's split follows them

Every player, person or agent, goes through the same calls (the CLI, the MCP tools and the web page call these and
nothing else). What a player sees: the goal (program.md, idea.md), the baseline file, the public train and validation
data, the rules, the board, and per own attempt the decision, the rule names that refused it and the shown score.
What a player never sees: the sealed data, any raw hidden score, the other players' files.

The referee is knos.autoresearch.judge.LocalJudge: static cheat rules (scope, imports, reaching for sealed data, the
shared knos.cheats library) before any code runs, two seeded runs that must agree, and its own code hashed into the
seal (judge drift is refused). A refused attempt shows no score; a player refused `max_refusals` times is out of the
game (a cheat must never be worth more than an honest failure: knos.referee.reward gives -1, 0 and 1).

LIMIT: the static rules are a filter, not an operating-system sandbox. A
game open to strangers must judge on a machine that holds neither the sealed file nor anything else of value.
"""
from __future__ import annotations

import hashlib
import json
import hmac
import re
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from ..autoresearch import task as artask
from ..autoresearch.judge import LocalJudge
from ..autoresearch.recorder import Recorder
from . import ladder
from .norm import normalized_sha256  # noqa: F401 - the duplicate key, also knos.game.norm

KINDS = ("human", "agent")
NOT_CHEATS = frozenset({"no_change"})        # refused, but not a cheat (the baseline again, a file that does not parse)
DEFAULT_RULES = {"rounds": 3, "per_round": 3, "ladder_eta": ladder.DEFAULT_ETA, "max_refusals": 2, "max_players": 64,
                 "identity_required": False}
ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def orcid_ok(value: str) -> bool:
    """An ORCID iD's form and its ISO 7064 MOD 11-2 check digit."""
    if not isinstance(value, str) or not ORCID.match(value):
        return False
    digits = value.replace("-", "")
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    return digits[-1] == ("X" if check == 10 else str(check))


def join_message(game_id: str, name: str) -> bytes:
    """What a player signs with its own ed25519 key to join under that key as its identity."""
    return f"knos-game:{game_id}:join:{name}".encode()
STATE = "game.json"
NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.")


def _field(v) -> str:
    """A field of science as the sources name it (OpenAlex's "Biochemistry, Genetics and Molecular Biology")."""
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > 100 or set(v.strip()) - NAME_OK - set(",&()/'"):
        raise GameError("field: 1 to 100 letters, digits, spaces and , & ( ) / ' - . _")
    return v.strip()


def _title(v) -> str:
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > 120 or not v.strip().isprintable() or set(v) & set("<>&\"`"):
        raise GameError("title: 1 to 120 printable characters, without < > & \" `")
    return v.strip()


class GameError(ValueError):
    """A request the game refuses: one sentence for the player."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _now() -> int:
    return int(time.time())


def _name(v, what: str, most: int = 40) -> str:
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > most or set(v.strip()) - NAME_OK:
        raise GameError(f"{what}: 1 to {most} letters, digits, spaces, '_', '-' or '.'")
    return v.strip()


class Game:
    def __init__(self, root: Path, state: dict, task: artask.Task, judge: LocalJudge | None = None, record: bool = True):
        self.root = Path(root)
        self.s = state
        self.task = task
        self.judge = judge or LocalJudge(task, mask=[str(self.root)])      # other players' files: hidden from a candidate
        self.lock = threading.RLock()
        self.rec = Recorder(self.root / "record", "game-" + state["id"], use_knos_record=record) if record else None

    # -- making and opening --------------------------------------------------------------------------------------------
    @classmethod
    def create(cls, root, task_dir, *, title: str, field: str = "ml-research", rules: dict | None = None, sealed=None,
               game_id: str | None = None, record: bool = True, judge: LocalJudge | None = None) -> "Game":
        root = Path(root)
        if (root / STATE).exists():
            raise GameError(f"a game already lives in {root}")
        t = artask.load(task_dir, sealed)
        j = judge or LocalJudge(t, mask=[str(root.resolve())])
        seal = j.seal()
        seal.setdefault("hidden_sha256", t.hidden_sha256())     # the hidden data's CONTENTS, checked at every attempt and at finish
        r = {**DEFAULT_RULES, **(rules or {})}
        if not 0 < float(r["ladder_eta"]) <= 0.5 or int(r["rounds"]) < 1 or int(r["per_round"]) < 1 or int(r["max_refusals"]) < 1:
            raise GameError("rules: rounds, per_round and max_refusals at least 1, ladder_eta in (0, 0.5]")
        gid = game_id or ("g" + seal["spec_hash"][:12])
        _name(gid, "game id", 64)
        state: dict[str, Any] = {"v": 1, "id": gid, "title": _title(title), "field": _field(field),
                 "task_dir": str(Path(task_dir).resolve()), "sealed": None if sealed is None else str(Path(sealed).resolve()),
                 "seal": seal, "synthetic": bool(t.spec.get("synthetic")), "rules": r, "round": 1, "status": "open",
                 "created": _now(), "players": {}, "attempts": [], "private": {"scores": {}, "baseline": None},
                 "pot": {"pledges": []}, "final": None}
        root.mkdir(parents=True, exist_ok=True)
        (root / "attempts").mkdir(exist_ok=True)
        g = cls(root, state, t, j, record)
        base = j.judge({t.editable: t.baseline}, None, stage="dev")
        if not base.passed:
            raise GameError("the baseline itself fails the referee: " + "; ".join(base.reasons))
        state["private"]["baseline"] = base.score
        state["baseline_shown"] = ladder.rounded(base.score, float(r["ladder_eta"]), t.maximize)  # type: ignore[arg-type]  # base.passed: a passed Verdict carries its score
        g._event("claim", {"spec_hash": seal["spec_hash"], "judge_hash": seal["judge_hash"], "game": gid, "status": "open",
                           "metric": t.spec["metric"], "field": state["field"], "synthetic": state["synthetic"]})
        g._event("paper", {"title": t.spec["name"], "program_sha256": _sha(t.program), "idea_sha256": _sha(t.idea),
                           "synthetic": state["synthetic"]}, ref="game-program-" + _sha(t.program)[:16])
        g.save()
        return g

    @classmethod
    def open(cls, root, record: bool = True, judge: LocalJudge | None = None) -> "Game":
        root = Path(root)
        try:
            state = json.loads((root / STATE).read_text(encoding="utf-8"))
        except (OSError, ValueError) as why:
            raise GameError(f"no game in {root}: {why}") from None
        t = artask.load(state["task_dir"], state.get("sealed"))
        return cls(root, state, t, judge, record)

    def save(self) -> None:
        tmp = self.root / (STATE + ".tmp")
        tmp.write_text(json.dumps(self.s, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.root / STATE)

    def _event(self, kind: str, payload: dict, ref: str | None = None) -> None:
        if self.rec is None:
            return
        try:
            if kind == "claim":
                self.rec.claim(payload)
            elif kind == "paper":
                self.rec.paper(ref or "game-paper", payload)
            else:
                self.rec.event(kind, payload)
        except ValueError as why:          # Knos Record refuses what looks like a secret: said in the state, never hidden
            self.s.setdefault("record_refused", []).append(f"{kind}: {str(why)[:160]}")

    # -- players -------------------------------------------------------------------------------------------------------
    def join(self, name: str, *, kind: str = "human", label: str = "", payee: str | None = None, github_id: int | None = None,
             orcid: str | None = None, pubkey: str | None = None, signature: str | None = None) -> dict:
        """A player: {"player": id, "key": the player's secret}. The key is shown once; submitting and reading one's own
        attempts through the web page or MCP needs it (only its sha256 is kept). `label`: what the player is when it is not a live person or a live model (e.g. "synthetic scripted
        human", "MOCK Nemotron reply"): shown next to the name everywhere. `payee`: the Solana address its prize goes to.

        Identity (after an outside judge took a pot's three paid places with one person behind three players):
        at most one of `github_id`, `orcid` (an ORCID iD, check digit verified) or `pubkey` + `signature` (an ed25519
        key and its signature of join_message(game id, name)). Each identity and each payee joins a game once; a
        second player with the same identity or the same payee is refused. A player with no identity plays and is
        ranked, but is never paid from the pot (knos.game.pot pays only players with an identity); a game with
        rules.identity_required refuses it at the door. GitHub and ORCID ids are claimed here, not proven: knos_pay
        pays a GitHub id only on that account's own signed token, and an ORCID token check is the payout path's job."""
        name = _name(name, "name")
        if kind not in KINDS:
            raise GameError(f"kind: one of {', '.join(KINDS)}")
        if payee is not None:
            from solders.pubkey import Pubkey
            try:
                payee = str(Pubkey.from_string(str(payee)))
            except ValueError:
                raise GameError("payee: a Solana address") from None
        if github_id is not None and (isinstance(github_id, bool) or not isinstance(github_id, int) or not 0 < github_id < 2 ** 63):
            raise GameError("github_id: the account's number")
        given = [x for x in (github_id, orcid) if x is not None]
        if len(given) > 1:
            raise GameError("one identity per player: a GitHub id, an ORCID iD or a signed key, not several")
        identity, proof_key = None, None
        if github_id is not None:
            identity = f"github:{github_id}"
        elif orcid is not None:
            if not orcid_ok(orcid):
                raise GameError("orcid: an ORCID iD like 0000-0002-1825-0097, with a valid check digit")
            identity = f"orcid:{orcid}"
        if pubkey is not None:
            from solders.pubkey import Pubkey
            from solders.signature import Signature
            try:
                pk, sig = Pubkey.from_string(str(pubkey)), Signature.from_string(str(signature or ""))
            except ValueError:
                raise GameError("pubkey and signature: an ed25519 key and its signature, base58") from None
            if not sig.verify(pk, join_message(self.s["id"], name)):
                raise GameError("signature: not this key's signature of the join message (knos.game.engine.join_message)")
            if identity is None:
                identity = f"key:{pk}"
            else:
                proof_key = str(pk)     # the wallet that signed the join: proves the id when the chain binds it to this wallet
        with self.lock:
            if identity is None and self.s["rules"].get("identity_required"):
                raise GameError("this game needs an identity to join: a GitHub id, an ORCID iD or a signed key")
            if identity is not None and any(p.get("identity") == identity for p in self.s["players"].values()):
                raise GameError("this identity already plays in this game: one player per identity")
            if payee is not None and any(p.get("payee") == payee for p in self.s["players"].values()):
                raise GameError("this payee address already belongs to another player in this game")
            if self.s["status"] == "final":
                raise GameError("the game is over")
            if any(p["name"].lower() == name.lower() for p in self.s["players"].values()):
                raise GameError(f"the name {name} is taken")
            if len(self.s["players"]) >= int(self.s["rules"]["max_players"]):
                raise GameError("the game is full")
            pid = "p" + _sha(f"{self.s['id']}:{name}")[:10]
            key = secrets.token_urlsafe(24)
            self.s["players"][pid] = {"key_sha256": _sha(key), "name": name, "kind": kind, "label": str(label)[:80], "payee": payee, "github_id": github_id, "identity": identity, "proof_key": proof_key,
                                      "joined": _now(), "refusals": 0, "out": False, "shown": None, "attempts": 0}
            self.save()
            return {"player": pid, "key": key}

    def check_key(self, pid: str, key) -> None:
        p = self.player(pid)
        if not isinstance(key, str) or not hmac.compare_digest(_sha(key), p.get("key_sha256", "")):
            raise GameError("wrong player key")

    def player(self, pid: str) -> dict:
        p = self.s["players"].get(pid)
        if p is None:
            raise GameError("unknown player: join first")
        return p

    # -- attempts ------------------------------------------------------------------------------------------------------
    def submit(self, pid: str, files: dict) -> dict:
        """One attempt, judged now on the sealed dev set. Returns what the player may see."""
        if not isinstance(files, dict) or not files or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
            raise GameError("files: {file name: text}")
        if sum(len(v) for v in files.values()) > 200_000:
            raise GameError("files: at most 200,000 characters")
        with self.lock:
            p = self.player(pid)
            if self.s["status"] != "open":
                raise GameError("the game is not taking attempts")
            if p["out"]:
                raise GameError("this player is out of the game: the referee refused its attempts too often")
            drift = self.sealed_moved()
            if drift:
                raise GameError(drift + ": the game takes no attempt on data other than what was sealed")
            used = sum(1 for a in self.s["attempts"] if a["pid"] == pid and a["round"] == self.s["round"])
            pending = self.s.setdefault("pending", {})
            if used + pending.get(pid, 0) >= int(self.s["rules"]["per_round"]):
                raise GameError(f"{self.s['rules']['per_round']} attempts a round: wait for the next round")
            pending[pid] = pending.get(pid, 0) + 1
            rnd = self.s["round"]
        t0 = time.monotonic()
        try:
            v = self.judge.judge(files, self.task.baseline, stage="dev")
        finally:
            with self.lock:
                self.s["pending"][pid] -= 1
        cheats = [c for c in v.cheats if c.severity == "refuse" and c.category not in NOT_CHEATS]
        if cheats:
            decision = "refused"
        elif not v.passed:
            decision = "failed"
        else:
            decision = "scored"
        src = files.get(self.task.editable, "")
        with self.lock:
            p = self.player(pid)
            n = len(self.s["attempts"]) + 1
            maximize = self.task.maximize
            moved = False
            if decision == "scored":
                p["shown"], moved = ladder.step(p["shown"], v.score, float(self.s["rules"]["ladder_eta"]), maximize)  # type: ignore[arg-type]  # "scored": v.passed, so v.score is set
                self.s["private"]["scores"][str(n)] = v.score
                (self.root / "attempts" / f"{n}.json").write_text(json.dumps({"pid": pid, "files": files}), encoding="utf-8")
            if decision == "refused":
                p["refusals"] += 1
                if p["refusals"] >= int(self.s["rules"]["max_refusals"]):
                    p["out"] = True
            p["attempts"] += 1
            reported = v.reported.get("val_accuracy") if isinstance(v.reported, dict) else None
            a = {"n": n, "pid": pid, "round": rnd, "at": _now(), "sha256": _sha(src), "norm_sha256": normalized_sha256(src), "decision": decision,
                 "shown": p["shown"] if decision == "scored" else None, "moved": moved,
                 "rules": sorted({c.rule for c in v.cheats if c.severity == "refuse"}),
                 "cheats": sorted({c.category for c in cheats}),
                 "reasons": _public_reasons(v, decision), "reported_val": reported, "judge_s": round(time.monotonic() - t0, 2)}
            self.s["attempts"].append(a)
            self.save()
            self._event("experiment", {"game": self.s["id"], "attempt": n, "player": pid, "kind": p["kind"], "label": p["label"] or "",
                                       "round": rnd, "decision": decision, "candidate_sha256": a["sha256"],
                                       "spec_hash": self.s["seal"]["spec_hash"], "synthetic": self.s["synthetic"]})
            for c in cheats:
                self._event("cheat", {"game": self.s["id"], "attempt": n, "rule": c.rule, "cheat": c.category, "severity": c.severity,
                                      "spec_hash": self.s["seal"]["spec_hash"]})
            if decision == "refused":
                self._event("refusal", {"game": self.s["id"], "attempt": n, "rules": a["rules"], "spec_hash": self.s["seal"]["spec_hash"]})
            return self._mine(a, p)

    def _mine(self, a: dict, p: dict) -> dict:
        words = {"scored": f"judged on sealed data; shown score {a['shown']}" + (" (moved)" if a["moved"] else " (not moved: the Ladder shows only gains above eta)"),
                 "failed": "it ran but did not pass the referee (not a cheat)",
                 "refused": "refused by the referee's cheat rules: no score"}[a["decision"]]
        return {**{k: a[k] for k in ("n", "round", "decision", "shown", "moved", "rules", "cheats", "reasons", "reported_val", "sha256")},
                "player": a["pid"], "out": p["out"], "refusals": p["refusals"], "said": words}

    def sealed_moved(self) -> str | None:
        """Why the hidden data on disk is not what the game sealed (the CONTENTS' hash moved), or None."""
        want = self.s["seal"].get("hidden_sha256")
        if not want:
            return None
        now = self.task.hidden_sha256()
        return None if now == want else f"sealed_changed: the hidden data hashes {now[:16]}, the game sealed {want[:16]}"

    def _norm(self, a: dict) -> str:
        """The duplicate key of a scored attempt: its program with comments, spacing and docstrings set aside, and its
        score on the sealed dev set (the same program always scores the same there, so this only separates files
        whose text differs in what the referee does not run)."""
        score = self.s["private"]["scores"].get(str(a["n"]))
        return f"{self._norm_text(a)}:{score!r}"

    def _norm_text(self, a: dict) -> str:
        if a.get("norm_sha256"):
            return a["norm_sha256"]
        f = self.root / "attempts" / f"{a['n']}.json"
        try:
            return normalized_sha256(json.loads(f.read_text(encoding="utf-8"))["files"].get(self.task.editable, ""))
        except (OSError, ValueError, KeyError):
            return a["sha256"]

    def history(self, pid: str) -> list[dict]:
        """A player's own attempts, as that player may see them (what an agent's next prompt is built from)."""
        p = self.player(pid)
        return [self._mine(a, p) for a in self.s["attempts"] if a["pid"] == pid]

    def best_source(self, pid: str) -> str:
        """The player's own best file so far by its shown score (its starting point); the baseline when none."""
        mine = [a for a in self.s["attempts"] if a["pid"] == pid and a["decision"] == "scored"]
        if not mine:
            return self.task.baseline
        top = max(mine, key=lambda a: (a["shown"] if self.task.maximize else -a["shown"], -a["n"]))
        got = json.loads((self.root / "attempts" / f"{top['n']}.json").read_text(encoding="utf-8"))
        return got["files"].get(self.task.editable, self.task.baseline)

    # -- rounds and the end ----------------------------------------------------------------------------------------------
    def close_round(self) -> dict:
        with self.lock:
            if self.s["status"] != "open":
                raise GameError("the game is not open")
            if self.s["round"] >= int(self.s["rules"]["rounds"]):
                self.s["status"] = "closed"
            else:
                self.s["round"] += 1
            self.save()
            return {"round": self.s["round"], "status": self.s["status"]}

    def finish(self) -> dict:
        """The referee's verdicts. For each player, its attempt with the best hidden dev score is
        judged once on the sealed FINAL set (both seeds) against the baseline on the same set. It passes when no rule
        refused it, both runs agree, the judging code is still the sealed one, and its lift over the baseline is at
        least the task's min_lift on the worse seed. Passing attempts are ranked by their mean lift (ties: the earlier
        attempt first). Nobody saw the final set before; nobody can submit after."""
        with self.lock:
            if self.s["status"] == "final":
                return self.s["final"]
            self.s["status"] = "judging"
            self.save()
        t, j = self.task, self.judge
        moved_reason = self.sealed_moved()
        base = j.judge({t.editable: t.baseline}, None, stage="final")
        drift = j.sealed_judge != self.s["seal"]["judge_hash"]
        from ..autoresearch.judge import judge_hash
        now = judge_hash()
        verdicts = []
        first: dict = {}
        for a in sorted(self.s["attempts"], key=lambda a: a["n"]):
            if a["decision"] == "scored":
                first.setdefault(self._norm(a), (a["n"], a["pid"]))
        for pid, p in self.s["players"].items():
            mine = [a for a in self.s["attempts"] if a["pid"] == pid and a["decision"] == "scored"]
            if not mine:
                continue
            sc = self.s["private"]["scores"]
            own = [a for a in mine if first.get(self._norm(a), (a["n"], pid))[1] == pid]     # identical files: only the first submitter
            if not own:
                dup = mine[0]
                verdicts.append({"player": pid, "name": p["name"], "kind": p["kind"], "label": p["label"], "attempt": dup["n"],
                                 "attempt_sha256": dup["sha256"], "passed": False, "eligible": False, "lift_per_seed": [], "lift": None,
                                 "reasons": [f"every scored attempt is identical to an earlier attempt of another player (attempt "
                                             f"{first[self._norm(dup)][0]}, the same program once comments, spacing and docstrings are set aside): credit goes "
                                             "to the first submitter only"], "cheats": [], "at": dup["at"]})
                continue
            mine = own
            top = max(mine, key=lambda a: (sc[str(a["n"])] if t.maximize else -sc[str(a["n"])], -a["n"]))
            files = json.loads((self.root / "attempts" / f"{top['n']}.json").read_text(encoding="utf-8"))["files"]
            v = j.judge(files, None, stage="final")
            reasons = []
            # Forfeiture rule: refusals count only against LATER attempts. Reaching max_refusals stops a player
            # from submitting again; it never voids an honest attempt made before (an outside judge saw an honest win
            # voided by two later refusals). Attempts are kept in order, so every scored attempt here predates the stop.
            if moved_reason:
                reasons.append(moved_reason)
            if drift or now != self.s["seal"]["judge_hash"]:
                reasons.append("judge_drift: the judging code changed since the game was sealed")
            if not base.passed:
                reasons.append("baseline: " + "; ".join(base.reasons))
            if not v.passed:
                reasons.append("; ".join(v.reasons) or "not passed")
            lifts = [t.lift(b, a) for a, b in zip(base.scores, v.scores)] if base.passed and v.passed else []
            if lifts and min(lifts) < float(t.spec["min_lift"]):
                reasons.append(f"lift {min(lifts):.4f} on the worse seed is below the agreed {t.spec['min_lift']}")
            verdicts.append({"player": pid, "name": p["name"], "kind": p["kind"], "label": p["label"], "attempt": top["n"],
                             "attempt_sha256": top["sha256"], "passed": not reasons, "reasons": reasons,
                             "eligible": bool(p.get("identity")), "identity": p.get("identity"),
                             "lift_per_seed": [round(x, 6) for x in lifts], "lift": round(sum(lifts) / len(lifts), 6) if lifts else None,
                             "cheats": sorted({c.category for c in v.cheats if c.severity == "refuse"}), "at": top["at"]})
        passing = sorted([x for x in verdicts if x["passed"]], key=lambda x: (-x["lift"], x["attempt"]))
        for rank, x in enumerate(passing, 1):
            x["rank"] = rank
        out = {"game": self.s["id"], "spec_hash": self.s["seal"]["spec_hash"], "judge_hash": now, "judge_unchanged": now == self.s["seal"]["judge_hash"],
               "sealed_unchanged": moved_reason is None,
               "min_lift": t.spec["min_lift"], "baseline_final": [round(x, 6) for x in base.scores], "verdicts": verdicts,
               "winner": passing[0]["player"] if passing else None, "passed": [x["player"] for x in passing],
               "data": "hidden_final (sealed; used once, here)", "synthetic": self.s["synthetic"], "at": _now()}
        with self.lock:
            self.s["final"] = out
            self.s["status"] = "final"
            self.save()
        for x in verdicts:
            self._event("verdict", {"game": self.s["id"], "stage": "final", "player": x["player"], "attempt": x["attempt"], "passed": x["passed"],
                                    "lift": x["lift"], "rank": x.get("rank"), "spec_hash": self.s["seal"]["spec_hash"], "synthetic": self.s["synthetic"]})
        self._event("claim", {"spec_hash": self.s["seal"]["spec_hash"], "game": self.s["id"], "status": "judged",
                              "attempts": len(self.s["attempts"]), "passed": len(passing), "synthetic": self.s["synthetic"]})
        return out

    # -- what anyone may read --------------------------------------------------------------------------------------------
    def board(self) -> list[dict]:
        """The public leaderboard: each player's shown (Ladder) score, attempts, refusals; never a raw hidden score."""
        rows = []
        for pid, p in self.s["players"].items():
            mine = [a for a in self.s["attempts"] if a["pid"] == pid]
            rows.append({"player": pid, "name": p["name"], "kind": p["kind"], "label": p["label"], "shown": p["shown"],
                         "attempts": len(mine), "refused": sum(1 for a in mine if a["decision"] == "refused"), "out": p["out"]})
        sign = 1 if self.task.maximize else -1
        rows.sort(key=lambda r: (r["shown"] is None, -(sign * (r["shown"] or 0)), r["name"].lower()))
        return rows

    def public(self) -> dict:
        t = self.task
        return {"id": self.s["id"], "title": self.s["title"], "field": self.s["field"], "status": self.s["status"], "round": self.s["round"],
                "rules": self.s["rules"], "synthetic": self.s["synthetic"], "spec_hash": self.s["seal"]["spec_hash"],
                "judge_hash": self.s["seal"]["judge_hash"], "metric": t.spec["metric"], "direction": t.spec["direction"],
                "editable": t.editable, "min_lift": t.spec["min_lift"], "baseline_shown": self.s.get("baseline_shown"),
                "program": t.program, "idea": t.idea, "board": self.board(), "pot": self.pot_public(),
                "final": self.s["final"], "players": len(self.s["players"]), "attempts": len(self.s["attempts"]),
                "never_shown": "the sealed data, any raw hidden score, other players' files"}

    def baseline(self) -> str:
        return self.task.baseline

    def public_data(self, which: str) -> str:
        """The public train or val rows as CSV (what every player may train and validate on)."""
        if which not in ("train", "val"):
            raise GameError("which: train or val")
        rows = self.task.public()[which]
        n =len(rows[0][0]) if rows else 0
        lines = [",".join([f"x{i}" for i in range(n)] + ["y"])]
        lines += [",".join([repr(float(v)) for v in x] + [str(int(y))]) for x, y in rows]
        return "\n".join(lines) + "\n"

    # -- the pot (amounts in base units of a 6-decimal mint; the money is in knos_pay orders, knos.game.pot) --------------
    def pledge(self, funder: str, amount: int, *, order: str | None = None, tx: str | None = None, cluster: str = "devnet",
               label: str = "") -> dict:
        funder = _name(funder, "funder")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise GameError("amount: base units, a whole number above 0")
        with self.lock:
            if self.s["status"] == "final":
                raise GameError("the game is over: the pot is closed")
            row = {"funder": funder, "amount": amount, "order": order, "tx": tx, "cluster": cluster, "label": label[:80], "at": _now()}
            self.s["pot"]["pledges"].append(row)
            self.save()
        self._event("funding", {"game": self.s["id"], "funder": funder, "amount": amount, "order": order or "", "tx": tx or "",
                                "cluster": cluster, "spec_hash": self.s["seal"]["spec_hash"], "synthetic": self.s["synthetic"]})
        return row

    def pot_total(self) -> int:
        return sum(int(x["amount"]) for x in self.s["pot"]["pledges"])

    def pot_public(self) -> dict:
        return {"total": self.pot_total(), "pledges": [{k: x.get(k) for k in ("funder", "amount", "order", "tx", "cluster", "label")}
                                                      for x in self.s["pot"]["pledges"]], "split": self.s["pot"].get("split")}


def _public_reasons(v, decision: str) -> list[str]:
    """Reasons a player may read: rule names and plain words; what a sealed run printed is withheld."""
    if decision == "scored":
        return []
    from ..referee.verdict import redact_hidden
    out = []
    for r in v.reasons[:5]:
        s = str(r)
        if decision == "failed" and "seed" in s:
            s = s.split(":")[0] + ": the run failed or overran its time budget (details withheld: sealed)"
        out.append(s[:200])
    return redact_hidden(out)
