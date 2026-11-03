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
    # Cloudflare (in front of Groq) rejects Python's default User-Agent with error 1010
    assert calls[0].get_header("User-agent").startswith("finagent-bench/")


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


def test_native_tool_calls_are_translated(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    seen = []

    def fake_urlopen(req, timeout):
        seen.append(json.loads(req.data))
        call = {"function": {"name": "repo.read_doc", "arguments": '{"arg": "a.txt"}'}}
        return _Resp(json.dumps({"choices": [{"message": {"content": None, "tool_calls": [call]}}]}).encode())

    complete = openai_compat_backend("groq", "m", rpm=0, _urlopen=fake_urlopen)
    assert json.loads(complete("s", [])) == {"tool": "read_doc", "arg": "a.txt"}
    assert {t["function"]["name"] for t in seen[0]["tools"]} == {"list_docs", "read_doc", "calculator", "final_answer"}


def test_final_answer_tool_call():
    from finagent_bench.backends import tool_call_to_json
    out = tool_call_to_json({"function": {"name": "final_answer", "arguments": '{"value": 12.5}'}})
    assert json.loads(out) == {"final_answer": 12.5}


def test_rejected_tool_call_is_recovered(monkeypatch):
    """Groq returns 400 tool_use_failed for undeclared tools; the model must get to self-correct."""
    monkeypatch.setenv("GROQ_API_KEY", "test")
    body = json.dumps({"error": {"code": "tool_use_failed", "message": "x",
                                 "failed_generation": '{"name": "answer", "arguments": {"value": 1}}'}}).encode()

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(body))

    complete = openai_compat_backend("groq", "m", rpm=0, _urlopen=fake_urlopen)
    assert json.loads(complete("s", [])) == {"tool": "answer"}


def test_invalid_tool_is_logged_and_model_can_recover():
    task = build_tasks()[0]
    script = iter(['{"tool": "answer"}', f'{{"final_answer": {task.answer}}}'])
    r = evaluate(LLMAgent(lambda s, m: next(script), name="x"), [task])
    assert r["summary"]["accuracy"] == 1.0 and r["summary"]["invalid_tool_calls"] == 1


def test_repeated_runs_report_spread():
    from finagent_bench.evaluate import evaluate_repeated, to_markdown
    task = build_tasks()[0]
    answers = iter([task.answer, 0.0])
    agent = LLMAgent(lambda s, m: f'{{"final_answer": {next(answers)}}}', name="flaky")
    r = evaluate_repeated(agent, [task], 2)
    assert r["summary"]["accuracy"] == 0.5 and r["summary"]["accuracy_range"] == [0.0, 1.0]
    assert "(0%-100%)" in to_markdown([r]) and "n=2" in to_markdown([r])


def test_history_is_rebuilt_as_native_tool_messages():
    from finagent_bench.backends import to_native_messages
    msgs = [{"role": "user", "content": "q"},
            {"role": "assistant", "content": '{"tool": "read_doc", "arg": "a.txt"}'},
            {"role": "user", "content": "Observation: hello"},
            {"role": "assistant", "content": "thinking out loud"},
            {"role": "user", "content": "Call one of the tools."}]
    out = to_native_messages(msgs)
    assert out[1]["tool_calls"][0]["function"] == {"name": "read_doc", "arguments": '{"arg": "a.txt"}'}
    assert out[2] == {"role": "tool", "tool_call_id": out[1]["tool_calls"][0]["id"], "content": "hello"}
    assert out[3]["content"] == "thinking out loud" and out[4]["role"] == "user"


def test_native_backend_gets_native_prompt(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    from finagent_bench.agents import NATIVE_TOOLS_PROMPT
    agent = LLMAgent(openai_compat_backend("groq", "m", rpm=0, _urlopen=None))
    assert agent.native and NATIVE_TOOLS_PROMPT in agent.system and "Tools (reply" not in agent.system
