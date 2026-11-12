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
HEADER_CSS = ""   # the one header's styles, set by scripts/site_pages.py before it writes these pages

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
code { overflow-wrap: anywhere; }
.btn[disabled] { opacity: .45; cursor: not-allowed; }
pre { background: var(--paper-2); border: 1px solid var(--line); border-radius: 8px; padding: 12px; overflow-x: auto; white-space: pre-wrap; word-break: break-all; }
.btn { display: inline-flex; align-items: center; min-height: 48px; padding: 0 18px; border-radius: 10px; background: var(--accent); color: var(--accent-fg); text-decoration: none; font-weight: 600; }
.row a, td a { display: inline-flex; align-items: center; min-height: 44px; }
.fine { color: var(--ink-2); }
footer { max-width: 760px; margin: 0 auto; padding: 16px; color: var(--ink-2); font-size: 16px; border-top: 1px solid var(--line); }
footer a { color: var(--ink-2); display: inline-flex; align-items: center; justify-content: center; min-height: 44px; min-width: 44px; margin-right: 12px; }
@media (max-width: 480px) { th, td { padding: 8px 4px; } #claims thead { display: none; } #claims tr { display: block; border-bottom: 1px solid var(--line); padding: 8px 0; } #claims td { display: block; border: 0; padding: 2px 0; text-align: left; } #claims td[data-behind]::before { content: "Test USDC behind: "; font-weight: 600; } #claims td[data-truth]::before { content: "Does it hold? "; font-weight: 600; } #claims td[data-demand]::before { content: "100 behind it in 7 days? "; font-weight: 600; } }
"""


# attacks tried on NEAR testnet, each refused by the contracts (near/CLAIMS.md)
ATTACKS = [("Settle a claim by vote", "a market settles only by its locked test", "371H72CAkzrN1ih486C32y9iFsrKd1ndqZXKxWL5tYyL"),
           ("Change a claim's locked test", "the test is locked when the job is funded", "DVXvKjBMhXhJgXKTNcF1DVMVXWLa7pzZB3ukon9dpkaH"),
           ("Settle before the test ran", "nothing settles until the locked test has run", "7D9AaoNRccUcmtWFt3yrWkZqq1LYC4ef6zMhttXjny6F"),
           ("Pay without a passing result", "a release needs the checker's token for a passing output", "E5GUcVks55r9Rn4b1HJBJagDB1bFbL8YMj41UFHFeHan"),
           ("Use a payment token twice", "each token is used once", "HcZ8nBuQYuYU5LKRVceSfXVdqBnLrj1shyddj3EQBsM2"),
           ("Spend over an agent's cap", "an agent's spending stops at its cap", "FdJPJf7RLdErvMBdeUkeUWdhqw4VGNEKtw5aVD4VnK4y")]


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
            f"<style>\n{CSS}{HEADER_CSS}</style>\n</head>\n<body>\n{header}\n<main>\n{body}\n</main>\n"
            f'<footer><span>NEAR testnet, test money, no customers yet.</span><br>'
            f'<a href="{REPO}">Source</a><a href="{up}pricing/">Pricing</a><a href="{up}status/">Status</a><a href="{up}privacy.html">Privacy</a></footer>\n'
            + (f"<script>\n{script}\n</script>\n" if script else "") + "</body>\n</html>\n")


LIVE_JS = """const HOSTED = "__HOSTED__";
const $ = (id) => document.getElementById(id);
const usd = (n) => (+n || 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
// the board and the counters are also files of this site, written by every Pages build (data/): a live answer within
// 1.2 s is used, else the file is shown at once, with its own read time, so a press never waits on a sleeping server
const SITE_ROOT = (document.querySelector("#kh .logo") || location).href, CACHED = { "/api/near/claims": "board.json", "/api/near/claim/counters": "counters.json" };
async function getJSON(path) {
  const live = (async () => { try { const r = await fetch(HOSTED + path); return r.ok ? await r.json() : null; } catch (e) { return null; } })();
  if (!CACHED[path]) return live;
  const file = fetch(new URL("data/" + CACHED[path], SITE_ROOT)).then((r) => r.ok ? r.json() : null).catch(() => null);
  const quick = await Promise.race([live, new Promise((res) => setTimeout(res, 1200, "slow"))]);
  if (quick && quick !== "slow") return quick;
  const f = await file;
  return f && Object.keys(f).length ? f : await live;
}
// NEAR testnet, read from this browser: no answer of Knos's server is trusted for these
const RPCS = ["https://rpc.testnet.fastnear.com", "https://rpc.testnet.near.org"];   // two public NEAR testnet RPCs
async function nearView(contract, method, args) {
  const body = JSON.stringify({ jsonrpc: "2.0", id: "k", method: "query", params: { request_type: "call_function", finality: "final", account_id: contract, method_name: method, args_base64: btoa(JSON.stringify(args)) } });
  let last = "no answer";
  for (const rpc of RPCS) {
    try {
      const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 8000);
      const r = await fetch(rpc, { method: "POST", headers: { "Content-Type": "application/json" }, body, signal: ctl.signal }).then((x) => x.json()).finally(() => clearTimeout(t));
      if (r.result && r.result.result) return JSON.parse(new TextDecoder().decode(new Uint8Array(r.result.result)));
      last = (r.error && (r.error.cause && r.error.cause.name || r.error.message)) || "no answer";
      if (/MethodNotFound|does not exist|CodeDoesNotExist/.test(JSON.stringify(r.error || {}))) break;
    } catch (e) { last = "NEAR's public RPCs are busy"; }
  }
  throw new Error(last);
}
async function sha256(bytes) { return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join(""); }
const thin = (m) => m.traders == null ? `${m.trades} trades` : `${m.traders} ${m.traders === 1 ? "trader" : "traders"}${m.traders < 5 ? ", thin" : ""}`;
function truthText(m, last) {
  if (last) return `Holds: proved by its locked test (${last})`;
  if (!m) return "opens with the first order";
  if (m.outcome === true) return "Holds: settled by the locked test";
  if (m.outcome === false) return "Fails: settled by the locked test";
  return `not proved yet: its first order runs the locked test (${thin(m)})`;
}
function demandText(m) {
  if (!m) return "opens soon";
  if (m.outcome === true) return +m.behind_usd >= 100 ? "Yes: 100 test USDC from outside backers within 7 days" : "Yes, settled on Knos's own test money before this rule";
  if (m.outcome === false) return "No: under 100 test USDC from outside backers within 7 days";
  return `${(+m.behind_usd).toFixed(2)} of 100 test USDC from outside backers this week, closes ${new Date(m.closes * 1000).toISOString().slice(0, 10)} (${thin(m)})`;
}
""".replace("__HOSTED__", HOSTED)


def claims_page(header: str, cs: list[dict]) -> str:
    rows = "".join(f'<tr data-claim="{e(c["name"])}"><td><a href="../claim/{e(c["name"])}/">{e(c["plain"])}</a><br>'
                   f'<span class="fine">{e(c["authors"])}, {c["year"]}</span></td>'
                   f'<td class="n" data-behind>reading</td><td data-truth>reading</td><td data-demand>reading</td></tr>' for c in cs)
    body = (f"<h1>Claims</h1>\n<p class=\"lead\">Every claim Knos can prove, each from a paper, each with a test locked on NEAR testnet. "
            f"Sorted by the test USDC paid for its proofs.</p>\n"
            f'<table id="claims"><thead><tr><th>Claim</th><th class="n">Test USDC paid for proofs</th><th>Does it hold?</th><th>100 behind it in 7 days?</th></tr></thead>\n<tbody>{rows}</tbody></table>\n'
            f'<p class="fine">Each claim has two markets on NEAR testnet, priced by an automatic market maker (LMSR): whether it holds, '
            f'settled by its locked test, and whether 100 test USDC are put behind proving it within 7 days, settled by the '
            f'record on NEAR.</p>\n'
            f'<p class="fine" id="as-of">Read live from NEAR testnet\'s public record.</p>\n'
            f'<h2>Tried on NEAR testnet, and refused</h2>\n<table><thead><tr><th>Attempt</th><th>Why NEAR refused it</th><th>Record</th></tr></thead><tbody>'
            + "".join(f'<tr><td>{e(a)}</td><td>{e(why)}</td><td><a href="https://testnet.nearblocks.io/txns/{tx}">{tx[:8]}...</a></td></tr>' for a, why, tx in ATTACKS)
            + '</tbody></table>\n<p class="fine">And in every live proof, agent B tries to spend over its cap and is refused. The contracts\' '
              '208 tests, 146 of them attacks, run on every change: <code>bash near/scripts/verify.sh</code>.</p>')
    script = LIVE_JS + """(async () => {
  const [c, b] = await Promise.all([getJSON("/api/near/claim/counters"), getJSON("/api/near/claims")]);
  const by = (c && c.by_claim) || (c && c.proofs != null ? { hyperloglog: { proofs: c.proofs, usd: c.usd } } : {});
  const rows = [...document.querySelectorAll("#claims tbody tr")];
  for (const r of rows) { const x = by[r.dataset.claim] || { proofs: 0, usd: 0 }, m = (b && b.claims && b.claims[r.dataset.claim]) || {};
    const proofs = Math.max(x.proofs || 0, m.proofs || 0), behind = Math.max(+x.usd || 0, +m.behind_usd || 0);   // the larger of the two reads of NEAR
    r.querySelector("[data-behind]").textContent = c || b ? `${usd(behind)} (${proofs.toLocaleString("en-US")} ${proofs === 1 ? "proof" : "proofs"})` : "not read";
    r.querySelector("[data-truth]").textContent = b ? truthText(m.truth, m.last_proof) : "not read";
    r.querySelector("[data-demand]").textContent = b ? demandText(m.demand) : "not read"; r.dataset.usd = x.usd; }
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
            f'<p><b>What it did not check:</b> {e(c["not_checked"])}.</p>\n'
            f'<p><b>A test by the paper\'s authors:</b> {e(c.get("outside_test", "not looked for yet"))}'
            + "".join(f' <a href="{u}">{e(u.split("/")[4])}</a>' for u in c.get("outside_test_links", [])) + '</p>\n'
            f'<h2>Check it yourself, in this browser</h2>\n<p>Your browser fetches the locked test from GitHub, hashes it, and reads '
            f'from NEAR testnet itself the hash this claim\'s newest job locked before any agent started. Then change one byte and check again.</p>\n'
            f'<p class="row"><button class="btn" id="verify" type="button">Check the test against NEAR</button> '
            f'<button class="btn" id="tamper" type="button">Change one byte and check again</button></p>\n'
            f'<p id="verdict" role="status"></p>\n'
            f'<h2>Its two markets on NEAR testnet</h2>\n<table><tbody><tr><th>Does it hold?</th><td><span id="truth">reading</span><span class="row" data-trade="truth"></span></td></tr>'
            f'<tr><th>100 test USDC behind it within 7 days?</th><td><span id="demand">reading</span><span class="row" data-trade="demand"></span></td></tr></tbody></table>\n'
            f'<p id="traded" role="status" class="fine"></p>\n'
            f'<p class="fine">Priced by an automatic market maker (LMSR) in test USDC; the first settles by the locked test, the '
            f'second by the record of what was put behind the claim.</p>\n'
            f'<h2>Backers</h2>\n<p id="backed" class="fine">Reading every backer from NEAR...</p>\n'
            f'<table id="backers" data-market="{MARKET}" hidden><thead><tr><th>When (UTC)</th><th>Backer</th><th class="n">Test USDC</th></tr></thead><tbody></tbody></table>\n'
            f'<h2>Proofs and receipts</h2>\n<p id="proofs">Reading NEAR testnet\'s public record...</p>\n<table id="receipts" hidden><thead><tr><th>When (UTC)</th>'
            f'<th class="n">Knos\'s fee, test USDC (48 of 49 parts before 12 Nov, 1 in 10 since)</th><th>Knos\'s fee transfer</th></tr></thead><tbody></tbody></table>\n'
            f'<h2>The record</h2>\n<p>Jobs: <a href="{EXPLORER}{JOBS}">{JOBS}</a>. Claim records: <a href="{EXPLORER}{MARKET}">{MARKET}</a>. '
            f'Payments: <a href="{EXPLORER}live.knos-swarm-1105.testnet?tab=tokentxns">the buyer test account</a>.</p>')
    script = LIVE_JS + """(async () => {
  const name = %s;
  const board = getJSON("/api/near/claims");
  // an open market can be traded: 1 test USDC of Yes or No, from the test account Knos holds for you
  board.then((b) => { const m = (b && b.claims && b.claims[name]) || {};
    for (const cell of ["truth", "demand"]) {
      const mk = m[cell];
      if (!mk || mk.outcome != null || (cell === "truth" && m.last_proof)) continue;
      const box = document.querySelector(`[data-trade="${cell}"]`);
      for (const side of ["yes", "no"]) {
        const btn = Object.assign(document.createElement("button"), { type: "button", className: "btn", textContent: `Buy ${side === "yes" ? "Yes" : "No"}, 1 test USDC` });
        btn.style.margin = "8px 8px 0 0";
        btn.addEventListener("click", async () => {
          const all = [...document.querySelectorAll("[data-trade] button")]; all.forEach((x) => { x.disabled = true; });
          const t0 = performance.now(); const out = $("traded");
          const tick = setInterval(() => { out.textContent = `Buying on NEAR testnet... ${((performance.now() - t0) / 1000).toFixed(1)} s`; }, 100);
          let x = null; try { x = await fetch(HOSTED + "/api/near/market/buy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ side, market: mk.id }), signal: AbortSignal.timeout(45000) }).then((r) => r.json()); } catch (e) { x = { ok: false, why: e.name === "TimeoutError" ? "no answer from the test network in 45 s; press again in a minute" : "the server did not answer" }; }
          clearInterval(tick); all.forEach((x) => { x.disabled = false; });
          if (x && x.ok) nearView(%s, "get_traders", { id: mk.id }).then((n) => { $(cell).textContent = (cell === "truth" ? truthText : demandText)({ ...mk, traders: n }); }).catch(() => {});
          out.replaceChildren(x && x.ok ? `Bought ${x.shares} shares of ${side === "yes" ? "Yes" : "No"} for ${x.paid_usd.toFixed(2)} test USDC, recorded on NEAR. ` : `Not bought: ${(x && x.why) || "no answer"}.`,
            ...(x && x.url ? [Object.assign(document.createElement("a"), { href: x.url, textContent: "The trade on NEAR" })] : []));
        });
        box.append(btn);
      }
    } });
  board.then(async (b) => { const m = (b && b.claims && b.claims[name]) || {};
    $("truth").textContent = b ? truthText(m.truth, m.last_proof) : "not read"; $("demand").textContent = b ? demandText(m.demand) : "not read";
    // the same two markets, read again by this browser from NEAR itself
    for (const [id, cell, text] of [[m.truth && m.truth.id, "truth", (x) => truthText(x, m.last_proof)], [m.demand && m.demand.id, "demand", demandText]]) {
      if (!id) continue;
      try { const v = await nearView(%s, "get_market", { id }); const traders = await nearView(%s, "get_traders", { id }).catch(() => null);
        const mm = { ...m[cell], id, trades: v.market.trades, traders, outcome: v.market.outcome, yes_cents: +v.yes_price / 10000 };
        if (cell === "demand") { const g = await nearView(%s, "get_outside", { claim: name, from: m.demand.opened, until: m.demand.closes }); mm.behind_usd = +g.total / 1e6; }
        $(cell).textContent = text(mm) + ". Read from NEAR by this browser."; } catch (err) { /* the server's reading stays */ }
    } });
  // every backer of this claim, read by this browser from NEAR: Knos's own accounts are labelled, and only the others
  // count toward the demand market
  (async () => { const t = $("backers"), mk = t.dataset.market;
    try {
      const [rows, all] = await Promise.all([nearView(mk, "get_backers", { claim: name, from_index: 0, limit: 200 }), nearView(mk, "get_backs", { claim: name, from_index: 0, limit: 500 })]);
      const tb = t.querySelector("tbody"), day = (s) => new Date(s * 1000).toISOString().slice(0, 16).replace("T", " ");
      let outside = 0;
      for (const [at, amount, who, own] of rows) {
        const tr = document.createElement("tr"), a = Object.assign(document.createElement("a"), { href: "https://testnet.nearblocks.io/address/" + who, textContent: own ? "Knos (test seed)" : who });
        if (!own) outside += +amount / 1e6;
        tr.append(Object.assign(document.createElement("td"), { textContent: day(at) }), Object.assign(document.createElement("td"), {}), Object.assign(document.createElement("td"), { className: "n", textContent: (+amount / 1e6).toFixed(2) }));
        tr.children[1].append(a); tb.append(tr);
      }
      const early = all.length - rows.length, earlyUsd = all.slice(0, Math.max(0, early)).reduce((s, x) => s + +x[1] / 1e6, 0);
      $("backed").textContent = `${outside.toFixed(2)} test USDC from outside backers, ${rows.filter((x) => x[3]).length} ${rows.filter((x) => x[3]).length === 1 ? "backing" : "backings"} by Knos (test seed).` +
        (early > 0 ? ` ${early} earlier backings (${earlyUsd.toFixed(2)} test USDC) were recorded before backers were named; all came from Knos's own test buyer.` : "");
      t.hidden = rows.length === 0;
    } catch (err) { $("backed").textContent = "The backers could not be read from NEAR just now."; }
  })();
  let text = null, job = null;
  async function check(bytes, changed) {
    const mine = await sha256(bytes), locked = job && job.criteria_hash;
    const ok = mine === locked;
    $("verdict").replaceChildren(Object.assign(document.createElement("b"), { textContent: ok ? "VERIFIED" : "NOT VERIFIED" }),
      ok ? `: the test's sha256 ${mine.slice(0, 16)}... is the one NEAR locked for ${job.id} before the agents started (read from NEAR just now).`
         : `: ${changed ? "with one byte changed, " : ""}the test's sha256 is ${mine.slice(0, 16)}..., not the ${String(locked).slice(0, 16)}... NEAR locked${job ? " for " + job.id : ""}.`);
  }
  $("verify").addEventListener("click", async () => {
    $("verify").disabled = true; const v0 = performance.now();
    const vt = setInterval(() => { $("verdict").textContent = `Fetching the test and reading NEAR... ${((performance.now() - v0) / 1000).toFixed(1)} s`; }, 100);
    try {
      const b = await board, id = b && b.claims && b.claims[name] && b.claims[name].truth && b.claims[name].truth.id;
      if (!id) { clearInterval(vt); $("verdict").textContent = b && b.claims && b.claims[name] && b.claims[name].read_at !== undefined || (b && b.read_at) ? "No job of this claim on NEAR yet: order the first proof." : "Knos is still reading this claim's jobs from NEAR: press again in a few seconds."; $("verify").disabled = false; return; }
      const [file, j] = await Promise.all([fetch(%s).then((r) => r.arrayBuffer()), nearView(%s, "get_job", { id: id.slice(4) })]);
      clearInterval(vt);
      text = new Uint8Array(file); job = { ...j, id: id.slice(4) };
      await check(text, false);
    } catch (err) { clearInterval(vt); $("verdict").textContent = `Not checked: ${err.message}. Press the button again in a few seconds.`; }
    clearInterval(vt); $("verify").disabled = false;
  });
  $("tamper").addEventListener("click", async () => {
    if (!text) {
      $("verdict").textContent = "Checking the test against NEAR first...";   // not checked yet: check first, then change the byte
      $("verify").click();
      await new Promise((res) => { const w = setInterval(() => { if (!$("verify").disabled) { clearInterval(w); res(); } }, 100); });
      if (!text) return;
    }
    $("verdict").textContent = "Changing one byte and hashing again...";
    const t = text.slice(); t[t.length - 2] ^= 1; await check(t, true);
  });
  const c = await getJSON("/api/near/claim/counters");
  if (!c) { $("proofs").textContent = "NEAR testnet's record could not be read just now."; return; }
  const x = (c.by_claim && c.by_claim[name]) || (name === "hyperloglog" && !c.by_claim ? { proofs: c.proofs, usd: c.usd } : { proofs: 0, usd: 0 });
  $("proofs").textContent = `${x.proofs.toLocaleString("en-US")} ${x.proofs === 1 ? "proof" : "proofs"} paid, ${usd(x.usd)} in test USDC behind this claim.`;
  const rows = (c.receipts || []).filter((r) => (r[3] || "hyperloglog") === name).slice(0, 25);
  if (rows.length) { const tb = document.querySelector("#receipts tbody");
    for (const [tx, amount, at] of rows) { const tr = document.createElement("tr");
      tr.innerHTML = `<td>${new Date(at * 1000).toISOString().slice(0, 16).replace("T", " ")}</td><td class="n">${amount == null ? "not read yet" : (+amount).toFixed(2)}</td><td><a href="https://testnet.nearblocks.io/txns/${tx}">${tx.slice(0, 10)}...</a></td>`;
      tb.append(tr); }
    $("receipts").hidden = false; }
})();""" % (json.dumps(c["name"]), json.dumps(MARKET), json.dumps(MARKET), json.dumps(MARKET), json.dumps(MARKET),
              json.dumps(f"https://raw.githubusercontent.com/drexthealpha/Knos/main/near/agents/job/{c['test']}"), json.dumps(JOBS))
    short = {"hyperloglog": "HyperLogLog", "jump-hash": "jump consistent hash", "xor-filter": "the xor filter", "morris-counter": "the Morris counter"}.get(c["name"], c["name"])
    return page(header, "../../", f"Knos: does {short} hold?", c["plain"], body, script, f"claim/{c['name']}/")   # a title under 52 characters


def agents_page(header: str) -> str:
    flow = (f'curl -X POST {HOSTED}/api/near/claim/flow -H "Content-Type: application/json" \\\n'
            '  -d \'{"url": "https://doi.org/10.46298/dmtcs.3545", "amount": 10}\'')
    body = ("<h1>For agents</h1>\n<p class=\"lead\">One call proves a paper's claim on NEAR testnet: it reads the paper, runs the locked "
            "test, puts the test USDC behind the claim and returns the verdict, the verified code and the receipt.</p>\n"
            f"<h2>The call</h2>\n<pre>{e(flow)}</pre>\n"
            "<p>The answer holds <code>verdict.holds</code> (true or false), <code>cap.refused</code> (an agent's over-budget step "
            "refused on NEAR), <code>paid</code>, <code>settled</code>, <code>receipt</code> with each transfer's link, and <code>code</code>: "
            "the verified code to download. It takes about 25 s (up to 2 min measured with three orders at once). The agent call has its own 10 live proofs a day; after those it "
            "answers with the last verified proof, marked <code>\"reused\": true</code>. <code>verdict.agent_a</code> says who wrote agent A's code: "
            "the private model on NEAR AI Cloud, or agent A's fixed program when the model's code for that claim failed its locked test.</p>\n"
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
            "90% to the agent whose code passed the locked test, 10% to Knos. For example, 3.00 behind a proof: 2.70 to the agent, "
            "0.30 to Knos. NEAR's market contract refuses any other split. The job itself also pays that agent 1.00. A failed "
            "proof pays nobody. Proving the same order again is free.</p>\n"
            "<p>A person checking one paper by hand costs $330 to $763 "
            "(<a href=\"https://labordynamicsinstitute.github.io/crress-book/\">Colliard and others, 2023</a>).</p>\n"
            "<p>Today this is test money on NEAR testnet: nobody has paid real money and Knos has no customers yet. Knos has no token and no points.</p>")
    return page(header, "../", "Knos pricing", "The test USDC you choose, paid only after the answer.", body, "", "pricing/")


def status_page(header: str) -> str:
    body = ("<h1>Status</h1>\n<p>Is Knos up right now? Each line is read live.</p>\n<table id=\"st\"><tbody>"
            "<tr><th>The proof service</th><td id=\"svc\">reading</td></tr>"
            "<tr><th>Live proofs today</th><td id=\"today\">reading</td></tr>"
            "<tr><th>NEAR testnet's record</th><td id=\"rec\">reading</td></tr>"
            "<tr><th>Latest full test run</th><td id=\"ci\">reading</td></tr>"
            "<tr><th>Uptime</th><td id=\"up\">reading</td></tr>"
            "<tr><th>Visits, 7 days</th><td id=\"funnel\">reading</td></tr>"
            "</tbody></table>\n<h2>Accounts that keep the demo up</h2>\n<table id=\"bal\"><tbody><tr><td>reading</td></tr></tbody></table>\n"
            "<p class=\"fine\">Each line is read now, from the hosted server, NEAR testnet and GitHub.</p>")
    script = LIVE_JS + """(async () => {
  const [l, c, t] = await Promise.all([getJSON("/api/near/live"), getJSON("/api/near/claim/counters"), getJSON("/api/near/tests")]);
  $("svc").textContent = l ? (l.live ? "up, on NEAR testnet" : "up, live runs switched off") : "not answering";
  $("today").textContent = l ? `${l.used_today} of ${l.cap_today} on the page, ${l.agent_used_today ?? 0} of ${l.agent_cap_today ?? 0} for agents` : "not read";
  $("rec").textContent = c && c.read_at ? `${c.proofs} proofs paid, ${usd(c.lost_usd)} lost, read ${c.read_at.replace("T", " ").replace("Z", " UTC")}` : "not read";
  $("ci").innerHTML = t && t.url ? `${t.passed ? "passed" : "failed"}, <a href="${t.url}">commit ${String(t.sha || "").slice(0, 8)}</a>` : "not read";
  // checks every 30 minutes by ledger.yml, kept on the gh-pages branch, so a restart cannot reset them
  fetch("https://raw.githubusercontent.com/drexthealpha/Knos/gh-pages/uptime.jsonl", { cache: "no-store" }).then((r) => r.ok ? r.text() : "").then((txt) => {
    const since = Date.now() - 7 * 864e5, rows = txt.split(/\\r?\\n/).filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter((x) => x && Date.parse(x.at) >= since);
    $("up").textContent = rows.length ? `up ${rows.filter((x) => x.up).length} of ${rows.length} checks in the last 7 days, from ${rows[0].at.slice(0, 16).replace("T", " ")} UTC` : "no checks yet";
  }).catch(() => { $("up").textContent = "not read"; });
  getJSON("/api/visits").then((v) => { const f = v && v.funnel;
    $("funnel").textContent = f ? `${f.visits} visits, ${f.first_press} pressed, ${f.first_result} got an answer, ${f.proof_finished} ran a proof, ${f.backed} backed, ${f.came_back} came back` + (v.results_counted_from ? ` (answers, proofs and backings counted from ${v.results_counted_from})` : "") + (v.leave_most ? `; most leave from ${v.leave_most}` : "") : "not read"; });
  const b = await getJSON("/api/near/balances"), unit = { near: "NEAR", allowance: "NEAR allowance", usdc: "test USDC" };
  const tb = document.querySelector("#bal tbody");
  if (!b || !b.rows) { tb.innerHTML = "<tr><td>not read</td></tr>"; return; }
  tb.replaceChildren(...b.rows.map((x) => { const tr = document.createElement("tr");
    const a = Object.assign(document.createElement("a"), { href: "https://testnet.nearblocks.io/address/" + x.account, textContent: x.what });
    const th = document.createElement("th"); th.append(a);
    const td = Object.assign(document.createElement("td"), { textContent: `${x.value == null ? "not read" : x.value} ${unit[x.kind]}, floor ${x.floor}${x.ok ? "" : ": LOW"}` });
    if (!x.ok) { td.style.color = "#c62828"; td.style.fontWeight = "600"; tr.style.borderBottom = "2px solid #c62828"; }
    tr.append(th, td); return tr; }));
})();"""
    return page(header, "../", "Knos status", "The proof service, today's live proofs and the latest test run, read live.", body, script, "status/")


def privacy_page(header: str) -> str:
    body = ("<h1>Privacy and terms</h1>\n<h2>This site</h2>\n<p>No cookies and no third-party scripts. "
            "To learn why people stay or leave, each page sends Knos small events of an anonymous visit: a random id your browser makes and "
            "resets every day, the page, each press and how long its answer took, whether you got an answer, ran a proof, backed a claim or "
            "downloaded code, three quick presses on one spot, an error shown, and the last page and its seconds before you leave. No IP "
            "address, account or cookie is stored with them. If your browser sends Do Not Track, nothing is sent. /status shows the totals. "
            "The paper link you paste goes to the "
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
    # each page with the source file it is made from: scripts/sitemap_dates.py writes that file's last commit date
    pages = [("", "web/door.html"), ("claims/", "near/claims/claims.json"), *[(f"claim/{c['name']}/", "near/claims/claims.json") for c in cs],
             ("prove/", "near/web/index.html"), ("agents/", "scripts/site_product.py"), ("labs/", "web/iris/index.html"),
             ("pricing/", "scripts/site_product.py"), ("status/", "scripts/site_product.py"), ("privacy.html", "scripts/site_product.py"),
             ("check/", "web/check-v0328/index.html")]
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"  <url><loc>{base}{p}</loc><lastmod>git:{src}</lastmod></url>\n" for p, src in pages) + "</urlset>\n", encoding="utf-8")
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
