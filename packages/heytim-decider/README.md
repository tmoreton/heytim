# Local Decider for the HeyTim Mac app

The Mac app owns one local helper process. It uses Strands Decider's typed pointer
head to choose an authorized bot and reasoning effort. It does not transcribe audio
or generate the final answer. Inference has no HTTP server and disables Hugging Face
network access. Only model preparation accesses the Hub.

## Reproducible runtime

- CPython 3.12.12 from uv's relocatable standalone distribution, never Homebrew Python.
- PyTorch 2.13.0, including its CPython 3.12 macOS 14 arm64 wheel.
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

Audit the full helper lock with pinned `pip-audit==2.10.1`, `--no-deps`,
`--disable-pip` and `--require-hashes`. The repository dependency gate includes
this lock. Its registry scan explicitly skips the Strands GitHub archive because
that commit has no corresponding registry package version; code review and the
pinned archive hash cover a different part of the dependency trust boundary.
The Torch 2.13.0 lock had no known registry advisories on 2026-10-14. This is a
database result, not proof that every PyTorch API is safe.

Supported inputs contain bounded text and bot metadata. The fixed model uses
verified, pinned safetensors files. The helper does not accept pickle, `.pth` or
`.pt2` model inputs, call `torch.export.load`, or run an RPC/distributed server.
Keep those limits when changing the model lifecycle; unused upstream model
loaders are not an authorization to accept arbitrary model files.

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
No candidates, the `clarify` option, confidence below 0.6, or a top-two probability
margin below 0.15 produce `botId:null` and `needsReview:true`. These are calibrated
starting thresholds, not measured production guarantees. Effort is one of
`low`, `high`, `max`; the app/backend must clamp it to the selected model's supported
settings and respect explicit user overrides.

Effort has a separate abstention rule: when `reasoningConfidence` is below 0.6,
`reasoningDeferred` is true and `reasoningEffort` preserves the selected bot's saved
preference (default high). `suggestedReasoningEffort` and `reasoningConfidence`
retain the raw classifier output. The helper always defers no-bot results.
For three choices, concentration 0.6 means a top probability of about 0.7333; this is
a calibrated starting policy, not a probability-of-correctness guarantee.

A local webhook source can have an optional, owner-selected `fallbackBotId` from
its permitted bots. When the validated classifier result abstains, the service
uses that configured fallback with the bot's saved reasoning preference; the
effective decision records `method:local_fallback` and retains the raw validated
result in `localDecision`. Without a fallback, uncertain messages wait for manual
review. Source policy and bot permissions are fenced and revalidated before
dispatch. Keep the Mac app running for local decisions; messages wait while it
is unavailable. The helper never chooses or applies a fallback itself.

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

The original final 10 cases in `tests/routing-final-acceptance.json` were written after
the effort policy froze. At the original 0.8 route cutoff on the pinned macOS
14-compatible MLX runtime, six accepted routes
were correct, two other routable factual questions abstained, and two unclear or
unsupported questions abstained. All six automatic effort decisions matched the
labels; raw effort accuracy was 9/10, with a mismatch on unsupported fiction that
was not dispatched. The final gate passed without changing its labels, rubric or
thresholds. Their outputs were subsequently used for route-cutoff calibration, so
these ten cases are now development/calibration coverage too.

`tests/routing-catalog.json` preserves three cases labeled before inference, using
the actual server projection of 10 or 17 public catalog bots with opaque UUIDs.
The evaluator selects each case's named `candidateSet`; unknown or missing set
names fail before model loading. Run this supplemental gate from this directory:

```sh
PYTHONPATH=src .runtime/python/cpython-3.12.12-macos-aarch64-none/bin/python3.12 \
  scripts/evaluate.py --model-root "$HOME/Library/Application Support/HeyTim/Decider/models" \
  --device mlx --fixtures tests/routing-catalog.json --output .build/evaluation-catalog.json
```

At the original 0.8 cutoff on Torch 2.13.0, the correct trip, budget and research
bots ranked first, but all three abstained: route confidence was 0.6169, 0.6716 and
0.7927, below the original dispatch cutoff. The gate failed with 0/3 routing
coverage; this result must not be
reported as successful automatic routing. Raw effort matched all three labels;
the budget effort confidence was only 0.2654. With no selected bot, all three
results deferred reasoning and dispatched nothing. The largest contexts were
2,546, 1,570 and 2,534 tokens of 4,096, with no truncation; catalog fingerprints
were excluded from the model input. These small checks expose a limitation with
larger, overlapping catalogs. Use source allowlists to limit candidates and keep
uncertain messages available for manual routing.

The original 16, secondary 12, original final 10 and catalog 3 cases are now 41
development/calibration examples. A retained-output simulation of global route
cutoffs 0.60, 0.65, 0.70, 0.75 and 0.80 accepted 35, 34, 33, 33 and 30 correct
routes respectively, with no wrong accepted routes and all six expected `clarify`
cases still abstaining. Catalog margins were 0.5011, 0.6132 and 0.7692, while
`clarify` probabilities were only 0.0220, 0.0282 and 0.0223. The route cutoff was
therefore calibrated to 0.60; the 0.15 margin and 0.50 effort gate stayed fixed.
Concentration measures how sharply the distribution peaks, not a calibrated
probability of correctness. These examples do not establish a production error
rate, and the original 0.80 failure reports remain preserved.

`tests/routing-catalog-acceptance.json` retains the next independently authored
12-case run, including its failure. With route cutoff 0.60 and the earlier effort
cutoff 0.50, seven of ten routable cases selected the correct bot, but one rigorous
statistical-analysis request automatically received high effort instead of the
frozen max label (reasoning confidence 0.5825). Raw effort matched 9/12 labels;
the gate failed rather than accepting that override.

The effort cutoff was subsequently calibrated to 0.60 without changing the rubric
or labels. Across all 53 retained cases, this defers that incorrect automatic
decision and retains 28 correct automatic effort decisions among 42 routed cases
(66.7%). The secondary 12-case subset still fails the unchanged 60% effort-coverage
gate at 5/10, and the later 12-case subset fails it at 4/7. These are explicit
coverage-only failures, not successful individual gates. All 53 examples are now
development/calibration evidence. Original failures remain preserved.

The subsequent independent eight-case run used the frozen 0.60 routing/effort
policy and unchanged 10/17-bot projections. It failed both unchanged coverage
gates: two of six routable requests selected the correct bot (33.3%), and one of
those two applied effort automatically (50%). No incorrect route or automatic
effort was accepted; raw effort matched 5/8 labels. The unchanged fixture is
preserved in `tests/routing-catalog-final.json`, and the full original results
remain under `output/webhook-routing/catalog-final-results.json`; this run is
not a passing acceptance gate and was not used for further tuning. Broad-catalog
automatic routing remains limited; use narrow permitted-bot lists and retain the
manual inbox fallback.
