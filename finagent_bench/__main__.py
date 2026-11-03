"""CLI.

  python -m finagent_bench                                   # offline baseline
  python -m finagent_bench --provider groq --model openai/gpt-oss-20b
  python -m finagent_bench --provider gemini --model gemini-2.5-flash --limit 5
"""
from __future__ import annotations

import argparse
import json
import os
import re

from .agents import BaselineAgent, LLMAgent
from .backends import PROVIDERS, anthropic_backend, openai_compat_backend
from .evaluate import evaluate, failure_report, to_markdown
from .tasks import build_tasks


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


def main() -> None:
    p = argparse.ArgumentParser(description="FinAgent-Bench: evaluate tool-using LLM agents on financial filings")
    p.add_argument("--provider", choices=[*PROVIDERS, "anthropic"], help="omit to run only the offline baseline")
    p.add_argument("--model", help="model id at the provider, e.g. openai/gpt-oss-20b")
    p.add_argument("--rpm", type=float, help="max requests per minute (default: safe value per provider)")
    p.add_argument("--limit", type=int, help="run only the first N tasks (quick smoke test)")
    p.add_argument("--max-steps", type=int, default=10)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--injection-rate", type=float, default=0.3)
    p.add_argument("--no-baseline", action="store_true", help="skip the baseline row")
    p.add_argument("--outdir", default="results")
    a = p.parse_args()

    tasks = build_tasks(a.seed, a.injection_rate)[: a.limit]
    agents = [] if (a.no_baseline and a.provider) else [BaselineAgent()]
    complete = None
    if a.provider:
        if not a.model:
            p.error("--model is required with --provider")
        complete = (anthropic_backend(a.model) if a.provider == "anthropic"
                    else openai_compat_backend(a.provider, a.model, a.rpm))
        agents.append(LLMAgent(complete, name=f"{a.provider}/{a.model}", max_steps=a.max_steps))

    print(f"{len(tasks)} tasks ({sum(t.injected for t in tasks)} with prompt injection)\n")
    results = []
    for ag in agents:
        print(f"Running {ag.name} ...", flush=True)
        results.append(evaluate(ag, tasks))
    print("\n" + to_markdown(results))

    os.makedirs(a.outdir, exist_ok=True)
    for r in results:
        stem = os.path.join(a.outdir, _slug(r["summary"]["agent"]))
        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2, default=str)
        with open(stem + "_failures.md", "w", encoding="utf-8") as f:
            f.write(failure_report(r))
    if complete is not None and getattr(complete, "usage", None):
        u = complete.usage
        print(f"\nAPI usage: {u['requests']} requests, {u['prompt_tokens']} prompt + "
              f"{u['completion_tokens']} completion tokens")
    print(f"\nResults and failure reports written to {a.outdir}/")


if __name__ == "__main__":
    main()
