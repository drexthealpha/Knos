"""The GitLab round as one command: a gitlab.com pipeline's ID token verified by knos_oidc at the PUBLIC id, and an
order paid on it by knos_pay.

    python scripts/gitlab_round.py check                                  what is missing, exactly; exit 3 when anything is
    GITLAB_TOKEN=... KNOS_GITLAB_PROJECT=group/name python scripts/gitlab_round.py run --rpc URL --keys DIR [--resume]
    python scripts/gitlab_round.py run --simulate                         the same steps on the local simulator, test key

`scripts/exercise_public.py run --only gitlab` runs the same function as the round `gitlab` (it passes itself in).

What the command does, in order, each step kept so that it is never done twice:

  1. reads the project, the token's user, and whether GitLab's signing keys are usable at the public knos_oidc;
  2. pushes examples/gitlab/.gitlab-ci.yml to the branch `knos` and protects it (the order pins this file's commit);
  3. adds the trigger job to the default branch's .gitlab-ci.yml when the project has none (TRIGGER below);
  4. opens a merge request whose description names the payee's address, and merges it;
  5. funds an order for that merge request from the wallet <keys>/funder.json: no token is needed to fund, so nobody
     has to start a pipeline in a browser;
  6. starts a pipeline on the default branch with the pay audience; its trigger job starts the pinned pipeline on
     `knos`, whose job reads the merge request from GitLab's API and leaves the signed token as an artifact;
  7. holds that token to the escrow's rules offline (no fee is spent on one the program would refuse), has knos_oidc
     verify it, and sends PayOrder.

Without a token or a project it prints what is missing and exits 3; so does a step that waits for GitLab (the
pipeline has not finished: run it again with `--resume`). Exit 1 only when something was not as it should be.
Nothing here runs on mainnet; the money is test USDC. The simulator's GitLab is a stand-in written here (`Stand`):
its tokens are signed by the test key the test build takes as a gitlab.com key, and it is evidence of nothing on
gitlab.com.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from knos.settle.v2 import oidc, pay, relay  # noqa: E402

API = "https://gitlab.com/api/v4"
HOST = "gitlab.com"
BRANCH = "knos"
CI_FILE = ".gitlab-ci.yml"
PINNED = ROOT / "examples" / "gitlab" / CI_FILE
GL_NS, GL_ID = 8 * 10 ** 17, 9 * 10 ** 17       # programs-v2/knos_pay/src/gl.rs: where namespace ids start, and project and user ids
TOKEN_LIFE = 3600                               # the escrow refuses a token that lives longer (lib.rs TOKEN_LIFE)
ARTIFACT = "knos-token.jwt"
# What the default branch's own .gitlab-ci.yml needs: a job that starts the pinned pipeline and hands it the audience.
# A pipeline that a `trigger:` job started is signed with `pipeline_source` "pipeline", which is what PayOrder asks for.
TRIGGER = """knos-pay:
  rules:
    - if: '$KNOS_AUD =~ /^knos3:pay:/'
  variables:
    KNOS_AUD: $KNOS_AUD
  trigger:
    project: $CI_PROJECT_PATH
    branch: knos
"""
MISSING = {
    "GITLAB_TOKEN": "GITLAB_TOKEN is not set: a gitlab.com personal access token with the scope `api`, of a user with the Maintainer role in the project "
                    "(it pushes one branch and protects it, opens and merges one merge request, and starts one pipeline)",
    "KNOS_GITLAB_PROJECT": "KNOS_GITLAB_PROJECT is not set: the path of a PUBLIC project on gitlab.com with instance runners on, as `group/name` "
                           "(or `python scripts/exercise_public.py note gitlab --keys <keys> project=group/name`)",
}


class Refused(Exception):
    """A token or a merge request the escrow's rules would not take: said before any fee is spent."""


def missing(env: Mapping[str, str] | None = None, noted: dict | None = None) -> list[str]:
    """Every credential the round lacks, each as one line that says what to set."""
    env = os.environ if env is None else env
    out = [] if env.get("GITLAB_TOKEN") else [MISSING["GITLAB_TOKEN"]]
    if not (env.get("KNOS_GITLAB_PROJECT") or (noted or {}).get("project")):
        out.append(MISSING["KNOS_GITLAB_PROJECT"])
    return out


