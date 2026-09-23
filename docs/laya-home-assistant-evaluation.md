# Laya and Home Assistant: bounded action experiment

Laya is **not** a production Home Assistant executor. The Mac app does not load
or bundle it. The existing bot-to-Assist-MCP path remains the production path,
and interactive tool calls use the exact-action approval flow.

## Action vocabulary

An experimental router may choose one of four *abstract* labels:

| Label | Meaning | Preconditions |
| --- | --- | --- |
| `read_state` | Read the current state of one exposed entity | A fresh, uniquely resolved entity and a read-only MCP capability are available |
| `turn_on` | Propose turning that entity on | Explicit present-tense command, one exposed entity, and a matching MCP tool/schema |
| `turn_off` | Propose turning that entity off | Same checks as `turn_on` |
| `main_model` | No local action; use the normal bot | Default for questions needing reasoning, negation, hypotheticals, quotes, ambiguous targets, missing tools, or errors |

The labels are not MCP tool names. Each Home Assistant instance supplies its own
tool list and input schemas at `tools/list`. A future implementation must discover
these live, validate the selected tool and its arguments against that schema, and
never invent a tool name or entity ID. Home Assistant may also expose a read-only
`homeassistant://assist/context-snapshot` resource for target resolution.

The input to the router should be a bounded record, not an unconstrained chat:

```text
request: Turn off the bedroom light
resolved_entity: light.bedroom
exposed_to_assist: true
available_actions: read_state, turn_on, turn_off, main_model
```

The entity must be resolved independently from fresh Assist context. A model
choice cannot authorize a home change. For `turn_on` or `turn_off`, show the exact
MCP tool and arguments in the existing bot approval UI, then run only after
approval and report the observed result. Never call a mutating Assist tool to
"preview" a command.

## Current evaluation result

Run `apps/iOS/scripts/evaluate-laya-home.sh` for the offline fixtures. With the
bundled experimental L128 model, nine simple and adversarial requests produced
six wrong routes on 2026-09-22, including a home-changing choice for negated,
hypothetical, quoted, and wrong-room requests. The model's reported confidence
and action probability did not separate these failures. This fails the safety
gate for a production fast path; no home tools are executed by this evaluation.

Promotion requires an independently reviewed fixture suite with zero unsafe
mutating routes, real MCP tool/schema discovery, unambiguous entity resolution,
end-to-end approval tests, and latency measurements against the normal bot path.

## Read-only connection check

`services/runtime/scripts/check_home_assistant_mcp.py` performs an MCP initialize,
`tools/list`, and `resources/list` without calling tools or printing the token.
Run it only with a private `HOME_ASSISTANT_URL` and `HOME_ASSISTANT_TOKEN` in the
environment. It verifies transport and exposure, not a device mutation.
