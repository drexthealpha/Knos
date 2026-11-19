"""The product's own pages, written by scripts/site_pages.py into the published site: the claims (claims/ and one page per
claim under claim/), the agent's way in (agents/), pricing/ and status/. Each carries the one header and a short
footer; every number on them is read live from the hosted server or NEAR testnet when the page opens.

The claims are near/claims/claims.json; each one's locked test is a file of near/agents/job/, and its sha256 is the
criteria hash every job for that claim is opened with on NEAR testnet."""
import hashlib
import html
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOSTED = "https://knos.onrender.com"
REPO = "https://github.com/drexthealpha/Knos"
JOBS = "jobs.knos-swarm-1105.testnet"
MARKET = "market.knos-swarm-1105.testnet"
EXPLORER = "https://testnet.nearblocks.io/address/"
GOAL = "The goal: Knos turns any research into a product billions of people use, in days, not years."
HEADER_CSS = ""   # the one header's styles, set by scripts/site_pages.py before it writes these pages


def _tool_page():
    """The server's page module (apps/wanted/knos_wanted/tool_page.py), loaded by its path: the one place the strings of
    web/i18n/ are read, the language control is drawn and the five answers of a fold are written (Round 13, H3)."""
    spec = importlib.util.spec_from_file_location("knos_tool_page", ROOT / "apps" / "wanted" / "knos_wanted" / "tool_page.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TP = _tool_page()


def en(key: str, **v) -> str:
    """One English string of web/i18n/en.json as plain text (a page of the build is written in English first)."""
    return TP.t("en", key, **v)

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
@media (max-width: 480px) { th, td { padding: 8px 4px; } #claims thead { display: none; } #claims tr { display: block; border-bottom: 1px solid var(--line); padding: 8px 0; } #claims td { display: block; border: 0; padding: 2px 0; text-align: left; } #claims td[data-behind]::before { content: "Test money put behind it: "; font-weight: 600; } #claims td[data-truth]::before { content: "Does it hold? "; font-weight: 600; } #claims td[data-demand]::before { content: "100 test dollars from outside Knos in 7 days? "; font-weight: 600; } }
/* a 390 px phone: no text under 16 px, every link and control a 44 px tap target */
@media (max-width: 460px) {
  main p a, main td a, main li a, main dd a { padding: 12px 0; margin: -12px 0; }
  main button, main .btn, main label, main summary, main code, main pre, main small, main th, main .fine, main input, main select { font-size: 16px; }
  main summary { display: flex; align-items: center; min-height: 44px; }
  nav a { display: inline-flex; align-items: center; min-height: 44px; }
}
"""


# attacks tried on NEAR testnet, each refused by the contracts (near/CLAIMS.md)
ATTACKS = [("Settle a claim by vote", "a market settles only by its locked test", "371H72CAkzrN1ih486C32y9iFsrKd1ndqZXKxWL5tYyL"),
           ("Change a claim's locked test", "the test is locked when the job is funded", "DVXvKjBMhXhJgXKTNcF1DVMVXWLa7pzZB3ukon9dpkaH"),
           ("Settle before the test ran", "nothing settles until the locked test has run", "7D9AaoNRccUcmtWFt3yrWkZqq1LYC4ef6zMhttXjny6F"),
           ("Pay without a passing result", "a release needs the checker's token for a passing output", "E5GUcVks55r9Rn4b1HJBJagDB1bFbL8YMj41UFHFeHan"),
           ("Use a payment token twice", "each token is used once", "HcZ8nBuQYuYU5LKRVceSfXVdqBnLrj1shyddj3EQBsM2"),
           ("Spend over an agent's cap", "an agent's spending stops at its cap", "FdJPJf7RLdErvMBdeUkeUWdhqw4VGNEKtw5aVD4VnK4y"),
           # Round 11, W3: the jobs contract's own answers, 14 Nov 2026
           ("Pay agent-a2.knos-swarn-1105.testnet, one letter off agent-a2", "the payee is not on the agent's allow-list", "FShgZgDA6pUwY3KxJ4yi76CDBGX8F1oiihR5NN97BFgw"),
           ("Spend past the day's cap", "over the daily cap: 4 spent today, daily cap 4", "HbfZUGFttohzRimGQHqvDugkQxiy8SQJZrtHTQTqX67b"),
           ("Take a job while an owner has paused the contract", "nothing moves but refunds while paused", "3taNnSqwfPhYTJxQaxXrnkCst7ZD4XyW1G3ZmvhJ4YE1"),
           ("Spend over the hold line", "held until the approver released it", "DGnkLSSL8NxjE5L2DBg9rYYjc4gJrSFj2SdPz6HwKgLJ"),
           ("Pass with a hard-coded answer (count() returns 30000)", "the AI reviewer rejected it; the rejection is on chain", "6ZfhCrRVPGgmVEkqPZT5JSD6Wq9tMX5PjUGsnvFpifmn")]


def claims() -> list[dict]:
    """The claims, each with its locked test's sha256 (the criteria hash its jobs are opened with)."""
    out = []
    for c in json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]:
        test = ROOT / "near" / "agents" / "job" / c["test"]
        out.append({**c, "sha256": hashlib.sha256(test.read_bytes()).hexdigest()})
    return out


def e(s) -> str:
    return html.escape(str(s), quote=True)


def theme_colors() -> str:
    """The browser bar takes the page colour: the dark and the light paper of web/brand/tokens.css, the one palette."""
    css = (ROOT / "web" / "brand" / "tokens.css").read_text(encoding="utf-8")
    dark = re.search(r":root \{\s*--paper: (#[0-9a-f]{6})", css)[1]
    light = re.search(r':root\[data-theme="light"\] \{\s*--paper: (#[0-9a-f]{6})', css)[1]
    return f'<meta name="theme-color" content="{dark}">\n<meta name="theme-color" content="{light}" media="(prefers-color-scheme: light)">\n'


# Round 13 WALK 1, on the deeper pages only (claims/, claim/*, agents/; privacy.html is frozen until 5 Dec): one primary
# control a screen (.btn), every other control .btn2; 16 px text; every link a 44 px target at every width; one closed
# "How it works" fold; the closed menu's links not laid out (they measured 12 by 44 px, unseen, beside it)
WALK_CSS = """code, pre, button { font-size: 16px; }
button { font-family: inherit; }
.btn[disabled], .btn2[disabled] { opacity: .45; cursor: not-allowed; }
.btn2 { display: inline-flex; align-items: center; min-height: 48px; padding: 0 16px; border-radius: 10px; border: 1px solid var(--ink-2); background: transparent; color: var(--ink); text-decoration: none; font-weight: 600; cursor: pointer; }
.how { margin: 24px 0 0; border-top: 1px solid var(--line); }
.how > summary { display: flex; align-items: center; min-height: 48px; cursor: pointer; font-weight: 600; }
.back { display: inline-flex; align-items: center; min-height: 44px; }
main p a, main td a, main li a, main dd a { padding: 12px 0; margin: -12px 0; }
details:not([open]) > .kmenu-panel { display: none; }
"""


def page(header: str, up: str, title: str, desc: str, body: str, script: str = "", canonical: str = "", foot: str = "", css: str = "") -> str:
    """A product page. With `foot` (the front door's screens, scripts/site_pages.py foot()): the foot carries the menu and
    the light or dark switch, the honesty line is the foot's heading, and the goal is the menu's first line."""
    links = (f'<a href="{REPO}">{e(en("nav.source"))}</a><a href="{up}pricing/">{e(en("nav.pricing"))}</a><a href="{up}status/">{e(en("nav.status"))}</a>'
             f'<a href="{up}privacy.html">{e(en("nav.privacy"))}</a>')
    bottom = (f'<footer><h2 class="fline">{e(en("foot.pages"))}</h2><div class="flinks">{links}</div>{foot}</footer>\n' if foot
              else f'<footer><span>{e(en("foot.pages"))}</span><br><span>{GOAL}</span><br>{links}</footer>\n')
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{e(title)}</title>\n<meta name=\"description\" content=\"{e(desc)}\">\n<meta name=\"color-scheme\" content=\"light dark\">\n"
            f'<link rel="canonical" href="https://drexthealpha.github.io/Knos/{canonical}">\n'
            f'<meta property="og:title" content="{e(title)}">\n<meta property="og:description" content="{e(desc)}">\n'
            f'<meta property="og:image" content="https://drexthealpha.github.io/Knos/brand/card.png">\n'
            f'{theme_colors()}<link rel="icon" href="{up}icon.svg" type="image/svg+xml">\n<link rel="icon" href="{up}favicon.ico" sizes="16x16 32x32 48x48">\n'
            f'<link rel="apple-touch-icon" href="{up}brand/apple-touch-icon.png">\n<link rel="stylesheet" href="{up}brand/tokens.css">\n'
            f"<style>\n{CSS}{HEADER_CSS}{css}</style>\n</head>\n<body>\n{header}\n<main>\n{body}\n</main>\n"
            + bottom + (f"<script>\n{script}\n</script>\n" if script else "") + "</body>\n</html>\n")


