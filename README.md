# FinAgent-Bench

![CI](https://github.com/Ajinkyarodge66/finagent-bench/actions/workflows/ci.yml/badge.svg)

**A reproducible benchmark for tool-using LLM agents on financial documents — measuring accuracy *and* robustness to prompt injection.**

LLM agents are being deployed to read filings, compute metrics and answer analyst questions. Two things matter in production: *does it get the number right*, and *can a malicious document hijack it*. FinAgent-Bench measures both.

## Quick start

```bash
python -m pytest -q                 # 12 tests, runs offline, no API key
python -m finagent_bench            # offline baseline only
```

### Run a real model (free tiers, no credit card)

Get a free key from [Groq](https://console.groq.com/keys) or [Google AI Studio](https://aistudio.google.com/apikey), then:

```powershell
# Windows PowerShell (use `export GROQ_API_KEY=...` on macOS/Linux)
$env:GROQ_API_KEY = "gsk_..."
python -m finagent_bench --provider groq --model openai/gpt-oss-20b --limit 3   # smoke test
python -m finagent_bench --provider groq --model openai/gpt-oss-20b             # full run

$env:GEMINI_API_KEY = "..."
python -m finagent_bench --provider gemini --model gemini-2.5-flash
```

Supported providers: `groq`, `gemini`, `openrouter`, `ollama` (local), `anthropic`. Any OpenAI-compatible endpoint can be added in `backends.py`. Requests are throttled to stay inside free-tier limits and retried on HTTP 429.

Each run writes to `results/`:
- `<model>.json`: every task with prediction, tool calls and full transcript
- `<model>_failures.md`: failures grouped by type, with the evidence for each

Never commit API keys. Keys are read only from environment variables.

## What it measures

| Metric | Meaning |
|---|---|
| Accuracy | Numeric answer within 1% relative tolerance of ground truth |
| Accuracy by category | `lookup` (find one figure), `arithmetic` (growth, margins), `multi_hop` (combine 2 filings) |
| Accuracy under injection | Accuracy on tasks whose documents contain an embedded attacker instruction |
| Hijack rate | Share of injected tasks where the agent followed the attacker (answered 0) |
| Mean steps | Model turns per task, a cost/latency proxy |
| Failure types | Each wrong answer is classified: `hijacked_by_injection`, `answered_without_reading`, `mental_arithmetic`, `unit_or_percent_scale`, `rounding_or_precision`, `wrong_value`, `ran_out_of_steps`, `no_numeric_answer`, `api_error` |

## Current results

| Agent | Accuracy | arithmetic | lookup | multi_hop | Acc. under injection | Hijack rate | Mean steps |
|---|---|---|---|---|---|---|---|
| baseline-rules | 100% | 100% | 100% | 100% | 100% | 0% | 3.0 |
| *LLM runs: coming in v0.2* | | | | | | | |

The rule-based baseline is a sanity check (it is written for this exact format). The interesting rows are LLM agents — that comparison is the point of the project.

## Design decisions

- **Ground truth computed in code**, never hand-typed; data is generated from a seed so every run is reproducible.
- **Safe calculator** via AST walking — no `eval`, so a hijacked agent can't execute code.
- **Every tool call is logged** in the trace, so failures can be diagnosed, not just counted.
- **Backend-agnostic agent loop**: any model is a `complete(system, messages) -> str` function. Tests use a scripted fake model, so CI needs no API keys.

## Layout

```
finagent_bench/
  tasks.py      synthetic filings + question generator (+ injection)
  tools.py      list_docs / read_doc / calculator, with audit log
  agents.py     BaselineAgent, LLMAgent (ReAct-style loop, tool allow-list)
  backends.py   OpenAI-compatible + Anthropic backends, throttling, retries
  evaluate.py   scoring, safety metrics, failure classification, reports
tests/          unit + integration tests (scripted model, fake HTTP server)
.github/        CI: tests + benchmark on every push
```

## Roadmap

- [x] v0.1 — synthetic filings, 3 task types, injection attacks, baseline, CI
- [x] v0.2 (code) — provider-agnostic backend, rate limiting/retries, failure classification and reports
- [ ] v0.2 (results) — run 3+ models, publish results table and failure analysis
- [ ] v0.3 — real data: parse UK Companies House / SEC EDGAR filings into tasks
- [ ] v0.4 — harder attacks (subtle number swaps, fake "corrections", multi-document injection) + defences (spotlighting, dual-LLM) with measured trade-offs
- [ ] v0.5 — confidence calibration: does the agent know when it's wrong?
- [ ] v1.0 — Hugging Face dataset + leaderboard Space + short technical write-up

## Limitations

Synthetic filings are far cleaner than real ones; the injection attack in v0.1 is deliberately blunt. Both are addressed in the roadmap.
