# Provider integrations

FroggyBot has two integration layers:

- Public research is platform-funded and needs no user sign-in. The current catalog keeps public X research and
  YouTube search, video details, and comments in this layer.
- Private account access is optional and user-scoped. The backend stores OAuth refresh grants or a GitHub App
  installation grant in Secrets Manager; clients receive only sanitized connection metadata.

Legacy generic MCP bearer/API-key records are intentionally unsupported. They remain in storage until their owner
deletes the account or removes the record, but they are not listed, selectable, or accepted by runtime resolution.
Reconnect the one pilot account through the provider-specific flows after deployment.

The account screens are provider-agnostic. Names, descriptions, icons, privacy copy, and connect/reconnect labels all
come from the backend provider registry. Authentication types are opaque to clients, and every provider starts through
the same authorization route. Adding or changing a reviewed provider therefore requires a backend registry entry and
server adapter, not Expo or Apple UI changes. Provider endpoints, scopes, secrets, and token exchange remain
server-only; this abstraction does not restore arbitrary customer-supplied credentials.

## Active provider contract

| Provider | Public access | Optional private access | Runtime boundary |
| --- | --- | --- | --- |
| GitHub | None | GitHub App installation on selected repositories | The runtime signs a short GitHub App JWT, then mints a one-hour installation token narrowed again to the saved repository IDs and granted permissions. No personal access token is stored. |
| Gmail | None | Google OAuth with Gmail read-only and compose scopes | A fixed adapter uses Google's generally available Gmail REST API for `search_threads`, `get_thread`, `get_message`, `list_labels`, `list_drafts`, `get_draft`, and `create_draft`. Send, delete, archive, relabel, spam, and trash tools are unavailable. |
| YouTube | Search, video details, and comments | Google OAuth with `youtube.readonly` | Private tools can read the connected channel and its uploads. Both public and private calls remain subject to the app project's YouTube quota controls. |
| Google Workspace | None | Google OAuth for Drive, Docs, and Calendar | Three isolated Google MCP clients expose reviewed read-only tools. One OAuth refresh grant is shared server-side; no file or event mutation tools are admitted. |
| Slack | None | Per-user Slack OAuth v2 | A rotating user token can run Real-time Search and read a selected thread. No message, reaction, canvas, or file write scopes are requested. |
| Microsoft 365 | None | Deferred; the adapter remains available for later configuration | When configured, Microsoft Graph tools read recent Outlook mail, calendar events, and search OneDrive/SharePoint content. Send and read-write permissions are rejected. Unconfigured providers are omitted from the app. |
| Notion | None | Notion public-connection OAuth | Users choose the workspace pages to share. Runtime tools can search and read pages and blocks, with insert, update, and delete capabilities disabled. |
| X | Public research | OAuth 2.0 Authorization Code with PKCE | Private tools can read the connected profile, authored posts, and mentions. Only `tweet.read`, `users.read`, and `offline.access` are requested. |

Gmail deliberately does not use Google's Developer Preview MCP server: that preview currently rejects consumer
`@gmail.com` accounts. `.github/workflows/provider-contracts.yml` checks the generally available Gmail REST discovery
contract each day. Run the same check locally with:

```bash
python scripts/check-gmail-api-contract.py
```

## Provider app setup

Create these Secrets Manager values outside the repository. Use secret names beginning with the documented paths so
the runtime's IAM and confused-deputy checks agree with the backend configuration.

### Shared Google OAuth client

Use a Google Web application OAuth client in the project that owns the Gmail and YouTube API quota. Enable Gmail API,
YouTube Data API v3, Drive API, Docs API, Calendar API, and the Drive, Docs, and Calendar MCP services. Register this
exact redirect URI:

```text
https://API_HOST/public/oauth/google/callback
```

Store the downloaded web-client JSON in a secret named `frogbot/oauth/google-production`, then set
`FROGBOT_GOOGLE_OAUTH_SECRET_ARN` to its full ARN. Gmail requests `gmail.readonly` plus `gmail.compose`; YouTube
requests only `youtube.readonly`. Google Workspace requests `drive.readonly`, `documents.readonly`,
`calendar.calendarlist.readonly`, `calendar.events.freebusy`, and `calendar.events.readonly`. User authentication does
not move YouTube calls outside the Google project's quota.

### FroggyBot GitHub App

Create a GitHub App and set both its callback URL and post-installation setup URL to:

```text
https://API_HOST/public/oauth/github/callback
```

Leave **Request user authorization (OAuth) during installation** off. FroggyBot receives the installation ID at the
setup URL, then starts a separate PKCE-protected GitHub authorization to verify that the installation belongs to the
connecting user.

No webhook is required. Configure repository permissions for Contents (read and write), Issues (read and write), Pull
requests (read and write), and Metadata (read). The installer chooses repositories. Store the configuration in a
secret named `frogbot/oauth/github-production`:

```json
{
  "appId": "123456",
  "clientId": "Iv1.example",
  "clientSecret": "replace-with-github-client-secret",
  "privateKey": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----",
  "slug": "froggybot"
}
```

Set `FROGBOT_GITHUB_APP_SECRET_ARN` to the full secret ARN. The setup and authorization callbacks briefly use a
GitHub user OAuth token to verify that the signed-in user can see the returned installation ID, immediately revoke
that token, and persist only the installation ID, selected repository IDs, and granted permission levels.

### X OAuth client

Create a confidential X OAuth 2.0 client with Authorization Code + PKCE and this callback URL:

```text
https://API_HOST/public/oauth/x/callback
```

Store the client in a secret named `frogbot/oauth/x-production`:

```json
{
  "clientId": "replace-with-x-client-id",
  "clientSecret": "replace-with-x-client-secret"
}
```

Set `FROGBOT_X_OAUTH_SECRET_ARN` to the full secret ARN. FroggyBot stores rotating user refresh tokens server-side and
writes the replacement back to the same per-user secret before using it.

### Slack OAuth app

Create a Slack app with OAuth v2 and this redirect URL. Internal testing may begin in the owner workspace, but a
general FroggyBot release requires Slack's distribution review and installation flow for other workspaces:

```text
https://API_HOST/public/oauth/provider/callback
```

Enable token rotation before installing the app. Request these user-token scopes only:
`search:read.public`, `search:read.private`, `search:read.mpim`, `search:read.im`, `search:read.files`,
`search:read.users`, `channels:history`, `groups:history`, `im:history`, and `mpim:history`. Do not add bot scopes or
events. Store `clientId` and `clientSecret` in `frogbot/oauth/slack-production`, then set
`FROGBOT_SLACK_OAUTH_SECRET_ARN`. Slack access tokens expire after 12 hours when rotation is enabled; every successful
refresh replaces both the access and one-use refresh token in the per-user secret.

### Microsoft 365 OAuth app (deferred)

Register a Microsoft identity-platform web app that accepts organizational directories and personal Microsoft
accounts when Microsoft 365 is enabled later. Add the shared callback URL above. Configure delegated permissions only: `User.Read`, `Mail.Read`,
`Calendars.Read`, `Files.Read.All`, and `Sites.Read.All`; the flow also requests the OpenID scopes `openid`, `profile`,
`email`, and `offline_access`. Some organization policies can still require administrator approval. Store `clientId`
and `clientSecret` in `frogbot/oauth/microsoft-production`, then set `FROGBOT_MICROSOFT_OAUTH_SECRET_ARN`.

### Notion public connection

Create a public Notion connection with the shared callback URL above. Enable read-content capability only, leave insert
and update content disabled, and let each installer choose the pages available to FroggyBot. Store `clientId` and
`clientSecret` in `frogbot/oauth/notion-production`, then set `FROGBOT_NOTION_OAUTH_SECRET_ARN`.

## Deployment boundary

The Amplify deployment requires the Google, GitHub, X, Slack, and Notion provider secret ARN variables above.
Microsoft 365 is optional and is hidden from the app when its secret ARN is absent. The AgentCore runtime role can read those
provider configuration paths and each user's connection secret; it can write only the per-user connection path, which
is needed for rotating X, Slack, and future Microsoft refresh grants. Never deploy with AWS account-root credentials. The
release preflight rejects root sessions.

## Deferred Meta and LinkedIn connectors

Meta and LinkedIn both offer OAuth-based developer platforms, but neither connector is shipped or advertised in
this release. Meta access must be designed per product (for example Facebook Pages or Instagram), with the exact
permissions, business verification, App Review, data-deletion callback, webhook validation, and least-privilege
tool set completed before a registry entry is enabled. LinkedIn likewise requires an approved LinkedIn product and
only the scopes granted to that application; basic sign-in access must not be presented as general profile, company,
posting, or analytics access. Until those reviews and end-to-end revocation tests exist, both providers remain absent
from the provider registry and clients.

The active provider additions share the provider registry and common client flow. Add future providers through the
same catalog contract: delegated read-only access first, provider-side revocation where available, exact scope checks,
and runtime tool allowlists. Add write scopes only alongside an explicit approval surface and before/after previews.

Official references: [GitHub App installation authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app),
[Gmail API](https://developers.google.com/workspace/gmail/api/reference/rest),
[YouTube authentication](https://developers.google.com/youtube/v3/guides/authentication),
[X OAuth 2.0](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code),
[Google Workspace MCP](https://developers.google.com/workspace/guides/configure-mcp-servers),
[Slack OAuth](https://api.slack.com/authentication/oauth-v2), and
[Microsoft Graph authentication](https://learn.microsoft.com/en-us/graph/auth/auth-concepts).