LIVE_JS = """const HOSTED = "__HOSTED__";
const $ = (id) => document.getElementById(id);
const usd = (n) => (n === null || n === undefined || n === "" || !isFinite(+n)) ? "unknown" : (+n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " test dollars";   // test money: never a dollar sign; a missing amount is unknown, not 0
// the board and the counters are also files of this site, written by every Pages build (data/): a live answer within
// 1.2 s is used, else the file is shown at once, with its own read time, so a press never waits on a sleeping server
const LOGO = document.querySelector("#kh .logo"), SITE_ROOT = LOGO && LOGO.href ? LOGO.href : new URL(LOGO && LOGO.dataset.root || "./", location).href, CACHED = { "/api/near/claims": "board.json", "/api/near/claim/counters": "counters.json" };
async function getJSON(path) {
  const live = (async () => { try { const r = await fetch(HOSTED + path); return r.ok ? await r.json() : null; } catch (e) { return null; } })();
  if (!CACHED[path]) return live;
  const file = fetch(new URL("data/" + CACHED[path], SITE_ROOT)).then((r) => r.ok ? r.json() : null).catch(() => null);
  const quick = await Promise.race([live, new Promise((res) => setTimeout(res, 1200, "slow"))]);
  if (quick && quick !== "slow") return quick;
  const f = await file;
  return f && Object.keys(f).length && !f.pending ? f : await live;   // a file the build wrote before it read NEAR says pending
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
    } catch (e) { last = "the public record is busy"; }
  }
  throw new Error(last);
}
async function sha256(bytes) { return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join(""); }
// R13 WALK 2: how many people predicted the answer in test dollars, in plain words (no "traded" or "price")
const thin = (m) => m.traders == null ? `${m.trades} ${m.trades === 1 ? "prediction" : "predictions"}` : `${m.traders} ${m.traders === 1 ? "person" : "people"} predicted${m.traders < 5 ? ", too few to trust" : ""}`;
// jobs paid to agents: the jobs contract's own count, read from this browser (get_totals and get_agent_record, since its
// 14 Nov 2026 upgrade; each pass of an agent is one job paid to it), else the hosted server's copy of the same read
const AGENTS = ["agent-a", "agent-a2", "agent-b", "agent-b2"].map((a) => a + ".knos-swarm-1105.testnet");
async function jobsPaid() {
  try {
    const [t, ...r] = await Promise.all([nearView("__JOBS__", "get_totals", {}), ...AGENTS.map((a) => nearView("__JOBS__", "get_agent_record", { agent: a }))]);
    const k = t["knos-usdc-1102.testnet"] || {};
    return { jobs: r.reduce((n, x) => n + (+x.passes || 0), 0), usd: (+k.paid || 0) / 1e6, at: new Date().toISOString() };
  } catch (e) {
    const t = await getJSON("/api/near/totals"), u = t && t.since_upgrade;
    return u ? { jobs: u.jobs_paid, usd: +u.paid_usd, at: u.read_at } : null;
  }
}
// Round 13 WALK 1: plain words on the screen (no proof, job or product name); the record's ids stay in the fold
function truthText(m, last) {
  if (last) return "Yes: a test fixed before any work started passed";
  if (!m) return "opens with the first check";
  if (m.outcome === true) return "Yes, settled by a test fixed before any work started";
  if (m.outcome === false) return "No, settled by a test fixed before any work started";
  return `Not checked yet; ${thin(m)}`;
}
function demandText(m) {
  if (!m) return "opens soon";
  if (m.outcome === true) return +m.behind_usd >= 100 ? "Yes: 100 test dollars from people outside Knos within 7 days" : "Yes, settled on Knos's own test money before this rule";
  if (m.outcome === false) return "No: under 100 test dollars from people outside Knos within 7 days";
  return `${(+m.behind_usd).toFixed(2)} of 100 by ${new Date(m.closes * 1000).toISOString().slice(0, 10)}; ${thin(m)}`;
}
""".replace("__HOSTED__", HOSTED).replace("__JOBS__", JOBS)


def claims_page(header: str, cs: list[dict]) -> str:
    # Round 13 WALK 1: one plain sentence and the list on the screen; every technical word, name and table in one closed fold
    rows = "".join(f'<tr data-claim="{e(c["name"])}"><td><a href="../claim/{e(c["name"])}/">{e(everyday(c))}</a><br>'
                   f'<span class="fine">{e(c["authors"])}, {c["year"]}</span></td>'
                   f'<td class="n" data-behind>reading</td><td data-truth>reading</td><td data-demand>reading</td></tr>' for c in cs)
    body = (f"<h1>Claims</h1>\n<p>Results from papers, each checked by a test fixed before any work starts. Pick one to see it.</p>\n"
            f'<table id="claims"><thead><tr><th>Claim</th><th class="n">Test money put behind it</th><th>Does it hold?</th><th>100 test dollars from outside Knos in 7 days?</th></tr></thead>\n<tbody>{rows}</tbody></table>\n'
            f'<p class="fine" id="as-of">Read live from the public record.</p>\n'
            f'<details class="how"><summary>How it works</summary>\n'
            f"<p>Knos locks a test before any work starts, and test money moves to the agent that did the work only if that test "
            f"passes. Here the work is code that proves a paper's claim. Each test is locked on a public test blockchain.</p>\n"
            + "".join(f'<p><a href="../claim/{e(c["name"])}/">{e(everyday(c))}</a>: {e(c["plain"])}</p>\n' for c in cs)
            + '<p>Each claim has two markets, their prices moving with each trade: whether it holds, '
            'settled by its locked test, and whether 100 test dollars are put behind it within 7 days, settled by the '
            'public record. Test money put behind it counts every payment the claim market recorded, Knos\'s own test account\'s '
            'included; the last column counts outside accounts only. All of it is test money: nothing real is charged.</p>\n'
            '<h2>Tried, and refused</h2>\n<table><thead><tr><th>Attempt</th><th>What the record did</th><th>Record</th></tr></thead><tbody>'
            + "".join(f'<tr><td>{e(a)}</td><td>{e(why)}</td><td><a href="https://drexthealpha.github.io/Knos/tx/?h={tx}">{tx[:8]}...</a></td></tr>' for a, why, tx in ATTACKS)
            + '</tbody></table>\n<p>And in every live check, agent B tries to spend over its cap and is refused. The contracts\' '
              '223 tests, 155 of them attacks, run on every change: <code>bash near/scripts/verify.sh</code>.</p>\n</details>')
    script = LIVE_JS + """(async () => {
  // the claim market's own record of what was put behind each claim (get_backed): its total and how many payments
  const b = await getJSON("/api/near/claims");
  const rows = [...document.querySelectorAll("#claims tbody tr")];
  for (const r of rows) { const m = (b && b.claims && b.claims[r.dataset.claim]) || {}, n = +m.proofs || 0, behind = +m.behind_usd || 0;
    const paid = `${usd(behind)} in ${n.toLocaleString("en-US")} ${n === 1 ? "payment" : "payments"}`, cell = r.querySelector("[data-behind]");
    cell.textContent = b ? `${paid}, Knos's own included` : "not read";
    // R13 WALK 2: whose payments, read by this browser from the claim market: every named backer, Knos's own marked by
    // the contract (set_own); backings from before backers were named carry no account and, by the contract's own
    // record, all came from Knos's own test buyer
    if (b && n > 0) nearView(__MARKET__, "get_backers", { claim: r.dataset.claim, from_index: 0, limit: 500 }).then((rows) => {
      const out = rows.filter((x) => !x[3]).reduce((s, x) => s + +x[1] / 1e6, 0);
      cell.textContent = out > 0 ? `${paid}, ${out.toFixed(2)} from outside Knos` : `${paid}, all from Knos's own test accounts`;
    }).catch(() => {});
    r.querySelector("[data-truth]").textContent = b ? truthText(m.truth, m.last_proof) : "not read";
    r.querySelector("[data-demand]").textContent = b ? demandText(m.demand) : "not read"; r.dataset.usd = behind; }
  rows.sort((a, b) => (+b.dataset.usd || 0) - (+a.dataset.usd || 0)).forEach((r) => r.parentNode.append(r));
  $("as-of").textContent = b && b.read_at ? `Read from the public record at ${b.read_at.replace("T", " ").replace("Z", " UTC")}.` : "The public record could not be read just now.";
})();""".replace("__MARKET__", json.dumps(MARKET))
    return page(header, "../", "Knos claims", "Results from papers, each checked by a test fixed before any work starts.", body, script, "claims/", css=WALK_CSS)


