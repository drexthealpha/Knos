"""U3 Rule 14 (LAWS/UX/U3.md, its automatic check): a word limit in the UX laws is an English figure, so each language
Knos ships gets a factor, the words of its locale file divided by the words of the English file, and the word checks
multiply their limits by it. This writes that factor for every file of web/i18n/ to ux/lang-factor.json.

Words are counted as the browser counts them: Intl.Segmenter at word granularity, the word-like segments, for every
language (the languages written without spaces need it), run in Node. A plural message counts its "other" form.

    python3 scripts/site_lang_factor.py           write ux/lang-factor.json
    python3 scripts/site_lang_factor.py --check   fail when the file is not what the locale files give
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "web" / "i18n"
OUT = ROOT / "ux" / "lang-factor.json"
COUNT_JS = r"""const d = JSON.parse(require("fs").readFileSync(0, "utf8")); const out = {};
for (const [lang, texts] of Object.entries(d)) { const seg = new Intl.Segmenter(lang, { granularity: "word" });
  out[lang] = texts.reduce((n, t) => n + [...seg.segment(t)].filter((s) => s.isWordLike).length, 0); }
process.stdout.write(JSON.stringify(out));"""


def texts(lang: str) -> list[str]:
    """Every string of a locale file (its _meta left out), a plural message by its "other" form."""
    strings = json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))["strings"]
    return [v.get("other", "") if isinstance(v, dict) else str(v) for v in strings.values()]


def factors() -> dict:
    langs = sorted(p.stem for p in I18N.glob("*.json"))
    node = shutil.which("node")
    if not node:
        raise SystemExit("site_lang_factor: Node is needed (Intl.Segmenter counts the words)")
    run = subprocess.run([node, "-e", COUNT_JS], input=json.dumps({lang: texts(lang) for lang in langs}), capture_output=True, text=True,
                         encoding="utf-8", check=True)
    words = json.loads(run.stdout)
    return {"_source": "scripts/site_lang_factor.py: the words of each web/i18n file (Intl.Segmenter, word-like segments) "
                       "divided by the words of en.json; U3 Rule 14",
            "words": words, "factor": {lang: round(words[lang] / words["en"], 3) for lang in langs}}


def main(argv: list[str]) -> int:
    got = json.dumps(factors(), ensure_ascii=False, indent=1) + "\n"
    if argv[:1] == ["--check"]:
        same = OUT.is_file() and OUT.read_text(encoding="utf-8") == got
        print("ux/lang-factor.json is what the locale files give" if same else "ux/lang-factor.json is out of date: run python3 scripts/site_lang_factor.py")
        return 0 if same else 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(got, encoding="utf-8", newline="\n")
    print(f"ux/lang-factor.json: {json.loads(got)['factor']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
