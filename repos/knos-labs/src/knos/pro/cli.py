"""`knos spend`, `knos budget ...`, `knos pro ...`, added to the main command line by `register`."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import typer

from .. import paths
from . import budget, licence, meter, prices, solana, tempo


def register(app: typer.Typer, out, Stop) -> None:
    def need_pro() -> dict:
        licence.reverify()
        st = licence.status(start_trial=True)
        if not st["active"]:
            raise Stop("Your 14-day Knos Pro trial has ended. Memory, claims and the edit guard stay free.",
                       "Keep spend and caps:  knos pro buy   (22 USDC / 30 days, Sibyl Pro included)")
        if st["why"] == "trial":
            out.print(f"[dim]Knos Pro trial: {st['days_left']:.0f} day(s) left. knos pro buy when you are ready.[/dim]")
        return st

    @app.command()
    def spend(
        days: int = typer.Option(1, "--days", min=1, help="how far back (1 = since midnight)"),
        host: str = typer.Option(None, "--host", help="only claude or codex"),
    ) -> None:
        """What your agents spent, at API list prices, from their own logs. Nothing leaves the machine."""
        need_pro()
        meter.update()
        since = meter.period_start("day") - timedelta(days=days - 1)
        got = meter.spent(since, host)
        label = "today" if days == 1 else f"the last {days} days"
        out.print(f"[bold]${got['usd']:.2f}[/bold] {label}, {got['tokens']:,} tokens, at API list prices"
                  + (" (some models unpriced: estimated at the dearest rate)" if got["estimated"] else ""))
        for r in got["by"][:12]:
            out.print(f"  {r['host']:<7} {r['model'][:30]:<30} ${r['usd']:>9.2f}  {r['messages']:>6} calls")
        out.print("  [dim]Cursor, Claude Desktop and OpenCode: not metered (they keep no local usage log Knos can "
                  "read), which is not the same as $0.[/dim]")
        s = budget.state()
        if s:
            out.print(f"  cap: ${s['spent']:.2f} of ${s['usd']:.2f} this {s['per']}" + ("  [red]REACHED[/red]"
                                                                                      if s["over"] else ""))
        if days > 1:
            for day, usd in meter.by_day(days):
                out.print(f"  [dim]{day}  ${usd:.2f}[/dim]")

    bud = typer.Typer(help="A cap on what your agents spend; past it, their edits are refused.")
    app.add_typer(bud, name="budget")

    @bud.callback(invoke_without_command=True)
    def budget_show(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is not None:
            return
        s = budget.state()
        if not s:
            out.print("No spend cap. Set one:  knos budget set 20 --per day")
            return
        out.print(f"${s['spent']:.2f} of ${s['usd']:.2f} this {s['per']}" + ("  - reached; edits are refused"
                                                                             if s["over"] else ""))

    @bud.command("set")
    def budget_set(first: str = typer.Argument(..., metavar="USD | AGENT", help="dollars; or an agent with --chain"),
                   second: str = typer.Argument(None, metavar="[AMOUNT]", help="with --chain: 5/day or 20"),
                   per: str = typer.Option("day", "--per", help="day, week or month"),
                   repo: str = typer.Option(None, "--repo", help="count and cap only this repo's agent sessions"),
                   chain: str = typer.Option(None, "--chain", help="tempo or solana: a limit the chain enforces"),
                   network: str = typer.Option(None, "--network", help="tempo: moderato|mainnet; solana: devnet|"
                                                                       "mainnet|localnet"),
                   token: str = typer.Option(None, "--token", help="tempo: pathUSD, USDC.e or AlphaUSD; "
                                                                   "solana: a mint address (default USDC)")) -> None:
        """Set the cap across every agent, or (with --chain) one agent's limit enforced by Tempo or Solana."""
        need_pro()
        if chain:
            _chain_set(first, second, chain, network, token)
            return
        try:
            usd = float(first)
        except ValueError:
            raise Stop(f"{first!r} is not an amount.", "Example:  knos budget set 20 --per day   or   "
                       "knos budget set claude 5/day --chain tempo") from None
        try:
            cap = budget.set_cap(usd, per, repo)
        except ValueError as why:
            raise Stop(str(why), "Example:  knos budget set 20 --per day") from None
        where = f" for {cap['repo']}" if cap.get("repo") else " across every repo"
        out.print(f"Cap set: ${cap['usd']:.2f} per {cap['per']}{where}. Past it, the edit guard refuses the next edit "
                  "(knos init wires the guard); overshoot is at most the turn already running.")

    @app.command("report")
    def report_cmd(days: int = typer.Option(7, "--days", min=1),
                   out_file: str = typer.Option(None, "--out", help="also write it as markdown here")) -> None:
        """A weekly report: spend by agent and model, agents' API payments, claims, and edits refused."""
        from datetime import datetime, timedelta, timezone

        from .. import paths as kpaths
        from .. import worth as tally
        from . import agentpay

        need_pro()
        meter.update()
        since = datetime.now(timezone.utc) - timedelta(days=days)
        got = meter.spent(since)
        lines = [f"# Knos report, last {days} days", "",
                 f"Model spend at API list prices: **${got['usd']:.2f}**"
                 + (" (some models unpriced: estimated at the dearest rate)" if got["estimated"] else ""), ""]
        lines += [f"- {r['host']} / {r['model']}: ${r['usd']:.2f} ({r['messages']} calls)" for r in got["by"][:15]]
        paid = agentpay.summary()
        if paid:
            lines += ["", "Agents' API payments (their own wallets):"]
            lines += [f"- {r['agent']} on {r['chain']} {r['network']}: {r['spent']:g} of cap {r['cap']:g}" for r in paid]
        here = kpaths.repo_here()
        if here is not None:
            w = tally.tally(here)
            lines += ["", f"In {here.name}: {w['claimed']} claims by {w['agents']} agent(s), {w['released']} released, "
                          f"{w['blocked']} edits refused because another agent held the file."]
        by_day = meter.by_day(days)
        if by_day:
            lines += ["", "By day: " + ", ".join(f"{d} ${u:.2f}" for d, u in by_day)]
        text = "\n".join(lines) + "\n"
        out.print(text, markup=False)
        if out_file:
            from pathlib import Path

            Path(out_file).write_text(text, encoding="utf-8")

    def _chain_set(agent, amount_text, chain, network, token):
        from .. import keystore
        from . import chainbudget as cb
        if chain not in cb.NETWORKS:
            raise Stop(f"No chain called {chain}.", "Use --chain tempo or --chain solana")
        network = network or cb.NETWORKS[chain][0]
        if network not in cb.NETWORKS[chain]:
            raise Stop(f"{chain} has no network {network}.", "Networks: " + ", ".join(cb.NETWORKS[chain]))
        try:
            amount, period = cb.parse_amount(amount_text or "")
            if chain == "tempo":
                got = cb.tempo_set(agent, amount, period, network, token or "pathUSD")
                every = {86_400: "day", 604_800: "week", 2_592_000: "month"}.get(period, "")
                out.print(f"{agent} may spend {amount:g} {token or 'pathUSD'}" + (f" per {every}" if every else "")
                          + f" on Tempo {network}: Tempo enforces it (Keychain access key {got['key']}).")
                out.print(f"Budget account {got['root']}: fund it; the agent pays from it and cannot exceed the "
                          "limit. Revoke: knos budget revoke " + agent + " --chain tempo")
            else:
                if period:
                    raise cb.BudgetError("Solana delegates are a total, not a rate: use --chain solana with 20")
                got = cb.solana_set(agent, amount, network, token)
                out.print(f"{agent} may spend {amount:g} from vault {got['vault']} on Solana {network}: the Token "
                          f"program enforces it (delegate {got['key']}).")
                out.print(f"Fund the vault with the token (send to the token account {got['vault']}). "
                          "Revoke: knos budget revoke " + agent + " --chain solana")
        except keystore.NotATerminal as why:
            raise Stop(str(why)) from None
        except (cb.BudgetError, keystore.KeystoreError) as why:
            raise Stop(str(why)) from None
        notice = cb.legacy_wallets_notice()
        if notice:
            out.print(f"[dim]{notice}[/dim]")

    @bud.command("show")
    def budget_chain_show() -> None:
        """Every chain-enforced agent limit, read from the chain now."""
        from . import chainbudget as cb
        rows = cb.entries()
        if not rows:
            out.print("No chain-enforced budgets. knos budget set claude 5/day --chain tempo")
            return
        for name, e in rows.items():
            try:
                got = cb.tempo_show(e) if e["chain"] == "tempo" else cb.solana_show(e)
                left = f"{got['remaining']:g} left"
            except Exception as why:  # noqa: BLE001
                left = f"unreadable now ({type(why).__name__})"
            out.print(f"  {name:<22} {e['network']:<9} limit {e['amount']:g}  {left}")

    @bud.command("revoke")
    def budget_revoke(agent: str = typer.Argument(...),
                      chain: str = typer.Option(..., "--chain", help="tempo or solana")) -> None:
        """End an agent's chain-enforced budget (on Tempo the key can never be used again)."""
        from .. import keystore
        from . import chainbudget as cb
        e = cb.entries().get(f"{agent}@{chain}")
        if not e:
            raise Stop(f"{agent} has no {chain} budget.", "knos budget show")
        try:
            tx = cb.tempo_revoke(e) if chain == "tempo" else cb.solana_revoke(e)
        except keystore.NotATerminal as why:
            raise Stop(str(why)) from None
        except (cb.BudgetError, keystore.KeystoreError) as why:
            raise Stop(str(why)) from None
        out.print(f"Revoked {agent}'s {chain} budget: {tx}")

    @bud.command("raise")
    def budget_raise(by: float = typer.Argument(..., help="dollars to add")) -> None:
        """Raise the cap."""
        need_pro()
        try:
            cap = budget.raise_cap(by)
        except ValueError as why:
            raise Stop(str(why), "Set one first:  knos budget set 20") from None
        out.print(f"Cap is now ${cap['usd']:.2f} per {cap['per']}.")

    @bud.command("clear")
    def budget_clear() -> None:
        """Remove the cap."""
        out.print("Cap removed." if budget.clear() else "There was no cap.")

    @bud.command("fund")
    def budget_fund(
        amount: float = typer.Argument(..., help="how much the agent may spend, in stablecoin"),
        agent: str = typer.Option(..., "--agent", help="a name for the agent, e.g. claude or researcher"),
        chain: str = typer.Option("tempo", "--chain", help="tempo (MPP) or solana (x402)"),
        network: str = typer.Option("mainnet", "--network", help="mainnet, or testnet (Tempo) / devnet (Solana)"),
    ) -> None:
        """Give an agent its own budget wallet: it can never spend more than you put in it."""
        from . import wallets

        need_pro()
        if chain not in wallets.CHAINS:
            raise Stop(f"No chain called {chain}.", "Use --chain tempo or --chain solana")
        ok = tempo.CHAINS if chain == "tempo" else solana.USDC
        if network not in ok:
            raise Stop(f"{chain} has no network called {network}.", "Networks: " + ", ".join(ok))
        if amount <= 0:
            raise Stop("An amount is more than zero.", f"knos budget fund --agent {agent} 5 --chain {chain}")
        try:
            addr = wallets.create(agent, chain)
        except (ValueError, wallets.NeedsExtra) as why:
            raise Stop(str(why), "knos budget fund --agent claude 5 --chain tempo") from None
        prev = budget.agents().get(agent, {})
        cap = amount + (float(prev.get("cap", 0)) if prev.get("chain") == chain else 0.0)
        budget.set_agent(agent, chain, network, cap, addr)
        out.print(f"{agent}'s wallet on {chain} {network}: {addr}")
        out.print(f"Its Knos cap is now {cap:g}. Fund it with {amount:g} from your own wallet:")
        out.print(wallets.fund_link(agent, chain, amount, network), markup=False)
        out.print("[dim]The key is kept owner-only in ~/.knos/wallets and never shown. The agent pays APIs with "
                  "knos pay (or the pay tool); it cannot spend more than this wallet holds.[/dim]")

    @bud.command("agents")
    def budget_agents() -> None:
        """Each agent's budget wallet: chain, cap, spent, and its balance on chain."""
        from . import agentpay, wallets

        rows = agentpay.summary()
        if not rows:
            out.print("No agent has a budget wallet. knos budget fund --agent claude 5 --chain tempo")
            return
        for r in rows:
            try:
                bal = f"{wallets.balance(r['agent'], r['chain'], r['network']):g}"
            except (OSError, ValueError, KeyError):
                bal = "?"
            out.print(f"  {r['agent']:<14} {r['chain']:<6} {r['network']:<8} cap {r['cap']:g}  spent "
                      f"{r['spent']:g}  balance {bal}  {r['address']}")

    @bud.command("sweep")
    def budget_sweep(
        agent: str = typer.Option(..., "--agent"),
        to: str = typer.Option(..., "--to", help="your own address to send what is left to"),
    ) -> None:
        """Send what is left in an agent's wallet back to you."""
        from . import wallets

        cfg = budget.agents().get(agent)
        if not cfg:
            raise Stop(f"{agent} has no budget wallet.", "knos budget agents")
        try:
            got = wallets.sweep(agent, cfg["chain"], cfg["network"], to)
        except (ValueError, OSError, wallets.NeedsExtra) as why:
            raise Stop(f"Not swept: {why}", "Check the address, then run it again.") from None
        if not got["tx"]:
            out.print("Nothing to sweep: the wallet is empty.")
            return
        link = (tempo.explorer_tx(cfg["network"], got["tx"]) if cfg["chain"] == "tempo"
                else solana.explorer_tx(cfg["network"], got["tx"]))
        out.print(f"Sent {got['amount']:g} back to {to}. {link}")

    @app.command("pay")
    def pay_cmd(
        url: str = typer.Argument(..., help="an API that may answer 402 Payment Required"),
        agent: str = typer.Option(..., "--agent", help="whose budget wallet pays"),
        method: str = typer.Option("GET", "--method", "-X"),
        data: str = typer.Option(None, "--data", "-d", help="request body"),
    ) -> None:
        """Fetch a paid API as an agent: MPP (Tempo) or x402 (Solana), from its own wallet, inside its cap."""
        from . import agentpay

        need_pro()
        try:
            got = agentpay.pay(agent, url, method.upper(), data.encode() if data else None)
        except agentpay.Refused as why:
            raise Stop(str(why), "knos budget agents") from None
        if got.paid:
            out.print(f"[dim]paid {got.paid:g} on {got.chain} from {agent}'s wallet[/dim]")
        out.print(got.body, markup=False)
        if got.status >= 400:
            raise typer.Exit(1)

    pro = typer.Typer(help="Knos Pro (Sibyl Pro included): status, buying with USDC on Solana or Tempo, activating a code.")
    app.add_typer(pro, name="pro")

    @pro.callback(invoke_without_command=True)
    def pro_status(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is not None:
            return
        st = licence.status()
        if st["why"] == "licence":
            out.print(f"Knos Pro ({st['plan']}) until {str(st['expires'])[:10]}. Paid: {st.get('via', '')}")
        elif st["why"] == "trial":
            out.print(f"Knos Pro trial, {st['days_left']:.0f} day(s) left.")
        elif st["why"] == "expired":
            out.print("The trial has ended. knos pro buy")
        else:
            out.print("Free. The 14-day Pro trial starts the first time you run knos spend or knos budget.")
        for name, p in prices.PLANS.items():
            out.print(f"  [dim]{name:<10} {p['usdc']:>4} USDC  {p['label']}[/dim]")

    def _pending_path():
        return paths.home() / "pending.json"

    def _finish(p: dict, found: dict) -> None:
        tx = found["signature"]
        if licence.was_used(p["chain"], tx):
            raise Stop("That payment has already activated Knos Pro once.", "Buy again:  knos pro buy")
        body = licence.from_payment(p["plan"], tx, p["ref"], p["network"], found["paid"], int(p.get("seats", 1)),
                                    chain=p["chain"], payer=found.get("payer", ""))
        where = licence.write(body)
        licence.mark_used(p["chain"], tx)
        _sibyl_pro(body)
        try:
            _pending_path().unlink()
        except OSError:
            pass
        link = (solana.explorer_tx(p["network"], tx) if p["chain"] == "solana" else tempo.explorer_tx(p["network"], tx))
        out.print(f"[green]Paid.[/green] {found['paid']:g} {p['unit']}. {link}")
        out.print(f"Knos Pro until {body['expires'][:10]}. Licence: {where}")

    def _wait(p: dict, minutes: float) -> None:
        deadline = time.monotonic() + minutes * 60
        out.print(f"Waiting for the payment on {p['chain']} {p['network']} (Ctrl+C to stop; resume: knos pro check)")
        while True:
            try:
                if p["chain"] == "solana":
                    found = solana.find_payment(p["ref"], float(p["amount"]), p["network"])
                else:
                    found = tempo.find_payment(p["ref"], float(p["amount"]), p["network"], int(p["from_block"]))
            except (OSError, ValueError) as why:
                found = None
                out.print(f"[dim]RPC: {why}; retrying[/dim]")
            if found:
                _finish(p, found)
                return
            if time.monotonic() > deadline:
                raise Stop("No payment seen yet.", "Check again later:  knos pro check")
            time.sleep(4)

    @pro.command("buy")
    def pro_buy(
        year: bool = typer.Option(False, "--year", help="Pro for a year (208) instead of 30 days (22)"),
        team: int = typer.Option(0, "--team", min=0, help="Team seats (32 each per 30 days, 3 minimum)"),
        chain: str = typer.Option("solana", "--chain", help="solana (USDC) or tempo (USDC.e or pathUSD)"),
        network: str = typer.Option("mainnet", "--network", help="mainnet, or devnet (Solana) / testnet (Tempo)"),
        wait: bool = typer.Option(True, "--wait/--no-wait", help="watch the chain for the payment"),
        minutes: float = typer.Option(15, "--minutes", help="how long to wait"),
    ) -> None:
        """Pay from any wallet: a Solana Pay link (USDC) or a Tempo transfer with memo. Verified on chain; no account.
        Sibyl Pro is included: Knos buys it for the paying wallet from this one payment."""
        if team and team < 3:
            raise Stop("Team starts at 3 seats.", "knos pro buy --team 3")
        plan = "team-seat" if team else ("pro-year" if year else "pro-month")
        seats = team or 1
        amount = float(prices.PLANS[plan]["usdc"]) * seats
        label = prices.PLANS[plan]["label"] + (f" x {seats}" if seats > 1 else "")
        if chain == "solana":
            if network not in solana.USDC:
                raise Stop(f"Solana has no network called {network}.", "Use --network mainnet or --network devnet")
            ref = solana.new_reference()
            url = solana.link(plan, amount, ref, network)
            p = {"chain": "solana", "ref": ref, "unit": "USDC"}
            out.print(f"{label}: {amount:g} USDC on Solana {network}.")
            out.print("Open this in your wallet (Phantom, Solflare, Backpack), or paste it into a Solana Pay QR:")
        elif chain == "tempo":
            if network not in tempo.CHAINS:
                raise Stop(f"Tempo has no network called {network}.", "Use --network mainnet or --network testnet")
            m = tempo.memo(plan, tempo.new_order())
            try:
                start = tempo.block_number(network)
            except (OSError, ValueError) as why:
                raise Stop(f"Tempo's RPC did not answer ({why}).", "Try again in a minute.") from None
            token = "USDC.e" if network == "mainnet" else "pathUSD"
            url = tempo.link(amount, m, network, token=token)
            p = {"chain": "tempo", "ref": m, "from_block": max(start - 20, 0), "unit": token}
            others = ", ".join(t for t in tempo.TOKENS[network] if t != token)
            out.print(f"{label}: {amount:g} {token} on Tempo {network} (chain {tempo.CHAINS[network]['id']})"
                      + (f"; {others} is accepted too." if others else "."))
            out.print(f"Send with transferWithMemo to {tempo.MERCHANT}, memo {tempo.memo_text(m)!r}. Payment link:")
        else:
            raise Stop(f"No chain called {chain}.", "Use --chain solana or --chain tempo")
        p.update({"network": network, "plan": plan, "seats": seats, "amount": amount,
                  "at": datetime.now(timezone.utc).isoformat()})
        _pending_path().write_text(json.dumps(p), encoding="utf-8")
        out.print(url, markup=False)
        _qr(url)
        if wait:
            _wait(p, minutes)

    def _sibyl_pro(body: dict) -> None:
        from .. import sibyl_pro
        try:
            g = sibyl_pro.from_licence(body)
        except sibyl_pro.Locked as why:
            out.print(f"[dim]Sibyl Pro: {why}[/dim]")
            return
        if g:
            sim = " (simulated on testnets)" if g.simulated else ""
            out.print(f"Sibyl Pro is included: active until {g.until[:10]}{sim}.")

    def _qr(url: str) -> None:
        """A terminal QR when the optional `qrcode` package is installed; the link above works without it."""
        try:
            import qrcode  # type: ignore
        except ImportError:
            return
        q = qrcode.QRCode(border=1)
        q.add_data(url)
        q.print_ascii(invert=True)

    @pro.command("check")
    def pro_check() -> None:
        """Look for the payment of the purchase started on this machine, and activate Pro if it is there."""
        try:
            p = json.loads(_pending_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise Stop("No purchase to check.", "Start one:  knos pro buy") from None
        _wait(p, minutes=0.1)

    @pro.command("activate")
    def pro_activate(
        code: str = typer.Argument(None, help="a signed licence code from Knos"),
        tempo_tx: str = typer.Option(None, "--tempo", help="a Tempo transaction hash that paid this machine's purchase"),
    ) -> None:
        """Activate with a signed licence code, or with the Tempo transaction that paid `knos pro buy --chain tempo`."""
        if tempo_tx:
            try:
                p = json.loads(_pending_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                p = {}
            if p.get("chain") != "tempo":
                raise Stop("No Tempo purchase was started on this machine.", "Start one:  knos pro buy --chain tempo")
            try:
                receipt = tempo.rpc(p["network"], "eth_getTransactionReceipt", [tempo_tx])
            except (OSError, ValueError) as why:
                raise Stop(f"Tempo's RPC did not answer ({why}).", "Try again in a minute.") from None
            ok, why, paid, payer = tempo.check_receipt(receipt, p["ref"], float(p["amount"]), p["network"])
            if not ok:
                raise Stop(f"That transaction does not pay this purchase: {why}.", "Check the hash, or: knos pro check")
            _finish(p, {"signature": tempo_tx, "paid": paid, "payer": payer})
            return
        if not code:
            raise Stop("Nothing to activate.", "knos pro activate <code>   or   knos pro activate --tempo <tx>")
        try:
            body = licence.decode_code(code)
        except (ValueError, TypeError):
            raise Stop("That is not a Knos licence code.", "Paste the whole code, or buy:  knos pro buy") from None
        if not licence.verify_signed(body):
            raise Stop("That code's signature does not verify.",
                       "Check it was pasted whole.")
        if not licence.valid(body):
            raise Stop("That licence has expired.", "knos pro buy")
        licence.write(body)
        out.print(f"Knos Pro ({body.get('plan')}) until {str(body.get('expires'))[:10]}.")