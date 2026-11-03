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
