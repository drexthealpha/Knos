"""One Messages API request to Anthropic, with the key from the environment (ANTHROPIC_API_KEY). The key goes only in the
request header: never into an answer, a log line or an error. Used by the app's model step (knos_wanted.model), which
holds the caps; this module only sends."""
from __future__ import annotations

import json
import os
import urllib.request


class NoKey(RuntimeError):
    pass


def messages(prompt: str, model: str, max_tokens: int = 400, timeout: float = 60) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise NoKey("no model key is set on this server")
    body = json.dumps({"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", body,
                                 {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
    return "".join(b.get("text", "") for b in out.get("content") or [] if b.get("type") == "text")
