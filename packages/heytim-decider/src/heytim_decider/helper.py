"""Local NDJSON inference. stdout is reserved for the protocol; diagnostics use stderr."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

MODEL_ID = "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"
MODEL_REVISION = "216d1ccb46a9e9b036eb9187b248db98480f77d4"
BASE_ID = "Qwen/Qwen3.5-2B-Base"
BASE_REVISION = "b1485b2fa6dfa1287294f269f5fb618e03d52d7c"
CODE_REVISION = "8b6faa553038a59e73fa7f16c4081f8ceb21d27e"
MAX_TEXT_BYTES = 16_384
MAX_REQUEST_BYTES = 131_072
MAX_BOTS = 32
EFFORTS = ("low", "high", "max")
MINIMUM_REASONING_CONFIDENCE = 0.5
ADAPTER_FILES = (
    "strands_decider_config.json", "head.safetensors", "lora/adapter_config.json",
    "lora/adapter_model.safetensors", "tokenizer.json", "tokenizer_config.json",
    "provenance.json", "MANIFEST.sha256", "LICENSE.md",
)
_protocol_lock = threading.Lock()


def emit(value: Any) -> None:
    with _protocol_lock:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), file=sys.__stdout__, flush=True)


def snapshot_path(root: Path, repo: str, revision: str) -> Path:
    return root / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots" / revision


def validate_params(params: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    text = params.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a nonempty string")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("transcript exceeds the 16384-byte limit; shorten it before routing")
    bots = params.get("bots")
    if not isinstance(bots, list) or len(bots) > MAX_BOTS:
        raise ValueError(f"bots must be a list of at most {MAX_BOTS} authorized candidates")
    clean = []
    ids: set[str] = set()
    for bot in bots:
        if not isinstance(bot, dict):
            raise ValueError("each bot must be an object")
        bot_id = bot.get("id")
        if (not isinstance(bot_id, str) or not bot_id or bot_id == "clarify"
                or len(bot_id.encode("utf-8")) > 128 or bot_id in ids):
            raise ValueError("bot ids must be unique, nonempty, at most 128 bytes and not 'clarify'")
        ids.add(bot_id)
        item: dict[str, Any] = {"id": bot_id}
        for field, limit in (("name", 200), ("description", 2000)):
            value = bot.get(field, "")
            if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
                raise ValueError(f"bot {field} must be a string of at most {limit} bytes")
            item[field] = value
        for field in ("toolIds", "skillIds"):
            value = bot.get(field, [])
            if (not isinstance(value, list) or len(value) > 20
                    or any(not isinstance(v, str) or len(v.encode("utf-8")) > 120 for v in value)):
                raise ValueError(f"bot {field} must contain at most 20 short strings")
            item[field] = value
        effort = bot.get("reasoningEffort", "high")
        if effort is not None and effort not in EFFORTS:
            raise ValueError("bot reasoningEffort must be low, high or max")
        item["reasoningEffort"] = effort
        clean.append(item)
    return text.strip(), clean


def questions_for(bots: list[dict[str, Any]]) -> dict[str, Any]:
    choices = {
        bot["id"]: {"name": bot["name"], "responsibility": bot["description"],
                    "tools": bot["toolIds"], "skills": bot["skillIds"]}
        for bot in bots
    }
    choices["clarify"] = (
        "Unrelated request, missing information, or ambiguous request that no single listed "
        "bot is clearly responsible for. Ask the user to choose a bot."
    )
    return {
        "agent": {
            "type": "choice",
            "instructions": "Choose the bot whose responsibility best matches the user's request.",
            "criteria": choices,
        },
        "effort": {
            "type": "choice",
            "instructions": "Choose how much reasoning is needed to answer the user's request.",
            "criteria": {
                "low": "Simple greeting, direct fact, short lookup, reminder, note capture, "
                       "straightforward formatting, or a basic meme with supplied image and "
                       "caption; no substantial analysis.",
                "high": "Ordinary multi-step analysis, comparison, debugging, planning, "
                        "or synthesis that needs careful reasoning.",
                "max": "Exceptionally difficult, sustained research or engineering: complex "
                       "architecture, many interacting constraints, deep proofs, or extensive "
                       "analysis of several competing solutions.",
            },
        },
    }


def select_result(answers: dict[str, Any], *, minimum_confidence: float,
                  minimum_margin: float,
                  bot_preferences: dict[str, str] | None = None) -> dict[str, Any]:
    route, effort = answers["agent"], answers["effort"]
    probabilities = route["probabilities"]
    if (not isinstance(probabilities, dict) or len(probabilities) < 2
            or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1
                   for v in probabilities.values())):
        raise ValueError("Decider returned an invalid probability distribution")
    if (not isinstance(route["confidence"], (int, float))
            or not math.isfinite(route["confidence"]) or not 0 <= route["confidence"] <= 1
            or route["choice"] not in probabilities or effort["choice"] not in EFFORTS
            or not isinstance(effort["confidence"], (int, float))
            or not math.isfinite(effort["confidence"]) or not 0 <= effort["confidence"] <= 1):
        raise ValueError("Decider returned an invalid choice or confidence")
    ordered = sorted(probabilities.values(), reverse=True)
    margin = ordered[0] - ordered[1] if len(ordered) > 1 else 0.0
    confidence = route["confidence"]
    selected = route["choice"]
    needs_review = selected == "clarify" or confidence < minimum_confidence or margin < minimum_margin
    reason = ("clarification" if selected == "clarify" else
              "low_confidence" if confidence < minimum_confidence else
              "ambiguous" if margin < minimum_margin else "selected")
    saved_effort = (bot_preferences or {}).get(selected, "high") if not needs_review else "high"
    reasoning_deferred = needs_review or effort["confidence"] < MINIMUM_REASONING_CONFIDENCE
    return {
        "modelId": MODEL_ID, "modelRevision": MODEL_REVISION,
        "botId": None if needs_review else selected,
        "reasoningEffort": saved_effort if reasoning_deferred else effort["choice"],
        "confidence": confidence, "probabilities": probabilities,
        "reasoningConfidence": effort["confidence"], "reasoningDeferred": reasoning_deferred,
        "suggestedReasoningEffort": effort["choice"], "needsReview": needs_review,
        "reason": reason,
    }


class Decider:
    def __init__(self, root: Path, device: str = "auto", *, minimum_confidence: float = 0.8,
                 minimum_margin: float = 0.15) -> None:
        self.root = root.expanduser().resolve()
        self.device = device
        self.minimum_confidence = minimum_confidence
        self.minimum_margin = minimum_margin
        self.engine: Any = None
        self.loaded_device: str | None = None

    @property
    def adapter(self) -> Path:
        return snapshot_path(self.root, MODEL_ID, MODEL_REVISION)

    @property
    def base(self) -> Path:
        return snapshot_path(self.root, BASE_ID, BASE_REVISION)

    def installed(self) -> bool:
        try:
            marker = json.loads((self.root / "installed.json").read_text())
        except (OSError, ValueError):
            return False
        return (marker.get("modelRevision") == MODEL_REVISION
                and marker.get("baseModelRevision") == BASE_REVISION
                and all((self.adapter / name).is_file() for name in ADAPTER_FILES)
                and (self.base / "config.json").is_file()
                and any(self.base.glob("*.safetensors")))

    def health(self) -> dict[str, Any]:
        return {
            "modelId": MODEL_ID, "modelRevision": MODEL_REVISION,
            "codeRevision": CODE_REVISION, "modelInstalled": self.installed(),
            "ready": self.installed(), "loaded": self.engine is not None,
            "device": self.loaded_device or self.device, "contextWindow": 4096,
        }

    def load(self) -> None:
        if self.engine is not None:
            return
        if not self.installed():
            raise ValueError("Local model setup is required; run this helper with --prepare")
        with contextlib.redirect_stdout(sys.stderr):
            from strands_decider.infer import EngineConfig, SystemOneEngine, load_mlx
            from strands_decider.modeling import StrandsDeciderModel

            devices = ("mlx", "mps") if self.device == "auto" else (self.device,)
            failures = []
            for device in devices:
                try:
                    config = EngineConfig(device=device, strict_window=True, max_batch=2)
                    if device == "mlx":
                        self.engine = load_mlx(str(self.adapter), config)
                    else:
                        model = StrandsDeciderModel.load(str(self.adapter))
                        self.engine = SystemOneEngine(model, config)
                    self.loaded_device = device
                    return
                except Exception as exc:
                    failures.append(f"{device}: {exc}")
                    print(f"Decider {device} load failed: {exc}", file=sys.stderr)
            raise RuntimeError("Could not load local decider: " + "; ".join(failures))

    def decide(self, params: Any) -> dict[str, Any]:
        text, bots = validate_params(params)
        if not bots:
            return {"modelId": MODEL_ID, "modelRevision": MODEL_REVISION, "botId": None,
                    "reasoningEffort": "high", "confidence": 0.0, "probabilities": {},
                    "reasoningDeferred": True, "reasoningConfidence": 0.0,
                    "suggestedReasoningEffort": "high",
                    "needsReview": True, "reason": "no_candidates"}
        self.load()
        with contextlib.redirect_stdout(sys.stderr):
            from strands_decider.schema import SystemOneRequest

            request = SystemOneRequest(state={"user_request": text}, questions=questions_for(bots))
            started = time.monotonic()
            response = self.engine.evaluate(request).model_dump()
        result = select_result(response["answers"], minimum_confidence=self.minimum_confidence,
                               minimum_margin=self.minimum_margin,
                               bot_preferences={b["id"]: b["reasoningEffort"] or "high" for b in bots})
        if result["botId"] is not None and result["botId"] not in {b["id"] for b in bots}:
            raise RuntimeError("Decider returned a bot outside the authorized candidate set")
        result["latencyMs"] = round((time.monotonic() - started) * 1000, 2)
        result["device"] = self.loaded_device
        result["inputTokens"] = response["usage"]["input_tokens"]
        return result


def configure_cache(root: Path, *, offline: bool) -> None:
    os.environ["HF_HUB_CACHE"] = str(root / "hub")
    os.environ["HF_HOME"] = str(root / "hub-home")
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1" if offline else "0"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"


def prepare(decider: Decider) -> None:
    decider.root.mkdir(parents=True, exist_ok=True)
    configure_cache(decider.root, offline=False)
    with contextlib.redirect_stdout(sys.stderr):
        from huggingface_hub import snapshot_download
        from tqdm.auto import tqdm

    class DownloadProgress(tqdm):
        stage = "download"

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.progress_unit = kwargs.get("unit", "it")
            self.completed = 0
            self.last_event = 0.0
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)

        def update(self, n: float = 1) -> bool | None:
            self.completed += n
            now = time.monotonic()
            if now - self.last_event >= 0.25 or (self.total and self.completed >= self.total):
                self.last_event = now
                event = {"type": "progress", "stage": self.stage}
                if self.progress_unit == "B":
                    event.update(message="Downloading model data", downloadedBytes=int(self.completed))
                    if self.total is not None:
                        event["totalBytes"] = int(self.total)
                else:
                    event["message"] = f"Downloaded {int(self.completed)} of {self.total or '?'} files"
                emit(event)
            return super().update(n)

    for repo, revision, patterns in (
        (MODEL_ID, MODEL_REVISION, list(ADAPTER_FILES)),
        (BASE_ID, BASE_REVISION, ["*.json", "*.safetensors", "*.jinja", "LICENSE*"]),
    ):
        emit({"type": "progress", "stage": "download", "message": f"Downloading {repo}"})
        with contextlib.redirect_stdout(sys.stderr):
            snapshot_download(repo_id=repo, revision=revision, cache_dir=str(decider.root / "hub"),
                              allow_patterns=patterns, tqdm_class=DownloadProgress)
    emit({"type": "progress", "stage": "verify", "message": "Verifying pinned model files"})
    manifest = (decider.adapter / "MANIFEST.sha256").read_text()
    hashes = {}
    for line in manifest.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            hashes[parts[1].lstrip("*")] = parts[0]
    for name in ADAPTER_FILES:
        if name == "MANIFEST.sha256":
            continue
        path = decider.adapter / name
        expected = hashes.get(name)
        if not expected or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Pinned adapter file failed verification: {name}")
    provenance = json.loads((decider.adapter / "provenance.json").read_text())
    if provenance.get("base_model_revision") != BASE_REVISION:
        raise ValueError("Adapter provenance does not match the pinned base model")
    marker = {"modelId": MODEL_ID, "modelRevision": MODEL_REVISION,
              "baseModelId": BASE_ID, "baseModelRevision": BASE_REVISION}
    temporary = decider.root / "installed.json.tmp"
    temporary.write_text(json.dumps(marker) + "\n")
    temporary.replace(decider.root / "installed.json")
    emit({"type": "progress", "stage": "load", "message": "Checking local inference"})
    decider.load()
    decider.decide({"text": "What is the chemical symbol for gold?", "bots": [{
        "id": "setup-research", "name": "Research", "description": "Answers factual questions"
    }]})
    emit({"type": "ready", **decider.health()})


def serve(decider: Decider) -> None:
    configure_cache(decider.root, offline=True)
    while True:
        line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            break
        if len(line) > MAX_REQUEST_BYTES:
            while line and not line.endswith(b"\n"):
                line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            emit({"id": None, "error": {"message": "request exceeds the 131072-byte limit"}})
            continue
        request_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            request_id = request.get("id")
            if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
                raise ValueError("id must be a string or integer")
            method = request.get("method")
            if method == "health":
                result = decider.health()
            elif method == "decide":
                result = decider.decide(request.get("params"))
            else:
                raise ValueError("method must be health or decide")
            emit({"id": request_id, "result": result})
        except Exception as exc:
            emit({"id": request_id, "error": {"message": str(exc)}})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "mlx", "mps", "cpu"), default="auto")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--minimum-confidence", type=float, default=0.8)
    parser.add_argument("--minimum-margin", type=float, default=0.15)
    args = parser.parse_args()
    if not 0 <= args.minimum_confidence <= 1 or not 0 <= args.minimum_margin <= 1:
        parser.error("confidence and margin thresholds must be between zero and one")
    decider = Decider(args.model_root, args.device, minimum_confidence=args.minimum_confidence,
                      minimum_margin=args.minimum_margin)
    if args.prepare:
        try:
            prepare(decider)
        except Exception as exc:
            emit({"type": "error", "message": str(exc)})
            raise SystemExit(1) from exc
    else:
        serve(decider)


if __name__ == "__main__":
    main()
