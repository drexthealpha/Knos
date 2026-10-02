"""`knos team …` and `knos mirror`: the team registry on Solana, from the command line."""

from __future__ import annotations

import time
from pathlib import Path

import typer


def register(app: typer.Typer, out, Stop, repo_of) -> None:
    team = typer.Typer(add_completion=False, help="a team registry on Solana: no server, nothing to host")
    app.add_typer(team, name="team")
    keys = typer.Typer(add_completion=False, help="carry your member key to your other machines")
    team.add_typer(keys, name="key")

    def _tf(repo: Path):
        from . import config
        tf = config.load(repo)
        if tf is None:
            raise Stop("This repo has no team yet (.knos/team.json).", "Start one:  knos team create --cluster devnet")
        return tf

    def _owner(tf):
        from .. import keystore
        from . import service
        try:
            return service.unlock_owner(tf.cluster)
        except keystore.NotATerminal as why:
            raise Stop(str(why)) from None
        except (keystore.KeystoreError, service.TeamError) as why:
            raise Stop(str(why)) from None

    @team.command("create")
    def create(cluster: str = typer.Option("devnet", "--cluster", help="devnet, mainnet or localnet"),
               name: str = typer.Option(None, "--name", help="your display name in the team"),
               owner_key: str = typer.Option(None, "--owner-key", metavar="FILE",
                                             help="use this funded Solana keypair file as the team owner key"),
               rpc_url: str = typer.Option(None, "--rpc", help="a custom RPC endpoint")) -> None:
        """Start a team registry for this repo."""
        import getpass
        from .. import keystore
        from . import config, service
        repo = repo_of(None)
        if config.load(repo) is not None:
            raise Stop("This repo already has a team (.knos/team.json).", "See it:  knos team status")
        if cluster not in config.CLUSTERS:
            raise Stop(f"Unknown cluster {cluster!r}.", "Use devnet, mainnet or localnet.")
        try:
            owner = service.owner_key_for_create(cluster, Path(owner_key) if owner_key else None)
            tf, cred = service.create(repo, cluster, name or getpass.getuser(), owner, rpc_url)
        except keystore.NotATerminal as why:
            raise Stop(str(why)) from None
        except (service.TeamError, keystore.KeystoreError) as why:
            raise Stop(str(why)) from None
        out.print(f"[green]✓[/green] team registry on Solana — no server, nothing to host (credential {cred})")
        out.print(f"[green]✓[/green] wrote .knos/team.json — commit it")
        out.print("Teammates run  knos init  in their clone and send you the join code it prints.")

    @team.command("add")
    def add(code: str = typer.Argument(..., help="the knos-join:… code your teammate sent"),
            fingerprint: str = typer.Option(None, "--fingerprint", help="the words your teammate read out"),
            cloud: str = typer.Option(None, "--cloud", help="instead: make a revocable member key for a cloud sandbox"),
            yes: bool = typer.Option(False, "--yes", help="skip the fingerprint question")) -> None:
        """Add a teammate from their join code (or a cloud sandbox key with --cloud NAME)."""
        import sys
        from . import service
        repo = repo_of(None)
        tf = _tf(repo)
        if cloud:
            owner = _owner(tf)
            got, path = service.add_cloud(tf, owner, cloud)
            out.print(f"[green]✓[/green] cloud member {cloud}: {' · '.join(got['steps']) or 'already added'}")
            out.print(f"Its key is in {path} (owner-only). Put that file's contents into the sandbox's secret "
                      "KNOS_MEMBER_KEY; see docs/CLOUD.md. Revoke with:  knos team remove " + got["key"])
            return
        try:
            key, display = service.parse_join_code(code)
        except (service.TeamError, ValueError) as why:
            raise Stop(str(why)) from None
        fp = service.fingerprint(key)
        if fingerprint and fingerprint.strip().lower() != fp:
            raise Stop(f"Fingerprint mismatch: this code gives {fp}. Do not add it.",
                       "Ask your teammate to read out the words their knos init printed.")
        if not fingerprint and not yes:
            if not sys.stdin.isatty():
                raise Stop(f"Check the fingerprint first: {fp}", "Then:  knos team add <code> --fingerprint " + fp)
            if not typer.confirm(f"Does {display}'s screen show the fingerprint {fp}?"):
                raise Stop("Not added.")
        owner = _owner(tf)
        try:
            got = service.add(tf, owner, code, repo=repo_of(None))
        except service.TeamError as why:
            raise Stop(str(why)) from None
        steps = got["steps"] or ["already a member"]
        out.print(f"[green]✓[/green] verified fingerprint · {' · '.join(steps)}  ({display})")

    @team.command("remove")
    def remove(who: str = typer.Argument(..., help="a member's name or public key")) -> None:
        """Take a member (or a cloud key) out of the team."""
        from . import service
        tf = _tf(repo_of(None))
        owner = _owner(tf)
        try:
            got = service.remove(tf, owner, who)
        except service.TeamError as why:
            raise Stop(str(why)) from None
        out.print(f"[green]✓[/green] {got['key']}: {' · '.join(got['steps']) or 'nothing to do'}")

    @team.command("leave")
    def leave() -> None:
        """Leave this team on this machine (the owner removes your key from the signers)."""
        from . import service
        tf = _tf(repo_of(None))
        got = service.leave(tf)
        out.print(f"Left {tf.name} here. Ask the owner to run:  knos team remove {got['key']}")

    @team.command("status")
    def status() -> None:
        """Who is in the team, how many claims are live, and this key's headroom."""
        from . import service
        tf = _tf(repo_of(None))
        try:
            got = service.status(tf)
        except Exception as why:  # noqa: BLE001
            raise Stop(f"Could not reach {tf.cluster}: {type(why).__name__}: {why}",
                       "Edits still work in local-only mode.") from None
        out.print(f"[bold]{got['name']}[/bold] on {got['cluster']}  credential {got['credential']}")
        out.print(f"  members {len(got['members'])} of {got['max_signers']} (SAS signer cap, measured)")
        for m in got["members"]:
            out.print(f"    {m['name'] or '(name sealed)':16} {m['key']}{'  owner' if m['owner'] else ''}")
        if "live_claims" in got:
            out.print(f"  live claims {got['live_claims']}")
        me = got.get("me")
        if me:
            state = "member" if me["member"] else "not added yet: send the owner your join code (knos init)"
            out.print(f"  this machine's key {me['key']}  {state}")
            out.print(f"  key float {me['sol']:.4f} SOL: room for about {me['claims_headroom']} live claims")

    @keys.command("export")
    def key_export(to: str = typer.Option("knos-member-key.sealed", "--to", help="where to write the sealed key")) -> None:
        """Seal your member key to a one-time code, for your other machine."""
        from . import service
        try:
            code = service.key_export(Path(to))
        except service.TeamError as why:
            raise Stop(str(why)) from None
        out.print(f"Wrote {to} (sealed). On the other machine:  knos team key import {Path(to).name}")
        out.print(f"One-time code (type it there; it is not stored anywhere): {code}")

    @keys.command("import")
    def key_import(path: str = typer.Argument(...)) -> None:
        """Install a member key sealed by `knos team key export`."""
        import getpass
        from .. import keystore
        from . import service
        code = getpass.getpass("One-time code: ")
        try:
            pub = service.key_import(Path(path), code)
        except keystore.KeystoreError as why:
            raise Stop(str(why)) from None
        out.print(f"[green]✓[/green] member key {pub} installed on this machine. Delete {path} now.")

    agent_app = typer.Typer(add_completion=False, help="what each agent did, verifiable on chain")
    app.add_typer(agent_app, name="agent")

    @agent_app.command("record")
    def agent_record(who: str = typer.Argument(..., help="an agent host on this machine: claude, codex, cursor, ..."),
                     days: int = typer.Option(3, "--days", min=1),
                     as_json: bool = typer.Option(False, "--json", help="output JSON for scripts")) -> None:
        """An agent's claims taken, finished and abandoned, and collisions, checked against its records on chain."""
        import json
        from . import live, records, units
        repo = repo_of(None)
        rt = live.runtime(repo)
        if rt is None:
            raise Stop("This machine is not in a team for this repo.", "knos init  (then send the join code)")
        host = live.HOST_NAMES.get(who.split("@")[0], who.split("@")[0])
        today = records.period_start()
        holders = {e["holder"] for e in live.events(rt, today - days * records.DAY) if e.get("holder")
                   and units.holder_host(rt.salt, bytes.fromhex(e["holder"])) == host}
        if not holders:
            if as_json:
                out.print(json.dumps({"host": host, "days": days, "holders": []}, indent=2), markup=False)
                return
            out.print(f"No record for {host} from this machine in the last {days} days.")
            return
        json_holders = []
        for h in sorted(holders):
            if not as_json:
                out.print(f"[bold]{host}[/bold] holder {h[:12]}…")
            holder_recs = []
            for d in range(days, -1, -1):
                start = today - d * records.DAY
                p = live.period_of(rt, bytes.fromhex(h), start)
                if not p.taken and not p.collisions:
                    continue
                when = time.strftime("%Y-%m-%d", time.gmtime(start))
                line = (f"  {when}  taken {p.taken}  finished {p.finished}  abandoned {p.abandoned}  "
                        f"collisions {p.collisions}")
                rec_entry: dict = {
                    "date": when,
                    "period_start": start,
                    "taken": p.taken,
                    "finished": p.finished,
                    "abandoned": p.abandoned,
                    "collisions": p.collisions,
                }
                if start == today:
                    if as_json:
                        rec_entry.update({"today": True, "on_chain": False, "status": "today: written to chain tomorrow"})
                        holder_recs.append(rec_entry)
                    else:
                        out.print(line + "  (today: written to chain tomorrow)")
                    continue
                try:
                    got = records.verify(rt.tf.url, rt.tf.credential, p)
                except Exception as why:  # noqa: BLE001
                    if as_json:
                        rec_entry.update({"today": False, "on_chain": None, "error": f"chain unreachable ({type(why).__name__})"})
                        holder_recs.append(rec_entry)
                    else:
                        out.print(line + f"  chain unreachable ({type(why).__name__})")
                    continue
                if not got["on_chain"]:
                    if as_json:
                        rec_entry.update({"today": False, "on_chain": False, "status": "not on chain yet"})
                        holder_recs.append(rec_entry)
                    else:
                        out.print(line + "  not on chain yet")
                else:
                    ok = got["counters_match"] and got["root_matches"]
                    if as_json:
                        rec = got.get("record")
                        rec_dict = None
                        if rec is not None:
                            rec_dict = {
                                "taken": rec.taken,
                                "finished": rec.finished,
                                "abandoned": rec.abandoned,
                                "collisions": rec.collisions,
                                "spent_micro_usd": rec.spent_micro_usd,
                                "merkle_root": rec.merkle_root.hex(),
                            }
                        rec_entry.update({
                            "today": False,
                            "on_chain": True,
                            "signer": got.get("signer", ""),
                            "counters_match": got["counters_match"],
                            "root_matches": got["root_matches"],
                            "verified": ok,
                            "record_on_chain": rec_dict,
                        })
                        holder_recs.append(rec_entry)
                    else:
                        out.print(line + ("  [green]verified on chain[/green]" if ok else
                                          "  [red]differs from the record on chain[/red]"))
            if as_json:
                json_holders.append({"holder": h, "records": holder_recs})
        if as_json:
            out.print(json.dumps({"host": host, "days": days, "holders": json_holders}, indent=2), markup=False)

    @app.command("prove")
    def prove(fact: str = typer.Argument(None, help="text of something an agent recorded"),
              days: int = typer.Option(7, "--days", min=1),
              job: str = typer.Option(None, "--job", help="a GitHub-posted job: pay it with --jwt-file's token"),
              jwt_file: Path = typer.Option(None, "--jwt-file", help="the GitHub Actions OIDC token (prove.yml)")) -> None:
        """Prove a recorded fact was in an agent's day, or (--job) pay a job with its GitHub Actions proof."""
        if job or jwt_file:
            return _prove_job(job, jwt_file)
        if not fact:
            raise Stop("Prove what?", 'knos prove "decided to shard by tenant"   or   knos prove --job ID --jwt-file F')
        from . import live, records
        repo = repo_of(None)
        rt = live.runtime(repo)
        if rt is None:
            raise Stop("This machine is not in a team for this repo.", "knos init")
        today = records.period_start()
        holders = {e["holder"] for e in live.events(rt, today - days * records.DAY) if e.get("holder")}
        for d in range(1, days + 1):
            start = today - d * records.DAY
            for h in holders:
                j = live.journal_for(rt, bytes.fromhex(h), start)
                hit = next((x for x in j if fact.lower() in str(x.get("text", "")).lower()), None)
                if hit is None:
                    continue
                p = live.period_of(rt, bytes.fromhex(h), start, j)
                target = records.leaf(rt.salt, {"journal": hit})
                path = records.proof(p.leaves, target)
                got = records.read(rt.tf.url, rt.tf.credential, bytes.fromhex(h), start)
                if got is None:
                    out.print("Found it, but that day's record is not on chain yet.")
                    return
                att, rec = got
                ok = records.verify_proof(target, path, rec.merkle_root)
                addr = records.record_address(rt.tf.credential, bytes.fromhex(h), start)
                out.print(f"{'[green]proven[/green]' if ok else '[red]does not match[/red]'}: {hit['text']!r}")
                out.print(f"  record {addr} ({time.strftime('%Y-%m-%d', time.gmtime(start))}), signed by {att.signer}")
                out.print(f"  leaf {target.hex()}")
                for sib in path:
                    out.print(f"  sibling {sib.hex()}")
                out.print(f"  merkle_root {rec.merkle_root.hex()}")
                return
        raise Stop(f"No recorded fact matching {fact!r} in a written record of the last {days} days.")

    def _prove_job(job: str | None, jwt_file: Path | None) -> None:
        from ..jobs import net
        from ..jobs import prove as gh
        if not job or not jwt_file:
            raise Stop("--job and --jwt-file go together.", "knos prove --job JOB_ID --jwt-file token.txt")
        try:
            jwt = jwt_file.read_text(encoding="utf-8").strip()
            job_id = net.resolve(job)
            gh.precheck(gh.claims(jwt), job_id)
        except OSError as why:
            raise Stop(f"Cannot read the token: {why}") from None
        except (net.Refused, ValueError) as why:
            raise Stop(f"Not sent: {why}") from None
        try:
            sigs = gh.prove(net.ledger(), net.key(), job_id, jwt)
        except net.Refused as why:
            raise Stop(str(why)) from None
        except LookupError as why:
            raise Stop(str(why)) from None
        except RuntimeError as why:
            raise Stop(f"The escrow refused: {why}") from None
        out.print(f"[green]proven[/green]: job {job_id.hex()[:16]} paid on its GitHub Actions proof")
        for s in sigs:
            out.print(f"  {s}", markup=False)

    @app.command("mirror", hidden=True)
    def mirror(once: bool = typer.Option(False, "--once")) -> None:
        """The background copy of the team's claims (started by the guard; one per team)."""
        from . import live
        raise typer.Exit(live.run_mirror(repo_of(None), once=once))


def join_hint(repo: Path) -> list[str]:
    """What `knos init` prints in a repo with .knos/team.json: joined, or the join code to send."""
    from . import config, service
    tf = config.load(repo)
    if tf is None:
        return []
    key = config.member_key(create=True)
    try:
        member = service.is_member(tf, key.pubkey())
    except Exception:  # noqa: BLE001
        return [f"! found .knos/team.json ({tf.name}) but {tf.cluster} is unreachable; claims stay local for now"]
    if member and config.salt(tf, key):
        return [f"✓ joined team {tf.name} on {tf.cluster}: claims are shared with every machine in it"]
    import getpass
    code = service.join_code(key.pubkey(), getpass.getuser())
    return [f"✓ found .knos/team.json — send this join code to the team owner: {code} "
            f"(fingerprint: {service.fingerprint(key.pubkey())})"]
