"""Summarize existing sanitized runtime failure markers without exporting logs."""

import collections
import json
import re
import subprocess
import time

GROUP = re.compile(
    r"/aws/bedrock-agentcore/runtimes/HeyTim_HeyTim-[A-Za-z0-9]+-DEFAULT"
)
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}")
LOCATION = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.py:[A-Za-z_][A-Za-z0-9_]*:[0-9]{1,6}")
CATEGORIES = {"image", "browser", "provider", "other", "stalled"}


def summarize(events):
    failures = collections.Counter()
    for event in events:
        message = event.get("message", "")
        if not isinstance(message, str) or "HEYTIM_TERMINAL_ERROR " not in message:
            continue
        try:
            marker = json.loads(message.split("HEYTIM_TERMINAL_ERROR ", 1)[1])
        except (ValueError, TypeError):
            continue
        if not isinstance(marker, dict) or marker.get("schema") != 1:
            continue
        category = marker.get("category")
        exception = marker.get("exception")
        location = marker.get("location")
        if not isinstance(category, str) or category not in CATEGORIES:
            category = "other"
        if not isinstance(exception, str) or not NAME.fullmatch(exception):
            exception = "UnknownError"
        if not isinstance(location, str) or not LOCATION.fullmatch(location):
            location = "runtime"
        failures[(category, exception, location)] += 1
    return [
        {"category": key[0], "exception": key[1], "location": key[2], "count": count}
        for key, count in sorted(failures.items())
    ]


def aws(*arguments):
    result = subprocess.run(
        ["aws", *arguments, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Read-only runtime diagnostics could not query CloudWatch")
    return json.loads(result.stdout)


def main():
    if aws("sts", "get-caller-identity").get("Account") != "820323452649":
        raise RuntimeError(
            "Runtime diagnostics require the dedicated production account"
        )
    groups = aws(
        "logs",
        "describe-log-groups",
        "--log-group-name-prefix",
        "/aws/bedrock-agentcore/runtimes/HeyTim_HeyTim-",
    )
    start = str(int((time.time() - 3600) * 1000))
    events = []
    for group in groups.get("logGroups", []):
        name = group.get("logGroupName", "")
        if not isinstance(name, str) or not GROUP.fullmatch(name):
            continue
        # Only sanitized terminal markers are selected. Raw responses stay in memory.
        result = aws(
            "logs",
            "filter-log-events",
            "--log-group-name",
            name,
            "--start-time",
            start,
            "--filter-pattern",
            '"HEYTIM_TERMINAL_ERROR"',
            "--max-items",
            "1000",
        )
        events.extend(result.get("events", []))
    print(json.dumps({"runtimeFailureSummary": summarize(events)}, indent=2))


if __name__ == "__main__":
    main()
