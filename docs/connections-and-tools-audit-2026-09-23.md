# Connections and tools audit

The supported workflow is: connect an account or trusted HTTPS MCP server in
Settings, then enable that exact connection ID in an individual bot's Tools list.
No new connection is automatically granted to any bot. Secrets remain in AWS
Secrets Manager; the client and bot prompt receive only public labels. The bot
runtime resolves only its assigned IDs. Adding another OAuth account uses a
fresh sign-in session to avoid silently reconnecting the existing identity.

| Connection | Multiple grants | Bot selection | Resource narrowing |
| --- | --- | --- | --- |
| X | Separate X user IDs | Each account | Read-only OAuth scopes |
| YouTube | Separate channel or Google user IDs | Each account | Read-only channel scope |
| Slack | Separate workspace/user IDs | Each account | Optional channel links |
| GitHub | Separate app installation IDs | Each installation | Individual installed repositories |
| Gmail | Separate email addresses | Each account | Reviewed read and draft tools |
| Google Workspace | Separate Google user IDs | Each account | Optional Drive, Sheets, or Calendar links |
| MCP servers | Separate endpoint URLs | Each server | Server-advertised tools; no client-side per-tool filter |

The visible Home Assistant setup is now the same MCP server form as any other
server. Enter its full `/api/mcp/assist` URL and a long-lived token. Existing
Home Assistant grants retain their IDs and credentials but appear under MCP
servers; updating the same endpoint through the generic form migrates the grant
in place. The update form keeps the endpoint fixed to preserve bot assignments.
The old API route and credential decoder remain only so older app
versions and stored grants continue to work.

Laya and its bundled Core ML checkpoint were removed. Mac accessibility actions
still require an exact visible control or the bounded Apple Notes flow. Home
Assistant commands now enter the normal bot/MCP tool path; there is no client
classification delay or separate model-driven approval route.

Current constraints: users may save up to 50 total connections, and a bot may
enable up to 12 tool IDs. Custom MCP connections require a bearer token and a
public HTTPS endpoint on port 443; local-network, tokenless, and OAuth-only MCP
servers are not yet supported. A server can advertise many tools, so users
should connect only servers they trust and assign them sparingly. This audit
does not claim that a newly added third-party server or live home-device action
was exercised.
