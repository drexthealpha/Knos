"""The published site's product pages, after scripts/build_site.sh has copied web/ and near/web/ into the site:

- index.html: the front door (web/door.html): the first tool (Round 13, A2 and A7), its numbers written in from
  docs/data/pricing.json and near/claims/claims.json; the earlier ask box below the first screen.
- prove/: the whole proof on NEAR (near/web/index.html), its files read from near/.
- labs/: the same check inside a lab's InterSystems IRIS (web/iris/index.html), its video and poster read from iris/.
- check/: the pull request checker exactly as entered at Colosseum (tag v0.3.28), from web/check-v0328/: the tag's own
  check.js and check_rules.js beside it, and its paying step on Knos's programs on Solana devnet. Its command palette
  (palette.js) is left out: it opens pages of the earlier one-page app, which the site no longer has.
- 404.html: the page for any missing address, under the same one header.
- near/ and iris/: old addresses, sent on to prove/ and labs/ at once, with the front door's title and preview.

Every page carries one header: the logo (the front door) and the product's pages. The source pages stay as they are
(their tests and the local NEAR server use them); only the published site is composed.

    python3 scripts/site_pages.py <site dir>
"""
import csv
import io
import json
import math
import re
import sys
from pathlib import Path

import site_product

ROOT = Path(__file__).resolve().parents[1]
# Round 13: plain names (the PLAIN-WORDS rule of ROUND13-ITEMS: no "prove", "agent", "IRIS" on a stranger's screens)
PAGES = [("claims/", "nav.claims"), ("prove/", "nav.papers"), ("agents/", "nav.builders"), ("labs/", "nav.labs"), ("check/", "nav.prs")]   # keys of web/i18n/en.json
# the product's pages; every other page of the build leaves the published site, each old address sent to the front door
KEEP = {"index.html", "404.html", "privacy.html", "prove/receipt/index.html", "tx/index.html"}   # Round 10, V6: one finished order, saved
CSS = ("#ask label a { display: inline !important; min-height: 0 !important; padding: 0 !important; }\n"   # the Prove page's Claims link sits in its sentence
       ".kh { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; max-width: 760px; margin: 0 auto; padding: 8px 16px; }\n"
       ".kh .logo { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; margin-inline-end: auto; color: var(--ink); text-decoration: none; font: 600 20px/1 var(--head); }\n"
       ".kh .mark { display: block; width: 28px; height: 27px; background: currentColor; -webkit-mask: var(--m) center / contain no-repeat; mask: var(--m) center / contain no-repeat; }\n"
       ".kh { position: relative; }\n"
       ".kmenu > summary { display: inline-flex; align-items: center; justify-content: center; min-height: 44px; min-width: 44px; padding: 0 12px; cursor: pointer; list-style: none; color: var(--ink); border: 1px solid var(--line); border-radius: 10px; font-size: 16px; }\n"
       ".kmenu > summary::-webkit-details-marker { display: none; }\n"
       ".kmenu:not([open]) > .kmenu-panel { display: none; }\n"   # a closed menu leaves no empty link boxes (R13 WALK 1)
       ".kmenu-panel { position: absolute; inset-inline: 16px; top: 56px; z-index: 30; max-width: 420px; margin-inline-start: auto; padding: 8px 12px; background: var(--paper-2); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--depth-2); }\n"
       ".kmenu-panel p { margin: 4px 0 8px; font-size: 16px; color: var(--ink-2); }\n"
       ".kh nav { display: flex; flex-direction: column; }\n"
       ".kh nav a, .kmenu-panel > a { display: flex; align-items: center; min-height: 44px; padding: 0 4px; color: var(--ink); text-decoration: none; font-size: 16px; }\n"
       ".kh nav a:hover, .kh nav a[aria-current] { text-decoration: underline; }\n")


def menu(up: str, here: str = "") -> str:
    """The menu: the goal as its first line, one press away (A7), then the product's pages."""
    cur = ' aria-current="page"'
    en = site_product.en
    links = "".join(f'<a href="{up}{p}"{cur if p == here else ""}>{en(key)}</a>' for p, key in PAGES)
    return (f'<details class="kmenu"><summary>{en("menu")}</summary><div class="kmenu-panel"><p class="kgoal">{en("goal")}</p>'
            f'<nav aria-label="Pages">{links}</nav><a href="{up}pricing/">{en("nav.pricing")}</a><a href="{up}status/">{en("nav.status")}</a></div></details>')


def header(up: str, here: str = "", lang: bool = False, screen: bool = False) -> str:
    """The one header: the Knos name and one control, "Menu" (Round 13, A2: a first screen holds the Knos name and the
    page's own words). The goal is the menu's first line, one press away on every page (A7). Its words are keys of
    web/i18n/en.json; on a page shown in every language (lang=True: the front door, the pricing page) the language
    control sits beside the menu, on the first screen (U7 R18).
    screen=True (the front door, pricing/ and status/, Round 13 FIX-SITE): the first screen holds at most three controls,
    the main input, its button and the language control (U3 Rule 1a, U7 R18), and the main action is among the first two
    (U3 Rule 10). So the Knos name there is not a link (the page's own main action is the way on) and the menu moves to the
    foot of the page (foot()), still one press away."""
    mark = f'<span class="mark" aria-hidden="true" data-no-mirror style="--m: url({up}brand/mark.svg)"></span>Knos'
    logo = f'<span class="logo" data-root="{up or "./"}">{mark}</span>' if screen else f'<a class="logo" href="{up or "./"}">{mark}</a>'
    # every language's own name, laid out unseen, so the scripts' fonts are ready before the language control opens
    # (U1 R3: its list shows within 0.1 s; drawing ten scripts for the first time took over 200 ms)
    warm = "".join(f'<span lang="{c}">{site_product.e(site_product.TP.meta(c)["name"])}</span>' for c in site_product.TP.LANGS)
    return (f'<header class="kh" id="kh">\n  {logo}\n'
            + (f"  {site_product.TP.switcher('en')}\n" if lang else "")
            + (f'  <span class="klang-list kwarm" aria-hidden="true">{warm}</span>\n' if lang and screen else "")
            + ("" if screen else f"  {menu(up, here)}\n") + "</header>")


