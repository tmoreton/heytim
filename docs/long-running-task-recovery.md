# Long-running task recovery

The September 26, 2026 incident ending at 18:36 UTC failed with `MaxTokensReachedException` after about 101 seconds.
It was not the eight-hour AgentCore deadline. A large JSON result was repeatedly truncated by line-oriented
retrieval and context management, which drove repeated provider reads. The runtime also counted output-limit
continuations across the entire job, even when successful work occurred between them. Exhausting that counter
escaped to the generic background-job error.

## Shared runtime behavior

- All background tasks use eight-turn agent slices. The SDK finishes the current tool batch before stopping;
  the runtime saves its snapshot and invokes the same agent with no new prompt. Completed actions remain in history.
- Public SDK `result` events drive limit and interrupt handling. Internal `stop` events are retained only for
  compatibility. Public tool-result messages reset the consecutive output-recovery counter.
- The entire job keeps one deadline and usage accumulator. Retries and fallback calls are included. The background
  envelope is 160 model attempts and 96 metered provider calls by default; image and YouTube sublimits are unchanged.
- Output recovery adapts the response allowance up to 16,384 tokens and stops after three consecutive recoveries
  without successful tool work. Terminal output exhaustion is classified explicitly.
- Every oversized tool result is stored behind a reference bound to its authorized turn. JSON can be inspected in
  readable lines or bounded character pages, so a long individual field remains accessible. Stored references survive
  recreation within that scope. Export converts saved records directly without provider calls or model transcription.
- Normal agent callbacks are disabled so model text, reasoning, and tool details are not printed into runtime logs.

## Verification

`services/runtime/tests/test_long_running.py` exercises the installed Strands harness with a deterministic model,
80 sequential actions, eight-turn slices, six separate output truncations, and a transient model timeout. It verifies every action executes
once, model attempts remain cumulatively counted, and checkpoints preserve the completed prefix of work.

`test_tool_results.py` exercises the installed automatic context manager with a large 21-record JSON result and
direct CSV export. The export takes one provider call and three model calls, retains all records and fields, and
supports durable workspace staging. Other cases cover multiple pages, long Unicode text, nested fields, CSV quoting
and formula escaping, restart retrieval, and rejection of references from another scope.

The streaming and runtime suites also cover no-progress recovery limits, deadline and idle timeout, cancellation,
duplicate job dispatch, checkpoint failure, terminal outcomes, and saving approval/device interrupts from the public
SDK result event. Run the full runtime and backend suites before
rollout; shared Apple verification covers both iOS and macOS.

## Recovery boundary

Automatic continuation is safe at an SDK slice boundary and for uncommitted model responses. It does not automatically
replay a process that died during an external action: that action may have completed without a persisted receipt.
The existing durable job claim prevents replay of such an uncertain run. Storage/network failures and genuine
cumulative budget exhaustion can still stop a task, with a classified outcome rather than a false completion.

This is a runtime change. Deploy it through the existing reviewed release path; no new client API or AWS resource
identity is required. A downloaded Apple binary alone does not update the hosted runtime.
