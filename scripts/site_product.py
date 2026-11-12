"""The product's own pages, written by scripts/site_pages.py into the published site: the claims (claims/ and one page per
claim under claim/), the agent's way in (agents/), pricing/ and status/. Each carries the one header and a short
footer; every number on them is read live from the hosted server or NEAR testnet when the page opens.

The claims are near/claims/claims.json; each one's locked test is a file of near/agents/job/, and its sha256 is the
criteria hash every job for that claim is opened with on NEAR testnet."""
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTED = "https://knos.onrender.com"
REPO = "https://github.com/drexthealpha/Knos"
JOBS = "jobs.knos-swarm-1105.testnet"
MARKET = "market.knos-swarm-1105.testnet"
EXPLORER = "https://testnet.nearblocks.io/address/"

CSS = """body { margin: 0; background: var(--paper); color: var(--ink); font: 400 17px/1.55 var(--text); }
a { color: var(--accent); }
main { max-width: 760px; margin: 0 auto; padding: 8px 16px 32px; }
h1 { font: 600 clamp(28px, 5vw, 40px)/1.15 var(--head); letter-spacing: -.02em; margin: 16px 0 12px; }
h2 { font: 600 22px/1.25 var(--head); margin: 28px 0 8px; }
p { margin: 0 0 12px; }
.lead { color: var(--ink-2); }
table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 16px; }
th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
code, pre { font: 15px/1.5 ui-monospace, "JetBrains Mono", Consolas, monospace; }
pre { background: var(--paper-2); border: 1px solid var(--line); border-radius: 8px; padding: 12px; overflow-x: auto; white-space: pre-wrap; word-break: break-all; }
.btn { display: inline-flex; align-items: center; min-height: 48px; padding: 0 18px; border-radius: 10px; background: var(--accent); color: var(--accent-fg); text-decoration: none; font-weight: 600; }
.row a, td a { display: inline-flex; align-items: center; min-height: 44px; }
.fine { color: var(--ink-2); }
footer { max-width: 760px; margin: 0 auto; padding: 16px; color: var(--ink-2); font-size: 16px; border-top: 1px solid var(--line); }
footer a { color: var(--ink-2); display: inline-flex; align-items: center; justify-content: center; min-height: 44px; min-width: 44px; margin-right: 12px; }
@media (max-width: 480px) { th, td { padding: 8px 4px; } }
"""


def claims() -> list[dict]:
    """The claims, each with its locked test's sha256 (the criteria hash its jobs are opened with)."""
    out = []
    for c in json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]:
        test = ROOT / "near" / "agents" / "job" / c["test"]
        out.append({**c, "sha256": hashlib.sha256(test.read_bytes()).hexdigest()})
    return out


def e(s) -> str:
    return html.escape(str(s), quote=True)


def page(header: str, up: str, title: str, desc: str, body: str, script: str = "", canonical: str = "") -> str:
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{e(title)}</title>\n<meta name=\"description\" content=\"{e(desc)}\">\n<meta name=\"color-scheme\" content=\"light dark\">\n"
            f'<link rel="canonical" href="https://drexthealpha.github.io/Knos/{canonical}">\n'
            f'<meta property="og:title" content="{e(title)}">\n<meta property="og:description" content="{e(desc)}">\n'
            f'<meta property="og:image" content="https://drexthealpha.github.io/Knos/brand/card.png">\n'
            f'<link rel="icon" href="{up}icon.svg" type="image/svg+xml">\n<link rel="stylesheet" href="{up}brand/tokens.css">\n'
            f"<style>\n{CSS}</style>\n</head>\n<body>\n{header}\n<main>\n{body}\n</main>\n"
            f'<footer><span>NEAR testnet, test money, no customers yet.</span><br>'
            f'<a href="{REPO}">Source</a><a href="{up}pricing/">Pricing</a><a href="{up}status/">Status</a><a href="{up}privacy.html">Privacy</a></footer>\n'
            + (f"<script>\n{script}\n</script>\n" if script else "") + "</body>\n</html>\n")


LIVE_JS = """const HOSTED = "%s";
const $ = (id) => document.getElementById(id);
const usd = (n) => (+n || 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
async function getJSON(path) { try { const r = await fetch(HOSTED + path); return r.ok ? await r.json() : null; } catch (e) { return null; } }
""" % HOSTED


