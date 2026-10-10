# Custom MCP connections

Users can open Settings → Accounts & MCP Servers → MCP server, or choose a Connect link from Chief's
Connect an integration skill. A link only opens a form. It cannot save credentials, assign tools or execute actions.

## Setup and permissions

1. Enter a name and public HTTPS MCP endpoint. Choose bearer-token or anonymous authentication.
2. Test the connection. The authenticated `POST /connections/mcp-servers/discover` route performs only
   `initialize`, `notifications/initialized` and bounded `tools/list` requests, then attempts to close any
   temporary MCP session. It does not call business tools.
3. Select tools and bots. No tools are selected automatically. Server descriptions are untrusted display text.
4. Saving rechecks the selected tools against their executable schema digests. Changed tools require another review.
5. The runtime filters discovery and rejects direct calls to unselected or changed tools. The selection belongs to
   the connection and applies to every bot assigned that connection. Different per-bot selections and multiple
   credential profiles for one endpoint are not yet supported.

New reviewed custom connections require an explicit action grant even when the bot otherwise runs automatically.
The owner's existing Always Allow decision can enable the reviewed surface; it does not permit additional server
tools or changed schemas. Scheduled runs require that grant in advance. Existing unreviewed connections retain their
compatibility behavior until the owner tests and reviews them. Old Apple clients can still save the original
unverified bearer-token connection format.

The saved `tested` status records the successful setup check, not continuous availability. An unavailable reviewed
server is omitted during runtime capability loading so other tools remain usable. HeyTim never fabricates a
successful external action. Credential rotation is server-side and changes the owner grant digest. Anonymous
connections use no credential secret. A unique internal revision marker occupies their credential reference field
so concurrent reconnects still use the existing conditional-write guard; the marker is never sent to the runtime.

## Network and resource boundaries

The cloud path requires public HTTPS on port 443. It rejects private/local addresses, URL credentials, query strings,
fragments and redirects. Discovery and runtime connect to the validated public IP while preserving the original
hostname for TLS verification. Runtime transport does not inherit environment proxies. OAuth provider adapters
retain their fixed, separately reviewed authentication behavior.

Discovery is bounded to 100 tools, 8 pages, 32 KB per tool schema and 256 KB per API discovery response. Repeated
cursors fail. Setup uses a 12-second discovery deadline and short socket reads; a read already in progress may
finish up to 3 seconds later; optional session cleanup uses a one-second socket timeout. Runtime initialize/list requests use short timeouts, reviewed discovery has page/count
and elapsed-time limits, and raw transport responses are capped at 8 MB. Existing result offloading remains active.
System DNS resolution still follows the operating system's resolver timeout; the application deadline is not a hard
upper bound on a stuck DNS resolver.

The current MCP SDK supports legacy Streamable HTTP protocol revisions through 2025-11-25. Generic MCP OAuth,
2026-07-28 protocol support, local stdio servers, a Mac private-network bridge, custom-header credentials and REST/
OpenAPI adapters are separate compatibility work. The setup must not promise that every MCP server is compatible.

## Home Assistant

Use the configured Home Assistant MCP integration and its `/api/mcp/assist` URL, with a Home Assistant access
token. SSH keys do not authenticate this HTTP endpoint. A LAN address such as `http://192.168.x.x:8123` is suitable
for an authorized local diagnostic but is not reachable by HeyTim's AWS runtime. Use an existing supported HTTPS
remote route to connect it to the cloud. Do not expose a local port automatically.

The October 9 local integration test discovered 27 native Home Assistant tools, selected only
`homeassistant__GetLiveContext`, successfully read context through the reviewed runtime client, and rejected an
unselected `intent__HassTurnOn` call before any network action. No device state was changed. That diagnostic used
an explicitly injected LAN transport; shipped URL validation was not relaxed. AWS reachability remains unverified.

## Verification

The runtime tests cover tool selection, schema changes, direct-call rejection, connection failure isolation,
cursor loops, TCP address pinning and secure setup links. Backend tests cover bounded discovery, sanitized failures,
TLS hostname preservation, tenant isolation, stale review rejection, explicit grants and credential-free anonymous
reconnection. Shared Apple tests cover link parsing and discovery decoding; the UI test verifies that saving remains
disabled until discovery and tool review.
