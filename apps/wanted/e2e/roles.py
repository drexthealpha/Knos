"""Evidence run: every role of Knos on a phone, from the front door, with video and screenshots, end to end.

    python apps/wanted/e2e/roles.py https://knos.onrender.com --front-door https://drexthealpha.github.io/Knos/ \
        --out evidence-run/ --evidence-gist [--topup-cmd CMD] [--faucet-wait MIN] [--note TEXT]
    (needs: pip install playwright; playwright install chromium)

ONE run on ONE phone viewport, and it ends with one line: `PASS: all six roles ...` or `FAIL: <role> ...` (exit 0/1).

Each role runs in its own browser context on a 375x812 phone viewport (touch, mobile) with a video recording, and a
virtual WebAuthn authenticator added over the Chrome DevTools Protocol (WebAuthn.addVirtualAuthenticator: ctap2,
internal, resident keys, user verification), so passkeys are really created and used by the app's own code: the
sign-in (the only one: Google, ORCID and email are shown as not available yet) and every payment (LazorKit smart
wallet, secp256r1 precompile) through static/passkey_wallet.js. Nobody makes an account anywhere.

Every person starts at the front door (the research products open for backing now) and taps ONE action of a product:
  researcher   "Cross your own paper": crosses a paper with a product idea (live Qloo on the server): OPEN or not
  maker        "Back it" on a product whose maker is wanted, then claims its milestone with a passkey (its receivable
               is paid to a wallet its passkey owns)
  buyer        "Back it" on the same product: devnet test units, then pre-orders the reserve with its OWN passkey wallet
  funder       "Fund a milestone" on it: funds the product's first project milestone from its passkey wallet (its own
               vault); then, as the lender, advances the maker cash in TWO taps: "Offer cash now" (the maker's passkey
               sells the receivable: TransferOwnership) and "Send the advance"; after the release, "Collect"
  maker        publishes its result (a secret gist, static bytes) and posts it: the FROST referee group (2 of 3 hosts
               re-check the page and sign) releases the order to the receivable wallet the lender now owns
  contributor  "Contribute": attempts a project milestone (paid to its passkey wallet), then submits work to the open
               knos.game round; a scored attempt's prize is released by the same FROST referee group
  agent        talks JSON-RPC to <base>/mcp
Writes <out>/<role>.png (+ <role>-<step>.png), <out>/<role>.webm and <out>/summary.json (PASS/FAIL per role, what was
seen, every devnet signature). Money: Solana devnet test units only.

--evidence-gist / --evidence-dir + --evidence-url / --evidence-url-template: the maker's public result page.
--topup-cmd: a command run as `CMD <vault> <units>` when a passkey wallet needs more devnet test units than the
faucet's per-hour limit gives (the operator of the test mint tops it up; labelled in the summary). Without it the run
waits out the faucet's limit for up to --faucet-wait minutes.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

PHONE = {"viewport": {"width": 375, "height": 812}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True,
         "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"}
DOI = "10.1038/nature16521"
PRODUCT = "a fitness watch with a sweat glucose sensor"
FRONT_DOOR = "https://drexthealpha.github.io/Knos/"
ROLES = ("researcher", "maker", "buyer", "funder", "contributor", "agent")
TRAIN = Path(__file__).resolve().parents[3] / "examples" / "autoresearch" / "train.py"
SIG = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{80,90}$")


class Run:
    def __init__(self, browser, base: str, out: Path, args):
        self.base, self.out, self.args = base, out, args
        self.summary = {"base": base, "front_door": args.front_door, "viewport": "375x812 phone",
                        "webauthn": "CDP WebAuthn.addVirtualAuthenticator (ctap2, internal)", "note": args.note, "roles": {},
                        "signatures": {}, "topups": [], "taps": {}, "lender_taps": []}
        self.browser, self.ctx, self.auth, self.closed = browser, {}, {}, set()
        self.page = _Pages(self._open)                    # a role's phone opens when the role first acts, and closes after its
        for role in ROLES:                                # last step (one video per role; fewer recorders at once)
            self.summary["roles"][role] = {"result": "PASS", "seen": [], "error": None, "screenshots": []}

    def _open(self, role):
        vid = self.out / f"_video_{role}"
        c = self.browser.new_context(**PHONE, record_video_dir=str(vid), record_video_size={"width": 375, "height": 812},
                                     extra_http_headers=dict(h.split(":", 1) for h in self.args.header))
        c.set_default_navigation_timeout(120_000)
        c.set_default_timeout(90_000)
        p = c.new_page()
        # the person presses Approve on each approval card (static/passkey_wallet.js) as it appears; the passkey then signs
        # (the document itself is observed: an init script runs before documentElement exists, so observing it threw)
        p.add_init_script("new MutationObserver(() => { const b = document.getElementById('pk-approve'); if (b) b.click(); })"
                          ".observe(document, { childList: true, subtree: true });")
        cdp = c.new_cdp_session(p)
        cdp.send("WebAuthn.enable")
        got = cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {"protocol": "ctap2", "transport": "internal", "hasResidentKey": True,
                                                                        "hasUserVerification": True, "isUserVerified": True,
                                                                        "automaticPresenceSimulation": True}})
        self.ctx[role], self.auth[role] = c, {"cdp": cdp, "id": got["authenticatorId"]}
        return p

    # -- helpers -------------------------------------------------------------------------------------------------
    def see(self, role, text):
        self.summary["roles"][role]["seen"].append(text)
        print(f"[{time.strftime('%H:%M:%S')}] {role}: {text[:220]}", flush=True)

    def shot(self, role, step):
        """A screenshot is evidence, never the step itself: the whole page, else the screen, else said so."""
        f = f"{role}-{step}.png"
        for full in (True, False):
            try:
                self.page[role].screenshot(path=str(self.out / f), full_page=full, timeout=60_000)
                self.summary["roles"][role]["screenshots"].append(f)
                return
            except Exception:  # noqa: BLE001 - a loaded machine may not draw a long page in time
                continue
        self.summary["roles"][role]["seen"].append(f"screenshot {f} could not be taken")

    def sigs(self, key, got):
        found = {k: v for k, v in _flat(got).items() if isinstance(v, str) and SIG.match(v)}
        if found:
            self.summary["signatures"][key] = found
        return found

    def api(self, role, path, body=None):
        """The app's own api() in the role's page (its session token)."""
        return self.page[role].evaluate("([p, b]) => api(p, b === null ? undefined : b)", [path, body])

    def creds(self, role) -> int:
        a = self.auth[role]
        return len(a["cdp"].send("WebAuthn.getCredentials", {"authenticatorId": a["id"]}).get("credentials", []))

    def door(self, role, action, slug=None):
        """Open the front door and tap ONE action of one product (the card of `slug`, else the first card); the app
        opens at that action. Returns the slug tapped."""
        p = self.page[role]
        p.goto(self.args.front_door, wait_until="domcontentloaded")
        p.wait_for_selector("#home-products li.hp", timeout=60_000)
        p.mouse.move(30, 300)                                     # a reader's first move: the live list is asked for
        p.wait_for_timeout(4000)                                  # and redraws the snapshot in place when the app answers
        cards = p.evaluate("() => [...document.querySelectorAll('#home-products li.hp')].map((li) => ({slug: li.dataset.slug, "
                           "wanted: /maker wanted/.test(li.querySelector('.hp-src').textContent)}))")
        live = p.evaluate("() => document.getElementById('home-products').dataset.live === '1'")
        self.shot(role, "front-door")
        if action == "research":
            sel = "#home-research"
        else:
            slug = slug or cards[0]["slug"]
            sel = f"#home-products li.hp[data-slug='{slug}'] a[data-app^='#{action}=']"
        p.locator(sel).first.click(no_wait_after=True)            # the page itself decides where the tap goes (awake: the app)
        p.wait_for_url(re.compile(re.escape(self.base) + "|wanted\\.html"), timeout=120_000)
        if "wanted.html" in p.url:                                # the wake page forwards once the app answers
            p.wait_for_url(re.compile(re.escape(self.base)), timeout=240_000)
        p.wait_for_function("() => typeof api === 'function'", timeout=60_000)
        self.summary["taps"].setdefault(role, []).append({"action": action, "slug": slug, "taps_to_app": 1, "landed": p.url, "live_list": live, "cards": cards})
        self.see(role, f"front door ({'live list' if live else 'snapshot'}): one tap on '{action}'{' of ' + slug if slug else ''} -> {p.url}")
        return slug

    def sign_in(self, role, view=None):
        """A passkey made and used on the virtual authenticator: the one sign-in. `view` None: where the page is."""
        p = self.page[role]
        if view is not None:
            p.goto(self.base + "/app/#" + view, wait_until="domcontentloaded")
        p.wait_for_function("() => typeof api === 'function'", timeout=30_000)
        p.click("#whoBtn")
        dead = p.evaluate("() => [...document.querySelectorAll('#signin button')].filter((b) => b.disabled && b.offsetParent !== null).length")
        if dead:
            raise RuntimeError(f"the sign-in sheet shows {dead} switched-off button(s): it shows only what works")
        p.fill("#pkName", f"Playwright {role}")
        p.click("#pkNew")
        p.wait_for_function("() => { try { return !!JSON.parse(localStorage.getItem('knos.session')||'null'); } catch (e) { return false; } }", timeout=60_000)
        p.wait_for_timeout(800)
        self.see(role, f"passkey created and used to sign in ({self.creds(role)} credential on the virtual authenticator); "
                       "Google, ORCID and email shown as not available yet")

    def click_until(self, role, selector, done_js, what, timeout=240, retry_on=("too many requests", "again", "try again", "transaction failed", "blockhash", "could not finish this step", "answered http 5", "could not be read")):
        """Click, wait for done_js; on a rate limit (shared tunnel address) or a transient error, wait and click again."""
        p, end = self.page[role], time.time() + timeout
        said = "() => [document.getElementById('err'), ...document.querySelectorAll('.note.err')].filter((e) => e && !e.hidden).map((e) => e.innerText).join(' | ')"
        busy = "() => { const s = document.getElementById('slow'); return !!s && !s.hidden; }"
        while True:
            p.locator(selector).first.click()
            try:
                p.wait_for_function(done_js, timeout=90_000)
                return
            except Exception:  # noqa: BLE001
                while time.time() < end and p.evaluate(busy) and not p.evaluate(said):     # still working (devnet, a loaded machine)
                    try:
                        p.wait_for_function(done_js, timeout=30_000)
                        return
                    except Exception:  # noqa: BLE001
                        continue
                text = (p.evaluate(said) or p.inner_text("body")[-2000:]).lower()
                if time.time() > end or not any(r in text for r in retry_on):
                    raise RuntimeError(f"{what}: no result ({_err_line(text)})") from None
                self.see(role, f"{what}: server said '{_err_line(text)}': waiting 60 s and trying again")
                p.wait_for_timeout(60_000)
                p.reload(wait_until="domcontentloaded")
                p.wait_for_function("() => typeof api === 'function'", timeout=30_000)
                p.wait_for_timeout(2500)

    def topup(self, role, vault, units):
        if not self.args.topup_cmd:
            return
        cmd = shlex.split(self.args.topup_cmd) + [vault, str(units)]
        got = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        line = (got.stdout.strip().splitlines() or [""])[-1]
        self.summary["topups"].append({"role": role, "vault": vault, "units": units, "result": line[:200],
                                       "label": "operator top-up of devnet test units (the test mint's authority), beyond the faucet's hourly limit"})
        self.see(role, f"operator top-up of {units} devnet test units to {vault[:8]}…: {line[:120]}")

    def fund(self, role, need):
        """Bring the role's passkey wallet to `need` test units: the operator's top-up when one is configured, else the
        app's own faucet (25 units a press, twice an hour per address), waiting out its limit up to --faucet-wait min."""
        w = self.api(role, "/api/wallet", {})
        if w["balance_units"] >= need:
            return w
        if self.args.topup_cmd:
            self.topup(role, w["vault"], int(need - w["balance_units"]) + 1)
            return self.api(role, "/api/wallet", {})
        end = time.time() + 60 * self.args.faucet_wait
        while w["balance_units"] < need:
            try:
                got = self.api(role, "/api/wallet/faucet", {})
                self.sigs(f"{role} faucet {time.strftime('%H:%M:%S')}", {"faucet": got.get("signature")})
                self.see(role, f"faucet: +{got.get('units')} devnet test units ({str(got.get('signature'))[:16]}…)")
            except Exception as why:  # noqa: BLE001 - the faucet's hourly limit: wait for the window to move
                if time.time() > end or "too many" not in str(why).lower():
                    raise RuntimeError(f"the faucet: {why}") from None
                self.see(role, f"faucet limit reached ({str(why)[:80]}): waiting 5 minutes")
                self.page[role].wait_for_timeout(300_000)
                continue
            self.page[role].wait_for_timeout(3000)
            w = self.api(role, "/api/wallet", {})
        return w

    def hook(self, name):
        cmd = getattr(self.args, name)
        if cmd:
            got = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            self.summary.setdefault("hooks", []).append({"hook": name, "cmd": cmd, "exit": got.returncode, "out": got.stdout[-300:]})
            print(f"hook {name}: exit {got.returncode} {got.stdout[-200:]}", flush=True)

    def commitment(self, role, order):
        return self.api(role, "/api/commitment?id=" + order)

    def wait_status(self, role, order, want, timeout=600):
        end = time.time() + timeout
        while time.time() < end:
            c = self.commitment(role, order)
            st = (c.get("factoring") or {}).get("status") if want in ("assigned", "advanced", "repaid") else c.get("status")
            if st == want:
                return c
            self.page[role].wait_for_timeout(5000)
        raise RuntimeError(f"commitment {order[:8]}: not {want} after {timeout} s")

    def close(self, role):
        """The role's last screenshot, its phone closed, its video kept."""
        if role in self.closed or role not in self.ctx:
            return
        self.closed.add(role)
        try:
            self.page[role].screenshot(path=str(self.out / f"{role}.png"), full_page=True)
        except Exception:  # noqa: BLE001
            pass
        vid = self.out / f"_video_{role}"
        self.ctx[role].close()
        v = next(vid.glob("*.webm"), None)
        if v:
            shutil.move(str(v), self.out / f"{role}.webm")
        shutil.rmtree(vid, ignore_errors=True)
        r = self.summary["roles"][role]
        r["screenshot"], r["video"] = f"{role}.png", f"{role}.webm"

    def finish(self):
        for role in ROLES:
            self.close(role)


