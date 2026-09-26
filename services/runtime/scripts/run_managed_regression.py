from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

import boto3
from bedrock_agentcore.evaluation import (
    AgentInvokerInput,
    AgentInvokerOutput,
    BatchEvaluationRunConfig,
    BatchEvaluationRunner,
    BatchEvaluatorConfig,
    CloudWatchDataSourceConfig,
    DatasetClient,
    DatasetManagementServiceProvider,
)

MAX_PROMPT_CHARS = 12_000
MAX_STREAM_BYTES = 2_000_000
EVALUATION_SERVICE_NAME = "HeyTimReleaseEvaluation"
DEFAULT_EVALUATION_LOG_GROUP = "/aws/bedrock-agentcore/evaluations/heytim-release-fixtures"
RUNTIME_ARN = re.compile(
    r"^arn:[a-z0-9-]+:bedrock-agentcore:(?P<region>[a-z0-9-]+):"
    r"[0-9]{12}:runtime/(?P<runtime_id>[A-Za-z][A-Za-z0-9_-]{0,99})$"
)


def evaluation_payload(value: Any) -> dict[str, Any]:
    """Wrap one managed fixture turn in the production runtime contract."""
    if not isinstance(value, str) or not value.strip():
        raise TypeError("managed regression turns must contain non-empty text")
    if len(value) > MAX_PROMPT_CHARS:
        raise ValueError("managed regression turn exceeds the runtime prompt limit")
    return {
        "prompt": value,
        "bot": {
            "name": "HeyTim Evaluation",
            "prompt": "Be helpful, direct, and honest.",
            # These lists are deliberately resolved here instead of weakening the
            # runtime's catalog boundary for evaluation traffic.
            "tools": [],
            "skills": [],
        },
    }


def _event_from_line(raw_line: Any) -> dict[str, Any]:
    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
    if line.startswith("data:"):
        line = line[5:].strip()
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return {}
    if isinstance(value, dict) and isinstance(value.get("data"), str):
        try:
            value = json.loads(value["data"])
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, dict):
        return {}
    if value.get("error") is not None or value.get("errorMessage") is not None:
        raise RuntimeError("AgentCore returned a runtime error event")
    event = value.get("event", value)
    return event if isinstance(event, dict) else {}


def completed_assistant_text(lines: Iterable[Any]) -> str:
    total_bytes = 0
    current_chunks: list[str] = []
    completed_text = ""
    terminal_error = False

    for raw_line in lines:
        total_bytes += len(raw_line) if isinstance(raw_line, bytes) else len(str(raw_line))
        if total_bytes > MAX_STREAM_BYTES:
            raise ValueError("AgentCore evaluation stream exceeded its size limit")
        event = _event_from_line(raw_line)
        if not event:
            continue
        control = event.get("heytimControl")
        if isinstance(control, dict):
            terminal_error = terminal_error or isinstance(
                control.get("terminalError"), dict
            )
            continue
        if "messageStart" in event:
            current_chunks = []
        block_delta = event.get("contentBlockDelta")
        delta = block_delta.get("delta") if isinstance(block_delta, dict) else None
        text = delta.get("text") if isinstance(delta, dict) else None
        if isinstance(text, str):
            current_chunks.append(text)
        message_stop = event.get("messageStop")
        if not isinstance(message_stop, dict):
            continue
        if message_stop.get("stopReason") == "end_turn":
            candidate = "".join(current_chunks).strip()
            if candidate:
                completed_text = candidate
        current_chunks = []

    if terminal_error:
        raise RuntimeError("AgentCore returned a terminal evaluation outcome")
    if not completed_text:
        raise ValueError("AgentCore evaluation stream had no completed assistant turn")
    return completed_text


class CuratedEvaluationSpanSink:
    """Write only fixed regression prompt/response pairs as supported OTEL spans."""

    def __init__(
        self,
        logs_client: Any,
        log_group_name: str,
        run_name: str,
        kms_key_arn: str | None = None,
    ) -> None:
        self.logs_client = logs_client
        self.log_group_name = log_group_name
        self.log_stream_name = f"run-{run_name}"
        self.lock = threading.Lock()
        try:
            logs_client.create_log_group(logGroupName=log_group_name)
        except logs_client.exceptions.ResourceAlreadyExistsException:
            pass
        logs_client.put_retention_policy(
            logGroupName=log_group_name,
            retentionInDays=30,
        )
        if kms_key_arn:
            logs_client.associate_kms_key(
                logGroupName=log_group_name,
                kmsKeyId=kms_key_arn,
            )
        logs_client.create_log_stream(
            logGroupName=log_group_name,
            logStreamName=self.log_stream_name,
        )

    def record(self, session_id: str, prompt: str, response: str) -> None:
        now_ns = time.time_ns()
        trace_id = secrets.token_hex(16)
        span = {
            "resource": {
                "attributes": {
                    "aws.service.type": "gen_ai_agent",
                    "aws.local.service": EVALUATION_SERVICE_NAME,
                    "service.name": EVALUATION_SERVICE_NAME,
                }
            },
            "scope": {
                "name": "opentelemetry.instrumentation.heytim_evaluation",
                "version": "1.0.0",
            },
            "traceId": trace_id,
            "spanId": secrets.token_hex(8),
            "name": "invoke_agent HeyTimEvaluation",
            "kind": "INTERNAL",
            "startTimeUnixNano": now_ns,
            "endTimeUnixNano": now_ns + 1,
            "attributes": {
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": "HeyTim Evaluation",
                "gen_ai.task.input": prompt,
                "gen_ai.task.output": response,
                "agentcore.invocation.user_prompt": prompt,
                "agentcore.invocation.agent_response": response,
                "session.id": session_id,
            },
            "status": {"code": "OK"},
        }
        event = {
            "timestamp": now_ns // 1_000_000,
            "message": json.dumps(span, separators=(",", ":")),
        }
        # A single stream keeps each run easy to audit. Serialize writes so this
        # remains compatible with accounts that still enforce sequence ordering.
        with self.lock:
            self.logs_client.put_log_events(
                logGroupName=self.log_group_name,
                logStreamName=self.log_stream_name,
                logEvents=[event],
            )


