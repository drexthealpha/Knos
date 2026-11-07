"""Write each claim market's page text with a small local model, from the market's price and its proof state.

    python3 near/scripts/claim_pages.py <out.json>     (in .github/workflows/claim-pages.yml; the standard library only)

Reads the markets of market.knos-swarm-1105.testnet from the testnet RPC: the two Lean claims and the newest job market.
For each, asks qwen2.5:1.5b-instruct through the Ollama on this runner (http://127.0.0.1:11434, no key) for at most two
short sentences a stranger reads: the claim, the price of Yes in cents, the proof's state. A text over 40 words or with
a word from the banned list is asked again (6 tries), else the market's own facts are written plainly instead and the
page says so. Writes [{id, claim, yes_c, status, text, words, model, written}] to <out.json>.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import sys
import urllib.request

RPC = "https://rpc.testnet.near.org"
MARKET = "market.knos-swarm-1105.testnet"
MODEL = "qwen2.5:1.5b-instruct"
CLAIMS = {"claim-split-1107": "Splitting a bid between two helpers never pays out more than the bid.",
          "claim-refund-1107": "The two helpers' pay plus the refund always equals the bid."}
BANNED = ("escrow", "hash", "json", "lmsr", "oracle", "smart contract", "blockchain", "devnet", "sibyl", "kardashev")


def view(method: str, args: dict):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "query", "params": {
        "request_type": "call_function", "finality": "final", "account_id": MARKET, "method_name": method,
        "args_base64": base64.b64encode(json.dumps(args).encode()).decode()}}).encode()
    with urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json"}), timeout=60) as r:
        return json.loads(bytes(json.loads(r.read())["result"]["result"]).decode() or "null")


def ask(prompt: str) -> str:
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.2, "num_predict": 90}}).encode()
    with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", body, {"Content-Type": "application/json"}), timeout=300) as r:
        return " ".join(str(json.loads(r.read()).get("response") or "").split())


def page(mid: str, v: dict) -> dict:
    m = v["market"]
    yes_c = round(int(v["yes_price"]) / 10_000)
    claim = CLAIMS.get(mid, "A helper's work passes this job's test.")
    what = "the helper's work" if mid.startswith("job:") else "the proof"
    status = (f"settled Yes: {what} passed its check" if m["outcome"] is True else f"settled No: {what} failed its check"
              if m["outcome"] is False else f"open: {what} has not been checked yet")
    prompt = (f"Write exactly two short sentences, under 35 words in all, for someone who knows nothing about software.\n"
              f"The first sentence is this, word for word: {claim}\n"
              + (f"The second sentence says that a Yes share costs {yes_c} cents and that the market is {status}.\n" if m["outcome"] is None
                 else f"The second sentence says that the market is {status}, and that Yes last traded at {yes_c} cents.\n")
              + "No other facts, no hype, no labels.")
    for _ in range(6):
        text = re.sub(r"^(claim|answer)\s*:\s*", "", ask(prompt).strip('"'), flags=re.I)
        words = len(re.findall(r"[\w'$%.,-]+", text))
        if (0 < words <= 40 and not any(b in text.lower() for b in BANNED) and f"{yes_c}" in text
                and text.lower().startswith(claim.lower().rstrip("."))):
            return {"id": mid, "claim": claim, "yes_c": yes_c, "status": status, "text": text, "words": words, "model": MODEL,
                    "written": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
        print(f"{mid}: not kept ({words} words): {text}", file=sys.stderr)
    text = f"{claim} Yes costs {yes_c}c. The market is {status}."
    return {"id": mid, "claim": claim, "yes_c": yes_c, "status": status, "text": text, "words": len(text.split()), "model": "none: the model's 6 answers broke the limits",
            "written": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}


def picked() -> list[str]:
    ids = view("get_markets", {})
    jobs = [i for i in ids if i.startswith("job:")]
    return [i for i in ("claim-split-1107", "claim-refund-1107") if i in ids] + jobs[-1:]


def main() -> int:
    if sys.argv[1] == "--fingerprint":       # what changes a page: a trade or a settlement in any market it shows
        marks = [(mid, (m := view("get_market", {"id": mid})["market"])["trades"], m["outcome"]) for mid in picked()]
        print("markets " + ";".join(f"{i}:{t}:{o}" for i, t, o in marks))
        return 0
    out = [page(mid, view("get_market", {"id": mid})) for mid in picked()]
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    for p in out:
        print(f"{p['id']}: {p['words']} words, Yes {p['yes_c']}c, {p['status']}: {p['text']}")
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
