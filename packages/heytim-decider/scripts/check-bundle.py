"""Exercise the relocated signed helper's NDJSON protocol and real labeled decisions."""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import time
from evaluation_policy import assess_case, summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path,
                        default=Path(__file__).parents[1] / "tests/routing-fixtures.json")
    args = parser.parse_args()
    fixture = json.loads(args.fixtures.read_text())
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    environment["PATH"] = "/usr/bin:/bin"
    stderr_file = args.output.with_suffix(".stderr.log")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with stderr_file.open("w") as errors:
        process = subprocess.Popen(
            [str(args.helper.resolve()), "--model-root", str(args.model_root.expanduser())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
            text=True, env=environment,
        )
        def request(value):
            process.stdin.write(json.dumps(value) + "\n")
            process.stdin.flush()
            if not select.select([process.stdout], [], [], 90)[0]:
                raise RuntimeError("Packaged helper response timed out")
            line = process.stdout.readline()
            if not line:
                raise RuntimeError(f"Packaged helper exited: {process.poll()}; see {stderr_file}")
            response = json.loads(line)
            if response.get("id") != value["id"]:
                raise RuntimeError("Packaged helper response id mismatch")
            if "error" in response:
                raise RuntimeError(response["error"]["message"])
            return response["result"]
        try:
            health = request({"id": "health", "method": "health"})
            assert health["modelInstalled"], "Pinned model must be installed"
            for case in fixture["cases"]:
                started = time.monotonic()
                result = request({"id": case["id"], "method": "decide",
                                  "params": {"text": case["text"], "bots": fixture["bots"]}})
                assessment = assess_case(case, result, fixture["bots"])
                rows.append({"id": case["id"], "expectedBotId": case["botId"],
                             "expectedEffort": case["effort"], **assessment,
                             "roundTripMs": round((time.monotonic() - started) * 1000, 2),
                             "result": result})
            # A too-long token sequence must fail without silently truncating the
            # transcript; the same process must still handle its next health call.
            process.stdin.write(json.dumps({"id": "overflow", "method": "decide", "params": {
                "text": "x! " * 5400, "bots": fixture["bots"]}}) + "\n")
            process.stdin.flush()
            if not select.select([process.stdout], [], [], 90)[0]:
                raise RuntimeError("Overflow request timed out")
            overflow = json.loads(process.stdout.readline())
            assert "error" in overflow and "context window" in overflow["error"]["message"]
            request({"id": "after-overflow", "method": "health"})
            recovered = request({"id": "inference-after-overflow", "method": "decide", "params": {
                "text": fixture["cases"][0]["text"], "bots": fixture["bots"]}})
            assert recovered["botId"] == fixture["cases"][0]["botId"]
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
    summary = summarize(rows, fixture["cases"])
    report = {"health": health, "cases": rows, **summary, "exitCode": process.returncode,
              "strictWindowVerified": True}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({**summary, "exitCode": process.returncode,
                      "strictWindowVerified": True}), flush=True)
    raise SystemExit(1 if summary["failedCases"] or process.returncode else 0)


if __name__ == "__main__":
    main()
