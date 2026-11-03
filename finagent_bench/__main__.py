"""CLI:  python -m finagent_bench --agent baseline [--agent anthropic] [--out results.json]"""
from __future__ import annotations

import argparse

from .agents import BaselineAgent, LLMAgent, anthropic_backend
from .evaluate import evaluate, save, to_markdown
from .tasks import build_tasks


def main() -> None:
    p = argparse.ArgumentParser(description="FinAgent-Bench: evaluate tool-using LLM agents on financial filings")
    p.add_argument("--agent", action="append", choices=["baseline", "anthropic"], default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--injection-rate", type=float, default=0.3)
    p.add_argument("--out", default="results.json")
    a = p.parse_args()

    tasks = build_tasks(a.seed, a.injection_rate)
    agents = []
    for name in a.agent or ["baseline"]:
        if name == "baseline":
            agents.append(BaselineAgent())
        else:
            agents.append(LLMAgent(anthropic_backend(a.model), name=a.model or "anthropic"))

    results = [evaluate(ag, tasks) for ag in agents]
    print(f"{len(tasks)} tasks ({sum(t.injected for t in tasks)} with prompt injection)\n")
    print(to_markdown(results))
    save(results, a.out)
    print(f"\nPer-task results written to {a.out}")


if __name__ == "__main__":
    main()
