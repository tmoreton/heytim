"""Acceptance accounting, including explicit effort abstentions and raw model misses."""

MINIMUM_REASONING_CONFIDENCE = 0.6


def assess_case(case, result, bots):
    route_ok = result["botId"] is None or result["botId"] == case["botId"]
    preferences = {bot["id"]: bot.get("reasoningEffort") or "high" for bot in bots}
    saved = preferences.get(result["botId"], "high")
    deferred = result["reasoningDeferred"]
    confidence = result["reasoningConfidence"]
    raw_ok = result["suggestedReasoningEffort"] == case["effort"]
    if deferred:
        effort_ok = result["reasoningEffort"] == saved and (confidence < MINIMUM_REASONING_CONFIDENCE or result["botId"] is None)
    else:
        effort_ok = (confidence >= MINIMUM_REASONING_CONFIDENCE and result["reasoningEffort"] == case["effort"]
                     and result["reasoningEffort"] == result["suggestedReasoningEffort"])
    return {"routeOK": route_ok, "effortOK": effort_ok, "rawEffortOK": raw_ok,
            "effortAutomaticallyApplied": result["botId"] is not None and not deferred,
            "savedReasoningEffort": saved}


def summarize(rows, cases):
    accepted = [row for row in rows if row["result"]["botId"] is not None]
    automatic = [row for row in accepted if row["effortAutomaticallyApplied"]]
    routable = sum(case["botId"] is not None for case in cases)
    routing_coverage = len(accepted) / routable if routable else 1.0
    effort_coverage = len(automatic) / len(accepted) if accepted else 1.0
    failures = [row["id"] for row in rows if not row["routeOK"] or not row["effortOK"]]
    if routing_coverage < 0.6:
        failures.append("routing_coverage_below_60_percent")
    if effort_coverage < 0.6:
        failures.append("effort_coverage_below_60_percent")
    return {"cases": len(rows), "acceptedRoutes": len(accepted),
            "incorrectAcceptedRoutes": sum(not row["routeOK"] for row in accepted),
            "routingCoverage": routing_coverage, "effortCoverage": effort_coverage,
            "automaticEffortDecisions": len(automatic),
            "incorrectAutomaticEffortDecisions": sum(not row["effortOK"] for row in automatic),
            "reasoningDeferred": sum(row["result"]["reasoningDeferred"] for row in rows),
            "rawEffortCorrect": sum(row["rawEffortOK"] for row in rows),
            "rawEffortFailures": [row["id"] for row in rows if not row["rawEffortOK"]],
            "appliedEffortPolicyCorrect": sum(row["effortOK"] for row in rows),
            "failedCases": failures}
