# Provider integrations

FroggyBot has two integration layers:

- Public research remains available through the web tools. X and YouTube search require their own connected accounts.
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
| YouTube | None | Google OAuth with `youtube.readonly` | Search and channel tools require an assigned YouTube account. Calls remain subject to the app project's YouTube quota controls. |
| Google Workspace | None | Google OAuth for Drive, Docs, Sheets, and Calendar | Up to four isolated Google MCP clients expose reviewed read-only tools. Bots can be limited to selected file, spreadsheet, and calendar IDs. |
| Slack | None | Per-user Slack OAuth v2 | A rotating user token can search and read threads. Optional channel IDs restrict returned search results and thread reads. |
| Microsoft 365 | None | Microsoft identity-platform OAuth | Microsoft Graph tools read Outlook mail and calendar events, and search OneDrive/SharePoint content. |
| Microsoft Teams | None | Microsoft identity-platform OAuth | A separate Teams connection reads joined teams, channels, and channel messages. Bots can be limited to selected team/channel pairs. |
| Notion | None | Notion public-connection OAuth | Users choose shared workspace pages at install time. Connections by different users in the same workspace stay separate. Bots can be further limited to selected page IDs and their descendant blocks. |
| HubSpot | None | HubSpot OAuth | Bots can search contacts, companies, and deals within individually assigned CRM accounts. |
| Jira | None | Atlassian OAuth with a single selected site | Bots can list projects and read issues. Optional project keys restrict each bot further. |
| Zoom | None | Zoom user-managed OAuth | Bots can list and read meetings from individually assigned Zoom accounts. Host start URLs are never returned. |
| X | None | OAuth 2.0 Authorization Code with PKCE | Search, profile, authored posts, and mentions require an assigned X account. |

Connections are stored separately even when they use the same provider. A bot receives only the connection IDs selected
in its editor. Provider actions have distinct internal names and account labels for each connection.
Leaving a resource field blank means all resources the selected account can read; entering IDs narrows that bot's tools.
GitHub repositories have a picker. Jira project keys, Teams team/channel pairs, Slack channel IDs, Notion page IDs,
and Google `file:ID`, `sheet:ID`, or `calendar:ID` entries currently use text fields.

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
YouTube Data API v3, Drive API, Docs API, Sheets API, Calendar API, and the Drive, Docs, Sheets, and Calendar MCP services. Register this
exact redirect URI:

```text
https://API_HOST/public/oauth/google/callback
```

Store the downloaded web-client JSON in a secret named `frogbot/oauth/google-production`, then set
`FROGBOT_GOOGLE_OAUTH_SECRET_ARN` to its full ARN. Gmail requests `gmail.readonly` plus `gmail.compose`; YouTube
requests only `youtube.readonly`. Google Workspace requests `drive.readonly`, `documents.readonly`,
`calendar.calendarlist.readonly`, `calendar.events.freebusy`, and `calendar.events.readonly`. User authentication does
not move YouTube calls outside the Google project's quota.
The Workspace MCP services are in Google's Developer Preview and require access to that program before live use.

### FroggyBot GitHub App

Create a GitHub App and set both its callback URL and post-installation setup URL to:

```text
https://API_HOST/public/oauth/github/callback
```

Leave **Request user authorization (OAuth) during installation** off. FroggyBot receives the installation ID at the
setup URL, then starts a separate PKCE-protected GitHub authorization to verify that the installation belongs to the
connecting user.

Configure the webhook URL `https://API_HOST/public/webhooks/github` and subscribe to the Issues event. Set a random secret of at least 32 characters in the App and as `webhookSecret` in the JSON below. Configure repository permissions for Contents (read and write), Issues (read and write), Pull
requests (read and write), and Metadata (read). The installer chooses repositories. Store the configuration in a
secret named `frogbot/oauth/github-production`:

```json
{
  "appId": "123456",
  "clientId": "Iv1.example",
  "clientSecret": "replace-with-github-client-secret",
  "privateKey": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----",
  "slug": "froggybot",
  "webhookSecret": "replace-with-random-webhook-secret"
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

### Microsoft 365 and Teams OAuth app

Register a Microsoft identity-platform web app and add the shared callback URL above. Microsoft 365 requests delegated
`User.Read`, `Mail.Read`, `Calendars.Read`, `Files.Read.All`, and `Sites.Read.All`. Teams requests delegated
`User.Read`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`, and `ChannelMessage.Read.All` through a separate connection.
Both flows request `openid`, `profile`, `email`, and `offline_access`. Teams channel-message consent may require an
organization administrator. Store `clientId`
and `clientSecret` in `frogbot/oauth/microsoft-production`, then set `FROGBOT_MICROSOFT_OAUTH_SECRET_ARN`.

### Notion public connection

Create a public Notion connection with the shared callback URL above. Enable read-content capability only, leave insert
and update content disabled, and let each installer choose the pages available to FroggyBot. Store `clientId` and
`clientSecret` in `frogbot/oauth/notion-production`, then set `FROGBOT_NOTION_OAUTH_SECRET_ARN`.

### HubSpot OAuth app

Register a HubSpot OAuth app with the shared callback URL. Request only `crm.objects.contacts.read`,
`crm.objects.companies.read`, and `crm.objects.deals.read`. Store `clientId` and `clientSecret` in
`frogbot/oauth/hubspot-production`, then set `FROGBOT_HUBSPOT_OAUTH_SECRET_ARN`.

### Jira OAuth app

Register an Atlassian 3LO app with the shared callback URL and request `offline_access` and `read:jira-work`.
Use a site-restricted grant; the callback rejects grants that expose more than one Jira site. Store `clientId` and
`clientSecret` in `frogbot/oauth/jira-production`, then set `FROGBOT_JIRA_OAUTH_SECRET_ARN`.

### Zoom OAuth app

Register a user-managed Zoom OAuth app with the shared callback URL. Add granular scopes `user:read:user`,
`meeting:read:list_meetings`, and `meeting:read:meeting`. Store `clientId` and `clientSecret` in
`frogbot/oauth/zoom-production`, then set `FROGBOT_ZOOM_OAUTH_SECRET_ARN`.

## Deployment boundary

The Amplify deployment requires the Google, GitHub, X, Slack, and Notion provider secret ARN variables above.
Microsoft 365, Teams, HubSpot, Jira, and Zoom are optional and hidden when their secret ARN is absent. The AgentCore runtime role can read those
provider configuration paths and each user's connection secret; it can write only the per-user connection path, which
is needed for rotating refresh grants. Never deploy with AWS account-root credentials. The
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
[Slack OAuth](https://api.slack.com/authentication/oauth-v2),
[Microsoft Graph authentication](https://learn.microsoft.com/en-us/graph/auth/auth-concepts),
[HubSpot OAuth](https://developers.hubspot.com/docs/apps/legacy-apps/authentication/oauth-quickstart-guide),
[Atlassian 3LO](https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/), and
[Zoom OAuth](https://developers.zoom.us/docs/integrations/end-user-auth/).
