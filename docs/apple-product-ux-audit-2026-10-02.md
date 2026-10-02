# HeyTim iPhone and Mac product UX audit — 2 October 2026

## Fix status

The findings below describe the starting experience. The current change set adds share-scope disclosure and a toolbar action, chat-load retry, an account-to-bot handoff, clearer group reply labels, account-wide token and estimated provider-cost totals in Plan, OTP resend, an actionable first-run sidebar, searchable time zones, full scheduled-run details, and inline routine-load recovery. It also fixes the interactive browser address and return-control failures, adds the AWS DCV live viewer, and enables the browser tool by default for new and existing bots while preserving later opt-outs.

Source and simulator tests cover these flows. Live two-account sharing, a real AgentCore browser stream, OAuth assignment, and signed iPhone and Mac release behavior still require environment checks after deployment.

## Scope and confidence

The product direction is the hosted, shareable HeyTim service. This audit reviews the current shared SwiftUI client and the API behavior behind important UI claims. It does not propose a local runtime or a second distribution model. It builds on the 29 September visual design audit, whose neutral shell and bot-specific color rules are largely present in the current code.

The findings below are source-verified unless marked as a usability hypothesis. This pass did **not** include a physical iPhone or live account walkthrough. The local build covers iOS and macOS, and the UI tests exercise mostly offline journeys. They are useful regression coverage but do not prove production sign-in, sharing, OAuth, permissions, or accessibility in a signed release.

## What already works well

- One shared SwiftUI experience adapts with native split navigation, lists, sheets, toolbars, menus, Quick Look, and platform-specific composer controls.
- Opaque neutral shell colors and black/white controls follow the requested direction; bot color stays in avatars, message surfaces, and the composer. The theme adjusts bot-colored small text for contrast.
- The transcript has draft preservation, queued messages, stop, scroll-to-latest, activity, tool approvals, attachments, and group reply routing.
- Connected-account, schedule, run-history, and most file screens have explicit loading and retry states.

## Prioritized findings