class _Pages(dict):
    """role -> its page, opened on first use."""
    def __init__(self, opener):
        super().__init__()
        self.opener = opener

    def __missing__(self, role):
        p = self[role] = self.opener(role)
        return p


def _flat(d, pre=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flat(v, f"{pre}{k}.") if isinstance(v, (dict, list)) else {f"{pre}{k}": v})
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out.update(_flat(v, f"{pre}{i}.") if isinstance(v, (dict, list)) else {f"{pre}{i}": v})
    return out


def _err_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return (lines[-1] if lines else "")[:160]


# -- the story ----------------------------------------------------------------------------------------------------------
def researcher(r: Run, st: dict):
    p = r.page["researcher"]
    r.door("researcher", "research")
    p.wait_for_selector("#crossForm", state="visible", timeout=30_000)
    p.fill("#ref", r.args.doi)
    p.fill("#product", r.args.product)
    if r.args.place:
        p.fill("#place", r.args.place)
    p.click("#crossBtn")
    p.wait_for_selector("#outcome .decision", timeout=600_000)
    rep = p.evaluate("report")
    d = rep.get("decision") or {}
    st["researcher_report"] = rep["hash"]
    r.see("researcher", f"crossing decided {d.get('verdict')} ({rep.get('label', '')[:40]}): target {d.get('target_units')}, "
                        f"reserve {d.get('reserve_units')}, report {rep['hash'][:16]}")
    r.shot("researcher", "decision")
    if d.get("verdict") not in ("OPEN", "REFUSE", "CANNOT_DECIDE"):
        raise RuntimeError(f"the crossing gave no decision: {d.get('verdict')}")


