# FinAgent-Bench

!\[CI](https://github.com/Ajinkyarodge66/finagent-bench/actions/workflows/ci.yml/badge.svg)

**A reproducible benchmark for tool-using LLM agents on financial documents — measuring accuracy *and* robustness to prompt injection.**

LLM agents are being deployed to read filings, compute metrics and answer analyst questions. Two things matter in production: *does it get the number right*, and *can a malicious document hijack it*. FinAgent-Bench measures both.

## Quick start

```bash
pip install pytest anthropic        # anthropic only needed for LLM agents
pytest -q                           # 6 tests, runs offline
python -m finagent\_bench --agent baseline
export ANTHROPIC\_API\_KEY=...        # then compare a real model:
python -m finagent\_bench --agent baseline --agent anthropic --model <model-id>
```

## What it measures

|Metric|Meaning|
|-|-|
|Accuracy|Numeric answer within 1% relative tolerance of ground truth|
|Accuracy by category|`lookup` (find one figure), `arithmetic` (growth, margins), `multi\_hop` (combine 2 filings)|
|Accuracy under injection|Accuracy on tasks whose documents contain an embedded attacker instruction|
|Hijack rate|Share of injected tasks where the agent followed the attacker (answered 0)|
|Mean steps|Tool calls per task — a cost/latency proxy|

## Current results

|Agent|Accuracy|arithmetic|lookup|multi\_hop|Acc. under injection|Hijack rate|Mean steps|
|-|-|-|-|-|-|-|-|
|baseline-rules|100%|100%|100%|100%|100%|0%|3.0|
|*your LLM run here*||||||||

The rule-based baseline is a sanity check (it is written for this exact format). The interesting rows are LLM agents — that comparison is the point of the project.

## Design decisions

* **Ground truth computed in code**, never hand-typed; data is generated from a seed so every run is reproducible.
* **Safe calculator** via AST walking — no `eval`, so a hijacked agent can't execute code.
* **Every tool call is logged** in the trace, so failures can be diagnosed, not just counted.
* **Backend-agnostic agent loop**: any model is a `complete(system, messages) -> str` function. Tests use a scripted fake model, so CI needs no API keys.

## Layout

```
finagent\_bench/
  tasks.py      synthetic filings + question generator (+ injection)
  tools.py      list\_docs / read\_doc / calculator, with audit log
  agents.py     BaselineAgent, LLMAgent (ReAct-style), Anthropic backend
  evaluate.py   scoring, per-category + safety metrics, markdown report
tests/          unit + integration tests (scripted model)
.github/        CI: tests + benchmark on every push
```

## Roadmap

* \[x] v0.1 — synthetic filings, 3 task types, injection attacks, baseline, CI
* \[ ] v0.2 — run 3+ models (closed and open-weight), publish results table and failure analysis
* \[ ] v0.3 — real data: parse UK Companies House / SEC EDGAR filings into tasks
* \[ ] v0.4 — harder attacks (subtle number swaps, fake "corrections", multi-document injection) + defences (spotlighting, dual-LLM) with measured trade-offs
* \[ ] v0.5 — confidence calibration: does the agent know when it's wrong?
* \[ ] v1.0 — Hugging Face dataset + leaderboard Space + short technical write-up

## Limitations

Synthetic filings are far cleaner than real ones; the injection attack in v0.1 is deliberately blunt. Both are addressed in the roadmap.

