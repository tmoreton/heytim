# Expo to SwiftUI design parity

This document records the native visual contract derived from the Expo implementation. The Expo source remains the
design authority and is not modified by the Apple client.

## Visual principles

- Warm, calm, light-only product surfaces; the interface must not inherit a system dark palette.
- FroggyBot green is reserved for identity, selection, progress, links, and primary actions.
- Cards and controls are soft rectangles with restrained borders instead of platform-default chrome.
- Bot identity always uses the frog silhouette. People use initial circles; groups stack two participant tiles.
- Content stays compact and readable: 290-point desktop drawer, 780-point conversation width, and 680–720-point editors.
- macOS keeps native windows and menus, while iPhone keeps native navigation, sheets, file picking, and dictation.

## Color tokens

| Role | Value | Use |
| --- | --- | --- |
| Brand | `#007A3D` | Logo, primary buttons, links, progress |
| Brand dark | `#006633` | Active labels and high-contrast green text |
| Sign-in canvas | `#F4F2EC` | Authentication background |
| App canvas | `#FBFBF9` | Conversation and composer background |
| Editor canvas | `#F8F7F3` | Libraries, settings, and editors |
| Drawer | `#F2F1ED` | Desktop/sidebar navigation |
| Surface | `#FFFFFF` | Cards, fields, composer, circular actions |
| Primary text | `#171714` | Headings and body copy |
| Muted text | `#6E6A62` | Secondary information and metadata |
| Warm muted text | `#77736B` | Explanatory copy and previews |
| Border | `#DEDAD0` | Controls and cards |
| Selection | `#E4F1EA` | Selected conversation and installed states |
| Assistant message | `#EFEFEC` | Normal assistant responses |
| Team answer | `#E9F4EE` | Synthesized group response |
| Approval | `#FFF7DF` | Human approval checkpoint |
| Destructive | `#A53A32` | Errors and destructive actions |

## Type and geometry

| Surface | Contract |
| --- | --- |
| Brand name | 34 pt heavy, -1.3 tracking |
| Sign-in card | 420 pt max width, 26 pt radius, 24 pt inset |
| Sign-in input/button | 56 pt height, 16 pt radius |
| Drawer | 290 pt ideal width; 70 pt header; 44 pt search; 64 pt rows |
| Conversation header | 58 pt minimum height |
| Messages | 780 pt max content width; 15/21 typography; 18 pt bubble radius |
| Composer | 780 pt max width; 51 pt minimum height; 20 pt radius |
| Reply target | 44 pt minimum height; capsule geometry |
| Editor content | 680–720 pt max width; 14–20 pt card radii |

## Component mapping

| Expo element | SwiftUI implementation | Apple adaptation |
| --- | --- | --- |
| `frogbot-foreground.png` | `FrogMark` and `BotAvatar` | Shared asset catalog image; bot colors use template tint plus face details |
| `PersonAvatar` | `PersonAvatar` | Deterministic five-color initial circle |
| `GroupAvatar` | `GroupAvatar` | Two overlapping bot/person tiles |
| Conversation drawer | `ConversationSidebar` | Custom scroll surface inside `NavigationSplitView` |
| Hamburger / more actions | Custom line mark + `Menu` | SF Symbols inside native menus where semantics matter |
| Message bubbles | `MessageBubble` | `UnevenRoundedRectangle` preserves Expo's speech-corner shapes |
| Reply chips | Composer reply picker | Same active/inactive fills, borders, avatars, and 44 pt targets |
| Attachment / dictation / send | Composer action row | `paperclip`, `mic`, `arrow.up`, and `stop.fill` SF Symbols |
| Page sheets | `FeatureSheet` | Native sheets/navigation with Expo canvas, tint, and light palette |

## Screen audit

### Authentication

- Match the cream background, centered frog mark, brand title/tagline, white card, green eyebrow, labeled field, full-width
  primary action, assurance divider, invitation link, and responsible-use footnote.
- Verification-code and invitation states use the same card rather than a separate system form.

### Conversation shell

- Match the logo lockup, create action, search field, uppercase group/bot sections, selected-row treatment, status badge,
  and account footer.
- The detail header uses the selected bot/group avatar, green status line, drawer toggle, and action menu.
- Empty, loading, memory, error, and processing states use the same token set.

### Messages and composer

- User messages are solid brand green with white type and a tight trailing speech corner.
- Assistant messages are neutral; team synthesis is pale green; approval is pale yellow; failures are pale red.
- Group replies show bot/person identity and round role. Activity and timing remain secondary to the answer.
- Composer, attachments, reply routing, dictation, stop, and send controls preserve 44 pt touch targets on iPhone.

### Libraries, editors, and settings

- Bot/skill libraries, bot/group editors, schedules, memory, connections, documents, share, and account screens use the
  editor canvas rather than default grouped-form gray or dark surfaces.
- Native toggles, pickers, navigation, share sheets, confirmation dialogs, secure browser views, and file importers remain
  native because they improve accessibility and platform behavior without changing FroggyBot's visual identity.

## Verification gates

- Build the single target for macOS and iPhone simulator.
- Run Swift unit tests and the iPhone launch/send UI test in offline demo mode.
- Inspect authentication and a populated conversation at desktop size.
- Inspect the collapsed conversation experience on an iPhone simulator.
- Confirm the Expo tree has no working-copy changes.