def _report_of(r: Run, role: str) -> dict:
    p = r.page[role]
    p.wait_for_function("() => /^#buy=[0-9a-f]{64}/.test(location.hash) && typeof report === 'object' && report && report.hash", timeout=240_000)
    p.wait_for_selector("#buyBox:not([hidden])", timeout=60_000)
    return p.evaluate("report")


def maker_claims(r: Run, st: dict):
    """The maker picks a front-door product whose maker is wanted (else the first) and claims its milestone."""
    p = r.page["maker"]
    # which of the front door's products still wants a maker: the app's own list (the cards say the same once live)
    board = p.request.get(r.base + "/api/front", timeout=120_000).json()
    p.goto(r.args.front_door, wait_until="domcontentloaded")
    p.wait_for_selector("#home-products li.hp", timeout=60_000)
    shown = p.evaluate("() => [...document.querySelectorAll('#home-products li.hp')].map((li) => li.dataset.slug)")
    wanted = [x["slug"] for x in board.get("products", []) if not x.get("maker") and x["slug"] in shown]
    if not wanted:
        raise RuntimeError(f"no product on the front door wants a maker: {[(x['slug'], x.get('maker')) for x in board.get('products', [])]}")
    st["slug"] = r.door("maker", "back", wanted[0])
    rep = _report_of(r, "maker")
    r.sign_in("maker")
    st["report"], st["reserve"] = rep["hash"], int((rep.get("decision") or {}).get("reserve_units") or 5)
    st["price"] = int(((rep.get("decision") or {}).get("plan") or {}).get("unit_price") or 2)
    r.click_until("maker", "#claimBtn", "() => document.querySelector('#claimNote').textContent.trim().length > 0", "claim")
    r.see("maker", f"claimed the milestone of {st['slug']} (report {st['report'][:16]}, reserve {st['reserve']} x {st['price']}): "
                   + p.inner_text("#claimNote")[:140])
    r.shot("maker", "claimed")