# Round 13 WALK 1: each claim in words a stranger needs no dictionary for, with no number (the numbers stay in its
# `plain` sentence of near/claims/claims.json, shown in the fold); a claim not named here shows its `plain` sentence
EVERYDAY = {"hyperloglog": "Count a huge crowd of visitors in a tiny memory",
            "jump-hash": "Share work between computers, moving little when one is added",
            "xor-filter": "Answer “have I seen this before?” in less memory",
            "morris-counter": "Count many events in a very small counter",
            "kepler-10b": "How long a year lasts on a faraway planet",
            "landsat-8-orbit": "A satellite whose orbit keeps pace with the sun",
            "cmapss-engine-life": "Tell how long a jet engine has left",
            "limit-check": "Name the first row of a test file that breaks a limit"}


def everyday(c: dict) -> str:
    return EVERYDAY.get(c["name"], c["plain"])


def usdc_market() -> dict:
    return json.loads((ROOT / "near/claims/usdc_market.json").read_text(encoding="utf-8"))


def usdc_section(c: dict) -> str:
    """Round 9 U8: the claim's markets in Circle's NEAR testnet USDC, from the visitor's own wallet. Until live, the block
    is hidden and loads nothing, except for the end-to-end test, which opens the page at #usdc-test."""
    u = usdc_market()
    live = bool(u.get("live"))
    load = ('<script type="module" src="../../usdc-market.js"></script>' if live else
            '<script>if (location.hash === "#usdc-test") { document.getElementById("usdc").hidden = false; import("../../usdc-market.js"); }</script>')
    cfg = {k: u[k] for k in ("market", "token", "jobs", "agent", "fee")} | {"claim": c["name"], "sha256": c["sha256"]}
    buy = lambda kind, side: f'<button class="btn" type="button" data-act="{kind}-{side}" disabled>{side.title()}, 1 USDC</button>'   # noqa: E731
    return (f"<section id=\"usdc\" data-cfg='{e(json.dumps(cfg))}'{'' if live else ' hidden'}>\n<h2>Trade or back it from your own wallet</h2>\n"
            f'<p class="row"><button class="btn" id="u-connect" type="button">Connect your NEAR testnet wallet</button> <span id="u-who"></span></p>\n'
            f'<p class="fine">Free test USDC: <a href="https://faucet.circle.com/">Circle\'s faucet</a>, network Near Testnet, 20 USDC every 2 hours.</p>\n'
            f'<table><tbody><tr><th>Does it hold?</th><td><span id="u-truth">reading</span> {buy("truth", "yes")} {buy("truth", "no")}</td></tr>'
            f'<tr><th>{u["demand_usdc"]} test USDC behind it within 7 days?</th><td><span id="u-demand">reading</span> {buy("demand", "yes")} {buy("demand", "no")}</td></tr></tbody></table>\n'
            f'<p class="row"><button class="btn" type="button" data-act="back" disabled>Back it, 1 USDC</button> <span id="u-behind"></span></p>\n'
            f'<p id="u-backers" class="fine"></p>\n<p id="u-said" role="status"></p>\n'
            f'<p class="fine">Each market seeded with {u["seed_usdc"]:.2f} test USDC by Knos, b = {u["b_usdc"]} USDC. '
            f'Contract: <a href="{EXPLORER}{u["market"]}">{u["market"]}</a>. Your wallet signs; Knos never holds your key.</p>\n'
            f'{load}\n</section>\n')