def foot(up: str) -> str:
    """The foot of a screen page: the menu (moved from the header, see header()) and the light or dark switch (U5 R11:
    the device's own setting first, and a visible switch). The switch is shown by THEME_JS; with no script it stays hidden."""
    return (f'<div class="kfoot">{menu(up)}<button type="button" id="theme" data-theme-toggle hidden>'
            f'{site_product.en("theme.dark")}</button></div>')


def with_header(html: str, up: str, here: str, lang: bool = False, screen: bool = False) -> str:
    """The page's own bar (or the front door's header) replaced by the one header; the bar's script and its prerender
    rules go with it."""
    html, n = re.subn(r'<header class="(?:bar k-bar|kh)" id="(?:k-bar|kh)">.*?</header>', lambda m: header(up, here, lang, screen), html, count=1, flags=re.S)
    assert n == 1, "the page has no header to replace"
    html = re.sub(r'<script type="speculationrules">.*?</script>\n?', "", html, flags=re.S)
    html = re.sub(r'<script>addEventListener\("load", \(\) => \{ const s = document\.createElement\("script"\); s\.src = "[./]*brand/bar\.js";.*?</script>\n?', "", html, flags=re.S)
    if ".kmenu-panel" not in html:
        html = html.replace("</head>", f'<style id="kh-css">\n{CSS}</style>\n</head>', 1)
    return html


def with_goal(html: str, up: str) -> str:
    """The goal and the pricing page, one line at the foot of a composed page (the front door has its own footer, the
    pages of scripts/site_product.py theirs): the vision is one tap or less from every screen, always labelled the goal."""
    if site_product.GOAL.split(": ", 1)[1] in html:
        return html
    foot = (f'<footer class="kgoal" style="max-width:760px;margin:0 auto;padding:16px;color:var(--ink-2);font-size:16px">'
            f'<span>{site_product.GOAL}</span><br><a href="{up}pricing/" style="display:inline-flex;align-items:center;min-height:44px">Pricing</a></footer>\n')
    i = html.rfind("</body>")
    return html[:i] + foot + html[i:] if i >= 0 else html


# ---- the three screens of Round 13 (the front door, pricing/, status/): FIX-SITE ---------------------------------------
# U7 R1 and U2 R4: no physical left or right in their styles (logical properties mirror in Arabic); U7 R11: font sizes in
# rem, so the reader's own text size is kept. The design system (web/brand/tokens.css, the one source, copied to the app
# by scripts/sync_brand.py) is written into each screen with both rewrites, which also spares a render-blocking request.
PHYSICAL = ((r"\bmargin-left\s*:", "margin-inline-start:"), (r"\bmargin-right\s*:", "margin-inline-end:"),
            (r"\bpadding-left\s*:", "padding-inline-start:"), (r"\bpadding-right\s*:", "padding-inline-end:"),
            (r"(?<![\w-])left\s*:", "inset-inline-start:"), (r"(?<![\w-])right\s*:", "inset-inline-end:"),
            (r"text-align\s*:\s*left\b", "text-align: start"), (r"text-align\s*:\s*right\b", "text-align: end"),
            (r"float\s*:\s*left\b", "float: inline-start"), (r"float\s*:\s*right\b", "float: inline-end"))


def logical_rem(css: str) -> str:
    """The same rules with logical properties for left and right, and every font size in rem (16 px = 1 rem)."""
    for a, b in PHYSICAL:
        css = re.sub(a, b, css)
    return re.sub(r"(?<![\w-])font(?:-size)?\s*:[^;}]*", lambda m: re.sub(r"(\d*\.?\d+)px", lambda n: f"{float(n[1]) / 16:g}rem", m[0]), css)


