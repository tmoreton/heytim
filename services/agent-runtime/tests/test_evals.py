from __future__ import annotations

import json

import pytest

from evals.run_matrix import (
    MODEL_VARIANTS,
    load_catalog_snapshot,
    load_scenarios,
    select_scenarios,
    summarize,
    validate_scenarios,
)


def test_catalog_snapshot_uses_schema_three_bot_catalog(monkeypatch) -> None:
    catalog = {
        "schemaVersion": 3,
        "repository": "tmoreton/frogbot-skills",
        "release": "skills-v42",
        "skills": [
            {
                "id": "analysis",
                "path": "skills/analysis/SKILL.md",
                "name": "Analysis",
                "description": "Analyze evidence.",
                "version": 2,
                "requiredToolIds": [],
            }
        ],
        "bots": [{"id": "chief", "name": "Chief", "skillIds": ["analysis"]}],
    }
    monkeypatch.setattr("evals.run_matrix._json_from_url", lambda _url: catalog)
    monkeypatch.setattr(
        "evals.run_matrix._text_from_url",
        lambda _url: "---\nname: Analysis\n---\nAnalyze the supplied evidence.",
    )

    release, skills, bots = load_catalog_snapshot()

    assert release == "skills-v42"
    assert skills["analysis"]["instructions"] == "Analyze the supplied evidence."
    assert set(bots) == {"chief"}


def test_catalog_snapshot_rejects_retired_schema(monkeypatch) -> None:
    monkeypatch.setattr(
        "evals.run_matrix._json_from_url",
        lambda _url: {
            "schemaVersion": 2,
            "repository": "tmoreton/frogbot-skills",
        },
    )

    with pytest.raises(ValueError, match="schema"):
        load_catalog_snapshot()


def test_scenario_corpus_covers_every_public_bot() -> None:
    scenarios = load_scenarios()
    bot_ids = {scenario["botId"] for scenario in scenarios}
    bots = {bot_id: {"id": bot_id} for bot_id in bot_ids}

    validate_scenarios(scenarios, bots)

    assert len(bot_ids) == 8
    assert "chief" in bot_ids
    assert len(scenarios) >= 24
    assert all(len(scenario["assertions"]) >= 4 for scenario in scenarios)


def test_scenario_validation_rejects_duplicate_ids() -> None:
    bots = {"chief": {"id": "chief"}}
    scenario = {
        "scenarioId": "duplicate",
        "botId": "chief",
        "prompt": "Test prompt",
        "expectedOutcome": "Test outcome",
        "assertions": ["First", "Second", "Third", "Fourth"],
    }

    with pytest.raises(ValueError, match="Duplicate"):
        validate_scenarios([scenario, json.loads(json.dumps(scenario))], bots)


def test_scenario_selection_happens_after_full_corpus_validation() -> None:
    scenarios = load_scenarios()

    selected = select_scenarios(scenarios, ["chief_vague_group_trip"])

    assert [scenario["scenarioId"] for scenario in selected] == [
        "chief_vague_group_trip"
    ]


def test_matrix_defines_low_and_high_for_primary_and_fallback_models() -> None:
    assert {
        (variant.model_id, variant.reasoning_effort) for variant in MODEL_VARIANTS
    } == {
        ("deepseek/deepseek-v4.1-flash", "low"),
        ("deepseek/deepseek-v4.1-flash", "high"),
        ("z-ai/glm-5.3", "low"),
        ("z-ai/glm-5.3", "high"),
    }


def test_summary_aggregates_scores_cost_and_latency() -> None:
    variant = MODEL_VARIANTS[0]
    results = [
        {
            "variant": variant.name,
            "latencyMs": 100,
            "evaluation": {"score": 75, "passed": False},
            "usage": {
                "models": [{"providerCostUsd": "0.001"}],
                "totals": {"totalTokens": 100},
            },
        },
        {
            "variant": variant.name,
            "latencyMs": 300,
            "evaluation": {"score": 100, "passed": True},
            "usage": {
                "models": [{"providerCostUsd": "0.002"}],
                "totals": {"totalTokens": 200},
            },
        },
    ]

    item = next(item for item in summarize(results) if item["variant"] == variant.name)

    assert item["averageScore"] == 87.5
    assert item["passRate"] == 0.5
    assert item["averageLatencyMs"] == 200
    assert item["totalTokens"] == 300
    assert item["providerCostUsd"] == "0.003"