def claim_page(header: str, c: dict) -> str:
    test_url = f"{REPO}/blob/main/near/agents/job/{c['test']}"
    src = "https://doi.org/" + c["doi"] if c.get("doi") else c["url"]   # a source with no DOI (a NASA page) links the page itself
    said = "The paper says" if c.get("doi") else "The page says"
    # Round 13 WALK 1: on the screen, the claim in everyday words, whether it holds, and one primary control (check it);
    # the paper, the locked test, the fingerprint check, the test-money trades (the NEAR entry, judged until 18 Nov: they
    # stay, as secondary controls) and the record all sit in one closed "How it works" fold. NEAR testnet is named once
    # there, for the NEAR judging.
    body = (f'<p><a class="back" href="../../claims/">All claims</a></p>\n<h1>{e(everyday(c))}</h1>\n'
            f'<p>A result from a paper, checked by a test fixed before any work started. Does it hold? <b id="truth">reading</b></p>\n'
            f'<p><a class="btn" href="../../prove/#paper={e(src)}">Check this claim</a></p>\n'
            f'<details class="how"><summary>How it works</summary>\n'
            f'<p><b>The claim:</b> {e(c["plain"])}</p>\n'
            f'<p>From <a href="{e(src)}">{e(c["paper"])}</a>, {e(c["authors"])}, {c["year"]}. {said}: '
            f'&ldquo;{e(c["quote"])}&rdquo;</p>\n'
            + (f'<p><b>Caveat:</b> {e(c["caveat"])}</p>\n' if c.get("caveat") else "")
            + (f'<p>Data: {e(c["data_credit"])}</p>\n' if c.get("data_credit") else "")
            + f'<h2>The locked test</h2>\n<p><a href="{test_url}">{e(c["test"])}</a>. Every job for this claim is locked on a public test '
            f'blockchain (NEAR testnet) to this exact file before any agent starts, and the checker runs only this file.</p>\n'
            f'<p><b>What it did not check:</b> {e(c["not_checked"])}.</p>\n'
            f'<p><b>A test by the paper\'s authors:</b> {e(c.get("outside_test", "not looked for yet"))}'
            + "".join(f' <a href="{u}">{e(u.split("/")[4])}</a>' for u in c.get("outside_test_links", [])) + '</p>\n'
            '<h2>Check it yourself, in this browser</h2>\n'
            f'<p>The test file\'s sha256, its fingerprint: <code>{c["sha256"]}</code></p>\n'
            '<p>Your browser fetches the locked test from Knos\'s public code, hashes it, and reads '
            'from the blockchain itself the hash this claim\'s newest job locked before any agent started. Then change one byte and check again.</p>\n'
            '<p class="row"><button class="btn2" id="verify" type="button">Check the test file</button> '
            '<button class="btn2" id="tamper" type="button">Change one byte and check again</button></p>\n'
            '<p id="verdict" role="status"></p>\n'
            '<h2>What people predict, in test dollars</h2>\n<table><tbody><tr><th>Does it hold?</th><td><span id="truth2">reading</span><span class="row" data-trade="truth"></span></td></tr>'
            '<tr><th>100 test dollars behind it within 7 days?</th><td><span id="demand">reading</span><span class="row" data-trade="demand"></span></td></tr></tbody></table>\n'
            '<p id="traded" role="status"></p>\n'
            + usdc_section(c) +
            f'<p>Prices in test dollars move with each trade. Nothing real is charged. The first market settles by the locked test, the '
            f'second by the public record of what was put behind the claim.</p>\n'
            f'<h2>Backers</h2>\n<p id="backed">Reading every backer from the public record...</p>\n'
            f'<table id="backers" data-market="{MARKET}" hidden><thead><tr><th>When (UTC)</th><th>Backer</th><th class="n">Test dollars</th></tr></thead><tbody></tbody></table>\n'
            f'<h2>Receipts</h2>\n<p id="proofs">Reading the public record...</p>\n<table id="receipts" hidden><thead><tr><th>When (UTC)</th>'
            f'<th class="n">Knos\'s fee, test dollars (48 of 49 parts before 12 Nov, 1 in 10 since)</th><th>Knos\'s fee transfer</th></tr></thead><tbody></tbody></table>\n'
            f'<h2>The record</h2>\n<p>Jobs: <a href="{EXPLORER}{JOBS}">{JOBS}</a>. Claim records: <a href="{EXPLORER}{MARKET}">{MARKET}</a>. '
            f'Payments: <a href="{EXPLORER}live.knos-swarm-1105.testnet?tab=tokentxns">Knos\'s own test account that sends the test money</a>.</p>\n</details>')
    script = LIVE_JS + """(async () => {
  const name = %s;
  const board = getJSON("/api/near/claims");
  const say = (cell, text) => { $(cell).textContent = text; if (cell === "truth") $("truth2").textContent = text; };
  // an open market can be traded: 1 test USDC of Yes or No, from the test account Knos holds for you
  board.then((b) => { const m = (b && b.claims && b.claims[name]) || {};
    for (const cell of ["truth", "demand"]) {
      const mk = m[cell];
      if (!mk || mk.outcome != null || (cell === "truth" && m.last_proof)) continue;
      const box = document.querySelector(`[data-trade="${cell}"]`);
      for (const side of ["yes", "no"]) {
        const btn = Object.assign(document.createElement("button"), { type: "button", className: "btn2", textContent: cell === "truth" ? `I think it ${side === "yes" ? "holds" : "fails"} (1 test dollar)` : `I think ${side} (1 test dollar)` });
        btn.style.margin = "8px 8px 0 0";
        btn.addEventListener("click", async () => {
          const all = [...document.querySelectorAll("[data-trade] button")]; all.forEach((x) => { x.disabled = true; });
          const t0 = performance.now(); const out = $("traded");
          const tick = setInterval(() => { out.textContent = `Buying with test money... ${((performance.now() - t0) / 1000).toFixed(1)} s`; }, 100);
          let x = null; try { x = await fetch(HOSTED + "/api/near/market/buy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ side, market: mk.id }), signal: AbortSignal.timeout(45000) }).then((r) => r.json()); } catch (e) { x = { ok: false, why: e.name === "TimeoutError" ? "no answer from the test network in 45 s; press again in a minute" : "the server did not answer" }; }
          clearInterval(tick); all.forEach((x) => { x.disabled = false; });
          if (x && x.ok) nearView(%s, "get_traders", { id: mk.id }).then((n) => { say(cell, (cell === "truth" ? truthText : demandText)({ ...mk, traders: n })); }).catch(() => {});
          out.replaceChildren(x && x.ok ? `Bought ${x.shares} shares of ${side === "yes" ? "Yes" : "No"} for ${x.paid_usd.toFixed(2)} test dollars, recorded on the public record. ` : `Not bought: ${(x && x.why) || "no answer"}.`,
            ...(x && x.url ? [Object.assign(document.createElement("a"), { href: x.url, textContent: "The trade, on the public record" })] : []));
        });
        box.append(btn);
      }
    } });
  board.then(async (b) => { const m = (b && b.claims && b.claims[name]) || {};
    say("truth", b ? truthText(m.truth, m.last_proof) : "not read"); $("demand").textContent = b ? demandText(m.demand) : "not read";
    // the same two markets, read again by this browser from NEAR itself
    for (const [id, cell, text] of [[m.truth && m.truth.id, "truth", (x) => truthText(x, m.last_proof)], [m.demand && m.demand.id, "demand", demandText]]) {
      if (!id) continue;
      try { const v = await nearView(%s, "get_market", { id }); const traders = await nearView(%s, "get_traders", { id }).catch(() => null);
        const mm = { ...m[cell], id, trades: v.market.trades, traders, outcome: v.market.outcome, yes_cents: +v.yes_price / 10000 };
        if (cell === "demand") { const g = await nearView(%s, "get_outside", { claim: name, from: m.demand.opened, until: m.demand.closes }); mm.behind_usd = +g.total / 1e6; }
        say(cell, text(mm) + ". Read from the public record by this browser."); } catch (err) { /* the server's reading stays */ }
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
      $("backed").textContent = `${outside.toFixed(2)} test dollars from outside backers, ${rows.filter((x) => x[3]).length} ${rows.filter((x) => x[3]).length === 1 ? "backing" : "backings"} by Knos (test seed).` +
        (early > 0 ? ` ${early} earlier backings (${earlyUsd.toFixed(2)} test dollars) were recorded before backers were named; all came from Knos's own test buyer.` : "");
      t.hidden = rows.length === 0;
    } catch (err) { $("backed").textContent = "The backers could not be read from the public record just now."; }
  })();
  let text = null, job = null;
  async function check(bytes, changed) {
    const mine = await sha256(bytes), locked = job && job.criteria_hash;
    const ok = mine === locked;
    $("verdict").replaceChildren(Object.assign(document.createElement("b"), { textContent: ok ? "Same file" : "Not the same file" }),
      ok ? `: the test's sha256 ${mine.slice(0, 16)}... is the one the blockchain locked for ${job.id} before the agents started (read from it just now).`
         : `: ${changed ? "with one byte changed, " : ""}the test's sha256 is ${mine.slice(0, 16)}..., not the ${String(locked).slice(0, 16)}... the blockchain locked${job ? " for " + job.id : ""}.`);
  }
  $("verify").addEventListener("click", async () => {
    $("verify").disabled = true; const v0 = performance.now();
    const vt = setInterval(() => { $("verdict").textContent = `Fetching the test and reading the public record... ${((performance.now() - v0) / 1000).toFixed(1)} s`; }, 100);
    try {
      const b = await board, id = b && b.claims && b.claims[name] && b.claims[name].truth && b.claims[name].truth.id;
      if (!id) { clearInterval(vt); $("verdict").textContent = b && b.claims && b.claims[name] && b.claims[name].read_at !== undefined || (b && b.read_at) ? "No job of this claim yet: run the first check on the Papers page." : "Knos is still reading this claim's jobs from NEAR: press again in a few seconds."; $("verify").disabled = false; return; }
      const [file, j] = await Promise.all([fetch(%s).then((r) => r.arrayBuffer()), nearView(%s, "get_job", { id: id.slice(4) })]);
      clearInterval(vt);
      text = new Uint8Array(file); job = { ...j, id: id.slice(4) };
      await check(text, false);
    } catch (err) { clearInterval(vt); $("verdict").textContent = `Not checked: ${err.message}. Press the button again in a few seconds.`; }
    clearInterval(vt); $("verify").disabled = false;
  });
  $("tamper").addEventListener("click", async () => {
    if (!text) {
      $("verdict").textContent = "Checking the test file first...";   // not checked yet: check first, then change the byte
      $("verify").click();
      await new Promise((res) => { const w = setInterval(() => { if (!$("verify").disabled) { clearInterval(w); res(); } }, 100); });
      if (!text) return;
    }
    $("verdict").textContent = "Changing one byte and hashing again...";
    const t = text.slice(); t[t.length - 2] ^= 1; await check(t, true);
  });
  const c = await getJSON("/api/near/claim/counters");
  if (!c) { $("proofs").textContent = "The public record could not be read just now."; return; }
  // the counters before they were split by claim were all HyperLogLog's; an answer with neither is not read
  const x = c.by_claim ? (c.by_claim[name] || { proofs: 0, usd: 0 }) : name === "hyperloglog" && c.proofs != null ? { proofs: c.proofs, usd: c.usd } : null;
  if (!x || x.proofs == null) { $("proofs").textContent = "The public record could not be read just now."; return; }
  $("proofs").textContent = `${x.proofs.toLocaleString("en-US")} ${x.proofs === 1 ? "transfer" : "transfers"} into Knos's fee account for this claim, with ${usd(x.usd)}; Knos's own test account's transfers are counted, so some of this money moved between Knos's own accounts.`;
  const rows = (c.receipts || []).filter((r) => (r[3] || "hyperloglog") === name).slice(0, 25);
  if (rows.length) { const tb = document.querySelector("#receipts tbody");
    for (const [tx, amount, at] of rows) { const tr = document.createElement("tr");
      tr.innerHTML = `<td>${new Date(at * 1000).toISOString().slice(0, 16).replace("T", " ")}</td><td class="n">${amount == null ? "not read yet" : (+amount).toFixed(2)}</td><td><a href="https://drexthealpha.github.io/Knos/tx/?h=${tx}">${tx.slice(0, 10)}...</a></td>`;
      tb.append(tr); }
    $("receipts").hidden = false; }
})();""" % (json.dumps(c["name"]), json.dumps(MARKET), json.dumps(MARKET), json.dumps(MARKET), json.dumps(MARKET),
              json.dumps(f"https://raw.githubusercontent.com/drexthealpha/Knos/main/near/agents/job/{c['test']}"), json.dumps(JOBS))
    short = {"hyperloglog": "HyperLogLog", "jump-hash": "jump consistent hash", "xor-filter": "the xor filter", "morris-counter": "the Morris counter",
             "kepler-10b": "Kepler-10b's period", "landsat-8-orbit": "Landsat 8's orbit", "cmapss-engine-life": "the engine-life baseline"}.get(c["name"], c["name"])
    return page(header, "../../", f"Knos: does {short} hold?", c["plain"], body, script, f"claim/{c['name']}/", css=WALK_CSS)   # a title under 52 characters