def tokens_css(up: str) -> str:
    css = (ROOT / "web" / "brand" / "tokens.css").read_text(encoding="utf-8")
    css = css.replace('url("../fonts/', f'url("{up}fonts/').replace('url("mark.svg")', f'url("{up}brand/mark.svg")').replace('url("wordmark.svg")', f'url("{up}brand/wordmark.svg")')
    return logical_rem(re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/", "", css, flags=re.S)).strip())


# set before the first paint: the light or dark choice kept in this browser (the key web/front.js and brand/bar.js use);
# and, for a page that will be shown in another language, its direction at once and the page held unseen until the
# strings are in (at most 1.5 s, at once if the file fails), so nothing jumps when they arrive (U1.md line 294: layout shift in Arabic), the strings file
# asked for at once, and in Chinese no Latin web font at all (U7 R12: no font download for CJK). The language is chosen as
# tool_page.STATIC_JS chooses it: ?lang=, the stored choice, then the browser's list, never a place.
HEAD_JS = r"""(() => { const de = document.documentElement, L = /*LANGS*/[], BASE = /*BASE*/"";
  try { const t = localStorage.getItem("knos-theme"); if (t === "light" || t === "dark") de.dataset.theme = t; } catch (e) { /* no storage */ }
  const match = (tag) => { const t = String(tag || "").toLowerCase(); if (!t) return null; for (const l of L) if (l.code.toLowerCase() === t) return l.code;
    const b = t.split(/[-_]/)[0]; if (b === "zh") return "zh-Hans"; return L.some((l) => l.code === b) ? b : null; };
  let kept = null; try { kept = localStorage.getItem("knos.lang"); } catch (e) { /* no storage */ }
  const want = match(new URLSearchParams(location.search).get("lang")) || match(kept) || (navigator.languages || [navigator.language]).map(match).find(Boolean) || "en";
  if (want === "en") return;
  de.dataset.want = want; de.dir = L.find((l) => l.code === want).dir; de.classList.add("k-wait");
  const pre = document.createElement("link"); pre.rel = "preload"; pre.as = "fetch"; pre.crossOrigin = "anonymous"; pre.href = BASE + want + ".json"; document.head.append(pre);
  const mo = new MutationObserver(() => { if (de.lang === want) done(); });
  const done = () => { mo.disconnect(); clearTimeout(late); de.classList.remove("k-wait"); if (de.lang !== want) { de.dir = "ltr"; delete de.dataset.want; } };
  const late = setTimeout(done, 1500);
  pre.onerror = done;   // no strings file: English at once
  mo.observe(de, { attributes: true, attributeFilter: ["lang"] });
})();"""
HEAD_CSS = ('html.k-wait body{visibility:hidden}'
            ':root[data-want="zh-Hans"]{--text:system-ui,-apple-system,"Segoe UI",sans-serif;--head:system-ui,-apple-system,"Segoe UI",sans-serif;--code:ui-monospace,Consolas,monospace}')

# the light or dark switch at the foot (foot()): it shows the theme it switches to, in the page's language
THEME_JS = r"""(() => { const b = document.getElementById("theme"), de = document.documentElement; if (!b) return;
  const now = () => de.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  const label = () => { b.textContent = KI.t(now() === "light" ? "theme.dark" : "theme.light"); };
  b.hidden = false; label(); KI.changed(label);
  b.addEventListener("click", () => { const t = now() === "light" ? "dark" : "light"; de.dataset.theme = t; try { localStorage.setItem("knos-theme", t); } catch (e) { /* no storage */ } label(); });
})();
// a link to another page of the site shows it was pressed at once, while the next page loads (U1 R3: a change within 0.1 s)
// (the next page is asked for once that look is on the screen, one frame later)
addEventListener("click", (e) => { const a = e.target.closest && e.target.closest("a[href]");
  if (!a || a.target || a.hasAttribute("download") || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const u = new URL(a.href, location); if (u.origin !== location.origin || u.pathname === location.pathname) return;
  e.preventDefault(); a.classList.add("k-going"); requestAnimationFrame(() => setTimeout(() => location.assign(u.href), 0)); }, true);
// a form the server answers (the tool's box on the pricing and status pages) shows its press the same way
// and, with a script, takes its table to the front door's tool (sessionStorage knos.handoff, read once there) as a link
addEventListener("submit", (e) => { const f = e.target, b = !e.defaultPrevented && f.dataset.to && f.querySelector("[type=submit]"); if (!b) return;
  e.preventDefault(); try { sessionStorage.setItem("knos.handoff", f.elements.table.value); } catch (x) { /* no storage */ }
  b.classList.add("k-going"); requestAnimationFrame(() => setTimeout(() => location.assign(new URL(f.dataset.to, location).href), 0)); });
addEventListener("pageshow", () => document.querySelectorAll(".k-going").forEach((a) => a.classList.remove("k-going")));"""

# the header, the foot and their controls on the three screens: every control at least 48 px with 8 px between them (U3 Rule 4)
SCREEN_CSS = (".kh .logo { cursor: default; }\n"
              ".kh .klang summary, .kmenu > summary { min-height: 48px; min-width: 48px; font-size: 16px; border-color: var(--ink-2); }\n"
              ".klang-list a, .kmenu-panel a, .kh nav a { min-height: 48px; }\n"
              "details:not([open]) > .klang-list, details:not([open]) > .kmenu-panel { display: none; }\n"
              ".how summary { min-height: 48px; }\n"
              "footer { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 18px; }\n"
              "footer > .fline { flex: 0 0 100%; margin: 0; font: 400 18px/1.5 var(--text); color: var(--ink-2); }\n"
              "footer a { min-height: 48px; min-width: 48px; margin: 0; }\n"
              ".flinks { display: flex; flex-wrap: wrap; gap: 8px; }\n"
              ".kfoot { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 8px; flex: 0 0 100%; }\n"
              ".kfoot .kmenu-panel { position: static; margin: 8px 0 0; max-width: none; }\n"
              "#theme { min-height: 48px; min-width: 48px; padding: 0 16px; font: 500 18px/1.5 var(--text); color: var(--ink); background: transparent; "
              "border: 2px solid var(--ink-2); border-radius: 10px; cursor: pointer; }\n"
              "#theme:focus-visible, .kmenu > summary:focus-visible, .klang summary:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }\n"
              "a.k-going, button.k-going { opacity: .6; cursor: progress; }\n"
              ".klang-list.kwarm { display: block; position: absolute; visibility: hidden; inline-size: 1px; block-size: 1px; overflow: hidden; padding: 0; border: 0; }\n"
              ".klang-list.kwarm > span { position: absolute; inset-inline-start: 0; inset-block-start: 0; }\n"
              # below the first screen, laid out only when it comes near the screen (U1 R5, U7 R22: on a cheap phone the first
              # paint waits for the layout of the whole page, and in Hindi and Arabic shaping that text is most of it); the
              # question box is a closed fold, whose content is not laid out until it opens
              "body > footer { content-visibility: auto; contain-intrinsic-size: auto 480px; }\n"
              ":root:lang(hi) p, :root:lang(hi) li, :root:lang(hi) dd { line-height: 1.85; }\n"
              ":root:lang(ar) p, :root:lang(ar) li, :root:lang(ar) dd { line-height: 1.6; }\n")


def screen(html: str, up: str) -> str:
    """One of the three screens made whole: the design system written in (tokens_css), every style block rewritten by
    logical_rem, the head script and its styles first in the head, and the theme switch's script after the language runtime."""
    langs = [{"code": c, "dir": site_product.TP.meta(c)["dir"]} for c in site_product.TP.LANGS]
    head = HEAD_JS.replace("/*LANGS*/[]", json.dumps(langs)).replace('/*BASE*/""', json.dumps(up + "i18n/"))
    html = html.replace(f'<link rel="stylesheet" href="{up}brand/tokens.css">', f'<style id="k-tokens">{tokens_css(up)}</style>', 1)
    html = html.replace("</head>", f"<style id=\"k-screen\">\n{SCREEN_CSS}</style>\n</head>", 1)
    html = re.sub(r"(<style[^>]*>)(.*?)(</style>)", lambda m: m[1] + logical_rem(m[2]) + m[3], html, flags=re.S)
    html = html.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n<script>{head}</script>\n<style id="k-head">{HEAD_CSS}</style>', 1)
    i = html.find("window.KI = window.KI")
    end = html.find("</script>", i)
    assert i >= 0 and end > i, "the screen has no language runtime"
    return html[:end] + "\n" + THEME_JS + "\n" + html[end:]


def retitle(html: str, title: str, desc: str) -> str:
    """A page's own plain title and description, in its tab and its link preview."""
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1, flags=re.S)
    for attr, value in (('name="description"', desc), ('property="og:title"', title), ('property="og:description"', desc),
                        ('name="twitter:title"', title), ('name="twitter:description"', desc)):
        html = re.sub(rf'<meta {attr} content="[^"]*"', f'<meta {attr} content="{value}"', html, count=1)
    return html