# ---- GitLab, as the round asks it ------------------------------------------------------------------------------------
class GitLab:
    """gitlab.com's REST API (version 4), with a personal access token. `http(method, url, body, headers)` returns
    (status, bytes): given by a test, else urllib."""

    def __init__(self, project: str, token: str, http: Callable[..., tuple[int, bytes]] | None = None):
        self.path, self.secret, self.http = project, token, http or _http
        self.at = f"{API}/projects/{urllib.parse.quote(project, safe='')}"

    def call(self, method: str, url: str, body: dict | None = None, ok: tuple[int, ...] = (200, 201), raw: bool = False) -> Any:
        status, got = self.http(method, url, body, {"PRIVATE-TOKEN": self.secret})
        if status == 404 and 404 not in ok:
            return None
        if status not in ok:
            raise RuntimeError(f"GitLab answered {status} to {method} {url.removeprefix(API)}: {got[:200].decode('utf-8', 'replace')}")
        return got if raw else json.loads(got or b"null")

    def project(self) -> dict | None:
        p = self.call("GET", self.at)
        return p and {"id": int(p["id"]), "path": p["path_with_namespace"], "namespace_id": int(p["namespace"]["id"]), "default_branch": p.get("default_branch"),
                      "visibility": p.get("visibility"), "runners": bool(p.get("shared_runners_enabled"))}

    def user(self) -> dict:
        u = self.call("GET", f"{API}/user")
        return {"id": int(u["id"]), "username": u["username"]}

    def branch(self, name: str) -> dict | None:
        b = self.call("GET", f"{self.at}/repository/branches/{urllib.parse.quote(name, safe='')}")
        return b and {"sha": b["commit"]["id"], "protected": bool(b["protected"]), "default": bool(b["default"])}

    def file(self, branch: str, path: str) -> str | None:
        got = self.call("GET", f"{self.at}/repository/files/{urllib.parse.quote(path, safe='')}/raw?ref={urllib.parse.quote(branch, safe='')}", raw=True)
        return None if got is None else got.decode("utf-8")

    def commit(self, branch: str, path: str, content: str, message: str, start: str | None = None) -> str:
        action = "create" if self.file(branch if start is None else start, path) is None else "update"
        body = {"branch": branch, "commit_message": message, "actions": [{"action": action, "file_path": path, "content": content}]}
        return str(self.call("POST", f"{self.at}/repository/commits", {**body, **({"start_branch": start} if start else {})})["id"])

    def protect(self, branch: str) -> None:
        # 40: Maintainer. 409: it is protected already.
        self.call("POST", f"{self.at}/protected_branches", {"name": branch, "push_access_level": 40, "merge_access_level": 40}, ok=(200, 201, 409))

    def open_mr(self, source: str, target: str, title: str, description: str) -> int:
        got = self.call("POST", f"{self.at}/merge_requests", {"source_branch": source, "target_branch": target, "title": title, "description": description,
                                                              "remove_source_branch": True})
        return int(got["iid"])

    def mr(self, iid: int) -> dict | None:
        m = self.call("GET", f"{self.at}/merge_requests/{iid}")
        return m and {"state": m["state"], "target_branch": m["target_branch"], "sha": m["sha"], "author_id": int(m["author"]["id"]),
                      "description": m.get("description") or ""}

    def merge(self, iid: int) -> bool:
        """True once merged. GitLab answers 405 or 422 while it still checks whether the request can be merged."""
        status, _got = self.http("PUT", f"{self.at}/merge_requests/{iid}/merge", {}, {"PRIVATE-TOKEN": self.secret})
        return status == 200

    def start(self, ref: str, aud: str) -> int:
        return int(self.call("POST", f"{self.at}/pipeline", {"ref": ref, "variables": [{"key": "KNOS_AUD", "value": aud}]})["id"])

    def token(self, pipeline: int) -> dict:
        """Where the pipeline and the pinned one it started stand: {"state": running | failed | success, "jwt", "why"}."""
        bridges = self.call("GET", f"{self.at}/pipelines/{pipeline}/bridges") or []
        down = next((b.get("downstream_pipeline") for b in bridges if b.get("name") == "knos-pay" and b.get("downstream_pipeline")), None)
        if down is None:
            up = self.call("GET", f"{self.at}/pipelines/{pipeline}") or {}
            ended = up.get("status") in ("failed", "canceled", "skipped")
            return {"state": "failed" if ended else "running", "why": f"pipeline {pipeline} is {up.get('status')} and started no pipeline on `{BRANCH}`"}
        jobs = self.call("GET", f"{self.at}/pipelines/{int(down['id'])}/jobs") or []
        job = next((j for j in jobs if j.get("name") == "knos-pay"), None)
        if job is None or job.get("status") in ("created", "pending", "running", "waiting_for_resource", "preparing"):
            return {"state": "running", "why": f"the pinned pipeline {down['id']} has not finished its job"}
        if job["status"] != "success":
            return {"state": "failed", "why": f"the pinned job {job['id']} ended `{job['status']}`: {job.get('web_url', '')}"}
        got = self.call("GET", f"{self.at}/jobs/{int(job['id'])}/artifacts/{ARTIFACT}", raw=True)
        if got is None:
            return {"state": "failed", "why": f"the pinned job {job['id']} left no {ARTIFACT}"}
        return {"state": "success", "jwt": got.decode("utf-8").strip(), "job": int(job["id"])}


