# Browser tool repair — September 9, 2026

## Reproduced failures

GitHub Engineer turn `1623bfc0-528e-4aff-8912-21b4e9a40fa4` recognized the
browser tool but repeatedly sent `browser_input` as a JSON-encoded string. Runtime
tool spans confirmed Pydantic rejected the nested value before browser execution.
No submission occurred.

After adding strict compatibility decoding, live diagnostic
`41966be0-91f1-4ce8-8779-fd4d957b900a` successfully reached browser initialization,
then failed. The upstream browser implementation applies `nest_asyncio` globally
and drives a nested event loop. Logs showed subsequent AnyIO/ASGI event-loop errors
and the primary model connection failing. This demonstrated why schema-only tests
were insufficient.

That connection failure also exposed a separate model constraint: at least one
prefixed GitHub MCP tool name exceeded the common 64-character limit. The runtime
now assigns every remote MCP tool a stable, connection-scoped alias no longer than
64 characters while retaining the original name for server calls.

## Shared runtime changes

- `CompatibleBrowserInput` decodes exactly one JSON object at the declared nested
  input boundary. Invalid JSON, non-objects, oversized input, unknown actions and
  missing required fields still fail validation. The model-facing schema remains
  the original typed action object; it does not advertise strings as valid input.
- Browser calls are asynchronous from the agent's perspective and serialized on
  one dedicated worker. Playwright uses its own loop without globally patching
  asyncio. Constructor loop changes are restored immediately and request/tracing
  context is copied into worker calls.
- Browser cleanup runs on the same worker. Close resets startup state so a later
  action can reopen the browser. Tracked AgentCore browser clients are stopped on
  close instead of being left running until their session timeout.

These changes apply to every bot using the shared browser adapter. No bot prompt,
permission grant, authentication rule, or Lambda recursion setting was changed.

## Verification

The full runtime suite passed 137 tests; Ruff, source-size and whitespace checks
passed. Regression tests cover real Strands tool dispatch for both input formats,
invalid-action rejection, an unchanged typed schema, server-loop responsiveness
during browser startup, AnyIO compatibility, context propagation, serialized
parallel calls, and close/reopen behavior.

Both deployment previews changed only the AgentCore code artifact. Version 44
contained the input fix and exposed the second issue during the live test above.
The failed diagnostic's exact browser session `01M24069KYYVCFQ3KD5EPDXG9S` was
stopped explicitly. Runtime version 45 deployed successfully and reported READY
at 21:18:11 UTC with execution isolation included.

Live GitHub Engineer turn `c39802dc-cefe-4627-aced-06288ccc2f42` completed from
21:18:56 to 21:19:36 UTC (about 41 seconds). Five browser tool spans reported OK,
the browser stop operation was logged, and the app saved COMPLETE with its
notification queued. The bot reported the actual rendered heading, "Build on the
Claude Platform", and Google, email and SSO sign-in options at
`https://platform.claude.com/plugins/submit`. The submission form is behind
authentication. No fields were filled, no login was attempted, and nothing was
submitted or changed on GitHub. The browser-tool repair is verified; the plugin
submission itself is not complete.

All production probes are read-only: inspect the current Anthropic plugin
submission page, report actual visible evidence, and close the browser. They must
not sign in, fill fields, submit a form, create accounts, or modify GitHub.

## Follow-up design

See [Chief-assisted bot maintenance](chief-bot-maintenance.md) for scoped
diagnostics, approved versioned repairs, health checks and reviewed regression
learning. This design is proposed, not an enabled management capability.
