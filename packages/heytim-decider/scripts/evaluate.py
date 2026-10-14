"""Run labeled cases against the real local model; retain all mismatches in the report.

Exit nonzero for incorrect accepted routes/automatic effort decisions or low coverage.
Raw effort mismatches remain visible even when uncertainty preserves a saved preference.
Development fixtures
must not be represented as a measured production accuracy/calibration dataset.
"""
import argparse
import json
from pathlib import Path
import resource
import statistics
import time

from heytim_decider.helper import Decider, configure_cache
from evaluation_policy import assess_case, summarize


def bots_for_case(fixture, case):
    if "candidateSets" not in fixture:
        if "candidateSet" in case:
            raise ValueError(f"Unknown candidateSet {case['candidateSet']!r} for case {case.get('id')!r}")
        return fixture["bots"]
    candidate_sets = fixture["candidateSets"]
    name = case.get("candidateSet")
    if (not isinstance(candidate_sets, dict) or not isinstance(name, str)
            or name not in candidate_sets):
        raise ValueError(f"Unknown candidateSet {name!r} for case {case.get('id')!r}")
    bots = candidate_sets[name]
    if not isinstance(bots, list):
        raise ValueError(f"candidateSet {name!r} must contain a list of bots")
    return bots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", default="auto", choices=("auto", "mlx", "mps", "cpu"))
    parser.add_argument("--fixtures", type=Path,
                        default=Path(__file__).parents[1] / "tests/routing-fixtures.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixtures.read_text())
    cases = [(case, bots_for_case(fixture, case)) for case in fixture["cases"]]
    decider = Decider(args.model_root, args.device)
    configure_cache(decider.root, offline=True)
    started = time.monotonic()
    decider.load()
    load_ms = round((time.monotonic() - started) * 1000, 2)
    rows, latencies = [], []
    for case, bots in cases:
        result = decider.decide({"text": case["text"], "bots": bots})
        assessment = assess_case(case, result, bots)
        rows.append({"id": case["id"], "expectedBotId": case["botId"],
                     "expectedEffort": case["effort"], "candidateCount": len(bots),
                     **({"candidateSet": case["candidateSet"]} if "candidateSet" in case else {}),
                     **assessment, "result": result})
        latencies.append(result["latencyMs"])
        print(json.dumps({"case": case["id"], "bot": result["botId"],
                          "effort": result["reasoningEffort"], "confidence": result["confidence"],
                          "reasoningDeferred": result["reasoningDeferred"], **assessment}), flush=True)
    summary = {**summarize(rows, fixture["cases"]),
               "gate": "routing-and-effort-policy",
               "loadMs": load_ms, "medianInferenceMs": statistics.median(latencies),
               "maxInferenceMs": max(latencies),
               "peakRSSBytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "device": decider.loaded_device}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"summary": summary, "cases": rows}, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    raise SystemExit(1 if summary["failedCases"] else 0)


if __name__ == "__main__":
    main()