def head_of(page: str) -> str:
    tags = re.findall(r'<title>.*?</title>|<meta (?:name|property)="(?:description|og:[a-z:_]+|twitter:[a-z:_]+)"[^>]*>', page, re.S)
    return "\n".join(tags)


def redirect(to: str, head: str) -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<script>location.replace("{to}" + location.hash);</script>\n'
            f'<meta http-equiv="refresh" content="0; url={to}">\n{head}\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<meta name="robots" content="noindex">\n'
            f'<link rel="canonical" href="https://drexthealpha.github.io/Knos/{to.lstrip("./")}">\n'
            f'</head><body><p><a href="{to}">Knos</a></p></body></html>\n')


BEACON = """<script>
// first-party only (knos_wanted.visits): a random visit id that resets every day, no cookie, no IP stored; Do Not Track sends nothing
(() => { if (navigator.doNotTrack === "1" || window.doNotTrack === "1") return;
  const H = "https://knos.onrender.com", day = new Date().toISOString().slice(0, 10); let v, back = false;
  try { const s = JSON.parse(localStorage.getItem("knos.visit") || "{}"); back = !!s.day && s.day !== day && Date.now() - (s.at || 0) < 7 * 864e5;
    v = s.day === day ? s.v : [...crypto.getRandomValues(new Uint8Array(8))].map((b) => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem("knos.visit", JSON.stringify({ v, day, at: s.day === day ? s.at : Date.now() })); } catch { v = [...crypto.getRandomValues(new Uint8Array(8))].map((b) => b.toString(16).padStart(2, "0")).join(""); }
  const page = location.pathname.replace(/^\\/Knos/, "") || "/", t0 = Date.now();
  const send = (e, x) => { try { fetch(H + "/api/visit", { method: "POST", body: JSON.stringify({ v, e, p: page, back, ...(x || {}) }), headers: { "content-type": "text/plain" }, credentials: "omit", keepalive: true, mode: "cors" }).catch(() => {}); } catch { /* no beacon */ } };
  send("view");
  window.knosNotWhat = (why) => send("notwhat", why ? { why: String(why).slice(0, 30) } : {});   // T8: one tap on a result
  let presses = [];
  addEventListener("click", (ev) => { const at = performance.now(), n = presses.filter((p) => at - p.t < 1000 && Math.abs(p.x - ev.clientX) < 30 && Math.abs(p.y - ev.clientY) < 30).length;
    presses = [...presses.slice(-5), { t: at, x: ev.clientX, y: ev.clientY }]; if (n >= 2) send("rage");
    const target = ev.target.closest("button, a"); if (!target) return; send("press");
    let seen = false; const mo = new MutationObserver(() => { if (!seen) { seen = true; mo.disconnect(); const ms = Math.round(performance.now() - at); if (ms > 400) send("slow", { ms }); } });
    mo.observe(document.body, { subtree: true, childList: true, characterData: true }); setTimeout(() => { if (!seen) { mo.disconnect(); send("slow", { ms: 400 }); } }, 2000);
    if (/download/i.test(target.textContent)) send("download"); }, { capture: true });
  const seenText = new Set(); let pressed = false;
  const kinds = [["result", /Yes, the claim holds|Answer: Yes|Answer: No|Nothing proved matches|cannot prove this paper|Nothing checked matches|cannot check this paper/], ["proof", /Receipt for proof|Receipt: paid/], ["backed", /Bought .* shares|test USDC behind this proof|test USDC moved on NEAR testnet: /], ["error", /Not read|No answer this time|did not answer/]];
  // only text that appears after this visit's first press counts: a page that shows a result as it loads is not one
  addEventListener("click", (ev) => { if (pressed || !ev.target.closest("button, a")) return; pressed = true;
    const t = document.body.textContent; for (const [k, re] of kinds) if (re.test(t)) seenText.add(k); }, { capture: true });
  setInterval(() => { if (!pressed) return; const t = document.body.textContent;
    for (const [k, re] of kinds)
      if (!seenText.has(k) && re.test(t)) { seenText.add(k); send(k); } }, 1500);   // a light check, off the press path
  // real visitors' timings (U1 R22): the largest paint, each press's event time and layout shifts, and in-page screen
  // changes where the browser reports them (window.knosVitals); on the front door, the price and the status page, sent once
  // when the page is left (POST /api/vitals), only from a browser whose person said yes to being counted
  const vit = { lcp: 0, inp: 0, cls: 0, soft: 0, icp: 0 };
  const watch = (type, f, o) => { try { if ((PerformanceObserver.supportedEntryTypes || []).includes(type)) new PerformanceObserver((l) => l.getEntries().forEach(f)).observe({ type, buffered: true, ...(o || {}) }); } catch { /* not measured here */ } };
  watch("largest-contentful-paint", (e) => { vit.lcp = Math.round(e.startTime); });
  watch("event", (e) => { if (e.interactionId) vit.inp = Math.max(vit.inp, Math.round(e.duration)); }, { durationThreshold: 40 });
  watch("layout-shift", (e) => { if (!e.hadRecentInput) vit.cls = Math.round((vit.cls + e.value) * 1000) / 1000; });
  watch("soft-navigation", () => { vit.soft++; });
  watch("interaction-contentful-paint", (e) => { vit.icp = Math.max(vit.icp, Math.round(e.startTime)); });
  window.knosVitals = vit;
  const screen = { "/": "door", "/index.html": "door", "/pricing/": "price", "/status/": "status" }[page];
  let measured = false;
  addEventListener("visibilitychange", () => { if (document.visibilityState !== "hidden") return; send("leave", { s: Math.round((Date.now() - t0) / 1000) });
    let yes = false, id = ""; try { yes = localStorage.getItem("knos.count") === "yes"; id = localStorage.getItem("knos.browser") || ""; } catch { /* no storage */ }
    if (measured || !screen || !yes || !id || !navigator.sendBeacon) return; measured = true;
    const test = navigator.webdriver === true || new URLSearchParams(location.search).has("knos_test");
    navigator.sendBeacon(H + "/api/vitals", new Blob([JSON.stringify({ screen, lcp: vit.lcp, inp: vit.inp, cls: vit.cls, browser: id, test })], { type: "text/plain" })); });
})();
</script>
"""


