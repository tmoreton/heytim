# Laya and Home Assistant: bounded action experiment

> Historical research note: Laya, its evaluation scripts, and the Home
> Assistant fast path have been removed. Home Assistant now uses an assigned
> MCP connection like other servers.

Laya is **not** trusted as a Home Assistant executor. The Mac app bundles the
pinned multilingual Core ML 128-token checkpoint and loads it lazily to classify
simple Home Assistant requests for bots with that connection enabled. It also
ranks safe, visible Mac buttons when an explicit click/press request has no
exact label match. Apple Notes with explicit text still uses the faster
deterministic path. The Home Assistant broker executes only after independently
checking the bot grant, live Assist context, and advertised MCP schema;
state-changing calls use the existing exact-action approval.

The Mac Accessibility inspector walks only the current app's focused window,
skips hidden and secure-text subtrees, and retains only bounded pressable
control labels. It does not send an Accessibility tree or field values to the
server. Approval rechecks the app PID, enabled state, action support, label,
window, and snapshot age. Apple's
[Accessibility client APIs](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions)
require an explicit user grant; the prompt does not synchronously grant it.

## Action vocabulary

An experimental router may choose one of four *abstract* labels:

| Label | Meaning | Preconditions |
| --- | --- | --- |
| `read_state` | Read the current state of one exposed entity | A fresh, uniquely resolved entity and a read-only MCP capability are available |
| `turn_on` | Propose turning that entity on | Explicit present-tense command, one exposed entity, and a matching MCP tool/schema |
| `turn_off` | Propose turning that entity off | Same checks as `turn_on` |
| `main_model` | No local action; use the normal bot | Default for questions needing reasoning, negation, hypotheticals, quotes, ambiguous targets, missing tools, or errors |

The labels are not MCP tool names. Each Home Assistant instance supplies its own
tool list and input schemas at `tools/list`. `check_home_assistant_mcp.py` reports
schema-bearing action candidates without calling any tool. The Mac app sends
only an optional Laya label and scores with the normal bot message. The runtime
broker re-lists MCP tools, reads fresh Assist context, requires exactly one
matching exposed light or switch name, and verifies the action schema accepts
a `name` string. It never accepts a model-supplied tool name or arguments. It
prefers the read-only `homeassistant://assist/context-snapshot` resource and
falls back to `GetLiveContext` on older servers.

The broker builds a bounded record from trusted server-side discovery:

```text
request: Turn off the bedroom light
resolved_name: Bedroom light
exposed_to_assist: true
available_actions: read_state, turn_on, turn_off, main_model
```

The name must be resolved independently from fresh Assist context. A model
choice cannot authorize a home change. For `turn_on` or `turn_off`, the runtime
creates an exact-action proposal with the MCP tool and arguments in the existing
bot approval UI. On approval, it rechecks the target, schema, grant, and digest
before calling the tool once. The worker consumes approval durably before
dispatch so an uncertain outcome is not retried. A fresh snapshot is used for
read-back; if confirmation is unavailable, the answer says so. Never call a
mutating Assist tool to "preview" a command.

## Current evaluation result

Run `apps/iOS/scripts/evaluate-laya-home.sh` for the offline fixtures. With the
pinned L128 model, nine simple and adversarial requests produced six wrong raw
routes on 2026-09-22, including home-changing choices for negated,
hypothetical, quoted, and wrong-room requests. The model's confidence and
action probability did not separate those failures. A deterministic single-
request guard plus model agreement now sends those six cases to the main model;
the nine-case offline suite passes, but the sample is far too small to certify
production use. No home tools are executed by this evaluation. The model's own
[card](https://huggingface.co/convaiinnovations/laya/blob/main/README.md)
warns that base checkpoints need specialization and task-specific calibration.

The narrow broker is now opt-in through the existing per-bot Home Assistant
tool grant. A simple status question can finish without the large model, and a
single on/off command can reach exact-action approval without that model.
Anything else falls back to the normal bot. New offline broker tests cover
ambiguous names, wrong model labels, missing grants, schema rejection,
approval mismatch, and confirmed read-back. In a separate local Laya run,
simple on/off labels took about 130–150 ms warm inference, but Laya was also
confidently wrong on a negation and a hypothetical; the backend grammar rejects
both. The read-state label allows lower model confidence because exact question
grammar and fresh context still determine the answer. These tests do not
establish live Home Assistant behavior. Production promotion still needs
read-only discovery against the connected instance and an explicitly authorized
live device test; no mutating device test has run.

## Read-only connection check

`services/runtime/scripts/check_home_assistant_mcp.py` performs an MCP initialize,
`tools/list`, and `resources/list` without calling tools or printing the token.
Run it only with a private `HOME_ASSISTANT_URL` and `HOME_ASSISTANT_TOKEN` in the
environment. It verifies transport and exposure, not a device mutation.