def buyer(r: Run, st: dict):
    p = r.page["buyer"]
    r.door("buyer", "back", st["slug"])
    _report_of(r, "buyer")
    r.sign_in("buyer")
    for _ in range(6):                                  # the page loads the wallet once; a failed read (devnet, DNS) hides it
        try:
            p.wait_for_selector("#pkWallet:not([hidden])", timeout=20_000)
            break
        except Exception:  # noqa: BLE001
            p.evaluate("loadWallet()")
    p.wait_for_selector("#pkWallet:not([hidden])", timeout=30_000)
    p.wait_for_selector("#preBtn:not([hidden])", timeout=30_000)       # a maker claimed it: a pre-order, not a commitment
    before = p.inner_text("#pkUnits")
    r.click_until("buyer", "#faucetBtn", f"() => document.querySelector('#pkUnits').textContent !== {json.dumps(before)}", "faucet")
    need = st["reserve"] * st.get("price", 2) + 2                      # the order (reserve x unit price) and its fee
    w = r.fund("buyer", need)
    p.evaluate("loadWallet()")
    p.wait_for_timeout(3000)
    r.see("buyer", f"passkey wallet {w['vault']} holds {w['balance_units']} test units (needs {need})")
    p.fill("#units", str(st["reserve"]))
    r.click_until("buyer", "#preBtn", "() => /escrow|✓|[1-9A-HJ-NP-Za-km-z]{8}…/.test(document.querySelector('#receipt').innerText)", "pre-order", timeout=400)
    r.see("buyer", "pre-order signed by the buyer's passkey: " + p.inner_text("#receipt")[:200].replace("\n", " "))
    rows = [c for c in r.api("buyer", "/api/commitments")["commitments"] if c.get("report") == st["report"] and c.get("via_kind") == "preorder"]
    c = rows[0]
    st["order"], st["claim"] = c["commitment"], c["claim_id"]
    r.sigs("buyer pre-order", c.get("signatures"))
    r.see("buyer", f"order {c['commitment']} locked, {c['units']} units, claim {c['claim_id']}")
    r.shot("buyer", "preordered")