def beacon(out: Path) -> None:
    """The first-party visit script on every product page (knos_wanted.visits), just before </body>."""
    pages = [out / "index.html", out / "prove" / "index.html", out / "labs" / "index.html", out / "check" / "index.html",
             *[out / p for p in ("claims/index.html", "agents/index.html", "pricing/index.html", "status/index.html")], *(out / "claim").rglob("index.html")]
    for p in pages:
        if p.is_file():
            t = p.read_text(encoding="utf-8")
            if "knos.visit" not in t and "</body>" in t:
                p.write_text(t.replace("</body>", BEACON + "</body>", 1), encoding="utf-8")


def sweep(out: Path) -> int:
    """Every page of the build that is not the product's becomes an old address: it sends a visitor to the front door
    (pricing.html to pricing/). Run again by the pages workflow after its own steps write pages (rank/)."""
    head = head_of((ROOT / "web" / "door.html").read_text(encoding="utf-8"))
    keep = KEEP | {f"{p}index.html" for p, _ in PAGES} | {"pricing/index.html", "status/index.html", "near/index.html", "iris/index.html",
                                                                 "data/pricing.html", "data/usage.html"}   # the pricing and status files, as pages (R13 WALK 1)
    keep |= {p.relative_to(out).as_posix() for p in (out / "claim").rglob("index.html")} if (out / "claim").is_dir() else set()
    moved = {"pricing.html": "pricing/"}
    gone = 0
    for p in sorted(out.rglob("*.html")):
        rel = p.relative_to(out).as_posix()
        if rel in keep or rel.startswith("near/vendor/") or 'http-equiv="refresh"' in p.read_text(encoding="utf-8", errors="replace")[:600]:
            continue
        to = "../" * rel.count("/") + moved.get(rel, "")
        p.write_text(redirect(to or "./", head), encoding="utf-8")
        gone += 1
    return gone