def agent_invoker(
    client: Any,
    runtime_arn: str,
    span_sink: CuratedEvaluationSpanSink,
) -> Callable[[AgentInvokerInput], AgentInvokerOutput]:
    def invoke(invoker_input: AgentInvokerInput) -> AgentInvokerOutput:
        if not isinstance(invoker_input.session_id, str) or not invoker_input.session_id:
            raise ValueError("AgentCore evaluation session ID is missing")
        payload = evaluation_payload(invoker_input.payload)
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            qualifier="DEFAULT",
            runtimeSessionId=invoker_input.session_id,
            contentType="application/json",
            accept="text/event-stream",
            payload=json.dumps(
                payload, separators=(",", ":")
            ).encode("utf-8"),
        )
        stream = response.get("response")
        if stream is None or not hasattr(stream, "iter_lines"):
            raise RuntimeError("AgentCore evaluation response stream is missing")
        try:
            text = completed_assistant_text(stream.iter_lines())
        finally:
            stream.close()
        span_sink.record(invoker_input.session_id, payload["prompt"], text)
        return AgentInvokerOutput(agent_output={"text": text})

    return invoke


def runtime_observability(runtime_arn: str, region: str) -> tuple[str, str]:
    match = RUNTIME_ARN.fullmatch(runtime_arn)
    if match is None or match.group("region") != region:
        raise ValueError("runtime ARN does not match the requested AWS Region")
    runtime_id = match.group("runtime_id")
    return (
        f"{runtime_id}.DEFAULT",
        f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run HeyTim's managed AgentCore regression dataset safely."
    )
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version", default="DRAFT")
    parser.add_argument("--region", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--evaluator", nargs="+", required=True)
    parser.add_argument("--ingestion-delay-seconds", type=int, default=180)
    parser.add_argument("--kms-key-arn")
    parser.add_argument(
        "--evaluation-log-group",
        default=DEFAULT_EVALUATION_LOG_GROUP,
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", args.name):
        raise ValueError("batch evaluation name is invalid")
    if args.ingestion_delay_seconds < 0:
        raise ValueError("ingestion delay cannot be negative")
    runtime_observability(args.runtime_arn, args.region)
    if not args.evaluation_log_group.startswith(
        "/aws/bedrock-agentcore/evaluations/"
    ):
        raise ValueError("evaluation log group is outside the approved namespace")
    session = boto3.Session(region_name=args.region)
    dataset_client = DatasetClient(
        region_name=args.region,
        boto3_session=session,
    )
    dataset = DatasetManagementServiceProvider(
        dataset_id=args.dataset_id,
        version_id=None if args.dataset_version == "DRAFT" else args.dataset_version,
        client=dataset_client,
    ).get_dataset()
    runtime_client = session.client("bedrock-agentcore", region_name=args.region)
    span_sink = CuratedEvaluationSpanSink(
        session.client("logs", region_name=args.region),
        args.evaluation_log_group,
        args.name,
        args.kms_key_arn,
    )
    runner = BatchEvaluationRunner(region=args.region)
    result = runner.run_dataset_evaluation(
        BatchEvaluationRunConfig(
            batch_evaluation_name=args.name,
            evaluator_config=BatchEvaluatorConfig(evaluator_ids=args.evaluator),
            data_source=CloudWatchDataSourceConfig(
                service_names=[EVALUATION_SERVICE_NAME],
                log_group_names=[args.evaluation_log_group],
                ingestion_delay_seconds=args.ingestion_delay_seconds,
            ),
            max_concurrent_scenarios=5,
            kms_key_arn=args.kms_key_arn,
            description="Curated non-sensitive HeyTim release regression",
            tags={"agentcore:project-name": "HeyTim"},
        ),
        dataset,
        agent_invoker(runtime_client, args.runtime_arn, span_sink),
    )
    return result.model_dump(mode="json", by_alias=True)


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(parse_args(argv))
    # Keep a stable, redacted CLI boundary for SDK, network, and stream failures.
    except Exception as error:  # noqa: BLE001
        print(
            f"Managed AgentCore regression failed: {type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