def _http(method: str, url: str, body: dict | None, headers: dict) -> tuple[int, bytes]:   # pragma: no cover - the network
    if not url.startswith(API + "/"):
        raise ValueError("only gitlab.com's API is asked")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={**headers, "Content-Type": "application/json"})  # noqa: S310 - a fixed https host
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return r.status, r.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


class Stand:
    """A stand-in for one gitlab.com project, in memory, for the simulator: it keeps branches, files and merge requests,
    starts the pinned pipeline only as GitLab would (the default branch's file has the trigger job, the branch `knos`
    is protected), runs the pinned job's checks (`judge`), and signs what GitLab documents with the test key."""
    PROJECT, NAMESPACE, USER = 20, 72, 4242

    def __init__(self, now: Callable[[], int], sign: Callable[[dict], str], claims: Callable[..., dict], path: str = "my-group/my-project"):
        self.now, self.sign, self.claims, self.path = now, sign, claims, path
        self.files: dict[str, dict[str, str]] = {"main": {"README.md": "a project\n"}}
        self.shas: dict[str, str] = {"main": "1" * 40}
        self.protected, self._n = {"main"}, 1
        self.mrs: dict[int, dict] = {}
        self.pipes: dict[int, tuple[str, str]] = {}
        self.source = "pipeline"        # what the pinned pipeline is signed as: a test sets another to see it refused

    def _sha(self) -> str:
        self._n += 1
        return f"{self._n:040x}"

    def project(self) -> dict | None:
        return {"id": self.PROJECT, "path": self.path, "namespace_id": self.NAMESPACE, "default_branch": "main", "visibility": "public", "runners": True}

    def user(self) -> dict:
        return {"id": self.USER, "username": "sample-user"}

    def branch(self, name: str) -> dict | None:
        return {"sha": self.shas[name], "protected": name in self.protected, "default": name == "main"} if name in self.shas else None

    def file(self, branch: str, path: str) -> str | None:
        return self.files.get(branch, {}).get(path)

    def commit(self, branch: str, path: str, content: str, message: str, start: str | None = None) -> str:
        if branch not in self.files:
            self.files[branch] = dict(self.files[start or "main"])
        self.files[branch][path] = content
        self.shas[branch] = self._sha()
        return self.shas[branch]

    def protect(self, branch: str) -> None:
        self.protected.add(branch)

    def open_mr(self, source: str, target: str, title: str, description: str) -> int:
        iid = len(self.mrs) + 1
        self.mrs[iid] = {"state": "opened", "target_branch": target, "sha": self.shas[source], "author_id": self.USER, "description": description, "source": source}
        return iid

    def mr(self, iid: int) -> dict | None:
        m = self.mrs.get(iid)
        return m and {k: v for k, v in m.items() if k != "source"}

    def merge(self, iid: int) -> bool:
        m = self.mrs[iid]
        self.files[m["target_branch"]].update(self.files.pop(m["source"]))
        self.shas[m["target_branch"]] = self._sha()
        m["state"] = "merged"
        return True

    def start(self, ref: str, aud: str) -> int:
        self.pipes[len(self.pipes) + 1] = (ref, aud)
        return len(self.pipes)

    def token(self, pipeline: int) -> dict:
        ref, aud = self.pipes[pipeline]
        if "trigger:" not in (self.file(ref, CI_FILE) or "") or BRANCH not in self.protected or self.file(BRANCH, CI_FILE) is None:
            return {"state": "failed", "why": f"pipeline {pipeline} started no pipeline on `{BRANCH}`"}
        try:
            judge(aud, have(self.project()), self.mr(int(aud.split(":")[6])), self.branch("main"))
        except (Refused, ValueError, IndexError) as why:
            return {"state": "failed", "why": f"the pinned job ended `failed`: {why}"}
        now = self.now()
        c = self.claims(aud=aud, iat=now, nbf=now - 5, exp=now + 300, jti=f"stand-{pipeline}", pipeline_source=self.source, ref=BRANCH,
                        ref_path=f"refs/heads/{BRANCH}", ref_protected="true", ci_config_ref_uri=uri_of(self.path), ci_config_sha=self.shas[BRANCH],
                        project_id=str(self.PROJECT), project_path=self.path, namespace_id=str(self.NAMESPACE), user_id=str(self.USER),
                        sub=f"project_path:{self.path}:ref_type:branch:ref:{BRANCH}")
        return {"state": "success", "jwt": self.sign(c), "job": pipeline}