def claims_page(header: str, cs: list[dict]) -> str:
    rows = "".join(f'<tr data-claim="{e(c["name"])}"><td><a href="../claim/{e(c["name"])}/">{e(c["plain"])}</a><br>'
                   f'<span class="fine">{e(c["authors"])}, {c["year"]}</span></td>'
                   f'<td class="n" data-behind>reading</td><td class="n" data-proofs>reading</td></tr>' for c in cs)
    body = (f"<h1>Claims</h1>\n<p class=\"lead\">Every claim Knos can prove, each from a paper, each with a test locked on NEAR testnet. "
            f"Sorted by the test USDC put behind it.</p>\n"
            f'<table id="claims"><thead><tr><th>Claim</th><th class="n">Test USDC behind</th><th class="n">Proofs paid</th></tr></thead>\n<tbody>{rows}</tbody></table>\n'
            f'<p class="fine" id="as-of">Read live from NEAR testnet\'s public record.</p>')
    script = LIVE_JS + """(async () => {
  const c = await getJSON("/api/near/claim/counters");
  const by = (c && c.by_claim) || (c && c.proofs != null ? { hyperloglog: { proofs: c.proofs, usd: c.usd } } : {});
  const rows = [...document.querySelectorAll("#claims tbody tr")];
  for (const r of rows) { const x = by[r.dataset.claim] || { proofs: 0, usd: 0 };
    r.querySelector("[data-behind]").textContent = c ? usd(x.usd) : "not read"; r.querySelector("[data-proofs]").textContent = c ? x.proofs.toLocaleString("en-US") : "not read"; r.dataset.usd = x.usd; }
  rows.sort((a, b) => (+b.dataset.usd || 0) - (+a.dataset.usd || 0)).forEach((r) => r.parentNode.append(r));
  $("as-of").textContent = c && c.read_at ? `Read from NEAR testnet's public record at ${c.read_at.replace("T", " ").replace("Z", " UTC")}.` : "NEAR testnet's record could not be read just now.";
})();"""
    return page(header, "../", "Knos claims", "Every claim Knos can prove on NEAR testnet, sorted by the test USDC behind it.", body, script, "claims/")


def claim_page(header: str, c: dict) -> str:
    test_url = f"{REPO}/blob/main/near/agents/job/{c['test']}"
    body = (f'<p class="fine"><a href="../../claims/">Claims</a></p>\n<h1>{e(c["plain"])}</h1>\n'
            f'<p>From <a href="https://doi.org/{e(c["doi"])}">{e(c["paper"])}</a>, {e(c["authors"])}, {c["year"]}. The paper says: '
            f'&ldquo;{e(c["quote"])}&rdquo;</p>\n'
            f'<p><a class="btn" href="../../prove/#paper={e("https://doi.org/" + c["doi"])}">Prove it on NEAR</a></p>\n'
            f'<h2>The locked test</h2>\n<p><a href="{test_url}">{e(c["test"])}</a>, sha256 <code>{c["sha256"]}</code>. '
            f'Every job for this claim is opened on NEAR testnet with this hash as its criteria hash, before any agent starts; '
            f'the checker runs only the file with this hash.</p>\n'
            f'<h2>Proofs and receipts</h2>\n<p id="proofs">Reading NEAR testnet\'s public record...</p>\n<table id="receipts" hidden><thead><tr><th>When (UTC)</th>'
            f'<th class="n">Fee, test USDC</th><th>Knos\'s fee transfer</th></tr></thead><tbody></tbody></table>\n'
            f'<h2>The record</h2>\n<p>Jobs: <a href="{EXPLORER}{JOBS}">{JOBS}</a>. Claim records: <a href="{EXPLORER}{MARKET}">{MARKET}</a>. '
            f'Payments: <a href="{EXPLORER}live.knos-swarm-1105.testnet?tab=tokentxns">the buyer test account</a>.</p>')
    script = LIVE_JS + """(async () => {
  const name = %s;
  const c = await getJSON("/api/near/claim/counters");
  if (!c) { $("proofs").textContent = "NEAR testnet's record could not be read just now."; return; }
  const x = (c.by_claim && c.by_claim[name]) || (name === "hyperloglog" ? { proofs: c.proofs, usd: c.usd } : { proofs: 0, usd: 0 });
  $("proofs").textContent = `${x.proofs.toLocaleString("en-US")} proofs paid, ${usd(x.usd)} in test USDC behind this claim, ${usd(c.lost_usd)} lost.`;
  const rows = (c.receipts || []).filter((r) => (r[3] || "hyperloglog") === name).slice(0, 25);
  if (rows.length) { const tb = document.querySelector("#receipts tbody");
    for (const [tx, amount, at] of rows) { const tr = document.createElement("tr");
      tr.innerHTML = `<td>${new Date(at * 1000).toISOString().slice(0, 16).replace("T", " ")}</td><td class="n">${amount == null ? "new" : (+amount).toFixed(2)}</td><td><a href="https://testnet.nearblocks.io/txns/${tx}">${tx.slice(0, 10)}...</a></td>`;
      tb.append(tr); }
    $("receipts").hidden = false; }
})();""" % json.dumps(c["name"])
    return page(header, "../../", f"{c['plain']} | Knos", c["plain"], body, script, f"claim/{c['name']}/")


