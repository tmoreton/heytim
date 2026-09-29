# Tool reliability within the eight-hour task limit

This audit keeps the existing eight-hour runtime lifetime and cumulative background
budgets of 160 model attempts and 96 metered provider calls. The eight-turn SDK
slice is a checkpoint, not a task limit: the same agent resumes its existing
history and usage accumulator. Image and YouTube sublimits remain in force.

## Repairs

GitHub and Google Workspace MCP transports previously captured an access token in
an HTTP header during setup and reused it for the entire task. GitHub installation
tokens expire after one hour; Google tokens include an `expires_in` lifetime.
The HTTP transport now refreshes before dispatch using the provider's reported
expiry, with a small margin. Workspace servers share one credential and renewal
lock across their transport threads. Refresh runs outside the agent's event loop.
Each renewal rereads the connection's stored grant, and GitHub still intersects
the bot's repository selection with that grant. Static bearer-token connections
and the existing direct provider API adapters retain their authentication paths.

Credentials are restricted to the connection's HTTPS origins. Failed renewal
does not fall back to an expired token. Authentication failures, provider errors,
and transport timeouts do not trigger a replay of a tool request. A 401 invalidates
the cached token for a subsequent, separately requested dispatch. Missing expiry
metadata disables caching; invalid or already-expired credentials are rejected.

The calculator previously checked magnitude only after evaluating an entire
expression. Nested powers could therefore allocate very large integers before
the check. It now checks every intermediate value, bounding the next operation
and rejecting non-finite and complex values.

Provider references: [GitHub installation token lifetime](https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/github-credential-types),
[Google OAuth token renewal](https://developers.google.com/identity/protocols/oauth2/web-server),
[HTTPX asynchronous authentication](https://www.python-httpx.org/advanced/authentication/).

## Regression coverage

All test paths below are relative to `services/runtime/tests/` unless specified.

| Tool family | Checks |
| --- | --- |
| All 15 catalog tools | `test_local_tools.py` resolves every published tool through the runtime binding validator. |
| Local arithmetic and clock | `test_local_tools.py`, `test_runtime_tools.py`: valid arithmetic, bounded computation, and configuration. |
| GitHub and Google Workspace MCP | `test_mcp_long_running.py` drives the installed MCP SDK and HTTP authentication with mocked provider responses from startup to 7h 59m 59s; all dispatches occur once. |
| Custom MCP and Home Assistant | `test_generic_mcp_connections.py`, `test_mcp_connections.py`, `test_home_assistant_decisions.py`: assigned credentials, names, endpoint guards, and approvals. |
| Token renewal | `test_mcp_auth.py`: simultaneous renewals, account isolation, short/invalid expiry, revoked credentials, event-loop responsiveness, origin checks, and no authentication replay. |
| Connected provider APIs | `test_provider_connections.py`, `test_finance_provider_tools.py`, `test_gmail_api.py`: account and resource scoping, read operations, token rotation, finance ledger reads, and draft creation. |
| Web search and provider quotas | `test_runtime_tools.py`: gateway dispatch counting, cumulative limits, and YouTube quota leases. |
| Browser and code execution | `test_browser_execution.py`, `test_browser_session.py`, `test_code_interpreter_input.py`, `test_runtime_tools.py`: SDK dispatch, connection isolation, serialized browser actions, reconnection, and background commands. |
| Files, workspaces, and large results | `test_tool_results.py`, `test_artifacts.py`, `test_workspace_assets.py`, `test_workspace_sync.py`, `test_repository_workspace.py`: full-record exports, paging, retained files, scoping, and repository access. |
| Images and memes | `test_image_generation.py`, `test_memes.py`, `test_points_screenshot_tool.py`: provider output validation, references, artifacts, and evidence capture. |
| Device tools and approvals | `test_device_tools.py`, `test_action_approval.py`, backend device/approval suites, and shared Apple verification: validated dispatch, exact interrupted-call matching, and client behavior. |
| Bot management and runtime recovery | `test_bot_management.py`, `test_long_running.py`, `test_runtime_jobs.py`, and backend worker suites: mutation tracking, 80 actions across checkpoints, truncation recovery, cancellation, durable claims, and terminal outcomes. |

These are deterministic regressions with simulated providers and elapsed time.
They do not certify live third-party availability or constitute a real eight-hour
production run. The binding check verifies catalog compatibility; provider and SDK
behavior are exercised in the separate suites listed above.

Run `./scripts/verify.sh runtime`, the API Python suite, catalog/contract checks,
`./scripts/apple-app.sh build`, and `./scripts/apple-app.sh verify`. The Apple
commands cover both iOS and macOS. Hosted runtime changes take effect through
the existing production release workflow; installing an Apple update alone does
not deploy them.
