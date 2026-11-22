"""L09 (IQ PLAN.md: forty languages, local language first; DISTRIBUTION/CHECKED-F8-G3.md:746, F6.md:239, F6.md:337,
F6.md:382, G3.md:174, G3.md:435): web/i18n holds at least 40 locale files, each with every key of en.json and none
longer than its max_length; Arabic, Persian, Urdu and Hebrew are written right to left and pass the mirror checks of
UX/U7.md:27 and UX/U7.md:57 on the front door; and with navigator.languages set to each locale, the first screen of the
front door renders in it. A native speaker's review of the machine-made files is a person's step (FOUNDER-STEPS).
The browser part builds the site and runs headless Chromium (node and the `playwright` package, found as
tests/web/overflow.mjs finds it: an import, else NODE_PATH; CHROME_PATH names a browser outside playwright). With none
it is skipped with the reason, unless KNOS_REQUIRE_BROWSER=1."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _posix
import pytest

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "web" / "i18n"
CATS = ("zero", "one", "two", "few", "many", "other")
RTL = ("ar", "fa", "ur", "he")
MT = "machine translated, not reviewed by a native speaker"
# CLDR 48 cardinal plural categories, as Intl.PluralRules gives them in Chromium (U7 R7)
PLURALS = {**dict.fromkeys("am az bn de el en fa fil gu ha hi hu kn ml mr nl pa sw ta te tr ur uz".split(), {"one", "other"}),
           "ar": set(CATS), **dict.fromkeys("cs pl ru uk".split(), {"one", "few", "many", "other"}),
           **dict.fromkeys("es fr it pt".split(), {"one", "many", "other"}), "he": {"one", "two", "other"},
           **dict.fromkeys("id ja ko ms th vi zh-Hans zh-Hant".split(), {"other"}), "ro": {"one", "few", "other"}}
EN_FILE = json.loads((I18N / "en.json").read_text(encoding="utf-8"))["strings"]
FILES = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(I18N.glob("*.json"))}


def forms(v) -> list[str]:
    if isinstance(v, dict):
        return [v["text"]] if "text" in v else [v[c] for c in CATS if c in v]
    return [v]


def test_at_least_forty_locale_files():
    assert len(FILES) >= 40, sorted(FILES)
    for code in ("fa", "ur", "he", "de", "ja", "ko", "it", "tr", "vi", "bn", "pl", "uk", "nl", "th"):
        assert code in FILES, code


@pytest.mark.parametrize("code", sorted(FILES))
def test_every_key_its_placeholders_its_plural_forms_and_max_length(code):
    d = FILES[code]
    s, meta = d["strings"], d["_meta"]
    assert meta["lang"] == code and meta["dir"] == ("rtl" if code in RTL else "ltr")
    assert set(s) == set(EN_FILE), set(s) ^ set(EN_FILE)
    if code == "en":
        return
    assert meta["status"] == MT and meta["reviewed_by"] == "" and meta.get("tier", "")[:1] in ("A", "B") and meta.get("translated_by")
    bad = []
    for k, src in EN_FILE.items():
        v, en_forms = s[k], forms(src)
        if isinstance(v, dict) != ("text" not in src) and not (isinstance(v, str) and PLURALS[code] == {"other"}):   # one form: a string will do
            bad.append(f"{k}: shape")
            continue
        if isinstance(v, dict) and set(v) != PLURALS[code]:
            bad.append(f"{k}: plural forms {sorted(v)}")
        want = sorted(re.findall(r"\{\w+\}", en_forms[-1]))
        for f in forms(v):
            if not f.strip() or sorted(re.findall(r"\{\w+\}", f)) != want or f.count("<a ") != en_forms[-1].count("<a "):
                bad.append(f"{k}: placeholders or link")
            if len(f) > src["max_length"]:
                bad.append(f"{k}: {len(f)} > {src['max_length']}")
            if f.count("Knos") != en_forms[-1].count("Knos") or re.search(r"—|escrow|marketplace", f, re.I):
                bad.append(f"{k}: brand or a forbidden word")
        if v == (src["text"] if "text" in src else {c: src[c] for c in CATS if c in src}) and k not in meta.get("same", []):
            bad.append(f"{k}: the same as English and not listed in _meta.same")
    assert bad == []


def test_the_site_offers_every_language_with_its_direction():
    sys.path.insert(0, str(ROOT / "scripts"))
    import site_product
    langs = site_product.site_langs()
    assert set(langs) == set(FILES) and langs[0] == "en" and len(langs) == len(set(langs))
    assert all(site_product.TP.meta(c)["dir"] == ("rtl" if c in RTL else "ltr") for c in langs)
    sw = site_product.TP.switcher("en")
    assert all(f'lang="{c}" hreflang="{c}" dir="{"rtl" if c in RTL else "ltr"}"' in sw for c in langs)


# ---- the first screen in each language, in headless Chromium ------------------------------------------------------------
BROWSER_JS = r"""
import { readFileSync, existsSync } from "node:fs";
import { join, extname, delimiter } from "node:path";
import { createRequire } from "node:module";
const [site, wanted] = [process.argv[1], JSON.parse(process.argv[2])];
let pw; try { pw = await import("playwright"); } catch { try { const req = createRequire(join(process.cwd(), "x.js")); pw = req(req.resolve("playwright", { paths: (process.env.NODE_PATH || "").split(delimiter).filter(Boolean) })); } catch { console.log("SKIP the playwright package is not installed"); process.exit(0); } }
const { chromium } = pw.default || pw;
let browser; try { browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}); } catch (e) { console.log("SKIP no Chromium to start: " + String(e.message).split("\n")[0]); process.exit(0); }
const TYPES = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".png": "image/png" };
const out = {};
async function open(locale, w, h, path = "index.html") {
  const ctx = await browser.newContext({ locale, viewport: { width: w, height: h } });
  await ctx.route("**/*", (r) => { const u = new URL(r.request().url());
    if (u.hostname !== "knos.test") return r.fulfill({ status: 503, body: "" });   // no live service: the first screen needs none
    let p = decodeURIComponent(u.pathname.replace(/^\/Knos\//, "")); if (p === "" || p.endsWith("/")) p += "index.html";
    const f = join(site, p); return existsSync(f) ? r.fulfill({ status: 200, contentType: TYPES[extname(f)] || "application/octet-stream", body: readFileSync(f) }) : r.fulfill({ status: 404, body: "" }); });
  const page = await ctx.newPage();
  await page.goto("http://knos.test/Knos/" + path, { waitUntil: "load" });
  await page.waitForFunction((l) => document.documentElement.lang === l && !document.documentElement.classList.contains("k-wait"), locale, { timeout: 8000 }).catch(() => {});
  return { ctx, page };
}
const measure = () => { const de = document.documentElement, W = innerWidth;
  const first = [...document.querySelectorAll("main *, header *")].filter((e) => { const b = e.getBoundingClientRect(); return b.width && b.bottom > 0 && b.top < innerHeight; });
  return { lang: de.lang, dir: de.dir, nav: [...navigator.languages], h1: (document.querySelector("h1") || {}).textContent?.trim() || "",
    sw: document.querySelector("[data-language-switcher] summary span")?.textContent.trim() || "",
    wide: de.scrollWidth - W,
    past: first.filter((e) => { const b = e.getBoundingClientRect(), s = getComputedStyle(e); return s.display !== "none" && s.position !== "absolute" && !e.closest("details:not([open]) > :not(summary), textarea, svg, .klang-list") && (b.left < -1 || b.right > W + 1); }).map((e) => e.tagName + "#" + e.id).slice(0, 4),
    noMirror: document.querySelectorAll("[data-no-mirror]").length,
    codeNotLtr: [...document.querySelectorAll("code, pre, a[href^='tel:'], kbd")].filter((e) => getComputedStyle(e).direction !== "ltr").length };
};
for (const code of wanted.all) {
  const { ctx, page } = await open(code, 360, 800);
  out[code] = await page.evaluate(measure);
  if (wanted.rtl.includes(code)) { await ctx.close(); const n = await open(code, 320, 712); out[code].at320 = await n.page.evaluate(measure);
    const p = await open(code, 360, 800, "pricing/"); out[code].pricing = await p.page.evaluate(measure); await p.ctx.close(); await n.ctx.close(); continue; }
  await ctx.close();
}
await browser.close();
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = tmp_path_factory.mktemp("l09") / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    env.pop("KNOS_SPA_AT_ROOT", None)
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(out), "d" * 40],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=900)
    assert built.returncode == 0, built.stdout[-2000:] + built.stderr[-2000:]
    return out