def agents_page(header: str) -> str:
    flow = (f'curl -X POST {HOSTED}/api/near/claim/flow -H "Content-Type: application/json" \\\n'
            '  -d \'{"url": "https://doi.org/10.46298/dmtcs.3545", "amount": 10}\'')
    body = ("<h1>For agents</h1>\n<p class=\"lead\">One call proves a paper's claim on NEAR testnet: it reads the paper, runs the locked "
            "test, puts the test USDC behind the claim and returns the verdict, the verified code and the receipt.</p>\n"
            f"<h2>The call</h2>\n<pre>{e(flow)}</pre>\n"
            "<p>The answer holds <code>verdict.holds</code> (true or false), <code>cap.refused</code> (an agent's over-budget step "
            "refused on NEAR), <code>paid</code>, <code>settled</code>, <code>receipt</code> with each transfer's link, and <code>code</code>: "
            "the verified code to download. It takes 10 to 45 s. The agent call has its own 10 live proofs a day; after those it "
            "answers with the last verified proof, marked <code>\"reused\": true</code>.</p>\n"
            "<h2>From a terminal</h2>\n"
            f"<pre>git clone {REPO} &amp;&amp; cd Knos\npython3 near/scripts/knos_prove.py https://doi.org/10.46298/dmtcs.3545 10</pre>\n"
            "<p>It makes the same call and prints the verdict, each payment and its link on the NEAR explorer.</p>\n"
            "<h2>Read without paying</h2>\n"
            f"<pre>curl -X POST {HOSTED}/api/near/claim/look -H \"Content-Type: application/json\" -d '{{\"url\": \"https://doi.org/10.46298/dmtcs.3545\"}}'\n"
            f"curl {HOSTED}/api/near/claim/counters</pre>\n"
            f'<p>Every route: <a href="{HOSTED}/openapi.json">the OpenAPI document</a>.</p>')
    return page(header, "../", "Knos for agents", "One call proves a paper's claim on NEAR testnet and returns the verdict, the code and the receipt.", body, "", "agents/")


def pricing_page(header: str) -> str:
    body = ("<h1>Pricing</h1>\n<p>You choose the test USDC you put behind a claim, from 1 to 100. It is paid only after the answer: "
            "1 part in 49 to the agent whose code passed the locked test, the other 48 to Knos as its fee. The job itself also pays "
            "that agent 1.00. Proving the same order again is free.</p>\n"
            "<p>A person checking one paper by hand costs $330 to $763 "
            "(<a href=\"https://labordynamicsinstitute.github.io/crress-book/\">Colliard and others, 2023</a>).</p>\n"
            "<p>Today this is test money on NEAR testnet: nobody has paid real money and Knos has no customers yet. Knos has no token.</p>")
    return page(header, "../", "Knos pricing", "The test USDC you choose, paid only after the answer.", body, "", "pricing/")


