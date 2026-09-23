# Laya, Mac Accessibility, and Home Assistant audit

Date: 2026-09-23

## What the platform APIs actually provide

macOS `AXIsProcessTrustedWithOptions` only requests Accessibility permission;
its return value does not wait for the user to grant it. HeyTim must refresh
trust when it regains focus and offer to reopen after a changed grant. An
`AXUIElement` represents a live, mutable UI object, so a recommendation cannot
be treated as authority to press the same object later. The current Mac path
uses `AXUIElementCreateApplication`, a focused window, a bounded tree walk,
visible buttons, and a fresh recheck at approval time. It does not use screen
pixels or Screen Recording permission. References:
[Apple trust check](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions),
[Apple AXUIElement APIs](https://developer.apple.com/documentation/applicationservices/1462083-axmakeprocesstrusted).

Home Assistant's [MCP Server](https://www.home-assistant.io/integrations/mcp_server)
serves the built-in Assist API at `/api/mcp/assist`. The authenticated Assist
user and Home Assistant's exposed-entity settings determine what is visible;
tool names and schemas must be discovered at runtime. `GetLiveContext` may
provide a read-only context-snapshot resource, while the
[built-in intents](https://developers.home-assistant.io/docs/intent_builtin/)
include `HassTurnOn`, `HassTurnOff`, and `HassGetState`. Their parameters are
names, areas, and domains, not a universal `entity_id` argument. We must not
invent such an argument from an entity ID or equate a model label with a real
MCP tool call.

The established integration pattern is to let Home Assistant supply the
capability list at request time, then dispatch only through one of those tool
contracts. Its [LLM API guidance](https://developers.home-assistant.io/docs/core/llm/)
describes the built-in Assist API as scoped to the same exposed entities and
capabilities as Assist, and third-party tools as dynamically contributed when
needed. For the Mac side, Apple's
[UI scripting guide](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/AutomatetheUserInterface.html)
likewise requires per-app Accessibility consent; HeyTim's local tree, proposal,
and revalidation follow that permission boundary instead of treating a model
output as an executable command.

## Changes in this branch

- Reintroduced the pinned, checksum-verified Laya Core ML model in the Mac
  bundle; it loads lazily and never downloads in the installed app. The Mac
  implementation uses it only after an explicit app-targeted click/press
  request fails an exact visible-label match. It selects from at most four
  already-filtered buttons plus `main_model`; high-impact controls are never
  candidates. The app still requires the per-bot tool toggle, macOS permission,
  and the existing chat action flow. Exact low-risk navigation controls can
  execute immediately; a Laya-only match still requires approval because its
  reported confidence is not an authorization signal.
- The Accessibility snapshot no longer retains arbitrary non-control labels.
  Secure/hidden subtrees are skipped. Before either automatic or approved
  execution, HeyTim checks age, target PID, label, enabled state, press support,
  and current window. An explicit Apple Notes request with exact note text and
  a unique `New Note` button can also execute immediately.
- The Home Assistant connection remains server-side. A read-only MCP diagnostic
  now reports exact discovered capabilities and schema-bearing candidates.
  A separate experimental Laya policy accepts only one explicit request, a
  fresh externally resolved exposed entity, and one discovered tool. It emits
  an advisory descriptor with **no executable arguments**. It is used by the
  offline fixture scorer, not by production Home Assistant turns.

## Evaluation and limits

The nine-case offline Home Assistant suite passes after the guard, but the raw
Laya checkpoint still makes six wrong choices on that small suite, including
confident choices for quoted and hypothetical commands. The guard, not the
model's reported confidence, is stopping those requests. The Mac intent
fixtures pass; a semantic `next month` versus `Next` button probe has low
model confidence and correctly abstains. These fixtures never contact Home
Assistant or control a Mac app.

This is intentionally not a Home Assistant fast path. Before the backend can
skip the main model, it needs a server-side broker that obtains a fresh Assist
snapshot, resolves exactly one exposed target, validates the precise live MCP
schema and arguments, preserves per-bot grants and approval, and persists the
tool result. The model must be calibrated on held-out HeyTim requests with
zero unsafe mutating routes before promotion. Laya's
[model card](https://huggingface.co/convaiinnovations/laya/blob/main/README.md)
specifically warns that the base checkpoints are weak on some zero-shot typed
decisions and ship overconfident.

The Mac model adds roughly 460 MB to the app. It may improve latency only for
the narrow semantic-button fallback; it will not save a cloud model turn for
ordinary messages. Apple Notes with explicit user-provided text remains a
deterministic local operation because introducing a model would add work and
failure modes. Mac local action messages are currently client-side and are not
yet a general server-invocable tool; broader cross-platform bot orchestration
is separate work.
