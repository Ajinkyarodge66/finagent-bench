"""Re-score saved results with the current scoring rules, without calling any model.

  python -m finagent_bench.rescore results/groq_openai_gpt-oss-20b_correction.json --attack correction
"""
from __future__ import annotations

import argparse
import json

from .evaluate import failure_report, rescore, to_markdown
from .tasks import ATTACKS, build_tasks


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("files", nargs="+")
    p.add_argument("--attack", choices=ATTACKS, default="blunt")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--injection-rate", type=float, default=0.3)
    a = p.parse_args()
    tasks = build_tasks(a.seed, a.injection_rate, a.attack)
    results = []
    for path in a.files:
        with open(path, encoding="utf-8") as f:
            r = rescore(json.load(f), tasks)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2, default=str)
        with open(path[:-len(".json")] + "_failures.md", "w", encoding="utf-8") as f:
            f.write(failure_report(r))
        results.append(r)
    print(to_markdown(results))


if __name__ == "__main__":
    main()