def agents_page(header: str) -> str:
    flow = (f'curl -X POST {HOSTED}/api/near/claim/flow -H "Content-Type: application/json" \\\n'
            '  -d \'{"url": "https://doi.org/10.46298/dmtcs.3545", "amount": 10}\'')
    # Round 13 WALK 1: one plain sentence and one control on the screen; the call, its fields and the commands in one
    # closed "How it works" fold, with no product's name
    body = ("<h1>For builders</h1>\n<p>Your program asks Knos whether a paper's claim holds, and gets yes or no with the code "
            "that passed.</p>\n"
            '<p><a class="btn" href="../prove/">See it answer a paper</a></p>\n'
            '<details class="how"><summary>How it works</summary>\n'
            "<p>Each answer comes from a test locked before any work started, run on a public test blockchain with test dollars "
            "held with the job. No real money moves.</p>\n"
            "<p>An answer takes 15 to 80 s when a job is ready and 1 to 2 min when one is not (checks on 14 Nov). Agents get 10 live "
            "checks a day; after those Knos answers with the last verified proof.</p>\n"
            "<p>Your agent sends a paper's link and an amount of test dollars. Knos reads the paper and runs "
            "the agents' code against the claim's locked test.</p>\n"
            "<p>It answers yes or no with the code that passed, to download. Each transfer of test dollars comes with its link on the public record.</p>\n"
            "<p>Reading a claim is free. When the code passes, the jobs contract sends 9 parts of the test dollars to the agent "
            "whose code passed and 1 part to Knos's test account.</p>\n"
            f"<h2>The call</h2>\n<pre>{e(flow)}</pre>\n"
            "<p>The answer holds <code>verdict.holds</code> (true or false), <code>cap.refused</code> (an agent's over-budget step "
            "refused on the blockchain), <code>paid</code>, <code>settled</code>, <code>receipt</code> with each transfer's link, and <code>code</code>: "
            "the verified code to download. A reused proof is marked <code>\"reused\": true</code>. <code>verdict.agent_a</code> says who wrote agent A's code: "
            "a private AI model, or agent A's fixed program when the model's code for that claim failed its locked test.</p>\n"
            "<h2>From a terminal</h2>\n"
            f"<pre>git clone {REPO} &amp;&amp; cd Knos\npython3 near/scripts/knos_prove.py https://doi.org/10.46298/dmtcs.3545 10</pre>\n"
            "<p>It makes the same call and prints the verdict, each payment and its link on the public record.</p>\n"
            "<h2>Read a claim</h2>\n"
            f"<pre>curl -X POST {HOSTED}/api/near/claim/look -H \"Content-Type: application/json\" -d '{{\"url\": \"https://doi.org/10.46298/dmtcs.3545\"}}'\n"
            f"curl {HOSTED}/api/near/claim/counters</pre>\n"
            f'<p>Every address a program can call: <a href="{HOSTED}/openapi.json">the list, as a file for programs</a>.</p>\n</details>')
    return page(header, "../", "Knos for builders", "Your program asks whether a paper's claim holds and gets yes or no with the code that passed.", body, "", "agents/", css=WALK_CSS)


DATA = ROOT / "docs" / "data"


def pricing() -> dict:
    """docs/data/pricing.json (C6): each number with its value, its unit and its source."""
    return json.loads((DATA / "pricing.json").read_text(encoding="utf-8"))


def usage() -> dict:
    """docs/data/usage.json (D3), written by scripts/site_usage.py from the hosted server's /api/usage."""
    return json.loads((DATA / "usage.json").read_text(encoding="utf-8"))


SITE = "https://drexthealpha.github.io/Knos/"


def numbers_page(header: str, which: str) -> str:
    """Round 13 WALK 1: the data file behind the pricing page (which="pricing") or the status page ("usage"), as a page of
    the site: each number of docs/data/<which>.json with its own words, and one control back. The raw file is still
    published beside it (data/<which>.json); a stranger who presses the fold's link gets this page instead."""
    if which == "pricing":
        d = pricing()
        nums = d["numbers"].values()
        rows = "".join(f'<tr><th>{e(v["unit"][:1].upper() + v["unit"][1:])}</th><td class="n">{v["value"]:,}</td></tr>' for v in nums)
        srcs = sorted({v["source"] for v in nums})
        body = (f"<h1>The pricing file</h1>\n<p>Every price on the pricing page is read from this one file. {e(d['money'][:1].upper() + d['money'][1:])}.</p>\n"
                f'<table id="file"><tbody>{rows}</tbody></table>\n'
                + "".join(f"<p>{'Each is' if len(srcs) == 1 else 'One is'} {e(s)}.</p>\n" for s in srcs)
                + '<p><a class="btn" href="../pricing/" data-primary>Back to pricing</a></p>')
        return page(header, "../", "Knos pricing file", "Every price on the Knos pricing page, read from one file.", body, "", "data/pricing.html")
    import site_usage
    u = usage()
    rows = "".join(f'<tr><th>{e(en("status." + k))}</th><td class="n">{int(u["totals"].get(k) or 0):,}</td></tr>' for k, _ in site_usage.COUNTS)
    rows += "".join(f'<tr><th>{e(en("status." + k))}</th><td class="n">'
                    + (e(en("status.too_few")) if u["measures"].get(k) is None else f'{u["measures"][k]:,}') + "</td></tr>" for k, _ in site_usage.MEASURES)
    at = u["read_at"].replace("T", " ")[:16] + " UTC" if u.get("read_at") else ""
    body = ("<h1>The status file</h1>\n<p>Every count on the status page is read from this one file"
            + (f", last read from Knos's server at {e(at)}" if at else "") + ".</p>\n"
            f'<table id="file"><tbody>{rows}</tbody></table>\n<p>Days counted: {len(u.get("days") or []):,}.</p>\n'
            '<p><a class="btn" href="../status/" data-primary>Back to status</a></p>')
    return page(header, "../", "Knos status file", "Every count on the Knos status page, read from one file.", body, "", "data/usage.html")


HOW_CSS = (".how summary { display: inline-flex; align-items: center; min-height: 44px; cursor: pointer; text-decoration: underline; }\n"
           # Round 13 WALK 1: every link of the pricing and status screens a 44 px box at every width, inside the fold too
           # (a link in a sentence keeps its line and grows its box), and no code or table text under 16 px
           "main p a, main dd a, main li a { padding-block: 12px; }\n"
           "main th a, main td a { display: inline-flex; align-items: center; min-height: 44px; }\n"
           "main code, main pre { font-size: 16px; }\n")


