# Native Apple design direction

The Expo app is HeyTim's feature and behavior reference, not a component or pixel-level blueprint. The Apple client
keeps the same account, conversations, capabilities, terminology, and brand identity while choosing the most natural
SwiftUI interaction for iPhone and Mac. The Expo source is preserved as the browser client and migration reference;
its native release paths are deprecated.

## Native-first principles

- Prefer Apple containers and controls: `NavigationSplitView`, `List`, `Form`, `NavigationStack`, `Inspector`,
  `Menu`, `Picker`, `TextField`, `ProgressView`, toolbars, sheets, alerts, and confirmation dialogs.
- Use semantic system colors and opaque, adaptive surfaces for the app shell so light mode, dark mode, increased
  contrast, and window vibrancy remain readable. Reserve translucent material for a deliberate floating control.
- Use semantic text styles and system control sizing so Dynamic Type, keyboard navigation, VoiceOver, pointer input,
  and Mac menu commands work without parallel custom implementations.
- Preserve HeyTim identity through the frog mark, bot and group avatars, friendly language, and custom message
  bubbles. Product identity belongs in content; platform chrome belongs to Apple.
- Use a black primary control on light surfaces and a white primary control on dark surfaces. Standard navigation and
  toolbar controls receive the system appearance automatically on current OS releases.
- Share one SwiftUI feature implementation between iPhone and Mac, with platform-specific presentation only where the
  system interaction genuinely differs.

## App shell and color

- Give launch, sidebar, transcript, and inspector an opaque neutral base. Separate panes with small luminance steps and
  restrained borders, as in the supplied ChatGPT and OpenGhost references. Avoid blur behind essential text or controls.
- Keep navigation, selected rows, search, menus, settings, status, and ordinary action buttons neutral. Use clear
  type hierarchy, spacing, and selection shape to show importance; do not use yellow as a generic action color.
- Invert the neutral foreground and control fill with appearance: near-black on light backgrounds, near-white on dark
  backgrounds. Secondary text must remain readable at normal text sizes in both modes.
- A bot's configured color may identify its avatar or icon, the conversation composer, and its message surface. Use a
  restrained tint or border for larger areas, with neutral foreground text so the bot color never reduces legibility.
  In group conversations, each bot's own color identifies its messages and inline content. User, system, approval,
  status, and error content use semantic neutral or status colors instead of inheriting the active bot's tint.
- Keep the generic frog mark neutral. Chief's frog avatar retains Chief yellow as bot identity; neither mark
  makes yellow a button, focus, selection, quote, or navigation color.

## Conversation design

The transcript remains a `ScrollView` and `LazyVStack` because SwiftUI has no public chat-bubble component and `List`
would weaken bottom anchoring and message layout. The surrounding interactions are native:

| Need | Native Apple solution |
| --- | --- |
| Conversation navigation | `NavigationSplitView`, sidebar `List`, search, toolbars |
| Conversation details | Full detail page on Mac, sheet on iPhone; narrow inspector only for compact context |
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
- Mac uses the system sidebar, a resizable split, a browser inspector, native menus and keyboard commands, Finder drops,
  contextual actions, and normal window materials.
- The same models, API client, state, message rendering, and feature views compile for both platforms.
- SwiftUI does not have a supported web target. The Expo web app remains the browser client and shares the backend API
  rather than the SwiftUI view tree.

## Brand guidance

- The selected bot's color identifies that bot in the conversation. The app shell and primary controls stay neutral.
- User, team, approval, and error messages use semantic adaptive surfaces; colored bot message backgrounds remain
  subtle enough for neutral foreground text to pass contrast checks.
- Frog, bot, person, and group avatars are product assets rather than substitutes for system navigation controls.
- Avoid fixed light-only canvases, custom imitations of sidebars or sheets, hard-coded text colors, and yellow controls.

## Verification gates

- Run `./scripts/apple-app.sh build` and `./scripts/apple-app.sh verify` for both iOS and macOS destinations.
- Run Swift unit tests and iPhone UI journeys in offline demo mode.
- Exercise sign-in, conversation send/reply, group routing, tool approval, files/photos, Quick Look documents, settings,
  light/dark appearance, and the adaptive inspector.
- Inspect a live Mac window for native layout and keyboard/pointer behavior.
- Review the separate website working copy independently of Apple app design changes.
