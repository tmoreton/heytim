from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class ModelVariant:
    name: str
    model_id: str
    reasoning_effort: str


MODEL_VARIANTS = (
    ModelVariant("deepseek-v4.1-flash-low", "deepseek/deepseek-v4.1-flash", "low"),
    ModelVariant("deepseek-v4.1-flash-high", "deepseek/deepseek-v4.1-flash", "high"),
    ModelVariant("glm-5.3-low", "z-ai/glm-5.3", "low"),
    ModelVariant("glm-5.3-high", "z-ai/glm-5.3", "high"),
)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation, TypeError, ValueError:
        return Decimal(0)


def summarize(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    present_variants = {result["variant"] for result in results}
    for variant in MODEL_VARIANTS:
        if variant.name not in present_variants:
            continue
        selected = [result for result in results if result["variant"] == variant.name]
        scored = [result for result in selected if "evaluation" in result]
        costs = sum(
            (
                _decimal(model.get("providerCostUsd"))
                for result in selected
                for model in result.get("usage", {}).get("models", [])
            ),
            Decimal(0),
        )
        tokens = sum(
            result.get("usage", {}).get("totals", {}).get("totalTokens", 0)
            for result in selected
        )
        summary.append(
            {
                "variant": variant.name,
                "runs": len(selected),
                "errors": sum(1 for result in selected if result.get("error")),
                "averageScore": (
                    round(
                        sum(result["evaluation"]["score"] for result in scored)
                        / len(scored),
                        2,
                    )
                    if scored
                    else None
                ),
                "passed": sum(1 for result in scored if result["evaluation"]["passed"]),
                "passRate": (
                    round(
                        sum(1 for result in scored if result["evaluation"]["passed"])
                        / len(scored),
                        4,
                    )
                    if scored
                    else None
                ),
                "averageLatencyMs": (
                    round(
                        sum(result["latencyMs"] for result in selected) / len(selected),
                        2,
                    )
                    if selected
                    else None
                ),
                "totalTokens": tokens,
                "providerCostUsd": format(costs, "f"),
            }
        )
    return sorted(
        summary,
        key=lambda item: (
            item["averageScore"] is not None,
            item["averageScore"] or 0,
            item["passRate"] or 0,
        ),
        reverse=True,
    )


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# HeyTim model behavioral evaluation",
        "",
        f"Run: {report['createdAt']}",
        f"Catalog release: {report['catalogRelease']}",
        f"Scenarios: {len(report['scenarios'])}",
        f"Judge: {report.get('judgeModelId', 'disabled')}",
        "",
        "## Model comparison",
        "",
        "| Variant | Avg score | Strict passes | Pass rate | Avg latency | Tokens | Provider cost | Errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["summary"]:
        score = "n/a" if item["averageScore"] is None else f"{item['averageScore']:.2f}"
        rate = "n/a" if item["passRate"] is None else f"{item['passRate']:.0%}"
        lines.append(
            f"| {item['variant']} | {score} | {item['passed']}/{item['runs']} | "
            f"{rate} | {item['averageLatencyMs']:.0f} ms | {item['totalTokens']} | "
            f"${item['providerCostUsd']} | {item['errors']} |"
        )
    lines.extend(["", "## Scenario results", ""])
    by_scenario = {item["scenarioId"]: item for item in report["scenarios"]}
    for scenario_id, scenario in by_scenario.items():
        lines.extend([f"### {scenario_id}", "", scenario["expectedOutcome"], ""])
        scenario_results = [
            result
            for result in report["results"]
            if result["scenarioId"] == scenario_id
        ]
        for result in sorted(scenario_results, key=lambda item: item["variant"]):
            if result.get("error"):
                lines.append(
                    f"- {result['variant']}: ERROR {result['error']['type']} — "
                    f"{result['error']['message']}"
                )
                continue
            evaluation = result.get("evaluation")
            if not evaluation:
                lines.append(f"- {result['variant']}: completed; not judged")
                continue
            status = "PASS" if evaluation["passed"] else "FAIL"
            failed = [
                item for item in evaluation["assertionScores"] if item["score"] < 2
            ]
            detail = (
                "; ".join(f"{item['score']}/2 {item['note']}" for item in failed)
                if failed
                else "all assertions satisfied"
            )
            lines.append(
                f"- {result['variant']}: {status} {evaluation['score']:.2f} — {detail}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
