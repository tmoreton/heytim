# Workspace Files and Documents audit

## Recommendation

Keep the two storage concepts separate, but present them through one **Files** destination in the app.

- **Working files** should contain the durable inputs and agent-managed assets that HeyTim can reuse and revise.
- **Created files** should contain the read-only outputs produced in chat that a person can preview or save.

This preserves their different ownership and lifecycle rules without asking people to understand two similar-sounding navigation items.

## Current behavior

| | Workspace Files | Documents |
| --- | --- | --- |
| Primary purpose | Durable working context | Finished chat outputs |
| Created by | A person uploading a file, or an agent saving an asset | An agent generating an artifact in a reply |
| Scope | Bot or group | Bot only in the current listing API |
| Mutability | Agent-managed assets have stable identity and revisions | Immutable output records |
| Reuse | Can be selected and attached to later turns | Can be previewed or downloaded |
| Limits | 50 files and 100 MB per workspace | Generated-artifact limits and bot lifecycle |
| Lifecycle | Explicit add/delete; scoped to its workspace | Preserved as bot output and removed with the bot |
| Download contract | Scope-aware workspace route | Ordinary bot file route |

## Download defect

The Workspace Files screen was downloading through the ordinary attachment route even though the API exposes dedicated bot and group workspace download routes. Workspace listing and updates use the authoritative workspace record, while the ordinary route relies on a secondary `FILE` alias. That mismatch makes download behavior depend on the alias being present and current.

The client now resolves a workspace file through its scope-aware workspace download route before fetching the short-lived signed URL. A regression test covers URL encoding, local preview creation, and cleanup.

## Proposed information architecture

Replace the two conversation-detail rows with one **Files** row. Within that view:

1. **Working files** — “Files HeyTim can reuse and update.” Include add, revision, delete, and attach controls.
2. **Created files** — “Files made in this chat.” Include preview and save/share controls.

Do not merge the underlying records or endpoints. A data-model merge would blur revision semantics, quotas, group membership checks, retention, and whether a file is working context or a finished output. The UI can later add a deliberate action to promote a created file into Working files when that is useful.

## Follow-up needed for a complete UI merge

- Add a group-scoped created-files listing API, or explicitly omit Created files for groups.
- Decide whether “made in this chat” means the current conversation only or all output retained by the bot.
- Add a **Keep as working file** action for generated outputs instead of silently changing their lifecycle.
- Preserve the two distinct download authorizations even when both sections share a screen.
