"""Write the product page for the NEAR job's research result with the small local model the claim pages use.

    python3 near/scripts/product_page.py <out.json>     (in .github/workflows/product-page.yml; the standard library only)

The job (near/agents/job/test_hll.py) asks helpers to build what one published result promises. This asks
qwen2.5:1.5b-instruct, through the Ollama on the runner (http://127.0.0.1:11434, no key), for a product name of at most
5 words and a pitch of at most 2 sentences and 40 words, for a person who knows nothing about software, from the
paper's own sentence. An answer that breaks a limit or uses a banned word is asked again (6 tries). If none is kept,
the page shows no text and says so: nothing is written in the model's place. Writes {paper, doi, quote, name, pitch,
model, kept, written} to <out.json>.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.request

MODEL = "qwen2.5:1.5b-instruct"
PAPER = "HyperLogLog: the analysis of a near-optimal cardinality estimation algorithm (Flajolet, Fusy, Gandouet, Meunier, 2007)"
DOI = "https://doi.org/10.46298/dmtcs.3545"
QUOTE = ("For instance, the new algorithm makes it possible to estimate cardinalities well beyond 10^9 with a typical "
         "accuracy of 2% while using a memory of only 1.5 kilobytes.")
BANNED = ("escrow", "hash", "blockchain", "token", "crypto", "revolution", "cardinalit", "algorithm", "guarantee", "billion")


def ask(prompt: str) -> str:
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.3, "num_predict": 120}}).encode()
    with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", body, {"Content-Type": "application/json"}),
                                timeout=300) as r:
        return " ".join(str(json.loads(r.read()).get("response") or "").split())


def kept(name: str, pitch: str) -> bool:
    words = len(re.findall(r"[\w'$%.,-]+", pitch))
    sentences = len([s for s in re.split(r"(?<=[.!?])\s+", pitch) if s])
    low = (name + " " + pitch).lower()
    return (0 < len(name.split()) <= 5 and 0 < words <= 40 and sentences <= 2 and "1.5" in pitch
            and not any(b in low for b in BANNED))


def main() -> int:
    prompt = ("A research paper says, word for word: \"" + QUOTE + "\"\n"
              "In plain words: it counts how many different visitors a website had, almost exactly, using only 1.5 kilobytes "
              "of memory.\nWrite a product page for a small business owner who knows nothing about software. Answer with "
              "exactly two lines:\nNAME: a product name of at most 5 words\nPITCH: at most 2 short sentences, under 40 words, "
              "that say what it does for them and mention 1.5 kilobytes. No hype, no other facts.")
    out = {"paper": PAPER, "doi": DOI, "quote": QUOTE, "model": MODEL, "kept": False, "name": "", "pitch": "", "tries": 0}
    for i in range(6):
        text = ask(prompt)
        out["tries"] = i + 1
        n = re.search(r"NAME:\s*(.+?)\s*(?:PITCH:|$)", text, re.I)
        p = re.search(r"PITCH:\s*(.+)$", text, re.I)
        name, pitch = (n.group(1).strip(" *\"") if n else ""), (p.group(1).strip(" *\"") if p else "")
        if kept(name, pitch):
            out.update(kept=True, name=name, pitch=pitch)
            break
        print(f"try {i + 1} not kept: {text}", file=sys.stderr)
    out["written"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
