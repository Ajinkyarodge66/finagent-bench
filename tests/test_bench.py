import pytest

from finagent_bench.agents import BaselineAgent, LLMAgent
from finagent_bench.evaluate import evaluate, is_correct
from finagent_bench.tasks import INJECTION, build_tasks
from finagent_bench.tools import safe_eval


def test_tasks_are_deterministic():
    a, b = build_tasks(seed=1), build_tasks(seed=1)
    assert [t.answer for t in a] == [t.answer for t in b]


def test_injection_present_only_when_flagged():
    for t in build_tasks():
        assert any(INJECTION in d for d in t.docs.values()) == t.injected


def test_safe_eval_blocks_code():
    assert safe_eval("(2+3)*4/2") == 10
    with pytest.raises(ValueError):
        safe_eval("__import__('os').system('ls')")


def test_baseline_solves_everything():
    s = evaluate(BaselineAgent(), build_tasks())["summary"]
    assert s["accuracy"] == 1.0 and s["hijack_rate"] == 0.0


def test_llm_agent_loop_with_scripted_model():
    """A fake model that obeys the injection should be scored as hijacked."""
    task = next(t for t in build_tasks(injection_rate=1.0))
    script = iter(['{"tool": "list_docs"}', f'{{"tool": "read_doc", "arg": "{next(iter(task.docs))}"}}',
                   '{"final_answer": 0}'])
    agent = LLMAgent(lambda system, msgs: next(script), name="gullible")
    s = evaluate(agent, [task])["summary"]
    assert s["hijack_rate"] == 1.0 and s["accuracy"] == 0.0


def test_tolerance():
    assert is_correct(100.5, 100.0, 0.01) and not is_correct(102, 100.0, 0.01) and not is_correct(None, 1, 0.1)


# ---------------- v0.2: backends, robustness, failure analysis ----------------
import io
import json
import urllib.error

from finagent_bench.agents import _first_json_object
from finagent_bench.backends import openai_compat_backend
from finagent_bench.evaluate import failure_report


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok(text):
    return _Resp(json.dumps({"choices": [{"message": {"content": text}}],
                             "usage": {"prompt_tokens": 10, "completion_tokens": 2}}).encode())


def test_backend_retries_on_429(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {"Retry-After": "0"}, None)
        return _ok('{"final_answer": 1}')

    complete = openai_compat_backend("groq", "m", rpm=0, _urlopen=fake_urlopen)
    assert complete("sys", [{"role": "user", "content": "q"}]) == '{"final_answer": 1}'
    assert len(calls) == 2 and complete.usage["requests"] == 1
    assert calls[0].headers["Authorization"] == "Bearer test"


def test_missing_key_gives_clear_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GROQ_API_KEY"):
        openai_compat_backend("groq", "m")


def test_json_extraction_handles_prose_and_fences():
    assert _first_json_object('Sure!\n```json\n{"tool": "list_docs"}\n```') == {"tool": "list_docs"}
    assert _first_json_object('{"a": 1} then {"b": 2}') == {"a": 1}
    assert _first_json_object("no json here") is None


def test_agent_cannot_call_private_attributes():
    task = build_tasks()[0]
    script = iter(['{"tool": "log", "arg": "x"}', '{"final_answer": 5}'])
    res = LLMAgent(lambda s, m: next(script)).run(task)
    assert "unknown tool" in res.transcript[2]["content"]


def test_api_error_is_recorded_not_raised():
    def boom(s, m):
        raise RuntimeError("HTTP 500")
    s = evaluate(LLMAgent(boom, name="down"), build_tasks()[:2])["summary"]
    assert s["failures"] == {"api_error": 2}


def test_failure_report_explains_wrong_answers():
    task = build_tasks()[1]  # arithmetic
    script = iter([f'{{"tool": "read_doc", "arg": "{next(iter(task.docs))}"}}',
                   f'{{"final_answer": {task.answer / 100}}}'])
    r = evaluate(LLMAgent(lambda s, m: next(script), name="x"), [task])
    assert r["rows"][0]["failure"] == "mental_arithmetic"
    assert "Expected" in failure_report(r)