def have(x: Any) -> Any:
    if x is None:
        raise Refused("GitLab has no such record")
    return x


# ---- the rules, offline ----------------------------------------------------------------------------------------------
def uri_of(project_path: str) -> str:
    """`ci_config_ref_uri` for the pinned file on the pinned branch: what an order's pin is the sha256 of."""
    return f"{HOST}/{project_path}//{CI_FILE}@refs/heads/{BRANCH}"


def judge(aud: str, project: dict, mr: dict | None, default: dict | None) -> tuple[int, Pubkey]:
    """What the pinned job checks before it lets the token out, in the same order (examples/gitlab/.gitlab-ci.yml):
    one payee with the whole share; the default branch is protected; the merge request is merged into it, at the
    head the audience names, written by the payee, and its description names the address. Returns (payee, address)."""
    parts = aud.split(":")
    if len(parts) != 8 or parts[:2] != ["knos3", "pay"]:
        raise Refused("the audience is not knos3:pay:<order>:<head>:<terms>:<mode>:<merge request>:<payees>")
    head, payees = parts[3], parts[7].split(",")
    if len(payees) != 1 or payees[0].count(".") != 2:
        raise Refused("the audience names more than one payee, or one with no address")
    payee, share, address = payees[0].split(".")
    if share != "10000":
        raise Refused("the payee's share is not the whole amount")
    if not (default and default["protected"] and default["default"]):
        raise Refused("the default branch is not protected")
    if mr is None or mr["state"] != "merged":
        raise Refused("the merge request is not merged")
    if mr["target_branch"] != project["default_branch"]:
        raise Refused("the merge request was not merged into the default branch")
    if mr["sha"] != head:
        raise Refused("the merge request's head is not the commit the audience names")
    if GL_ID + int(mr["author_id"]) != int(payee):
        raise Refused("the payee is not the merge request's author")
    if f"Knos-Pay-To: {address}" not in mr["description"].splitlines():
        raise Refused("the merge request's description does not name the address")
    return int(payee), Pubkey.from_string(address)