def pricing_page(header: str) -> str:
    """Round 13, C6: every number on this page is read from docs/data/pricing.json, each in a span named for it. Plain
    words outside the closed How it works fold (the PLAIN-WORDS rule); prices in dollars, never tokens or credits.
    Round 13, H3: every string is a key of web/i18n/en.json; the page is written in English, and the script of
    tool_page.STATIC_JS shows it in the browser's language (?lang=, the stored choice, navigator.languages); the fold
    opens with the five answers of the Plain Language Spec, section 2."""
    n = {k: v["value"] for k, v in pricing()["numbers"].items()}
    spans = {"free": "free_runs_per_day", "n": "pack_runs", "price": "pack_price"}

    def comp(key: str, v: dict, sp: dict | None = None) -> str:   # a composite string the script can swap: its values ride along
        return f"<!--k:{key} {json.dumps(v)}-->{TP.h('en', key, sp, **v)}<!--/k-->"
    pack = {"n": n["pack_runs"], "price": n["pack_price"]}
    keys = [("a.price.get", {"free": n["free_runs_per_day"], **pack}), ("a.price.next", {}), ("a.price.pay", {"free": n["free_runs_per_day"], **pack}),
            ("a.price.why", {"url": TP.PRICING_FILE, "test": TP.TEST_URL}), ("a.price.who", {"issues": TP.ISSUES})]
    answers = [f"<!--k:{k} {json.dumps(v)}-->{a}<!--/k-->" for (k, v), a in zip(keys, TP.price_answers("en", n))]
    body = (f"<div class=\"first\"><h1>{e(en('price.h'))}</h1>\n"
            f'<table id="prices"><tbody><tr><th>{e(en("price.sample"))}</th><td>{e(en("price.free"))}</td></tr>'
            f'<tr><th>{e(en("price.own"))}</th><td>{comp("price.free_day", {"n": n["free_runs_per_day"]}, {"n": "free_runs_per_day"})}</td></tr>'
            f'<tr><th>{e(en("price.after"))}</th><td>{comp("pay.headline", pack, spans)}</td></tr></tbody></table>\n'
            f"{try_link('../')}\n<p>{e(en('pay.line'))}</p></div>\n"
            f'<details class="how"><summary>{e(en("how"))}</summary>'
            + TP.five("en", answers)
            + f'<p>{comp("price.f1", {"url": "../data/pricing.html"})}</p>'
            f"<p>{e(en('price.f2'))}</p>"
            f'<p>{comp("price.f3", {"url": REPO + "/blob/main/docs/PRICING.md"})}</p><p data-mt hidden></p></details>')
    # Round 13 WALK 1: the pricing file opens as a page of the site (numbers_page), not as the raw file
    body = body.replace(TP.PRICING_FILE, SITE + "data/pricing.html")
    out = page(header, "../", en("price.title"), "Sample runs are free; runs on your own file have a free daily allowance, then a pack in test money.", body,
               TP.static_runtime("../i18n/"), "pricing/", FOOT("../") if FOOT else "")
    return out.replace("</style>", HOW_CSS + TP.SWITCH_CSS + "\n" + SCREEN_PAGE_CSS + "</style>", 1)


FOOT = None   # the foot of the three screens (scripts/site_pages.py foot), set by it before it writes these pages
PLAY = ('<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="currentColor" data-no-mirror>'
        '<path d="M8 5v14l11-7z"/></svg>')


def try_link(up: str) -> str:
    """The main action of the pricing and status pages: the tool's box holding the sample, and Try it, with its words and an
    icon (U2 Rule 16, U7 R26), the one primary control (U3 Rule 5), among the first two controls (U3 Rule 10). Every Knos
    screen has its main input on the first screen (U4 Rules 6 and 7): the box is the front door's, a plain form that the
    server runs and answers with the result page, so it works with no script too; with a script the table goes to the
    front door's tool (`up`), as the link did (scripts/site_pages.py THEME_JS)."""
    text = sample()
    conf = (ROOT / "apps" / "wanted" / "knos_wanted" / "runner_conf.py").read_text(encoding="utf-8")
    label = en("tool.sample_made_up" if "'sample_made_up': False" not in conf else "tool.sample_nasa")
    return (f'<form class="trybox" id="trybox" method="post" action="https://knos.onrender.com/t/limit-check/run" data-to="{up}#tool">'
            '<input type="hidden" name="column" value="capacity_ah" dir="auto"><input type="hidden" name="rule" value="above" dir="auto">'
            '<input type="hidden" name="limit" value="1.4" dir="auto">'
            f'<button class="btn go" id="try" type="submit" data-primary data-main-action>{PLAY}{e(en("tool.try"))}</button>'
            f'<label for="list">{e(label)}</label>'
            f'<textarea id="list" name="table" rows="2" dir="auto" wrap="off" spellcheck="false" autocomplete="off">{e(text)}</textarea></form>')


# the pricing and status pages as screens (Round 13 FIX-SITE): text 18 px (U2 Rule 11), the main action wide and in the middle
# of the first screen (U3 Rule 8, U5 R9), the foot below the first screen (U3 R3: that screen holds the page's own words only),
# tables without ruled cells (a ruled cell is a box of its own: U3 R3's six blocks)
SCREEN_PAGE_CSS = """body { font-size: 18px; overflow-wrap: anywhere; }
.first { min-height: calc(100vh - 48px); min-height: calc(100svh - 48px); }
.trybox { display: flex; flex-direction: column; }
.trybox label { order: 1; font-weight: 600; margin: 4px 0; font-size: 18px; }
.trybox textarea { order: 2; display: block; width: 100%; box-sizing: border-box; font: 18px/1.4 ui-monospace, Consolas, monospace;
  padding: 8px 10px; border: 2px solid var(--ink-2); border-radius: 8px; background: var(--paper); color: var(--ink); resize: vertical; white-space: pre; overflow: auto; height: 3em; }
.trybox .btn.go { order: 3; border: 2px solid transparent; font: inherit; font-weight: 600; cursor: pointer; }
main { min-height: calc(100vh - 64px); min-height: calc(100svh - 64px); box-sizing: border-box; }
main code { font-family: ui-monospace, Consolas, monospace; }
main th, main td { border-bottom: 0; padding-block: 8px; padding-inline: 0 8px; }
main .fine, main p, main dd, main dt, main summary { font-size: 18px; }
.btn.go { display: flex; justify-content: center; gap: 8px; width: 100%; box-sizing: border-box; min-height: 52px; margin: 8px 0 16px; }
.btn.go svg { flex: none; }
main .btn:focus-visible, main summary:focus-visible, main a:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
@media (max-width: 460px) { main p, main .fine, main summary, main dd, main dt { font-size: 18px; } }
"""


