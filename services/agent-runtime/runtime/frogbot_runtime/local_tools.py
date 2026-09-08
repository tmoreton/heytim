from __future__ import annotations

import ast
import operator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from strands import tool

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _evaluate_number(node: ast.AST) -> int | float:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_number(node.left)
        right = _evaluate_number(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("Exponent is too large")
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_number(node.operand))
    raise ValueError("Expression contains an unsupported operation")


@tool
def calculate(expression: str) -> str:
    """Evaluate arithmetic using numbers, parentheses, and +, -, *, /, //, %, or **."""
    if not isinstance(expression, str):
        raise TypeError("expression must be a string")
    if not expression.strip() or len(expression) > 200:
        raise ValueError("expression must be non-empty and at most 200 characters")
    result = _evaluate_number(ast.parse(expression, mode="eval").body)
    if abs(float(result)) > 1e100:
        raise ValueError("Result is too large")
    return str(result)


@tool
def current_time(timezone: str = "UTC") -> str:
    """Return the current date and time in an IANA timezone such as UTC or America/New_York."""
    if not isinstance(timezone, str):
        raise TypeError("timezone must be a string")
    if len(timezone) > 64:
        raise ValueError("timezone must be at most 64 characters")
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone}") from exc
    return now.isoformat(timespec="seconds")


CUSTOM_TOOLS = {"calculator": calculate, "current_time": current_time}
