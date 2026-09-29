from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from heytim_runtime import local_tools
from heytim_runtime.capability_contract import tool_bindings

CATALOG = json.loads((Path(__file__).resolve().parents[3] / "catalog/catalog.json").read_text())


@pytest.mark.parametrize("definition", CATALOG["tools"], ids=lambda item: item["id"])
def test_every_catalog_tool_has_a_supported_runtime_binding(definition):
    binding, = tool_bindings({"tools": [definition]})
    assert binding["id"] == definition["id"]
    assert binding["kind"] == definition["runtime"]["kind"]


def test_calculator_rejects_explosive_intermediate_results_before_more_work(monkeypatch):
    calls = []

    def power(left, right):
        calls.append((left, right))
        return left ** right

    monkeypatch.setitem(local_tools._BINARY_OPERATORS, ast.Pow, power)
    with pytest.raises(ValueError, match="too large"):
        local_tools.calculate("((10**12)**12)**12")
    assert len(calls) == 2


@pytest.mark.parametrize("expression", ["1e309 - 1e309", "(-1)**0.5", "1e100 * 10"])
def test_calculator_never_returns_nonfinite_complex_or_unbounded_values(expression):
    with pytest.raises((ValueError, TypeError)):
        local_tools.calculate(expression)


@pytest.mark.parametrize("expression,expected", [
    ("(20 + 5) * 4 / 2", "50.0"), ("2**12", "4096"),
    ("-123.45 + 3.45", "-120.0"), ("1e100", "1e+100"),
])
def test_calculator_retains_supported_arithmetic(expression, expected):
    assert local_tools.calculate(expression) == expected