def status_page(header: str) -> str:
    """Round 13, D3: each use count with its label, from docs/data/usage.json, written into the page at build time (a 0
    is shown as 0; a measure with too few browsers says so). The live service lines sit in the closed How it works fold:
    they name the test network and the server's parts (the PLAIN-WORDS rule)."""
    import site_usage
    u = usage()
    # Round 13 FIX-SITE: a screen of its own words (U3 R3: at most 40 words on the first screen): the counts, the main
    # action, when they were read; the three measures (still "not enough browsers yet") and the live lines in the fold.
    # Every label is a key of web/i18n/en.json, shown in the browser's language; the live lines stay English, marked so.
    # each label is its key of web/i18n/en.json (status.<name>), the words the script shows in every language
    rows = "".join(f'<tr><th>{e(en("status." + k))}</th><td class="n" data-count="{k}">{int(u["totals"].get(k) or 0):,}</td></tr>' for k, _ in site_usage.COUNTS)
    meas = "".join(f'<tr><th>{e(en("status." + k))}</th><td class="n" data-measure="{k}">'
                   + (e(en("status.too_few")) if u["measures"].get(k) is None else f'{u["measures"][k]:,}') + "</td></tr>" for k, _ in site_usage.MEASURES)
    # the time keeps its own left-to-right order inside a right-to-left sentence (U7 R2): a left-to-right isolate around it
    at = "\u2066" + u["read_at"].replace("T", " ")[:16] + " UTC\u2069" if u.get("read_at") else ""
    when = f'<!--k:status.when {json.dumps({"at": at})}-->{TP.h("en", "status.when", at=at)}<!--/k-->' if at else e(en("status.none"))
    body = (f"<div class=\"first\"><h1>{e(en('nav.status'))}</h1>\n"
            f'<table id="use"><tbody>{rows}</tbody></table>\n{try_link("../")}\n<p class="fine" id="use-when">{when}</p></div>\n'
            f'<details class="how"><summary>{e(en("how"))}</summary>\n'
            # Round 13 WALK 1: the raw file opens as a page of the site (numbers_page); the live lines name no other
            # company's product (the WALK counts names inside the fold too)
            f'<table id="meas"><tbody>{meas}</tbody></table>\n<p><a href="../data/usage.html">{e(en("status.file"))}</a></p><p data-mt hidden></p>\n'
            '<div lang="en" dir="ltr">\n'
            "<p>Is Knos up right now? Each line is read live.</p>\n<table id=\"st\"><tbody>"
            "<tr><th>The proof service</th><td id=\"svc\">reading</td></tr>"
            "<tr><th>Live proofs today</th><td id=\"today\">reading</td></tr>"
            "<tr><th>Jobs paid to agents</th><td id=\"jobs\">reading</td></tr>"
            "<tr><th>The test network's record</th><td id=\"rec\">reading</td></tr>"
            "<tr><th>Latest full test run</th><td id=\"ci\">reading</td></tr>"
            "<tr><th>Uptime</th><td id=\"up\">reading</td></tr>"
            "<tr><th>Visits, 7 days</th><td id=\"funnel\">reading</td></tr>"
            "</tbody></table>\n<h2>Accounts that keep the demo up</h2>\n<table id=\"bal\"><tbody><tr><td>reading</td></tr></tbody></table>\n"
            "<p class=\"fine\">Each line is read now, from Knos's server, the test network and Knos's public code record.</p>\n"
            "<p class=\"fine\">The jobs count adds up each agent's passes in the jobs "
            "contract's <code>get_agent_record</code>; the money paid out is its <code>get_totals</code>.</p></div></details>")
    script = LIVE_JS + """// R13 WALK 2: the counts come from the published data file when the page loads (the file is refreshed between
// builds); the copy written in at build time stays when the file cannot be read. "Counted to" is the time of
// whichever copy is shown.
fetch("../data/usage.json", { cache: "no-store" }).then((r) => r.ok ? r.json() : null).then((u) => {
  if (!u || !u.totals || !u.read_at) return;
  const n = (x) => Number(x).toLocaleString("en-US");
  document.querySelectorAll("[data-count]").forEach((td) => { const v = u.totals[td.dataset.count]; if (Number.isInteger(v) && v >= 0) td.textContent = n(v); });
  document.querySelectorAll("[data-measure]").forEach((td) => { const v = (u.measures || {})[td.dataset.measure]; td.textContent = v == null ? KI.t("status.too_few") : n(v); });
  const at = "\\u2066" + String(u.read_at).replace("T", " ").slice(0, 16) + " UTC\\u2069", v = { at };
  $("use-when").innerHTML = "<!--k:status.when " + JSON.stringify(v) + "-->" + KI.html("status.when", v) + "<!--/k-->";
}).catch(() => { /* the build's copy stays */ });
(async () => {
  const [l, c, t] = await Promise.all([getJSON("/api/near/live"), getJSON("/api/near/claim/counters"), getJSON("/api/near/tests")]);
  $("svc").textContent = l ? (l.live ? "up, on the test network" : "up, live runs switched off") : "not answering";
  $("today").textContent = l ? `${l.used_today} of ${l.cap_today} on the page, ${l.agent_used_today ?? 0} of ${l.agent_cap_today ?? 0} for agents` : "not read";
  $("rec").textContent = c && c.read_at ? `${c.proofs} transfers into Knos's fee account, many just Knos paying itself; ${usd(c.lost_usd)} lost; read ${c.read_at.replace("T", " ").replace("Z", " UTC")}` : "not read";
  jobsPaid().then((j) => { $("jobs").textContent = j ? `${j.jobs} since the jobs contract's 14 Nov upgrade; ${usd(j.usd)} paid out by it for jobs opened since then, the agent's 9 parts and Knos's 1 part together` : "not read"; });
  $("ci").innerHTML = t && t.url ? `${t.passed ? "passed" : "failed"}, <a href="${t.url}">commit ${String(t.sha || "").slice(0, 8)}</a>` : "not read";
  // checks every 30 minutes by ledger.yml, kept on the gh-pages branch, so a restart cannot reset them
  fetch("https://raw.githubusercontent.com/drexthealpha/Knos/gh-pages/uptime.jsonl", { cache: "no-store" }).then((r) => r.ok ? r.text() : "").then((txt) => {
    const since = Date.now() - 7 * 864e5, rows = txt.split(/\\r?\\n/).filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter((x) => x && Date.parse(x.at) >= since);
    $("up").textContent = rows.length ? `up ${rows.filter((x) => x.up).length} of ${rows.length} checks in the last 7 days, from ${rows[0].at.slice(0, 16).replace("T", " ")} UTC` : "no checks yet";
  }).catch(() => { $("up").textContent = "not read"; });
  getJSON("/api/visits").then((v) => { const f = v && v.funnel;
    $("funnel").textContent = f ? `${f.visits} visits, ${f.first_press} pressed, ${f.first_result} got an answer, ${f.proof_finished} ran a proof, ${f.backed} backed, ${f.came_back} came back` + (v.results_counted_from ? ` (answers, proofs and backings counted from ${v.results_counted_from})` : "") + (v.leave_most ? `; most leave from ${v.leave_most}` : "") : "not read"; });
  const b = await getJSON("/api/near/balances"), unit = { near: "test coins for fees", allowance: "test coins of fee allowance", usdc: "test dollars" };
  const tb = document.querySelector("#bal tbody");
  if (!b || !b.rows) { tb.innerHTML = "<tr><td>not read</td></tr>"; return; }
  tb.replaceChildren(...b.rows.map((x) => { const tr = document.createElement("tr");
    const a = Object.assign(document.createElement("a"), { href: "https://testnet.nearblocks.io/address/" + x.account, textContent: String(x.what).replace(/^Buyer, fees$/, "Knos's own test account, coins for fees").replace(/^Buyer, /, "Knos's own test account, ").replace(/\\bNEAR\\b/g, "coins").replace(/\\btest USDC\\b/g, "test dollars") });
    const th = document.createElement("th"); th.append(a);
    const td = Object.assign(document.createElement("td"), { textContent: `${x.value == null ? "not read" : x.value} ${unit[x.kind]}, floor ${x.floor}${x.ok ? "" : ": LOW"}` });
    if (!x.ok) { td.style.color = "#c62828"; td.style.fontWeight = "600"; tr.style.borderBottom = "2px solid #c62828"; }
    tr.append(th, td); return tr; }));
})();"""
    return page(header, "../", en("status.title"), "How the tool is used, each count from the data file, zeros shown as 0.", body,
                TP.static_runtime("../i18n/") + "\n" + script, "status/", FOOT("../") if FOOT else "").replace(
        "</style>", HOW_CSS + TP.SWITCH_CSS + "\n" + SCREEN_PAGE_CSS + "</style>", 1)


