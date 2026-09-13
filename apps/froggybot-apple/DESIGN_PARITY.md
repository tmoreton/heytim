# Native Apple design direction

The Expo app is FroggyBot's feature and behavior reference, not a component or pixel-level blueprint. The Apple client
keeps the same account, conversations, capabilities, terminology, and brand identity while choosing the most natural
SwiftUI interaction for iPhone and Mac. The Expo source remains unchanged.

## Native-first principles

- Prefer Apple containers and controls: `NavigationSplitView`, `List`, `Form`, `NavigationStack`, `Inspector`,
  `Menu`, `Picker`, `TextField`, `ProgressView`, toolbars, sheets, alerts, and confirmation dialogs.
- Use semantic system colors and materials so light mode, dark mode, increased contrast, window vibrancy, and Liquid
  Glass adapt automatically.
- Use semantic text styles and system control sizing so Dynamic Type, keyboard navigation, VoiceOver, pointer input,
  and Mac menu commands work without parallel custom implementations.
- Preserve FroggyBot identity through the frog mark, bot and group avatars, green tint, friendly language, and custom
  message bubbles. Product identity belongs in content; platform chrome belongs to Apple.
- Keep custom Liquid Glass restrained to an important floating action such as Send. Standard navigation and toolbar
  controls receive the system appearance automatically on current OS releases.
- Share one SwiftUI feature implementation between iPhone and Mac, with platform-specific presentation only where the
  system interaction genuinely differs.

## Conversation design

The transcript remains a `ScrollView` and `LazyVStack` because SwiftUI has no public chat-bubble component and `List`
would weaken bottom anchoring and message layout. The surrounding interactions are native:

| Need | Native Apple solution |
| --- | --- |
| Conversation navigation | `NavigationSplitView`, sidebar `List`, search, toolbars |
| Conversation details | Adaptive `Inspector`—trailing pane on Mac, sheet on iPhone |
| Writing | Vertically growing `TextField`, focus state, native submit behavior |
| Reply routing | Menu-style `Picker` with normalized group/bot selection |
| Attachments | `PhotosPicker`, `fileImporter`, Finder drag and drop |
| Documents | Local authenticated download followed by Quick Look |
| Message actions | Text selection, context menus, `ShareLink`, save/export actions |
| Tool approval | `GroupBox` plus a system `confirmationDialog` |
| Bot activity | `ProgressView` and `DisclosureGroup` |
| Long conversations | Native scroll-position tracking and “Jump to Latest” |
| Cancellation | Independent Stop and Send controls |

Photos are transferred as temporary files, stripped of original metadata, downsampled, and converted to JPEG using
ImageIO before upload. Attachment count, byte, and image-dimension limits come from the backend bootstrap contract.
Drafts and pending attachments stay with the conversation where they were created.

## Platform adaptation

- iPhone uses compact navigation, adaptive sheets, PhotosPicker, share sheets, touch-sized controls, and interactive
  keyboard dismissal.
- Mac uses the system sidebar, resizable split panes and inspector, native menus and keyboard commands, Finder drops,
  contextual actions, and normal window materials.
- The same models, API client, state, message rendering, and feature views compile for both platforms.
- SwiftUI does not have a supported web target. The Expo web app remains the browser client and shares the backend API
  rather than the SwiftUI view tree.

## Brand guidance

- FroggyBot green is the app tint and identifies primary actions, selection, progress, and bot identity.
- User messages may remain green; assistant, team, approval, and error messages use semantic adaptive surfaces.
- Frog, bot, person, and group avatars are product assets rather than substitutes for system navigation controls.
- Avoid fixed light-only canvases, custom imitations of sidebars or sheets, and hard-coded text colors.

## Verification gates

- Build the single target for the iOS 17 and macOS 14 minimums and current Apple OS releases.
- Run Swift unit tests and iPhone UI journeys in offline demo mode.
- Exercise sign-in, conversation send/reply, group routing, tool approval, files/photos, Quick Look documents, settings,
  light/dark appearance, and the adaptive inspector.
- Inspect a live Mac window for native layout and keyboard/pointer behavior.
- Confirm the Expo tree has no working-copy changes.
