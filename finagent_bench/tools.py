"""Tools an agent may call. Every call is logged so behaviour can be audited."""
from __future__ import annotations

import ast
import operator as op
from dataclasses import dataclass, field

_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.Pow: op.pow, ast.USub: op.neg, ast.UAdd: op.pos,
}


def safe_eval(expr: str) -> float:
    """Evaluate arithmetic without `eval` (no names, calls or attributes allowed)."""

    def _ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_ev(node.left), _ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_ev(node.operand))
        raise ValueError(f"disallowed expression: {ast.dump(node)[:60]}")

    return _ev(ast.parse(expr, mode="eval"))


@dataclass
class Toolbox:
    docs: dict[str, str]
    log: list[dict] = field(default_factory=list)

    def list_docs(self) -> list[str]:
        self.log.append({"tool": "list_docs"})
        return sorted(self.docs)

    def read_doc(self, name: str) -> str:
        self.log.append({"tool": "read_doc", "arg": name})
        return self.docs.get(name, f"ERROR: no document named {name!r}")

    def calculator(self, expr: str) -> float | str:
        self.log.append({"tool": "calculator", "arg": expr})
        try:
            return safe_eval(expr)
        except Exception as e:  # report errors back to the agent, don't crash
            return f"ERROR: {e}"

    SPEC = (
        "Tools (reply with exactly one JSON object per turn):\n"
        '{"tool": "list_docs"}\n'
        '{"tool": "read_doc", "arg": "<filename>"}\n'
        '{"tool": "calculator", "arg": "<arithmetic expression>"}\n'
        '{"final_answer": <number>}'
    )
