# HeyTim design audit — 30 September 2026

## Scope and evidence

This review compares the two supplied desktop screenshots (ChatGPT and OpenGhost) with the shared iPhone/Mac SwiftUI app and marketing website. The references show design patterns, not HeyTim screens. Findings about HeyTim come from `apps/iOS/Sources/HeyTimUI`, `apps/iOS/DESIGN_PARITY.md`, and `apps/website/src`. The neutral design changes are committed on the isolated `codex/heytim-design-followup-20261001` branch and are distinguished from the tagged Apple release below. Both Apple destinations built, and the shared Apple verification passed for the native design changes. The website build, four tests, and visual checks of the home and directory in both light and dark appearances passed. Home, library, skills, support, and privacy also fit 375- and 240-pixel dark viewports without horizontal scrolling. The revised generic mark was visually checked in the dark website header; its light colors are specified in the SVG but still need a rendered check. Rendered iPhone/Mac contrast, VoiceOver, Increase Contrast, and actual 200% browser zoom also remain to check.

## What to take from the references

| Reference | Useful element | HeyTim decision |
| --- | --- | --- |
| ChatGPT | Opaque charcoal reading canvas, a lighter solid sidebar, neutral selected row, narrow transcript, and a distinct bottom composer | Keep separate opaque canvas/sidebar/composer layers and a bounded reading measure. The user-message blue in that screenshot is outside HeyTim's color rule. |
| ChatGPT | Optional compact Outputs/Subagents/Sources panel | Consider a collapsible activity/files pane on wide Mac windows, after the core conversation is settled. Keep full editing and permissions in their existing full-size views. |
| OpenGhost | Compact folder/chat navigation, inset main pane, quiet selected row, and a contextual text-selection action | Keep the inset Mac canvas and compact sidebar. A text-selection action may be useful later if it is keyboard and VoiceOver accessible. |
| OpenGhost | Blurred content and a gold chart | The blur appears to obscure screenshot content, so it provides no evidence about body-text readability. Do not copy the gold treatment as an app-wide accent. |

## Design contract

| Element | Light appearance | Dark appearance | Color ownership |
| --- | --- | --- | --- |
| Reading canvas | White | Charcoal | Neutral |
| Sidebar and cards | Soft gray, opaque | Gray above canvas, opaque | Neutral |
| Primary action | Near-black fill, white label | Near-white fill, dark label | Neutral |
| Navigation, links, selection, status | Dark/gray text and shape | White/gray text and shape | Neutral |
| Bot icon/avatar | Configured bot color | Configured bot color | Bot identity |
| Composer | Neutral body, subtle bot tint and readable bot-colored edge | Same adaptive treatment | Selected bot identity |
| Bot reply | Low-opacity bot tint; neutral body text | Low-opacity bot tint; neutral body text | Speaking bot identity, including group replies |
| User, system, approval messages | Neutral surfaces | Neutral surfaces | No bot tint |

Chief yellow belongs to Chief's avatar, composer, and replies. Generic website header/footer marks and the favicon use an adaptive black/white version; bot artwork keeps each bot's color. Bot color should never carry the only meaning of a message, state, or action. Retain semantic red for destructive actions and actual errors, always with a label or icon. Third-party provider marks can keep their own recognizable artwork inside connector listings; their surrounding controls remain neutral.

## Prioritized findings