def spend_checks(c: dict, project: dict, pinned_sha: str, aud: str, now: int) -> None:
    """The claims of a pay token held to what knos_pay asks of a GitLab token (gl.rs `read`, then the order's pin), in
    its order. Refused names the claim: a token that fails here would cost its fee and pay nothing."""
    def no(claim: str, want: object) -> Refused:
        return Refused(f"the token's `{claim}` is {c.get(claim)!r}; the escrow takes only {want!r}")
    if c.get("iss") != oidc.ISSUERS[oidc.GITLAB]:
        raise no("iss", oidc.ISSUERS[oidc.GITLAB])
    if int(c.get("exp", 0)) - int(c.get("iat", 0)) > TOKEN_LIFE:
        raise Refused(f"the token lives over an hour ({int(c.get('exp', 0)) - int(c.get('iat', 0))} s): give the job a shorter timeout")
    if int(c.get("exp", 0)) + oidc.LATE <= now:
        raise Refused("the token expired over an hour ago: start the pipeline again")
    for claim, want in (("runner_environment", "gitlab-hosted"), ("ref_type", "branch"), ("ref_protected", "true"), ("pipeline_source", "pipeline"),
                        ("ref_path", f"refs/heads/{BRANCH}"), ("project_path", project["path"]), ("ci_config_ref_uri", uri_of(project["path"])),
                        ("ci_config_sha", pinned_sha), ("project_id", str(project["id"])), ("namespace_id", str(project["namespace_id"])), ("aud", aud)):
        if c.get(claim) != want:
            raise no(claim, want)


def keys_state(w: Any, jwks: dict | None = None) -> tuple[list[str], list[str]]:
    """(usable, not usable): each key GitLab publishes today, by its `kid`, as the public knos_oidc holds it."""
    doc = (jwks or {}).get(oidc.GITLAB) or relay._jwks(oidc.GITLAB, jwks)
    good: list[str] = []
    bad: list[str] = []
    now = w.now()
    for kid, n in oidc.jwks_keys(doc):
        ok, why = oidc.key_usable(oidc.read_key(w.account(oidc.key_pda(oidc.GITLAB, n))), now)
        (good if ok else bad).append(kid if ok else f"{kid}: {why}")
    return good, bad


# ---- the round -------------------------------------------------------------------------------------------------------
def simulated_forge(w: Any) -> Stand:
    """The stand-in, on the simulator's clock, signing with the 4096-bit seed key; that key is registered as the test
    build's gitlab.com key and offered to the relay as GitLab's key set."""
    s = w.s
    key = s.signing_key(4096)
    n = s.modulus(key)
    if oidc.read_key(w.account(oidc.key_pda(oidc.GITLAB, n))) is None:
        assert w.c.register(oidc.GITLAB, n), w.c.err
    w.jwks = {**(w.jwks or {}), oidc.GITLAB: {"keys": [{"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": "k", "n": s.b64(oidc.modulus_bytes(n))}]}}

    def now() -> int:
        w.c.warp(1)
        return int(w.c.now())
    return Stand(now, lambda c: s.sign_jwt(key, c), s.gitlab_claims)


def payee_wallet(w: Any) -> Pubkey:
    """Where the round's merge request asks to be paid: the wallet of <keys>/gitlab_payee.json when there is one, else
    one made from the relayer's own key, so that the test USDC stays with whoever runs the round."""
    keys = getattr(w, "keys", None)
    if keys is not None and (keys / "gitlab_payee.json").is_file():
        from knos import chain
        return chain.wallet(keys / "gitlab_payee.json").pubkey()
    return Keypair.from_seed(hashlib.sha256(b"knos gitlab round payee" + bytes(w.relayer.secret())).digest()).pubkey()


