"""python -m knos.threshold <command>: Knos's FROST referee hosts.

    dkg-local --out DIR [--group PATH]     run the DKG as three separate processes on this machine (one per host);
                                           writes DIR/share-render.json, share-gh.json, share-pc.json (0600) and
                                           the PUBLIC group record (default config/referee-frost.json)
    dkg-party --id N --relay DIR --run ID --out FILE    one DKG party (what dkg-local starts; or one per host)
    sign-session --session ID [--coordinator URL] [--github-oidc] [--verdicts DIR]   one signing session (GitHub
                                           Actions: share from $KNOS_REFEREE_FROST_SHARE, the JSON itself)
    serve [--coordinator URL] [--every S] [--once] [--github-oidc] [--verdicts DIR] [--healthz-every S]
                                           take part in every open session (the PC daemon; GitHub Actions with --once
                                           --github-oidc: each post carries the job's OIDC token, audience knos-referee)
                                           --verdicts DIR: write the code referee's verdict file for every session this
                                           host's own check agreed with (knos.threshold.codeattest; referee.yml attests them)
                                           --healthz-every S: also GET <coordinator>/healthz every S seconds and log it
    info                                   the group key and hosts (public)
Never prints a share.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from . import GROUP_FILE, HOSTS, load_group, load_share

COORDINATOR = "https://knos.onrender.com"


def _share(arg: str | None) -> dict:
    src = arg or os.environ.get("KNOS_REFEREE_FROST_SHARE")
    if not src:
        sys.exit("give --share FILE or set KNOS_REFEREE_FROST_SHARE")
    return load_share(src)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos.threshold")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("dkg-local")
    a.add_argument("--out", required=True)
    a.add_argument("--group", default=str(GROUP_FILE))
    b = sub.add_parser("dkg-party")
    b.add_argument("--id", type=int, required=True)
    b.add_argument("--relay", required=True)
    b.add_argument("--run", required=True)
    b.add_argument("--out", required=True)
    for name in ("sign-session", "serve"):
        c = sub.add_parser(name)
        c.add_argument("--share")
        c.add_argument("--coordinator", default=os.environ.get("KNOS_REFEREE_COORDINATOR", COORDINATOR))
        if name == "sign-session":
            c.add_argument("--session", required=True)
        else:
            c.add_argument("--every", type=float, default=30.0)
            c.add_argument("--once", action="store_true")
            c.add_argument("--healthz-every", type=float, default=0.0, help="also GET <coordinator>/healthz this often (seconds; 0: never)")
        c.add_argument("--verdicts", default="", help="write the code referee's verdict file of each session this host agreed with here")
        c.add_argument("--github-oidc", action="store_true", help="add this GitHub Actions job's OIDC token to every post")
    sub.add_parser("info")
    ns = ap.parse_args(argv)

    if ns.cmd == "dkg-party":
        from .dkg import DirRelay, party
        print(json.dumps(party(ns.id, DirRelay(ns.relay), ns.run, ns.out)))
        return 0
    if ns.cmd == "dkg-local":
        from .dkg import DirRelay, group_record
        out = Path(ns.out).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        os.chmod(out, 0o700)
        relay, run_id = out / ".relay", uuid.uuid4().hex
        procs = [subprocess.Popen([sys.executable, "-m", "knos.threshold", "dkg-party", "--id", str(i), "--relay", str(relay),
                                   "--run", run_id, "--out", str(out / f"share-{HOSTS[i]}.json")], stdout=subprocess.PIPE)
                 for i in sorted(HOSTS)]
        res = [json.loads(p.communicate(timeout=900)[0] or b"{}") for p in procs]
        if any(p.returncode for p in procs):
            sys.exit("the DKG failed in one party; no group record written")
        rec = group_record(DirRelay(relay), run_id)
        shutil.rmtree(relay)                            # public packages and ciphertexts only; not kept
        Path(ns.group).write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"group_key": rec["group_key"], "parties": [r.get("id") for r in res], "group_record": ns.group}))
        return 0
    if ns.cmd == "info":
        g = load_group()
        print(json.dumps({k: g[k] for k in ("group_key", "min", "max", "hosts", "panel", "keygen")}, indent=1))
        return 0
    from knos import chain
    from .participant import HttpClient, serve, sign_session
    token = None
    if ns.github_oidc:
        from .ghoidc import request_token
        token = request_token
    share, client, led = _share(ns.share), HttpClient(ns.coordinator, host_token=token), chain.ledger()
    on_verdict = None
    if ns.verdicts:
        from . import codeattest

        def on_verdict(s, digest, ev):
            codeattest.write(codeattest.verdict(s, digest, ev), ns.verdicts)
    if ns.cmd == "sign-session":
        got = sign_session(share, client, ns.session, led, on_verdict=on_verdict)
        print(json.dumps(got))
        return 0 if got["outcome"] in ("shared",) or got["outcome"].startswith("not chosen") else 1
    serve(share, client, led, every=ns.every, once=ns.once, on_verdict=on_verdict, healthz_every=ns.healthz_every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