| Priority | Finding and evidence | Decision and status |
| --- | --- | --- |
| **P0** | The former bot-colored inline link/accent text can fall below the [4.5:1 normal-text target](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) on a dark tinted reply. Calculated examples using the current 18% dark bubble blend: blue about **4.22:1**, lavender **4.26:1**, rose **4.13:1**. | Keep bot color in avatar, bubble fill/border, and composer; use neutral foreground text and links inside replies. This is changed in the isolated native worktree, **not** in the tagged Apple release. Verify rendered results across every catalog color and both appearances. |
| **P0** | The former sign-in placeholder used primary text at 45% opacity, making a small but necessary example hard to see. | The isolated native patch uses the higher-contrast status text token. Verify the actual field in light and dark mode, including larger text sizes. |
| **P0** | The website on the tagged release remains light-only with blue primary actions and yellow promotional surfaces. | The committed, unshipped website branch replaces these with neutral light/dark tokens, black/white actions, and bot color only in bot art and demo replies. Its build, four tests, and light/dark visual checks of home and directory passed. |
| **P1** | The explicit selected-color token is subtle against the drawer (about **1.13:1** light, **1.39:1** dark), but it is **not used** by the sidebar row. The Mac sidebar uses native `List(selection:)` with tagged plain buttons; the row also gains semibold text and an accessibility selected trait. Code inspection cannot establish the actual system highlight or keyboard-focus appearance. | Inspect selected and keyboard-focused rows in a running Mac build before changing the row. Keep native selection if it is clear; if it is not, add a neutral shape/leading marker in addition to text weight. A standalone state indicator should meet [3:1 non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html). |
| **P1** | The tagged release's composer `TextField` tracks focus, but its shared surface always draws the same one-point bot-colored border. Thin tinted bubble borders may also be low contrast after opacity is applied. | The isolated branch now draws a two-point neutral outer ring with a gap while the composer is focused, preserving the resting bot-colored edge. Treat bubble borders as decoration. Verify on Mac with keyboard navigation and Increase Contrast before shipping. |
| **P1** | Busy transcripts and tool activity can compete with the answer, especially on a wide Mac display. | Preserve the 720-point Mac message width and expandable activity. Add a side utility pane only for persistent files, sources, or activity that users need while reading, with a collapse control and a compact-window fallback. |
| **P1** | The homepage gives Gmail, Google Workspace, Slack, Notion, and YouTube prominent connection tiles even though their production OAuth connections are currently disabled pending provider review. The small beta note does not make each tile's status clear. | Before publishing the website redesign, show enabled connections as usable and place unapproved providers in a clearly labeled future-availability section, or omit their tiles. Keep the app's disabled connection cards hidden until approval. |
| **P1** | The neutral website patch changes many high-visibility components at once: header, buttons, demo, catalog, and legal pages. | The build and four tests passed, and home/directory were visually checked in light and dark appearances. Narrow dark viewport reflow passed at 375 and 240 pixels; finish actual 200% zoom, hover/focus, reduced motion, and touch-target checks. Static token checks pass for ordinary website muted copy (about **6.91:1** on the light paper) and both primary button pairings (above **16:1**). |
| **P2** | OpenGhost suggests contextual actions on selected answer text. | Prototype only after the reading and navigation work is verified. Provide a normal menu/keyboard path and avoid floating controls that cover selected text. |

## Current implementation state

- **Tagged release candidate:** Native startup, sidebar, inset Mac reading canvas, sign-in card, general buttons, send controls, user/system/approval surfaces, and bot avatar/composer/reply fills already use the neutral shell and bot-color separation. Mac rows are compact; the transcript has a bounded width. See `Theme.swift`, `ButtonStyles.swift`, `MainView.swift`, and `ConversationMessageView.swift`.
- **Isolated, committed follow-up:** Native message text/activity accents and sign-in placeholder are corrected; the composer gets a neutral focus ring. Both iOS and macOS built, and `./scripts/apple-app.sh verify` passed for these native design edits. Website color tokens, component styles, dark appearance, and neutral generic marks are updated; its build, four tests, and light/dark home and directory visual checks passed. These edits are outside the live release worktree and have not been shipped.
- **Still to verify:** Native contrast with real text antialiasing and every bot tint; actual selected/focused sidebar rows and composer on Mac; iPhone at large Dynamic Type; VoiceOver names/order; website light appearance at 240 pixels, the light header mark, and actual 200% zoom. Repeat the required two-destination Apple build and shared verification after any further native edits.

The previous [Apple-specific audit](apple-app-ui-ux-audit-2026-09-29.md) records the first neutral-shell pass. This document adds the cross-platform comparison and the remaining contrast/focus decisions.