def round_gitlab(book: Any, st: dict, ep: Any, forge: Any = None, env: Mapping[str, str] | None = None, sleep: Callable[[float], None] = time.sleep,
                 polls: int = 40) -> None:
    """A gitlab.com pipeline's token is verified by knos_oidc and pays a wallet-funded order to a merge request's author."""
    w = book.w
    if "paid" in st:
        return
    if forge is None and w.mode == "simulated":
        forge = simulated_forge(w)
    if forge is None:
        env = os.environ if env is None else env
        noted = w.outside("gitlab") or {}
        lacks = missing(env, noted)
        if lacks:
            raise ep.Need("the GitLab round", "; ".join(lacks) + ". Then `python scripts/gitlab_round.py run --rpc <rpc> --keys <keys>`")
        forge = GitLab(env.get("KNOS_GITLAB_PROJECT") or noted["project"], env["GITLAB_TOKEN"])
    project = forge.project()
    if project is None:
        raise ep.Need("the GitLab round", "GitLab has no such project for this token: check KNOS_GITLAB_PROJECT and the token's scope `api`")
    if project["visibility"] != "public" or not project["runners"] or not project["default_branch"]:
        raise ep.Need("the GitLab round", f"{project['path']} must be public (the pinned job reads GitLab's API with no token), have instance runners on "
                                          "(the escrow takes only a GitLab-hosted runner) and have a default branch with one commit")
    good, bad = keys_state(w, w.jwks)
    if not good:
        raise ep.Cannot("the public knos_oidc holds no usable key of gitlab.com (" + "; ".join(bad) + "). A GitLab key is named by a run of the rotate workflow, "
                        "waits a day and is approved by the guardian (docs/OIDC.md, \"The trust root\"); `knos keys` prints each key's state")
    me, default = forge.user(), project["default_branch"]
    st["project"] = {"path": project["path"], "id": project["id"], "namespace": project["namespace_id"], "user": me["id"]}

    # 2. the pin: the example's file on the protected branch `knos`
    text = PINNED.read_text(encoding="utf-8")
    if forge.file(BRANCH, CI_FILE) != text:
        forge.commit(BRANCH, CI_FILE, text, "Knos: the pinned pipeline (examples/gitlab/.gitlab-ci.yml)", start=None if forge.branch(BRANCH) else default)
    forge.protect(BRANCH)
    pin = forge.branch(BRANCH)
    ep._check(bool(pin and pin["protected"]), f"the branch `{BRANCH}` is not protected")
    uri, sha = uri_of(project["path"]), pin["sha"]

    # 3. the default branch starts it
    own = forge.file(default, CI_FILE)
    if own is None:
        forge.commit(default, CI_FILE, TRIGGER, "Knos: start the pinned pipeline with the audience it is given")
    elif "knos-pay:" not in own or "trigger:" not in own:
        raise ep.Need("the GitLab round", f"{project['path']} has a {CI_FILE} of its own on `{default}` with no job `knos-pay`: add this job to it (nothing of "
                                          "yours is overwritten here):\n" + TRIGGER)
    ep._check(bool(have(forge.branch(default))["protected"]), f"the default branch `{default}` is not protected: the pinned job pays nothing for it")

    # 4. a merge request by the token's user, naming where it is paid, merged
    payee, wallet = GL_ID + me["id"], payee_wallet(w)
    if "mr" not in st:
        source = f"knos-round-{w.now()}"
        forge.commit(source, f"knos-round/{source}.txt", "A change made for the Knos GitLab round. Test data.\n", "Knos round: one line", start=default)
        st["mr"] = {"iid": forge.open_mr(source, default, "Knos round: one line", f"A change made for the Knos GitLab round.\n\nKnos-Pay-To: {wallet}")}
    iid = st["mr"]["iid"]
    for _ in range(polls):
        if have(forge.mr(iid))["state"] == "merged" or forge.merge(iid):
            break
        sleep(3)
    mr = have(forge.mr(iid))
    if mr["state"] != "merged":
        raise ep.Need("the GitLab round", f"merge request !{iid} of {project['path']} is `{mr['state']}`: merge it, then this again with `--resume`")

    # 5. the order: a wallet funds it for this project and this pin
    terms = pay.terms_json({"accept": "", "checks": [], "mode": "merge", "v": 2})
    repo = GL_ID + project["id"]
    order = pay.order_pda(pay.scope_of(repo, iid), w.funder.pubkey(), 0)
    if "order" not in st:
        need = ep.AMOUNT + max(rule(ep.AMOUNT) for _words, rule in ep.FEE_RULES.values())
        ep._check(w.tokens(w.funder_token) >= need, f"the funding wallet {w.funder.pubkey()} holds {ep.money(w.tokens(w.funder_token))} test USDC; "
                                                    f"this round needs {ep.money(need)}")
        sig = w.send([pay.fund_order_wallet_ix(w.funder.pubkey(), w.funder_token, w.mint, repo, iid, ep.AMOUNT, uri, sha, terms)], w.funder)
        st["order"] = {"signature": sig, "address": str(order), "pin": sha}
        book.tx(st, f"a wallet funds an order for merge request !{iid} of the GitLab project {project['id']}, pinned to `{BRANCH}` at {sha[:12]}", sig, "knos_pay")
    o = ep.have(pay.read_order(w.account(order)), "the order")
    ep._check(o.repo_id == repo and o.wf_sha == sha and o.wf_repo_hash == pay.wf_repo_hash(uri), "the order does not pin this project's file at this commit")

    # 6. the pipeline, and its token
    aud = pay.order_pay_audience(order, mr["sha"], o.terms, o.mode, iid, [(payee, 10_000, wallet)])
    judge(aud, project, mr, forge.branch(default))
    if "token" not in st:
        if "pipeline" not in st:
            st["pipeline"] = forge.start(default, aud)
        got: dict = {"state": "running", "why": "not asked yet"}
        for _ in range(polls):
            got = forge.token(st["pipeline"])
            if got["state"] != "running":
                break
            sleep(15)
        if got["state"] == "running":
            raise ep.Need("the GitLab round", f"{got['why']}: this again with `--resume` when it has (a token is taken up to an hour after it expires)")
        if got["state"] == "failed":
            st.pop("pipeline")
            raise ep.Failed(f"{got['why']}. Nothing was sent to Solana; the order {order} stays open and goes back to its funder at its deadline")
        st["token"] = {"jwt": got["jwt"], "job": got.get("job")}
    jwt = st["token"]["jwt"]

    # 7. held to the rules for nothing, then verified and spent
    try:
        spend_checks(relay.claims_of(jwt), project, sha, aud, w.now())
    except Refused as why:
        st.pop("token"), st.pop("pipeline", None)
        raise ep.Failed(f"{why}. No fee was spent; the order {order} stays open") from None
    before = w.tokens(pay.ata(wallet, w.mint))
    seen = relay.verify_only(w.ledger, w.relayer, jwt, w.jwks, now=w.clock())
    ep._check(bool(seen.get("ok")), f"knos_oidc did not verify GitLab's token: {seen.get('why')}")
    account = Pubkey.from_string(seen["account"])
    t = ep.have(oidc.read_token(w.account(account)), "the verified token")
    verified = (seen.get("sigs") or [""])[-1] or next(iter(w.ledger.history(account, 5)), "")
    book.tx(st, f"knos_oidc verifies the token of GitLab job {st['token']['job']} ({len(seen.get('sigs') or [])} transactions; this is the last)", verified, "knos_oidc")
    me_ = w.relayer.pubkey()     # as the relay prepares PayOrder: the relayer's and the fee owner's token accounts exist first
    first = [pay.create_ata_ix(me_, owner, o.mint, o.token_program) for owner in (me_, pay.FEE_OWNER) if w.account(pay.ata(owner, o.mint, o.token_program)) is None]
    paid = w.send([*first, pay.pay_order_ix(me_, account, t.key, order, o, [(payee, wallet)], pr=iid, used=jwt)])
    ep._check(w.account(order) is None, "the order is still open after PayOrder")
    ep._check(w.tokens(pay.ata(wallet, w.mint)) - before == o.amount, "the payee's account did not rise by the order's amount")
    st["paid"] = {"signature": paid, "amount": o.amount, "payee": payee, "token": str(account)}
    book.tx(st, f"the order pays {ep.money(o.amount)} to the merge request's author (GitLab user {me['id']})", paid, "knos_pay")
    book.done(st, "verify_gitlab", "knos_oidc", verified,
              [f"knos_oidc verified an ID token gitlab.com signed for job {st['token']['job']} of {project['path']} under a key GitLab publishes",
               f"its account {account} is VERIFIED and names the key {t.key}"])
    book.done(st, "gitlab_pay", "knos_pay", paid,
              [f"an order for GitLab project {project['id']} pinned sha256({uri}) and the commit {sha}",
               f"a pipeline that a pipeline started on the protected branch `{BRANCH}` at that commit signed the pay audience",
               f"the order closed and {ep.money(o.amount)} reached the address the merge request's description names",
               "the order was funded from a wallet, so no pipeline run by hand and no Balance was needed"])