| Priority | Experience | Evidence | Recommended fix and acceptance check |
| --- | --- | --- | --- |
| **P0** | **Sharing does not explain the data shared.** The direct chat screen says only “Share [name]” and “Anyone with this link can accept the invitation.” Creating that link actually snapshots the bot setup and up to 100 recent user/assistant text exchanges into the recipient's own copy. A group link instead invites the recipient into the live room. Both links last 30 days. This difference matters before the user creates a link. | `SupportingFeatureSheets.swift` `ShareView`, `AppModel.share`, backend `sharing.py::_create_share`, `groups.py::_create_group_invite` | Use distinct headings: “Share a copy of this bot and chat” and “Invite someone to this room.” Describe precisely what the recipient receives, the 30-day expiry, and where to revoke. Ideally let direct-chat users choose bot setup only versus setup plus chat. Test both flows with real recipient accounts. |
| **P1** | **A failed chat load can look like an empty conversation.** Selecting a chat starts `try? await loadMessages()`, discarding the error. The transcript shows “Start a conversation” when messages are empty and loading ends. A network failure can therefore be mistaken for lost history; there is no inline retry. | `AppModel.swift` `select` and `loadMessages`, `MainView.swift` `transcriptContent`/`emptyConversation` | Track loading, loaded-empty, and failed states separately. Show an inline “Couldn’t load chat” with Retry. Keep last known messages visible with a stale-state label when possible. Simulate a failed messages request on both platforms. |
| **P1** | **The signature sharing action is buried.** Chat toolbars show Details (and Browser for eligible bots); Share sits within a long Details form after files and schedules. On Mac, opening Details covers the conversation, which interrupts collaboration. | `MainView.swift` `ConversationView.toolbar`, `ConversationInspector.conversationActions`; Mac details UI tests | Put a Share/Invite action next to the conversation identity, especially for groups. Keep the full management form behind Details. On Mac, use a compact side inspector for lightweight context and preserve the chat when sharing. Validate at narrow and wide window widths. [Apple's sharing guidance](https://developer.apple.com/design/human-interface-guidelines/collaboration-and-sharing) also recommends a convenient toolbar Share action. |
| **P1** | **Connecting an account ends before it becomes useful.** OAuth success opens an “Account Connected” alert and tells the user to assign it to a bot, but offers only OK. Assignment is elsewhere in a bot's Tools editor. A successful connection may feel like a completed setup when it is not. | `SupportingFeatureSheets.swift` `ConnectionsView` success alert, `FeatureSheets.swift` bot tools editor and template details | Replace the dead-end alert with a next step: “Choose a bot to use this account,” then show the selected bot, account scope, and saved state. For templates that require an account, expose a setup checklist after Add Bot. Test newly connected and already connected accounts. |
| **P1** | **Hosted usage signals conflict.** Every completed bot message shows model/provider, reasoning, six-decimal USD cost, and cache percentage. Usage & Plan shows work credits but no aggregate tokens or provider cost. The USD value is model cost, not the amount billed to the user; the screen does not make that distinction. The prior request to remove the DeepSeek label is not reflected in this source. | `ConversationMessageView.swift` `ModelUsageCaption`, `SupportingFeatureSheets.swift` `billingSection` | For the hosted product, make remaining/used credits the primary customer metric. If provider cost remains visible, label it explicitly as estimated provider cost, not a charge, and put tokens/caching in a collapsed advanced view. Resolve whether the previously requested period total belongs in Plan; if so, define the period and account-wide scope before implementation. |
| **P1** | **Group reply routing names the absence of a bot, not the action.** “No Bot Reply” and “All Bots” are technically accurate but do not tell a new member whether a message posts to people, starts a team round, or uses credits. | `MainView.swift` `Composer.replyPicker`; `AppModel.activeGroupReplyBotId`; backend `group_messages.py::_send_group_message` | Label choices “Post to people only,” “Ask [bot],” and “Ask the whole team.” Add one short explanation near the selected route, including when a reply consumes a work credit. Verify the people-only path produces no AI response. |
| **P2** | **Recovery from first-run and sign-in friction is weak.** The sidebar's empty state has no Add Bot action (although a fresh account opens the library automatically). The verification-code screen has no visible Resend option; the fallback is “Use a different email address.” “Welcome back” is also shown before the app knows whether the email belongs to a returning user. | `MainView.swift` `ConversationSidebar`, `AppModel.load`; `AuthView.swift`; `AuthSession.swift` | Make empty states actionable. Offer a timed Resend code action, clear delivery guidance, and a neutral “Continue with email” heading. Test expired or undelivered OTPs and dismissal of first-run onboarding. |
| **P2** | **Schedules and run history leave details hard to reach.** Time zone choices are limited to current zone, four U.S. zones, UTC, and a previously saved zone. Run history truncates output after five lines without an obvious full-run destination. | `FeatureSheets.swift` `ScheduleEditor.timeZoneOptions`, `ScheduleRunsView` | Offer searchable IANA zones with friendly names and preserve the chosen identifier. Add a full run detail view with complete output, errors, activity, and files, or link directly to the associated chat run. Test a non-U.S. timezone and a long failed run. |
| **P2** | **One failure path mislabels an error as no data.** Event routines catch load errors in a global alert and then show “No event routines yet” if the arrays remain empty. | `SupportingFeatureSheets.swift` `GroupRoutinesView.load` and empty sections | Use the same inline error and retry pattern already present on Schedules and Connections. Test failure on first load and refresh failure with existing rows. |
| **P2 hypothesis** | **Settings and Details carry too many destinations at one level.** Settings spans team setup, memory, skills, connections, plan, display, device actions/Health, notifications, shared links, privacy, account, and about. Details has its own long utility list. This likely raises search cost on iPhone and removes chat context on Mac, but needs a live navigation/observational pass. | `SupportingFeatureSheets.swift` `AccountView`, `MainView.swift` `ConversationInspector` | Put high-frequency items beside the task they serve; group remaining settings into short pages with clear names. Measure whether new users can locate Invite, usage, connected-account assignment, and run history without prompting. |

## Platform-specific review

### iPhone

- Check the first-run path with the bot gallery dismissed, a small device, large Dynamic Type, keyboard open, and a group with several bots. The composer and group route picker must remain reachable.
- Verify the Share and Join flows with two real accounts, including permissions, previous room history, expired/revoked links, and return to the correct conversation.
- Check OTP autofill, resend, and a delayed code. Test attachment/photo permission, Quick Look, push permission and opening a notification, Health permissions, and approval dialogs. Compare the signed TestFlight build with this source: the earlier device screenshot showed an AI-processing prompt on Send, while that copy is absent from the current SwiftUI client.

### Mac

- Check the compact one-line sidebar with long or duplicate bot/group names, search, resize, keyboard navigation, and VoiceOver. It currently omits preview and date to stay compact; test whether that harms recognition before adding density.
- Keep the chat visible when users open Share, recent activity, or files. Verify window resizing, sidebar toggling, Cmd-K compose, Cmd-Return send, drag/drop attachments, Quick Look, browser handoff, and Sparkle update entry.
- Review the app at System/Light/Dark, larger text settings, Increase Contrast, Reduce Transparency, and reduced motion. [Apple's color guidance](https://developer.apple.com/design/human-interface-guidelines/color) calls for all appearance and contrast variants to remain legible.

## Recommended sequence

1. Fix the share disclosure and test the two actual recipient flows.
2. Fix failed chat loading and the connection-to-bot handoff.
3. Expose Invite/Share, clarify group routing and hosted usage language.
4. Address OTP recovery, schedule zones, full run details, and inline routine errors.
5. Run a visual and accessibility pass on both destinations, then two or three observed first-time-user tasks: share a room, connect a service and use it, and schedule a result.

The next verification pass should use `./scripts/apple-app.sh build` and `./scripts/apple-app.sh verify` for both destinations, plus signed-build checks for live authentication, sharing, notifications, and provider connection. Source and offline UI tests alone cannot establish those journeys.