def door_claims() -> list[dict]:
    """The claims registry as the front door answers from it: each claim, its paper (DOI, arXiv id) and its locked test
    with the test file's sha256."""
    import hashlib
    out = []
    for c in json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]:
        doi = str(c.get("doi") or "")
        ax = re.search(r"arxiv\.(\d{4}\.\d{4,5})", doi, re.I)
        test = ROOT / "near" / "agents" / "job" / c["test"]
        out.append({k: c[k] for k in ("name", "plain", "quote", "paper", "authors", "year", "test")} |
                   {"doi": doi, "arxiv": ax.group(1) if ax else str(c.get("arxiv") or ""), "url": str(c.get("url") or ""),
                    "sha256": hashlib.sha256(test.read_bytes()).hexdigest()})
    return out


DATA = ROOT / "docs" / "data"


def numbers() -> dict:
    """docs/data/pricing.json: each number's value by name (C6)."""
    return {k: v["value"] for k, v in json.loads((DATA / "pricing.json").read_text(encoding="utf-8"))["numbers"].items()}


def companies() -> int:
    """F1: the one company count a public page may show, the rows of docs/data/scorecard_summary.json (a copy of
    LAWS/MISSION/SCORECARD/SUMMARY.json). Records of a first list (R1 finding 23), none of them a buyer."""
    return int(json.loads((DATA / "scorecard_summary.json").read_text(encoding="utf-8"))["rows"])


COMPANY_LINE = re.compile(r"[\d,]+ companies are on a first list\. No outside company has bought from Knos\.")


def company_line() -> str:
    return f"{companies():,} companies are on a first list. No outside company has bought from Knos."


LIMIT = ROOT / "near" / "agents" / "job" / "data" / "limit"   # the first tool's sample and the files its locked test checks


def sample_text() -> str:
    """The first tool's sample file (near/agents/job/data/limit/sample.csv), as the front door's box holds it."""
    return (LIMIT / "sample.csv").read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n")


def data_rows(text: str) -> int:
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    return len(rows) - 1 if rows and any(not _is_num(c) for c in rows[0]) else len(rows)


def _is_num(cell: str) -> bool:
    try:
        return math.isfinite(float(cell.strip()))
    except ValueError:
        return False


def sample_facts() -> dict:
    """The numbers the front door's fold says about the sample: its first and last capacity_ah, its rows, and the most
    rows of any file the locked test checks."""
    rows = list(csv.DictReader(io.StringIO(sample_text())))
    return {"first": rows[0]["capacity_ah"], "last": rows[-1]["capacity_ah"], "rows": f"{len(rows):,}",
            "longest": f"{max(data_rows(f.read_text(encoding='utf-8')) for f in LIMIT.glob('*.csv')):,}"}


