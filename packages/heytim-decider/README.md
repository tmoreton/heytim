# Local Decider for the HeyTim Mac app

The Mac app owns one local helper process. It uses Strands Decider's typed pointer
head to choose an authorized bot and reasoning effort. It does not transcribe audio
or generate the final answer. Inference has no HTTP server and disables Hugging Face
network access. Only model preparation accesses the Hub.

## Reproducible runtime

- CPython 3.12.12 from uv's relocatable standalone distribution, never Homebrew Python.
- Strands code commit `8b6faa553038a59e73fa7f16c4081f8ceb21d27e`.
- Model `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`, revision
  `216d1ccb46a9e9b036eb9187b248db98480f77d4`.
- Base `Qwen/Qwen3.5-2B-Base`, revision `b1485b2fa6dfa1287294f269f5fb618e03d52d7c`.
- Runtime dependencies and archive hashes are pinned in `requirements.lock`.
  The installer selects macOS 14 arm64 wheels explicitly, matching the app's
  deployment target rather than choosing newer-OS MLX wheels on the build host.

Run `apps/iOS/scripts/prepare-decider.sh` before a Mac build. It prepares only the
ignored `.runtime` directory. It does not download model weights. Regenerate the
lock deliberately with `MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile requirements.in
--generate-hashes --python-version 3.12.12 --python-platform aarch64-apple-darwin
--output-file requirements.lock` from this directory.

The Xcode generator's Mac-only build phase calls `scripts/stage-macos.sh` before
the app is signed. It embeds a native launcher under `Contents/Helpers/HeyTimDecider`
and standalone Python under `Contents/Resources/HeyTimDeciderRuntime` (Python scripts
must be sealed as resources, not mistaken for unsigned nested helper code).
Every Mach-O library/extension is signed using
the app's signing identity. Developer ID builds retain Hardened Runtime; ad-hoc
local builds clear that flag because they have no Team ID for library validation.
No broad library-validation or JIT exemption is added. Dependencies and their
distribution license files remain included in the runtime.

## App invocation and setup

Run `Contents/Helpers/HeyTimDecider/bin/heytim-decider --model-root PATH` using
`Process` and pipes. PATH should be the app's Application Support
`HeyTim/Decider/models` directory. The native launcher ignores ambient Python
paths, disables user site packages and bytecode writes, and locates its interpreter
relative to itself. Models stay outside the immutable signed bundle.

Run the same executable with `--prepare` for first-use installation. It downloads
the pinned adapter and base, verifies adapter hashes/provenance, then checks model
loading and inference. stdout emits NDJSON events:

```json
{"type":"progress","stage":"download","message":"Downloading model data","downloadedBytes":1024,"totalBytes":4096}
{"type":"progress","stage":"verify","message":"Verifying pinned model files"}
{"type":"progress","stage":"load","message":"Checking local inference"}
{"type":"ready","modelId":"StrandsAgents/strands-decider-2B-qwen3.5-v1-2610","modelRevision":"216d1ccb46a9e9b036eb9187b248db98480f77d4","ready":true,"modelInstalled":true,"loaded":true,"device":"mlx"}
```

Progress byte totals refer to the current transfer and can reset when a different
file starts. An error emits `{"type":"error","message":"..."}` and exits nonzero.
Logs go to stderr; stdout contains only protocol events. The app must keep one
preparation active, show failure states and permit retry. Setup needs approximately
5 GB of model storage plus the runtime and temporary download headroom.

## Inference protocol

One request/response per newline, serialized on a warm process:

```json
{"id":"1","method":"health"}
{"id":"2","method":"decide","params":{"text":"Plan a vacation itinerary","bots":[{"id":"trip","name":"Trip Planner","description":"Plans trips and itineraries","toolIds":[],"skillIds":[],"reasoningEffort":"high"}]}}
```

Health never triggers download or model loading. `ready` means the pinned files
have been installed; `loaded` indicates an engine is resident. Decide loads on
first use, then reuses the engine. `--device auto` tries MLX and falls back to MPS
only if loading fails; explicit `mlx`, `mps`, and `cpu` are available for diagnostics.