def funder_funds(r: Run, st: dict):
    """The funder taps "Fund a milestone" on the same product: its passkey funds the project's first milestone."""
    p = r.page["funder"]
    r.door("funder", "fund", st["slug"])
    p.wait_for_selector(f"#fundList li[data-slug='{st['slug']}'] .fundBtn", timeout=120_000)
    r.sign_in("funder")
    face = st["reserve"] * st.get("price", 2)
    w = r.fund("funder", 10 + 1 + face * r.args.advance_rate / 100 + 1)
    r.see("funder", f"funder's passkey wallet {w['vault']} holds {w['balance_units']} test units")
    p.reload(wait_until="domcontentloaded")
    card = f"#fundList li[data-slug='{st['slug']}']"
    p.wait_for_selector(card + " .fundBtn", timeout=60_000)
    p.fill(card + " .fu", "10")
    r.click_until("funder", card + " .fundBtn", f"() => !!document.querySelector(\"{card} .note.ok\")", "fund a milestone", timeout=400)
    note = p.inner_text(card + " .note.ok")
    proj = r.api("funder", "/api/front?slug=" + st["slug"])
    pr = r.api("funder", f"/api/project?id={proj['project']}")
    m = next(x for x in pr["milestones"] if x["key"] == proj["first_milestone"])
    mine = [o for o in m["orders"] if o["kind"] == "funder" and o["status"] == "locked"]
    if not mine:
        raise RuntimeError("the milestone's escrow is not locked on devnet: " + note[:160])
    st["project"], st["milestone"] = proj["project"], proj["first_milestone"]
    r.sigs("funder funds the first milestone (project escrow)", mine[-1].get("signatures"))
    r.see("funder", f"funded milestone '{m['name']}' of project {proj['project']} with 10 test units: escrow {mine[-1]['order']}")
    r.shot("funder", "funded")


def lender_offers(r: Run, st: dict):
    """Tap one of two: "Offer cash now" on the buyer's receivable (the advance rate is the lender's choice)."""
    p = r.page["funder"]
    p.goto(r.base + "/app/#fund", wait_until="domcontentloaded")
    p.wait_for_function("() => typeof api === 'function'", timeout=30_000)
    sel = f".lendGo[data-go='quote'][data-c='{st['order']}']"
    p.wait_for_selector(sel, timeout=90_000)
    if r.args.advance_rate != 90:
        li = f"#lendList li[data-c='{st['order']}']"
        p.click(li + " details summary")
        p.fill(li + " .ar", str(r.args.advance_rate))
    r.click_until("funder", sel, f"() => !document.querySelector(\"{sel}\")", "offer cash now")
    r.summary["lender_taps"].append("Offer cash now")
    r.see("funder", f"tap 1 of 2: offered cash now ({r.args.advance_rate}% of the receivable)")
    r.shot("funder", "offered")


def maker_sells(r: Run, st: dict):
    p = r.page["maker"]
    p.goto(r.base + "/app/#make", wait_until="domcontentloaded")
    sel = f".acBtn[data-c='{st['order']}']"
    p.wait_for_selector(sel, timeout=90_000)
    r.click_until("maker", sel, "() => /✓|[1-9A-HJ-NP-Za-km-z]{8}…/.test(document.querySelector('#receipt') ? document.querySelector('#receipt').innerText : '')", "sell the receivable", timeout=400)
    c = r.wait_status("maker", st["order"], "assigned", 180)
    r.sigs("maker sells the receivable (TransferOwnership)", {"sold_to_lender": (c.get("signatures") or {}).get("sold_to_lender")})
    r.see("maker", "sold the receivable with its passkey (LazorKit TransferOwnership): " + json.dumps(c.get("factoring"))[:200])
    r.shot("maker", "sold")


def lender_advances(r: Run, st: dict):
    """Tap two of two: "Send the advance" (the lender's passkey pays the maker)."""
    p = r.page["funder"]
    p.goto(r.base + "/app/#fund", wait_until="domcontentloaded")
    p.reload(wait_until="domcontentloaded")
    sel = f".lendGo[data-go='advance'][data-c='{st['order']}']"
    p.wait_for_selector(sel, timeout=90_000)
    r.click_until("funder", sel, f"() => !document.querySelector(\"{sel}\")", "send the advance", timeout=400)
    c = r.wait_status("funder", st["order"], "advanced", 180)
    r.summary["lender_taps"].append("Send the advance")
    r.sigs("lender pays the advance", {"advance": (c.get("signatures") or {}).get("advance")})
    r.see("funder", "tap 2 of 2: sent the advance with its passkey: " + json.dumps(c.get("factoring"))[:200])
    r.shot("funder", "advanced")