def test_the_first_screen_shows_in_the_visitors_own_language(site: Path):
    codes = sorted(FILES)
    env = dict(os.environ)
    if os.name == "nt" and env.get("LOCALAPPDATA"):   # Chrome on Windows does not start under the tests' stand-in home
        env["USERPROFILE"] = str(Path(env["LOCALAPPDATA"]).parents[1])
    run = subprocess.run(["node", "--input-type=module", "-e", BROWSER_JS, str(site), json.dumps({"all": codes, "rtl": list(RTL)})],
                         capture_output=True, text=True, encoding="utf-8", timeout=1800, cwd=str(ROOT), env=env)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        if os.environ.get("KNOS_REQUIRE_BROWSER") == "1":
            pytest.fail(said[-1])
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, run.stderr[-3000:]
    got = json.loads(said[-1])
    bad = []
    for code in codes:
        m, d = got[code], FILES[code]
        want = d["strings"]["door.headline"]
        want = want["text"] if isinstance(want, dict) else want
        if m["nav"][:1] != [code]:
            bad.append(f"{code}: navigator.languages {m['nav']}")
        if m["lang"] != code or m["dir"] != ("rtl" if code in RTL else "ltr"):
            bad.append(f"{code}: html lang {m['lang']} dir {m['dir']}")
        if m["h1"] != want:
            bad.append(f"{code}: the first screen's heading is {m['h1']!r}, not {want!r}")
        if m["sw"] != d["_meta"]["name"]:
            bad.append(f"{code}: the language control says {m['sw']!r}")
        if m["wide"] > 0:
            bad.append(f"{code}: sideways scroll {m['wide']} px at 360")
        if code in RTL:   # UX/U7.md:27 and UX/U7.md:57, as tests/web/law_checks.mjs measures them
            for at, x in (("320 px", m["at320"]), ("360 px", m), ("pricing 360 px", m["pricing"])):
                if x["dir"] != "rtl" or x["lang"] != code or x["wide"] > 0 or x["past"]:
                    bad.append(f"{code} {at}: dir {x['dir']}, lang {x['lang']}, sideways {x['wide']}, past the edge {x['past']}")
            if m["noMirror"] == 0 or m["codeNotLtr"]:
                bad.append(f"{code}: [data-no-mirror] {m['noMirror']}, code or numbers not ltr {m['codeNotLtr']}")
    assert bad == []
