"""Model backends. Any provider with an OpenAI-compatible chat endpoint works.

Uses only the standard library (no SDK needed), throttles to stay under free-tier
rate limits, and retries on 429/5xx honouring the server's Retry-After header.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable

from . import __version__

# name -> (base_url, env var holding the API key, default requests-per-minute)
PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", 25),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", 10),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", 15),
    "ollama": ("http://localhost:11434/v1", None, 0),  # local, no key, no throttle
}

Complete = Callable[[str, list[dict]], str]

# Native function-calling schemas. Models like gpt-oss are trained to emit real tool
# calls and refuse to follow a plain-text JSON protocol, so we give them real tools and
# translate each call back into the agent's JSON protocol.
_STR_ARG = {"type": "object", "properties": {"arg": {"type": "string"}}, "required": ["arg"]}
TOOLS = [
    {"type": "function", "function": {"name": "list_docs", "description": "List available documents.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_doc", "description": "Read a document by filename.",
                                      "parameters": _STR_ARG}},
    {"type": "function", "function": {"name": "calculator",
                                      "description": "Evaluate an arithmetic expression, e.g. (12.5/10-1)*100.",
                                      "parameters": _STR_ARG}},
    {"type": "function", "function": {"name": "final_answer", "description": "Submit the final numeric answer.",
                                      "parameters": {"type": "object", "properties": {"value": {"type": "number"}},
                                                     "required": ["value"]}}},
]


def tool_call_to_json(call: dict) -> str:
    """Translate an OpenAI-style tool call into the agent's JSON protocol."""
    name = call["function"]["name"].split(".")[-1]  # some models prefix a namespace
    try:
        args = json.loads(call["function"].get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    if name == "final_answer":
        return json.dumps({"final_answer": args.get("value")})
    out = {"tool": name}
    if "arg" in args:
        out["arg"] = args["arg"]
    return json.dumps(out)


def _recover_failed_generation(raw: bytes) -> str | None:
    """Groq rejects calls to undeclared tools server-side (code `tool_use_failed`) but returns
    the model's attempt. Hand that attempt back to the agent so it can reply "unknown tool"
    and the model gets a chance to self-correct, as it would in a real agent framework."""
    try:
        err = json.loads(raw)["error"]
        if err.get("code") != "tool_use_failed":
            return None
        gen = json.loads(err["failed_generation"])
        args = gen.get("arguments", {})
        return tool_call_to_json({"function": {"name": gen["name"],
                                               "arguments": args if isinstance(args, str) else json.dumps(args)}})
    except Exception:
        return None


def openai_compat_backend(
    provider: str,
    model: str,
    rpm: float | None = None,
    native_tools: bool = True,
    max_retries: int = 6,
    timeout: float = 120,
    _urlopen=urllib.request.urlopen,  # injectable for tests
) -> Complete:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose from {sorted(PROVIDERS)}")
    base_url, key_env, default_rpm = PROVIDERS[provider]
    key = os.environ.get(key_env) if key_env else None
    if key_env and not key:
        raise SystemExit(f"Set the {key_env} environment variable first (see README).")
    rpm = default_rpm if rpm is None else rpm
    min_gap = 60.0 / rpm if rpm else 0.0
    last = [0.0]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "requests": 0}

    def complete(system: str, messages: list[dict]) -> str:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0,
            "max_tokens": 2048,
            **({"tools": TOOLS, "tool_choice": "auto"} if native_tools else {}),
        }).encode()
        headers = {"Content-Type": "application/json", "User-Agent": f"finagent-bench/{__version__}"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        for attempt in range(max_retries + 1):
            wait = min_gap - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
            req = urllib.request.Request(f"{base_url}/chat/completions", body, headers)
            try:
                with _urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read())
                u = data.get("usage") or {}
                usage["prompt_tokens"] += u.get("prompt_tokens", 0)
                usage["completion_tokens"] += u.get("completion_tokens", 0)
                usage["requests"] += 1
                msg = data["choices"][0]["message"]
                if msg.get("tool_calls"):
                    return tool_call_to_json(msg["tool_calls"][0])
                return msg.get("content") or ""
            except urllib.error.HTTPError as e:
                raw = e.read() if hasattr(e, "read") and e.fp is not None else b""
                if e.code == 400:
                    recovered = _recover_failed_generation(raw)
                    if recovered is not None:  # model made an invalid tool call: let the agent handle it
                        usage["requests"] += 1
                        return recovered
                if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    time.sleep(float(retry_after) if retry_after else min(2 ** attempt, 60))
                    continue
                detail = raw[:300].decode(errors="replace")
                raise RuntimeError(f"HTTP {e.code}: {detail}") from e
        raise RuntimeError("retries exhausted")

    complete.usage = usage  # type: ignore[attr-defined]
    return complete


def anthropic_backend(model: str) -> Complete:
    import anthropic  # optional dependency

    client = anthropic.Anthropic()

    def complete(system: str, messages: list[dict]) -> str:
        r = client.messages.create(model=model, max_tokens=1024, system=system, messages=messages)
        return "".join(b.text for b in r.content if b.type == "text")

    return complete