def gist_page(r: Run, st: dict) -> str:
    """The maker publishes its result as a SECRET GitHub gist (`gh gist create`, the maker's own GitHub account) and
    posts the file's raw URL at that revision: a static page whose bytes are the same for every referee host."""
    name = "knos-milestone-" + st["claim"].split(":")[-1][:16] + ".txt"
    d = Path(r.out) / "_gist"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text(f"Knos milestone result\nclaim: {st['claim']}\norder: {st['order']}\nproduct: {st.get('slug')}\n"
                 f"result: the prototype was built and measured (the maker's evidence for this milestone)\n", encoding="utf-8")
    got = subprocess.run(["gh", "gist", "create", "--desc", f"Knos milestone evidence for {st['claim']}", str(f)], capture_output=True, text=True, timeout=120)
    if got.returncode != 0:
        raise RuntimeError("gh gist create: " + (got.stderr or got.stdout)[-200:])
    gid = got.stdout.strip().rstrip("/").rsplit("/", 1)[-1]
    raw = subprocess.run(["gh", "api", f"gists/{gid}", "--jq", ".files[].raw_url"], capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[0]
    st["evidence_gist"] = {"gist": got.stdout.strip(), "raw": raw, "file": name, "secret": True}
    r.see("maker", f"published the result as a secret gist {got.stdout.strip()} (raw, pinned to its revision: {raw})")
    return raw


def maker_proves(r: Run, st: dict):
    p = r.page["maker"]
    if r.args.resume_order:                           # a re-run: post on an order that is already locked
        st["order"], st["claim"] = r.args.resume_order, r.args.resume_claim
        r.sign_in("maker", "make")
    if r.args.evidence_dir:
        page = (f"<!doctype html><meta charset=utf-8><title>Milestone result</title><h1>Milestone result</h1>"
                f"<p>Claim {st['claim']}: the prototype ({st.get('slug')}) was built and measured; result attached.</p>")
        Path(r.args.evidence_dir, "index.html").write_text(page, encoding="utf-8")
    url = r.args.evidence_url or ""
    if r.args.evidence_url_template:
        url = r.args.evidence_url_template.format(claim=st["claim"])
    elif url.startswith("@"):                              # a file holding the URL, read when the page is posted
        url = Path(url[1:]).read_text(encoding="utf-8").strip()
    if r.args.evidence_gist:
        url = gist_page(r, st)
    elif not r.args.evidence_url_template:
        url = url.rstrip("/") + "/"
    r.hook("hook_before_post")
    p.goto(r.base + "/app/#make", wait_until="domcontentloaded")
    sel = f".ev[data-c='{st['order']}']"
    p.wait_for_selector(sel, timeout=60_000)
    p.fill(sel, url)
    p.locator(f".msBtn[data-c='{st['order']}']").click()      # the server checks the page, then the referee group signs
    p.wait_for_timeout(8000)
    if "not verified" in p.inner_text("body").lower():
        raise RuntimeError("milestone not verified: " + _err_line(p.inner_text("body")))
    r.see("maker", f"posted the result page {url}: the FROST referee group checks it")
    r.shot("maker", "posted")
    r.hook("hook_on_session")
    try:
        c = r.wait_status("maker", st["order"], "released", 60 * r.args.release_wait)
    finally:
        r.hook("hook_after_release")                  # also when the release did not come: never leave a host paused
    r.sigs("release by the FROST referee group", c.get("signatures"))
    sess = (c.get("referee_session") or {})
    r.see("maker", f"released by the FROST group key: signers {sess.get('signers')}, signature {str(sess.get('signature'))[:16]}…, "
                   f"release tx {(c.get('signatures') or {}).get('referee_group_pass')}")
    p.reload(wait_until="domcontentloaded")
    p.wait_for_timeout(2500)
    r.shot("maker", "released")


def lender_collects(r: Run, st: dict):
    p = r.page["funder"]
    p.goto(r.base + "/app/#fund", wait_until="domcontentloaded")
    p.reload(wait_until="domcontentloaded")
    sel = f".lendGo[data-go='collect'][data-c='{st['order']}']"
    p.wait_for_selector(sel, timeout=90_000)
    r.click_until("funder", sel, f"() => !document.querySelector(\"{sel}\")", "collect", timeout=400)
    c = r.wait_status("funder", st["order"], "repaid", 180)
    r.sigs("lender collects", {"collect": (c.get("signatures") or {}).get("collect")})
    r.see("funder", "collected the repayment with its passkey: " + json.dumps(c.get("factoring"))[:200])
    r.shot("funder", "collected")


def contributor(r: Run, st: dict):
    p = r.page["contributor"]
    r.door("contributor", "contribute", st.get("slug"))
    p.wait_for_selector("#needList li .makeBtn, #taskBox .tBtn", timeout=120_000)
    r.sign_in("contributor")
    w = r.api("contributor", "/api/wallet", {})
    # a parallel attempt at a project milestone (B1): paid to the contributor's passkey wallet when it is verified
    if st.get("slug") and p.locator(f"#needList li[data-slug='{st['slug']}'] .makeBtn").count():
        li = f"#needList li[data-slug='{st['slug']}']"
        r.click_until("contributor", li + " .makeBtn", f"() => !!document.querySelector(\"{li} .note\")", "make it")
        r.see("contributor", "attempted the milestone: " + p.inner_text(li + " .note")[:160].replace("\n", " "))
    p.wait_for_selector(".tBtn", timeout=60_000)
    p.locator(".tname").first.fill(f"pw{time.strftime('%H%M%S')}")
    p.locator(".twal").first.fill(w["vault"])
    # a real attempt: standardized inputs and squared features (the baseline itself is refused as "no change")
    code = TRAIN.read_text(encoding="utf-8").replace("'standardize': False", "'standardize': True").replace("'features': 'linear'", "'features': 'square'")
    p.locator(".tsub").first.fill(code)
    p.locator(".tBtn").first.click()
    p.wait_for_selector("#taskBox .card .note", timeout=600_000)
    note = p.inner_text("#taskBox .card .note")
    r.see("contributor", "the sealed referee answered: " + note[:220].replace("\n", " "))
    r.shot("contributor", "judged")
    m = re.search(r"session ([0-9a-f]{8})", note)
    if "scored" not in note:
        raise RuntimeError("the attempt was not scored")
    if not m:
        raise RuntimeError("no prize session: " + note[:200])
    sid = next(s["id"] for s in r.api("contributor", "/api/referee/pending")["sessions"] if s["id"].startswith(m.group(1)))
    r.hook("hook_on_session")
    end, s = time.time() + 60 * r.args.release_wait, {}
    while time.time() < end:
        s = r.api("contributor", "/api/referee/session?id=" + sid)
        if s.get("state") == "signed" and s.get("result"):
            break
        p.wait_for_timeout(5000)
    else:
        raise RuntimeError(f"the prize was not released in {r.args.release_wait} min: session {sid} {s.get('state')}, "
                           f"committed {s.get('committed')}, shared {s.get('shared')}, error {s.get('error')}")
    r.sigs("prize release by the FROST referee group", s.get("result"))
    r.see("contributor", f"prize released by the FROST group (signers {s.get('signers')}): {json.dumps(s.get('result'))[:200]}")
    p.goto(f"https://explorer.solana.com/address/{w['vault']}?cluster=devnet", wait_until="domcontentloaded")
    p.wait_for_timeout(6000)
    r.shot("contributor", "paid")


def agent(r: Run, st: dict):
    p, out = r.page["agent"], []
    mcp = r.args.mcp or (r.base + "/mcp")
    calls = [("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "playwright", "version": "1"}}),
             ("tools/list", {}), ("tools/call", {"name": "knos_milestones", "arguments": {}}), ("tools/call", {"name": "knos_templates", "arguments": {}})]
    for i, (method, params) in enumerate(calls, 1):
        q = p.request.post(mcp, data=json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}),
                           headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}, timeout=120_000)
        res = (q.json().get("result") or {})
        if q.status != 200 or not res:
            raise RuntimeError(f"{mcp} {method}: HTTP {q.status}")
        if method == "initialize":
            out.append(f"initialize {q.status}: {res.get('serverInfo')}")
        elif method == "tools/list":
            out.append(f"tools/list {q.status}: {len(res.get('tools', []))} tools")
        else:
            sc = res.get("structuredContent") or {}
            out.append(f"{params['name']} {q.status}: " + json.dumps(sc)[:220])
    for x in out:
        r.see("agent", x)
    html = "<meta name=viewport content='width=device-width'><body style='font:14px system-ui;padding:16px'><h1>Agent via MCP</h1>" + \
           f"<p>{mcp}</p>" + "".join(f"<p>{x.replace('<', '&lt;')}</p>" for x in out) + "</body>"
    p.set_content(html)
    p.wait_for_timeout(1200)
    r.shot("agent", "mcp")