def run(say: Callable[[str], None], simulate: bool, rpc: str | None, keys: Path | None, env: Mapping[str, str] | None = None, forge: Any = None, w: Any = None) -> int:
    """The round alone. 0: paid. 3: something is missing or GitLab has not finished (said exactly). 1: something was wrong."""
    import exercise_public as ep
    made = w is None
    if w is None:
        if not simulate:
            lacks = missing(env, None if keys is None else (ep._json(keys / ep.OUTSIDE) or {}).get("gitlab"))
            lacks += [] if rpc and keys else ["--rpc and --keys are not given: a devnet RPC URL, and the folder holding relayer.json and funder.json"]
            if lacks:
                say("the GitLab round did not start. Missing:")
                for line in lacks:
                    say(f"  - {line}")
                return 3
        w = ep.Simulated() if simulate else ep.Public(str(rpc), Path(str(keys)), say)
    try:
        where = None if simulate or keys is None else keys / ep.EVIDENCE
        old = ep._json(where) if where else None
        ev = old if old and old.get("mode") == w.mode else ep.new_evidence(w, ep.simulated_programs() if simulate else ep.read_programs(ep.mc._rpc(str(rpc))))
        st = ev["rounds"].setdefault("gitlab", {"round": "gitlab"})
        say(f"[gitlab] {' '.join((round_gitlab.__doc__ or '').split())}")
        code, why = 0, ""
        try:
            round_gitlab(ep.Book(ev, w, say), st, ep, forge=forge, env=env)
            st.pop("stopped", None)
        except ep.Need as need:
            code, why = 3, f"{need}: {need.how}"
        except ep.Cannot as no:
            code, why = 3, f"cannot: {no}"
        except ep.Skip as skip:
            code, why = 3, f"skipped: {skip}"
        except ep.Failed as bad:
            code, why = 1, f"failed: {bad}"
        except Exception as bad:  # noqa: BLE001 - written down like every other round's trouble, with the steps done so far kept
            code, why = 1, f"failed: {type(bad).__name__}: {str(bad)[:300]}"
        if why:
            st["stopped"] = why
            say(f"  {why}")
        else:
            say(f"  paid: {st['paid']['signature']}" + (" (simulated: evidence of nothing on gitlab.com or devnet)" if simulate else ""))
        if where:
            ep._write(where, ev)
            say(f"wrote {where}")
        return code
    finally:
        if made and simulate:
            w.close()


def main(argv: list[str] | None = None, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description="The GitLab round: one command.")
    ap.add_argument("command", choices=("check", "run"))
    ap.add_argument("--rpc")
    ap.add_argument("--keys", type=Path)
    ap.add_argument("--simulate", action="store_true", help="the local simulator, a stand-in for gitlab.com and the test key")
    ap.add_argument("--resume", action="store_true", help="accepted for symmetry: every run takes up where the last one stopped")
    a = ap.parse_args(argv)
    if a.command == "check":
        lacks = missing()
        for line in lacks:
            say(f"missing: {line}")
        if not lacks:
            say("GITLAB_TOKEN and KNOS_GITLAB_PROJECT are set; `run` reads the project, GitLab's keys on chain and the funding wallet next")
        return 3 if lacks else 0
    return run(say, a.simulate, a.rpc, a.keys)


if __name__ == "__main__":
    raise SystemExit(main())