def job_line() -> str:
    """The job that built the first tool, from released.json beside the released program; until then, that it is not released."""
    try:
        r = json.loads((LIMIT / "released.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        r = {}
    url = str(r.get("release_url") or r.get("url") or r.get("link") or "") if isinstance(r, dict) else ""
    return f'<a href="{site_product.e(url)}">The public record</a>.' if url else "It has not been released yet."


def fill(html: str) -> str:
    """A page's numbers written in from their files: each <span data-n="name"> from docs/data/pricing.json, each
    <span data-claim="field"> from the HyperLogLog claim of near/claims/claims.json, the first tool's sample and its
    <span data-sample="name"> facts, the <span data-job> line from released.json, and the company sentence (F1)."""
    n = numbers()
    html = re.sub(r'(<span data-n="(\w+)">)[^<]*(</span>)', lambda m: f"{m[1]}{n[m[2]]:,}{m[3]}", html)
    c = next(x for x in json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"] if x["name"] == "hyperloglog")
    html = re.sub(r'(<span data-claim="(\w+)">)[^<]*(</span>)', lambda m: f"{m[1]}{site_product.e(c[m[2]])}{m[3]}", html)
    if "data-sample" in html:
        f = sample_facts()
        html = re.sub(r'(<span data-sample="(\w+)">)[^<]*(</span>)', lambda m: f"{m[1]}{f[m[2]]}{m[3]}", html)
        html = re.sub(r'(<textarea id="list"[^>]*data-sample>).*?(</textarea>)', lambda m: m[1] + site_product.html.escape(sample_text(), quote=False) + m[2], html, flags=re.S)
        html = re.sub(r"(<span data-job>).*?(</span>)", lambda m: m[1] + job_line() + m[2], html, flags=re.S)
    return COMPANY_LINE.sub(company_line(), html)


def run_seconds() -> int:
    """The most seconds one run of the first tool may take, as the server reads it (tool_run, runner_conf.py): the
    timeout_s of the claim whose locked test is test_limit.py, else the checker's default. The front door's waiting bar
    counts against it until the server's own answer gives it (limits.max_seconds)."""
    for c in json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]:
        if c.get("test") == "test_limit.py" and c.get("timeout_s"):
            return int(c["timeout_s"])
    conf = (ROOT / "apps" / "wanted" / "knos_wanted" / "runner_conf.py").read_text(encoding="utf-8")
    return int(re.search(r"'checker_default_seconds': (\d+)", conf)[1])


def released() -> bool:
    """The first tool's program has been released (released_solution.py is beside its sample)."""
    return (LIMIT / "released_solution.py").is_file()


PERIGNON = "https://labordynamicsinstitute.github.io/crress-book/sessions/6/perignon/"
TEST_URL = "https://github.com/drexthealpha/Knos/blob/main/near/agents/job/test_limit.py"
NASA_URL = "https://data.nasa.gov/dataset/li-ion-battery-aging-datasets"


def comp(key: str, v: dict, spans: dict | None = None) -> str:
    """A composite string in English with its values, between the marks the page's script swaps it by (tool_page.STATIC_JS)."""
    return f"<!--k:{key} {json.dumps(v)}-->{site_product.TP.h('en', key, spans, **v)}<!--/k-->"


def made_up() -> bool:
    """The sample is the generated table (runner_conf.py sample_made_up), so its label and its source line say so."""
    conf = (ROOT / "apps" / "wanted" / "knos_wanted" / "runner_conf.py").read_text(encoding="utf-8")
    return "'sample_made_up': False" not in conf


def strings(html: str) -> str:
    """Round 13, H3 a: every {{key}} of the front door written in from web/i18n/en.json (a plain string escaped, a
    composite one with its values and the spans the number checks read), the {{@name}} the build chooses, and the
    language runtime at /*I18N*/."""
    tp, n, f = site_product.TP, numbers(), sample_facts()
    rows, longest = data_rows(sample_text()), int(f["longest"].replace(",", ""))
    pack = {"n": n["pack_runs"], "price": n["pack_price"]}
    pspans = {"free": "free_runs_per_day", "n": "pack_runs", "price": "pack_price"}
    job = re.search(r'href="([^"]+)"', job_line())
    sample_v = {"n": rows, "first": f["first"], "last": f["last"], "limit": "1.4", "url": NASA_URL}
    sample_sp = {"first": 'data-sample="first"', "last": 'data-sample="last"', "n": 'data-sample="rows"'}
    pay_v = {"free": n["free_runs_per_day"], **pack}
    five = [comp("a.res.get", {}), comp("a.res.next", {}), comp("a.pay", pay_v),
            comp("a.why_released" if released() else "a.why_unreleased", {"n": longest}), comp("a.tool.who", {"issues": tp.ISSUES})]
    special = {
        "tool.sample_label": tp._e(tp.t("en", "tool.sample_made_up" if made_up() else "tool.sample_nasa")),
        "five": tp.five("en", five),
        "fold.sample": comp("fold.sample_made_up", sample_v, sample_sp) if made_up() else comp("fold.sample_nasa", {"url": NASA_URL}),
        "fold.built": comp("fold.built_released", {"url": job[1]}) if job else tp.h("en", "fold.built_unreleased"),
    }
    composite = {"pay.headline": (pack, pspans), "pay.confirm": (pack, pspans), "fold.test": ({"n": longest, "url": TEST_URL}, {"n": 'data-sample="longest"'}),
                 "fold.price": (pay_v, pspans), "ask.cost": ({"low": 330, "high": 763, "url": PERIGNON}, None)}

    def one(m):
        key, hints = m[1], dict(h.split("=", 1) for h in m[2].split())
        if key.startswith("@"):
            out = special[key[1:]]
        elif key in composite:
            out = comp(key, *composite[key])
        else:
            out = tp._e(tp.t("en", key))
        # a number the source shows beside a key (so the facts check reads it there) must be what the build writes
        text = re.sub(r"<[^>]+>", "", out)
        for name, want in hints.items():
            assert re.search(rf"(?<![\d.]){re.escape(want)}(?![\d])", text), f"web/door.html: {{{{{key}}}}} says {name}={want}, the build writes: {text}"
        return out
    html = re.sub(r"\{\{(@?[\w.]+)((?: \w+=[^ }]+)*)\}\}", one, html)
    html = html.replace("<script>/*I18N*/</script>", "<script>\n" + tp.static_runtime("i18n/") + "\n</script>", 1)
    return html.replace("</head>", f'<style id="k-i18n-css">{tp.SWITCH_CSS}</style>\n</head>', 1)


def main(site: str) -> int:
    out = Path(site)
    door = fill(strings((ROOT / "web" / "door.html").read_text(encoding="utf-8")))
    door = door.replace("/*CLAIMS*/[]/*END*/", json.dumps(door_claims(), ensure_ascii=False).replace("</", "<\\/"))
    door = door.replace('aria-valuemax="0"', f'aria-valuemax="{run_seconds()}"', 1)
    door = with_header(door, "", "", lang=True, screen=True).replace("<!--FOOT-->", foot(""), 1)
    (out / "index.html").write_text(screen(door, ""), encoding="utf-8")
    (out / "door.html").unlink(missing_ok=True)
    near = fill((ROOT / "near" / "web" / "index.html").read_text(encoding="utf-8"))
    near = near.replace('fetch("latest.json"', 'fetch("../near/latest.json"')
    # the wallet button's blank page (near/web/embed.html) needs the local NEAR server, so it is not published (S17-006)
    near = re.sub(r'<a href="embed\.html">[^<]*</a>', "", near)
    # the proof page opens on the proof: its heading says what the page does, the front door asks the question
    # (Round 13 WALK 1: plain words; the chain and its terms are in the page's "How it works" fold)
    near, n = re.subn(r"<!-- k-first -->.*?<!-- /k-first -->", '<h1 class="k-first" id="k-first">Check a paper\'s claim</h1>', near, count=1, flags=re.S)
    assert n == 1, "the NEAR page has no first block"
    near = retitle(near, "Knos: check a paper's claim", "Give a paper's link: Knos checks its claim with test money and hands you code that works.")
    near = re.sub(r'\s*<p class="vision"[^>]*>.*?</p>', "", near, flags=re.S)
    (out / "prove").mkdir(exist_ok=True)
    (out / "prove" / "index.html").write_text(with_goal(with_header(near, "../", "prove/"), "../"), encoding="utf-8")
    iris = (ROOT / "web" / "iris" / "index.html").read_text(encoding="utf-8")
    iris = iris.replace('"knos-iris.mp4"', '"../iris/knos-iris.mp4"').replace('poster="poster.png"', 'poster="../iris/poster.png"')
    # the labs page opens on its own heading (its section names the check inside IRIS)
    # (Round 13 WALK 1: no product's name on the screen or in its fold)
    iris, n = re.subn(r"<!-- k-first -->.*?<!-- /k-first -->", '<h1 class="k-first" id="k-first">For labs</h1>\n<p class="k-a">Knos checks each lab step\'s '
                      'test result against terms set before the work, inside the lab\'s own database.</p>', iris, count=1, flags=re.S)
    assert n == 1, "the IRIS page has no first block"
    iris = retitle(iris, "Knos for labs", "The check inside a lab's own database, with its install steps and video.")
    (out / "labs").mkdir(exist_ok=True)
    (out / "labs" / "index.html").write_text(with_goal(with_header(iris, "../", "labs/"), "../"), encoding="utf-8")
    # the checker as entered at Colosseum: the tag's page and files, under the one header, dated as the build
    chk = (ROOT / "web" / "check-v0328" / "index.html").read_text(encoding="utf-8")
    built = re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', (out / "check" / "index.html").read_text(encoding="utf-8"))
    chk = chk.replace("KNOS_BUILD_DATE", built.group(1) if built else "2026-11-12")
    chk, n = re.subn(r'<header class="bar">.*?</header>', lambda m: header("../", "check/"), chk, count=1, flags=re.S)
    assert n == 1, "the check page has no header to replace"
    chk = chk.replace("</head>", f'<style id="kh-css">\n{CSS}.kh nav {{ display: flex !important; }}\n</style>\n</head>', 1)   # the tag's app.css hides a header nav on phones
    (out / "check" / "index.html").write_text(with_goal(chk, "../"), encoding="utf-8")
    for f in (ROOT / "web" / "check-v0328").rglob("*.js"):   # the tag's check.js and every module it loads (share, badge, motion)
        if f.name == "palette.js":   # opens the earlier one-page app's pages (front.js): motion.js catches the missing file
            continue
        to = out / "check" / f.relative_to(ROOT / "web" / "check-v0328")
        to.parent.mkdir(parents=True, exist_ok=True)
        to.write_bytes(f.read_bytes())
    # the badge preview on check/ loads brand/checked.svg next to the page (the tag's share.js)
    (out / "check" / "brand").mkdir(parents=True, exist_ok=True)
    (out / "check" / "brand" / "checked.svg").write_bytes((ROOT / "web" / "brand" / "checked.svg").read_bytes())
    # the missing-address page under the one header (its <base> is the site root, so the links need no "../")
    (out / "404.html").write_text(with_header((ROOT / "web" / "404.html").read_text(encoding="utf-8"), "", ""), encoding="utf-8")
    # the saved receipt and the transaction viewer have no bar of their own: the one header goes above their content
    for rel, up in (("prove/receipt/index.html", "../../"), ("tx/index.html", "../")):
        p = out / rel
        if p.is_file() and 'id="kh"' not in (t := p.read_text(encoding="utf-8")):
            t = t.replace("<body>\n", f"<body>\n{header(up, '')}\n", 1).replace("</head>", f'<style id="kh-css">\n{CSS}</style>\n</head>', 1)
            t = with_goal(t, up)
            p.write_text(t, encoding="utf-8")
    head = head_of(door)
    (out / "near" / "index.html").write_text(redirect("../prove/", head), encoding="utf-8")
    (out / "iris" / "index.html").write_text(redirect("../labs/", head), encoding="utf-8")
    site_product.HEADER_CSS = CSS
    site_product.FOOT = foot
    made = site_product.write(out, header)
    for rel in ("pricing/index.html", "status/index.html"):   # the two screens besides the front door (screen())
        (out / rel).write_text(screen((out / rel).read_text(encoding="utf-8"), "../"), encoding="utf-8")
    # the data files behind the pricing and status pages, published beside them (F4 new rule 12, F7 finding 1)
    (out / "data").mkdir(exist_ok=True)
    for name in ("pricing.json", "usage.json", "scorecard_summary.json"):
        (out / "data" / name).write_bytes((DATA / name).read_bytes())
    (out / "tools.html").write_text(redirect("./", head), encoding="utf-8")   # linked from earlier posts: sends to the front door
    beacon(out)
    gone = sweep(out)
    print(f"product pages: the front door, {len(made) + 2} pages ({', '.join(['prove/', 'labs/'] + made)}); near/ and iris/ send on; {gone} older pages send to the front door")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--sweep"]:
        print(f"older pages sent to the front door: {sweep(Path(sys.argv[2]))}")
        sys.exit(0)
    sys.exit(main(sys.argv[1]))
