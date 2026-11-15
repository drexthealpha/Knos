"""`knos board`: one live page of this repo, served on 127.0.0.1 only, for as long as the command runs.

Every run makes a new random token and the page answers only to requests that carry it, so another local user or a
web page in your browser cannot read it. Everything shown is read from the same files the CLI reads (claims.db, the
store, the guard's settings, and Pro's meter when Pro is active); nothing is sample data. When there is nothing to
show, it says so.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import guard, version


def snapshot(repo: Path) -> dict:
    from .claims import Claims, claims_db
    from .memory import Memory

    data: dict = {"repo": repo.name, "path": str(repo), "version": version(), "claims": [], "agents": [],
                  "events": [], "notes": 0, "size_mb": 0.0, "guard": guard.installed(), "spend": None}
    if claims_db(repo).exists():
        with Claims(repo) as c:
            data["claims"] = [x.as_dict() for x in c.live()]
            data["agents"] = c.agents()[:20]
            data["events"] = c.events(limit=25)
    try:
        with Memory(repo) as mem:
            data["notes"] = len(mem.notes())
            data["size_mb"] = round(mem.size_mb(), 2)
    except Exception:
        pass
    try:
        from .pro import budget, licence, meter

        if licence.status()["active"]:
            meter.update(min_interval=30)
            today = meter.spent(meter.period_start("day"))
            data["spend"] = {"today": round(today["usd"], 2), "estimated": today["estimated"],
                             "cap": budget.state(), "by": today["by"][:8]}
            from .pro import agentpay

            wallets = []
            for w in agentpay.summary():
                base = ("https://explorer.solana.com/address/" + w["address"] +
                        ("" if w["network"] == "mainnet" else f"?cluster={w['network']}")) if w["chain"] == "solana" \
                    else (("https://explore.tempo.xyz" if w["network"] == "mainnet" else
                           "https://explore.testnet.tempo.xyz") + "/address/" + w["address"])
                wallets.append({**w, "explorer": base})
            data["wallets"] = wallets
    except Exception:
        pass
    return data


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Knos board</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mute:#6b6a65;--line:#e4e1d8;--warn:#a1520b;--ok:#2f6b3a;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--mute:#9a988f;--line:#2c2b28;--warn:#e39a4c;
--ok:#7fc28b;--card:#1c1c1a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.45 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:860px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:20px;margin:0 0 2px}h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);
margin:24px 0 8px}.sub{color:var(--mute);font-size:13px;word-break:break-all}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:6px 0}
.row{display:flex;gap:8px;justify-content:space-between;flex-wrap:wrap}.mono{font-family:ui-monospace,Menlo,Consolas,monospace;
font-size:13px;word-break:break-all}.warn{color:var(--warn)}.ok{color:var(--ok)}.empty{color:var(--mute);font-style:italic}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}
.stat b{display:block;font-size:22px}.stat span{color:var(--mute);font-size:12px}
</style></head><body><main>
<h1>Knos &middot; <span id="repo"></span></h1><div class="sub" id="path"></div>
<div class="stats" style="margin-top:14px">
<div class="card stat"><b id="nclaims">-</b><span>files claimed now</span></div>
<div class="card stat"><b id="nagents">-</b><span>agent sessions today</span></div>
<div class="card stat"><b id="nnotes">-</b><span>notes written down</span></div>
<div class="card stat"><b id="spend">-</b><span id="spendlabel">spend today (Pro)</span></div></div>
<h2>Claimed right now</h2><div id="claims"></div>
<h2>Agents seen today</h2><div id="agents"></div>
<h2>Recent</h2><div id="events"></div>
<h2>Spend today (Pro)</h2><div id="byhost"></div>
<h2>Agent wallets (Pro)</h2><div id="wallets"></div>
<h2>Edit guard</h2><div id="guard" class="card mono"></div>
<p class="sub" id="foot"></p>
</main><script>
const T=new URLSearchParams(location.search).get('t');
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function list(id,rows,fn,empty){const el=document.getElementById(id);
 el.innerHTML=rows.length?rows.map(fn).join(''):'<div class="card empty">'+empty+'</div>'}
async function tick(){try{const r=await fetch('/api?t='+encodeURIComponent(T),{cache:'no-store'});
 if(!r.ok)throw new Error(r.status);const d=await r.json();
 repo.textContent=d.repo;path.textContent=d.path;nclaims.textContent=d.claims.length;
 nagents.textContent=d.agents.length;nnotes.textContent=d.notes;
 if(d.spend){spend.textContent='$'+d.spend.today.toFixed(2);const c=d.spend.cap;
  spendlabel.textContent=c?('of $'+c.usd.toFixed(2)+' '+c.per+' cap'+(c.over?' - REACHED':'')):'spend today, API list prices'}
 else{spend.textContent='-';spendlabel.textContent='spend: knos pro'}
 list('claims',d.claims,c=>'<div class="card"><div class="row"><b>'+esc(c.who)+'</b><span class="sub">'+
  Math.round(c.minutes_left)+' min left</span></div><div class="mono">'+esc(c.globs.join(', ')||'(advisory)')+
  '</div><div class="sub">'+esc(c.description)+'</div></div>',
  'Nothing is claimed. Agents claim files with remember(..., claiming=true).');
 list('agents',d.agents,a=>'<div class="card row"><span class="mono">'+esc(a.host)+'/'+esc(String(a.session).slice(0,8))+
  '</span><span class="sub">'+esc(String(a.started_at).slice(11,16))+' UTC</span></div>',
  'No agent session has started here today (the session hook records them: knos init).');
 list('events',d.events,e=>'<div class="card row"><span><span class="'+(e.kind==='blocked'?'warn':'')+'">'+
  esc(e.kind)+'</span> '+esc(e.kind==='blocked'?(e.by+' tried '+e.path+', held by '+e.held_by):
  (e.who||'')+(e.globs?' '+e.globs.join(', '):''))+'</span><span class="sub">'+esc(String(e.ts).slice(11,16))+
  '</span></div>','Nothing has happened here yet.');
 list('byhost',(d.spend&&d.spend.by)||[],b=>'<div class="card row"><span class="mono">'+esc(b.host)+' / '+
  esc(b.model)+'</span><span>$'+Number(b.usd).toFixed(2)+'</span></div>',
  d.spend?'Nothing spent today (Claude Code and Codex are metered; other hosts are not).':'Knos Pro shows spend per agent and model: knos pro');
 list('wallets',d.wallets||[],w=>'<div class="card"><div class="row"><b>'+esc(w.agent)+'</b><span class="sub">'+
  esc(w.chain)+' '+esc(w.network)+'</span></div><div class="sub">spent '+Number(w.spent)+' of cap '+Number(w.cap)+
  '</div><a class="mono" href="'+esc(w.explorer)+'" target="_blank" rel="noopener">'+esc(w.address)+'</a></div>',
  'No agent has a budget wallet. knos budget fund --agent claude 5 --chain tempo');
 guard.innerHTML=Object.entries(d.guard).map(([k,v])=>esc(k)+': '+(v?'<span class="ok">on</span>':'off')).join(' &middot; ');
 foot.textContent='knos '+d.version+' \\u00b7 127.0.0.1 only \\u00b7 refreshed '+new Date().toLocaleTimeString();
}catch(e){foot.textContent='The board stopped answering ('+e.message+'). Is knos board still running?'}}
tick();setInterval(tick,3000);
</script></body></html>"""


def make_server(repo: Path, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    token = secrets.token_urlsafe(18)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            given = (parse_qs(url.query).get("t") or [""])[0]
            if not secrets.compare_digest(given, token):
                self._send(403, b"knos board: this page needs the address knos board printed.\n", "text/plain")
                return
            if url.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif url.path == "/api":
                try:
                    body = json.dumps(snapshot(repo), default=str).encode()
                except Exception as why:
                    self._send(500, json.dumps({"error": str(why)}).encode(), "application/json")
                    return
                self._send(200, body, "application/json")
            else:
                self._send(404, b"not found\n", "text/plain")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={token}"
    return server, url


def serve(repo: Path, port: int = 0, open_browser: bool = True, say=print) -> None:
    server, url = make_server(repo, port)
    say(f"Knos board for {repo.name}: {url}")
    say("Only this machine can open it, and only with that address. Ctrl+C stops it.")
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