def privacy_page(header: str) -> str:
    """Each thing the site and the server do with what a visitor sends, one short line each (12 words at most)."""
    site = ["No cookies, and no outside tracker.",
            "The Prove page loads one script library, GSAP, from cdnjs.",
            "Your browser checks that file's integrity; it sends nothing of yours.",
            "Each page sends Knos small events of an anonymous visit.",
            "The visit id is random, made by your browser, reset daily.",
            "Events name the page, each press and how long it took.",
            "They say whether you got an answer or ran a proof.",
            "They say whether you backed a claim or downloaded code.",
            "Also three quick presses on one spot, and any error shown.",
            'A tap on "Not what I need", and any word you add.',
            "Also the last page, and its seconds before you leave.",
            "No IP address, account or cookie is stored with them.",
            "Do Not Track in your browser stops every event.",
            "The status page shows the totals.",
            "What you type goes to the Knos server, which answers.",
            "The server reads a paper's title from its public record, Crossref.",
            "Your browser also reads NEAR testnet's public record.",
            "The tool sends your file to the Knos server.",
            "The server keeps your file with its result page and link.",
            "Your own file is shown only to people with its link.",
            "Say yes to counting, and your browser keeps a random id.",
            "With that yes, pages also send how fast they drew.",
            "And whether your first table was the sample or your own.",
            "Without that yes, the server counts runs only as totals."]
    if usdc_market().get("live"):
        site += ["On a claim page, a NEAR sign-in library loads from esm.sh.",
                 "Your NEAR testnet account signs each trade; Knos never sees your key."]
    server = ["No account and no sign-in.", "It counts requests per address, only to limit them.",
              "Every proof and payment is public on NEAR testnet."]
    terms = ["Test money on NEAR testnet, worth nothing.", f'The code is MIT licensed: <a href="{REPO}/blob/main/LICENSE">read the licence</a>.',
             "It comes with no warranty, as the licence says.", f'Report a problem in <a href="{REPO}/issues">GitHub issues</a>.']

    def ul(lines: list[str]) -> str:
        return "<ul>\n" + "".join(f"<li>{t}</li>\n" for t in lines) + "</ul>"
    body = (f"<h1>Privacy and terms</h1>\n<h2>This site</h2>\n{ul(site)}\n<h2>The server</h2>\n{ul(server)}\n"
            f"<h2>Terms</h2>\n{ul(terms)}")
    return page(header, "", "Knos privacy and terms", "No cookies; an anonymous daily visit id and no IP stored; test money on NEAR testnet.", body, "", "privacy.html")


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
    put("pricing/index.html", pricing_page(header("../", "", True, True)))
    put("status/index.html", status_page(header("../", "", True, True)))
    put("data/pricing.html", numbers_page(header("../", ""), "pricing"))   # the two files behind them, as pages (R13 WALK 1)
    put("data/usage.html", numbers_page(header("../", ""), "usage"))
    put("privacy.html", privacy_page(header("", "")))
    (out / "sitemap.xml").write_text(sitemap_xml(cs), encoding="utf-8")
    (out / "llms.txt").write_text(llms_txt(cs), encoding="utf-8")
    return done


def sitemap_xml(cs: list[dict]) -> str:
    """The published sitemap. web/sitemap.xml is this same text (python3 scripts/site_product.py --sources)."""
    base = "https://drexthealpha.github.io/Knos/"
    # each page with the source file it is made from: scripts/sitemap_dates.py writes that file's last commit date
    pages = [("", "web/door.html"), ("claims/", "near/claims/claims.json"), *[(f"claim/{c['name']}/", "near/claims/claims.json") for c in cs],
             ("prove/", "near/web/index.html"), ("agents/", "scripts/site_product.py"), ("labs/", "web/iris/index.html"),
             ("pricing/", "scripts/site_product.py"), ("status/", "scripts/site_product.py"), ("privacy.html", "scripts/site_product.py"),
             ("check/", "web/check-v0328/index.html")]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"  <url><loc>{base}{p}</loc><lastmod>git:{src}</lastmod></url>\n" for p, src in pages) + "</urlset>\n")


SAMPLE_URL = "https://raw.githubusercontent.com/drexthealpha/Knos/main/near/agents/job/data/limit/sample.csv"


def sample() -> str:
    """The first tool's sample file: the text the front door's box (web/door.html, #list) is filled with at build time."""
    return (ROOT / "near" / "agents" / "job" / "data" / "limit" / "sample.csv").read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n")


def sample_result() -> str:
    """The sample's result sentence as the locked test fixes it (near/agents/job/test_limit2.py, the sample case): the
    first row whose capacity_ah is at or below 1.4, found the way its separate script finds it (limit_check10.py), and
    the rows passed, failed and unmeasurable."""
    import csv
    import io
    import math
    rows = list(csv.DictReader(io.StringIO(sample())))
    r, row = next((n, x) for n, x in enumerate(rows, 1) if float(x["capacity_ah"]) <= 1.4)
    vals = [float(x["capacity_ah"]) for x in rows]
    p, u = sum(math.isfinite(v) and v > 1.4 for v in vals), sum(not math.isfinite(v) for v in vals)
    return (f"Failed at row {r}: {row['capacity_ah']} is not above 1.4. "
            f"Rows: {p} passed, {len(vals) - p - u} failed, {u} unmeasurable.")


def where_you_are() -> str:
    """B6: the section README.md and llms.txt both carry: the one command that adds the connector, and one worked
    example with the sample and its result. README.md holds this same text (tests/test_site_tool.py)."""
    body = '{id: "limit-check", table: ., column: "capacity_ah", rule: "above", limit: 1.4}'
    return ("## Use Knos where you already are\n\n"
            "Add Knos to a chat or coding assistant that takes connectors, with one command:\n\n"
            f"```\nclaude mcp add --transport http knos {HOSTED}/mcp\n```\n\n"
            "It gives two tools: `tools` lists what Knos can do, and `run` runs one. A worked example, the front door's sample "
            "battery test checked against its limit without the connector:\n\n"
            f"```\ncurl -s {SAMPLE_URL} | jq -Rs '{body}' | curl -s -X POST {HOSTED}/api/run -H \"Content-Type: application/json\" -d @-\n```\n\n"
            f"The answer's `result` is `{sample_result()}` Its `link` opens the result. Through the connector, `run` with the "
            "same `id`, `table`, `column`, `rule` and `limit` returns the same answer.\n")


def llms_txt(cs: list[dict]) -> str:
    """The site's llms.txt (https://llmstxt.org/). web/llms.txt is this same text (python3 scripts/site_product.py --sources)."""
    base = "https://drexthealpha.github.io/Knos/"
    claims_md = "".join(f"- [{c['plain']}]({base}claim/{c['name']}/): from {c['authors']}, {c['year']}; locked test sha256 {c['sha256']}\n" for c in cs)
    call = '{"url": "https://doi.org/10.46298/dmtcs.3545", "amount": 10}'
    door = (ROOT / "web" / "door.html").read_text(encoding="utf-8")
    desc = html.unescape(re.search(r'<meta name="description" content="([^"]*)"', door)[1])   # the front door's own line opens it
    return (
        f"# Knos\n\n> {desc}\n\n"
        "Knos locks a test before any work starts, and test money moves to the agent that did the work only if that test passes. Here the "
        "work is code that proves a paper's claim, against a test locked on NEAR testnet. The result is kept on NEAR, so a "
        "second check is free. Test money only and no customers yet.\n\n"
        f"## Pages\n\n- [Front door]({base}): check a test file against a limit; below it, ask about research\n"
        f"- [Claims]({base}claims/): every claim, sorted by the test USDC behind it\n"
        f"- [Prove]({base}prove/): run the check of a claim and get the verdict, the verified code and the receipt\n"
        f"- [For agents]({base}agents/): the one-call API and the terminal tool\n"
        f"- [For labs]({base}labs/): the same check inside InterSystems IRIS\n"
        f"- [Check pull requests]({base}check/): the pull request check, the same Knos built earlier on Solana devnet (Colosseum, tag v0.3.28)\n\n"
        f"## Claims\n\n{claims_md}\n"
        f"## For agents\n\n`POST {HOSTED}/api/near/claim/flow` with `{call}`: the verdict, the code and the receipt.\n\n"
        + where_you_are() + "\n"
        f"## Optional\n\n- [Source]({REPO}): the repository, MIT licence\n")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--sources"]:
        # the sources of web/ that the build overwrites with these pages: kept the same text as the published files
        import site_pages
        HEADER_CSS = site_pages.CSS
        (ROOT / "web" / "llms.txt").write_text(llms_txt(claims()), encoding="utf-8", newline="")
        (ROOT / "web" / "sitemap.xml").write_text(sitemap_xml(claims()), encoding="utf-8", newline="")
        (ROOT / "web" / "privacy.html").write_text(privacy_page(site_pages.header("", "")), encoding="utf-8", newline="")
        FOOT = site_pages.foot
        (ROOT / "web" / "status" / "index.html").write_text(site_pages.screen(status_page(site_pages.header("../", "", True, True)), "../"), encoding="utf-8", newline="")