STORY = [("researcher", researcher), ("maker", maker_claims), ("buyer", buyer), ("funder", funder_funds), ("funder", lender_offers),
         ("maker", maker_sells), ("funder", lender_advances), ("maker", maker_proves), ("funder", lender_collects),
         ("contributor", contributor), ("agent", agent)]
INDEPENDENT = (researcher, contributor, agent)        # steps that need nothing an earlier role made


def verdict(summary: dict) -> str:
    """The one line the run ends with."""
    bad = [f"{k}: {v['error']}" for k, v in summary["roles"].items() if v["result"] == "FAIL"]
    if bad:
        return "FAIL: " + " | ".join(bad)
    skipped = [k for k, v in summary["roles"].items() if v["result"] != "PASS"]
    if skipped:
        return f"FAIL: not run: {', '.join(skipped)}"
    return (f"PASS: all six roles on a 375x812 phone from {summary.get('front_door')}, {len(summary['signatures'])} signed devnet steps, "
            f"lender {len(summary['lender_taps'])} taps ({' + '.join(summary['lender_taps'])}) and collected, {summary.get('seconds')} s")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--out", default="evidence-run")
    ap.add_argument("--front-door", default=FRONT_DOOR, help="where every person starts (the research products open for backing)")
    ap.add_argument("--mcp", default=None, help="the agent's MCP endpoint (default <base>/mcp)")
    ap.add_argument("--doi", default=DOI)
    ap.add_argument("--product", default=PRODUCT)
    ap.add_argument("--place", default=None)
    ap.add_argument("--evidence-dir", default=None, help="the folder the maker's result page is written to")
    ap.add_argument("--evidence-url", default=None, help="the public https URL that folder is served at")
    ap.add_argument("--topup-cmd", default=None)
    ap.add_argument("--faucet-wait", type=int, default=0, help="minutes to wait out the faucet's hourly limit (live runs)")
    ap.add_argument("--advance-rate", type=int, default=90, help="the lender's advance rate, 50 to 98 percent")
    ap.add_argument("--evidence-url-template", default=None, help="the maker's public page, {claim} = the claim id")
    ap.add_argument("--hook-before-post", default=None, help="a shell command run before the maker posts its evidence")
    ap.add_argument("--hook-after-release", default=None, help="a shell command run after the release (also when it fails)")
    ap.add_argument("--hook-on-session", default=None, help="a shell command run when a referee session opens (e.g. dispatch referee.yml)")
    ap.add_argument("--roles", default=",".join(ROLES), help="the roles to run, comma-separated (their steps of the story only)")
    ap.add_argument("--resume-order", default=None, help="maker: post the evidence on this locked order (a re-run)")
    ap.add_argument("--resume-claim", default=None, help="maker: the claim id of --resume-order")
    ap.add_argument("--evidence-gist", action="store_true", help="the maker publishes its result as a secret gist (gh gist create)")
    ap.add_argument("--release-wait", type=int, default=15, help="minutes to wait for the referee group's release")
    ap.add_argument("--note", default="")
    ap.add_argument("--header", action="append", default=[], help="NAME:VALUE sent with every request (e.g. a tunnel's documented no-interstitial header)")
    ap.add_argument("--chromium", default=None, help="a Chrome/Chromium executable (default: Playwright's)")
    args = ap.parse_args(argv)
    if not (args.evidence_url or args.evidence_url_template or args.evidence_gist):
        ap.error("--evidence-gist, --evidence-url or --evidence-url-template: the maker's result page must be a public https page")
    from playwright.sync_api import sync_playwright
    base, out = args.base.rstrip("/"), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    st: dict = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium) if args.chromium else pw.chromium.launch()
        r = Run(browser, base, out, args)
        t0 = time.time()
        only = set(args.roles.split(","))
        story = [(ro, stp) for ro, stp in STORY if ro in only]
        if args.resume_order:                         # a re-run of the maker posts on the order it names, nothing before
            story = [(ro, stp) for ro, stp in story if ro != "maker" or stp is maker_proves]
        for role in ROLES:
            if role not in only:
                r.summary["roles"][role].update(result="NOT RUN", error="not asked for (--roles)")
        failed = False
        last = {ro: i for i, (ro, _) in enumerate(story)}
        for i, (role, step) in enumerate(story):
            if failed and step not in INDEPENDENT:
                r.summary["roles"][role]["seen"].append(f"skipped {step.__name__}: an earlier step failed")
                if r.summary["roles"][role]["result"] == "PASS":
                    r.summary["roles"][role].update(result="FAIL", error=f"not run: {step.__name__} needs an earlier step that failed")
                continue
            try:
                step(r, st)
            except Exception as why:  # noqa: BLE001 - a failed step is evidence too
                failed = failed or step not in INDEPENDENT
                r.summary["roles"][role].update(result="FAIL", error=f"{step.__name__}: {type(why).__name__}: {str(why)[:300]}")
                print(role, "FAIL", r.summary["roles"][role]["error"], flush=True)
                try:
                    r.shot(role, "fail-" + step.__name__)
                except Exception:  # noqa: BLE001
                    pass
            if last[role] == i:
                r.close(role)
        r.summary["state"], r.summary["seconds"] = st, round(time.time() - t0, 1)
        r.finish()
        browser.close()
    r.summary["verdict"] = verdict(r.summary)
    (out / "summary.json").write_text(json.dumps(r.summary, indent=1), encoding="utf-8")
    for role, v in r.summary["roles"].items():
        print(role, v["result"], v["error"] or "", flush=True)
    print(r.summary["verdict"], flush=True)
    return 0 if r.summary["verdict"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