def status_page(header: str) -> str:
    body = ("<h1>Status</h1>\n<table id=\"st\"><tbody>"
            "<tr><th>The proof service</th><td id=\"svc\">reading</td></tr>"
            "<tr><th>Live proofs today</th><td id=\"today\">reading</td></tr>"
            "<tr><th>NEAR testnet's record</th><td id=\"rec\">reading</td></tr>"
            "<tr><th>Latest full test run</th><td id=\"ci\">reading</td></tr>"
            "</tbody></table>\n<p class=\"fine\">Each line is read now, from the hosted server and GitHub.</p>")
    script = LIVE_JS + """(async () => {
  const [l, c, t] = await Promise.all([getJSON("/api/near/live"), getJSON("/api/near/claim/counters"), getJSON("/api/near/tests")]);
  $("svc").textContent = l ? (l.live ? "up, on NEAR testnet" : "up, live runs switched off") : "not answering";
  $("today").textContent = l ? `${l.used_today} of ${l.cap_today} on the page, ${l.agent_used_today ?? 0} of ${l.agent_cap_today ?? 0} for agents` : "not read";
  $("rec").textContent = c && c.read_at ? `${c.proofs} proofs paid, ${usd(c.lost_usd)} lost, read ${c.read_at.replace("T", " ").replace("Z", " UTC")}` : "not read";
  $("ci").innerHTML = t && t.url ? `${t.passed ? "passed" : "failed"}, <a href="${t.url}">commit ${String(t.sha || "").slice(0, 8)}</a>` : "not read";
})();"""
    return page(header, "../", "Knos status", "The proof service, today's live proofs and the latest test run, read live.", body, script, "status/")


def privacy_page(header: str) -> str:
    body = ("<h1>Privacy and terms</h1>\n<h2>This site</h2>\n<p>No cookies, analytics or trackers. The paper link you paste goes to the "
            "Knos server, which reads the paper's title from its public record (Crossref) and answers. Your browser also reads "
            "NEAR testnet's public record.</p>\n<h2>The server</h2>\n<p>No account and no sign-in. It counts requests per address only to "
            "limit them. Every proof and payment is public on NEAR testnet.</p>\n<h2>Terms</h2>\n<p>Test money on NEAR testnet, worth "
            f'nothing. The code is MIT licensed, with no warranty: <a href="{REPO}/blob/main/LICENSE">the licence</a>. Report a problem in '
            f'<a href="{REPO}/issues">GitHub issues</a>.</p>')
    return page(header, "", "Knos privacy and terms", "No cookies or trackers; test money on NEAR testnet.", body, "", "privacy.html")


def write(out: Path, header) -> list[str]:
    """Write the product's pages under the site `out`; `header(up, here)` gives the one header. Returns their paths."""
    cs = claims()
    done = []
    def put(rel: str, text: str):
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        done.append(rel)
    put("claims/index.html", claims_page(header("../", "claims/"), cs))
    for c in cs:
        put(f"claim/{c['name']}/index.html", claim_page(header("../../", ""), c))
    put("agents/index.html", agents_page(header("../", "agents/")))
    put("pricing/index.html", pricing_page(header("../", "")))
    put("status/index.html", status_page(header("../", "")))
    put("privacy.html", privacy_page(header("", "")))
    base = "https://drexthealpha.github.io/Knos/"
    pages = ["", "claims/", *[f"claim/{c['name']}/" for c in cs], "prove/", "agents/", "labs/", "pricing/", "status/", "privacy.html"]
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"  <url><loc>{base}{p}</loc></url>\n" for p in pages) + "</urlset>\n", encoding="utf-8")
    claims_md = "".join(f"- [{c['plain']}]({base}claim/{c['name']}/): from {c['authors']}, {c['year']}; locked test sha256 {c['sha256']}\n" for c in cs)
    call = '{"url": "https://doi.org/10.46298/dmtcs.3545", "amount": 10}'
    (out / "llms.txt").write_text(
        "# Knos\n\n> Paste a paper. Knos checks if its claim works, on NEAR testnet.\n\n"
        "Two agents write code against a test locked on NEAR testnet before they start. The one whose code passes is paid; the "
        "result is kept on NEAR, so a second check is free. Test money only, no customers yet, no token.\n\n"
        f"## Pages\n\n- [Front door]({base}): paste a paper, see if Knos can prove its claim\n"
        f"- [Claims]({base}claims/): every claim, sorted by the test USDC behind it\n"
        f"- [Prove]({base}prove/): order a proof and get the verdict, the verified code and the receipt\n"
        f"- [For agents]({base}agents/): the one-call API and the terminal tool\n"
        f"- [For labs]({base}labs/): the same check inside InterSystems IRIS\n\n## Claims\n\n{claims_md}\n"
        f"## For agents\n\n`POST {HOSTED}/api/near/claim/flow` with `{call}`: the verdict, the code and the receipt.\n\nSource: {REPO}\n",
        encoding="utf-8")
    return done
