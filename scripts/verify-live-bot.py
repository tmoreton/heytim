#!/usr/bin/env python3
"""Invoke one deployed bot with its live catalog and connection configuration."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import boto3


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Set {name} before running this check.")
    return value


repository_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository_root / "services" / "API" / "amplify" / "functions"))

region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
function_name = required("HEYTIM_WORKER_FUNCTION")
user_id = required("HEYTIM_USER_ID")
bot_id = required("HEYTIM_BOT_ID")
prompt = os.environ.get(
    "HEYTIM_LIVE_BOT_PROMPT",
    "Reply exactly HEYTIM_LIVE_BOT_OK and do not use any tools.",
)

lambda_client = boto3.client("lambda", region_name=region)
configuration = lambda_client.get_function_configuration(FunctionName=function_name)
os.environ.update(configuration["Environment"]["Variables"])
os.environ.setdefault("AWS_REGION", region)
os.environ.setdefault("AWS_DEFAULT_REGION", region)

from worker.agent import _invoke  # noqa: E402
from worker.support import _bot_key, table  # noqa: E402

bot = table.get_item(
    Key=_bot_key(user_id, bot_id),
    ConsistentRead=True,
).get("Item")
if not bot:
    raise SystemExit("The requested live bot was not found.")

result = _invoke(
    user_id,
    bot_id,
    bot,
    billing_user_id=user_id,
    history=[{"role": "user", "content": [{"text": prompt}]}],
)
print(json.dumps({
    "botId": bot_id,
    "botName": bot.get("name"),
    "terminalError": result.terminal_error,
    "text": result.text,
    "pendingApproval": result.pending_approval,
}, default=str))
if result.terminal_error or not result.text.strip():
    raise SystemExit(1)
