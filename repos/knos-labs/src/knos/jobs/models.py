"""The worker's model, on the operator's own key (BYOK). Knos never resells model access: workers sell finished work.

    KNOS_WORKER_MODEL=anthropic:claude-sonnet-4-5      key in ANTHROPIC_API_KEY
    KNOS_WORKER_MODEL=openai:gpt-4.1-mini              key in OPENAI_API_KEY
    KNOS_WORKER_MODEL=openrouter:<model>               key in OPENROUTER_API_KEY (free models exist)
    KNOS_WORKER_MODEL=groq:<model>                     key in GROQ_API_KEY (free tier)
    KNOS_WORKER_MODEL=gemini:gemini-3.8-flash          key in GEMINI_API_KEY (free tier)
    KNOS_WORKER_MODEL=claude-code                      the operator's own Claude Code (`claude -p`), on their plan
    KNOS_WORKER_MODEL=codex                            the operator's own Codex CLI (`codex exec`), on their plan
    KNOS_WORKER_MODEL=scripted                         no model: for tests and demos (labelled as such)

Plain HTTPS calls; no SDK dependency.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable

SYSTEM = ("You are a professional worker completing a paid job. Return only the deliverable itself: no preamble, no "
          "explanation, no markdown fences unless the brief asks for them. Follow every standing preference of this "
          "buyer exactly.")

Model = Callable[[str], str]


def _post(url: str, headers: dict, body: dict, timeout: float = 120.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json",
                                                                              **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - the operator's chosen provider
        return json.loads(r.read())


def _openai_like(base: str, key_env: str, model: str) -> Model:
    key = os.environ.get(key_env, "")
    if not key:
        raise LookupError(f"set {key_env} to use this model")

    def call(prompt: str) -> str:
        got = _post(f"{base}/chat/completions", {"Authorization": f"Bearer {key}"},
                    {"model": model, "messages": [{"role": "system", "content": SYSTEM},
                                                  {"role": "user", "content": prompt}], "temperature": 0.2})
        return got["choices"][0]["message"]["content"]
    return call


def _gemini(model: str) -> Model:
    """Gemini's native API (free tier). Busy (429/503) is retried, then the lite model is tried."""
    import time
    import urllib.error
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise LookupError("set GEMINI_API_KEY to use this model")

    def once(m: str, prompt: str) -> str:
        got = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                    {"x-goog-api-key": key},
                    {"systemInstruction": {"parts": [{"text": SYSTEM}]},
                     "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                     "generationConfig": {"temperature": 0.2}})
        return "".join(p.get("text", "") for p in got["candidates"][0]["content"]["parts"])

    def call(prompt: str) -> str:
        last: Exception | None = None
        for m in (model, "gemini-3.5-flash-lite"):
            for wait in (0, 2, 5):
                time.sleep(wait)
                try:
                    return once(m, prompt)
                except urllib.error.HTTPError as e:
                    last = e
                    if e.code not in (429, 500, 503):
                        raise
        raise last  # type: ignore[misc]
    return call


def from_env(spec: str | None = None) -> Model:
    spec = spec or os.environ.get("KNOS_WORKER_MODEL", "")
    if not spec:
        raise LookupError("set KNOS_WORKER_MODEL (e.g. groq:llama-3.3-70b-versatile) and its API key")
    provider, _, model = spec.partition(":")
    if provider == "scripted":
        return scripted
    if provider in ("claude-code", "codex"):
        return _agent_cli(provider)
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise LookupError("set ANTHROPIC_API_KEY")

        def call(prompt: str) -> str:
            got = _post("https://api.anthropic.com/v1/messages",
                        {"x-api-key": key, "anthropic-version": "2023-06-01"},
                        {"model": model, "max_tokens": 4096, "system": SYSTEM,
                         "messages": [{"role": "user", "content": prompt}]})
            return "".join(b.get("text", "") for b in got.get("content", []))
        return call
    if provider == "openai":
        return _openai_like("https://api.openai.com/v1", "OPENAI_API_KEY", model)
    if provider == "openrouter":
        return _openai_like("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", model)
    if provider == "groq":
        return _openai_like("https://api.groq.com/openai/v1", "GROQ_API_KEY", model)
    if provider == "gemini":
        return _gemini(model or "gemini-3.8-flash")
    raise LookupError(f"unknown model provider {provider!r}")


def _agent_cli(provider: str) -> Model:
    """An agent the operator already runs, headless, in an empty folder (so it reads none of their files)."""
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("claude" if provider == "claude-code" else "codex")
    if not exe:
        raise LookupError(f"{provider} is not installed on this machine")

    def call(prompt: str) -> str:
        full = SYSTEM + "\n\n" + prompt
        args = [exe, "-p", full] if provider == "claude-code" else [exe, "exec", full]
        with tempfile.TemporaryDirectory() as tmp:
            got = subprocess.run(args, cwd=tmp, capture_output=True, text=True, timeout=600)
        if got.returncode != 0:
            raise RuntimeError(f"{provider} failed: {got.stderr[-300:]}")
        return got.stdout
    return call


def scripted(prompt: str) -> str:
    """A deterministic stand-in: returns the brief's `scripted_answer` if the prompt carries one."""
    marker = "SCRIPTED_ANSWER:"
    if marker in prompt:
        return prompt.split(marker, 1)[1].split("\n:END", 1)[0].strip("\n")
    for line in prompt.splitlines():
        if line.startswith("It must include: "):
            return " ".join(line[len("It must include: "):].split("; "))
    return "done"


def strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip() + ("\n" if t.strip() else "")