```json
{"id":"2","result":{"modelId":"StrandsAgents/strands-decider-2B-qwen3.5-v1-2610","modelRevision":"216d1ccb46a9e9b036eb9187b248db98480f77d4","botId":"trip","reasoningEffort":"high","confidence":0.95,"probabilities":{"trip":0.975,"clarify":0.025},"reasoningConfidence":0.7,"reasoningDeferred":false,"suggestedReasoningEffort":"high","needsReview":false,"reason":"selected"}}
```

Example numbers are illustrative. Errors are `{"id":"2","error":{"message":"..."}}`.
No candidates, the `clarify` option, confidence below 0.8, or a top-two probability
margin below 0.15 produce `botId:null` and `needsReview:true`. These are conservative
initial policy thresholds, not measured production guarantees. Effort is one of
`low`, `high`, `max`; the app/backend must clamp it to the selected model's supported
settings and respect explicit user overrides.

Effort has a separate abstention rule: when `reasoningConfidence` is below 0.5,
`reasoningDeferred` is true and `reasoningEffort` preserves the selected bot's saved
preference (default high). `suggestedReasoningEffort` and `reasoningConfidence`
retain the raw classifier output. No-bot results always defer without dispatch.
For three choices, concentration 0.5 means a top probability of two-thirds; this is
a calibrated starting policy, not a probability-of-correctness guarantee.

Inputs allow at most 16,384 UTF-8 transcript bytes, 32 bots, 2,000 bytes per
description and 131,072 bytes per request. Candidate ids must be unique and cannot
be `clarify`. Only authorized candidates should be supplied. Combined input must
fit the trained 4,096-token window; overflow errors rather than truncates. Use
concise capability descriptions, not full system prompts. Questions are independent;
the effort question does not see the agent answer.

## Verification and known limits

Run `PYTHONPATH=src .runtime/python/cpython-3.12.12-macos-aarch64-none/bin/python3.12
-m unittest discover -s tests` for input/policy/protocol tests. `scripts/evaluate.py`
loads the actual model against labeled fixtures and fails for incorrect accepted
routes, incorrect automatically applied effort, or coverage below 60%. Explicit
effort abstentions must preserve the selected bot's saved preference. Coverage is
computed among selected bots; raw effort misses are always retained separately.
`scripts/check-bundle.py` exercises the relocated native
helper with Python paths removed, real model decisions and strict-window recovery.
Keep evidence under ignored `.build`/`.logs`, not model weights in Git.

The fixture set is hand-authored development coverage. It is not an independent
benchmark, production calibration set, or proof against prompt injection. Preserve
misclassifications in evaluation reports and evaluate real traffic before lowering
fallback thresholds. A raw first run misclassified one simple supplied-image meme
as high effort; adding that case to the low-effort rubric resolved the development
fixture. The Mac path is Apple Silicon only and must be compile-guarded in the
shared Swift app. Final repository verification must cover both iOS and macOS.

An independently authored 12-case set is preserved in `tests/routing-heldout.json`.
With the unchanged rubric, all 10 accepted bot routes were correct and two uncertain
requests abstained; effort matched 10/12 labels. A short travel request and simple
expense split were assigned high rather than low. Those results informed the separate
0.5 effort abstention threshold, so both the original 16 and this secondary 12 are
development/calibration data. The semantic rubric was not tuned against the secondary
set. Neither set establishes production accuracy.

The fresh final 10 cases in `tests/routing-final-acceptance.json` were written after
that policy froze. On the pinned macOS 14-compatible MLX runtime, six accepted routes
were correct, two other routable factual questions abstained, and two unclear or
unsupported questions abstained. All six automatic effort decisions matched the
labels; raw effort accuracy was 9/10, with a mismatch on unsupported fiction that
was not dispatched. The final gate passed without changing its labels, rubric or
thresholds. This is small acceptance coverage, not a production accuracy estimate.
