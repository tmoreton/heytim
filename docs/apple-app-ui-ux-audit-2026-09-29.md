# HeyTim Apple app UI and UX audit — 29 September 2026

## Scope and evidence

This audit covers the shared SwiftUI iPhone and Mac app in `apps/iOS`. The supplied ChatGPT and OpenGhost screenshots are visual references; neither shows HeyTim. Findings about HeyTim come from its views, theme, and navigation code. The marketing website is a separate surface with its own in-progress design work.

## What to borrow from the references

| Reference | Useful pattern | HeyTim application |
| --- | --- | --- |
| ChatGPT | Visually solid sidebar, quiet selected row, narrow reading column, raised composer, restrained toolbar | Give the sidebar its own opaque neutral layer; preserve the bounded transcript; make the composer the main action area. |
| OpenGhost | Small inset around the main content, generous spacing, compact navigation rows, Settings at the bottom | Use a subtle rounded Mac canvas, one-line Mac chat rows, and bottom-anchored Settings. |
| Both | Strong text hierarchy and very little decorative color | Use neutral controls and surfaces in both appearances; reserve hue for the bot being represented. |

The blur in the OpenGhost screenshot appears to obscure content. It is not a readability pattern to reproduce. The ChatGPT screenshot has a long, truncated history list; HeyTim should preserve search and avoid growing a similarly noisy sidebar.

## Findings and decisions

| Priority | Finding | Decision |
| --- | --- | --- |
| P0 | A yellow global accent colored buttons, form controls, status treatments, approval surfaces, and even invalid color fallbacks. | Use near-black controls in light mode and near-white controls in dark mode. Keep Chief yellow only as Chief's bot color. Keep red for destructive actions and errors. |
| P0 | The conversation had a fixed blue accent while its composer used the selected bot color. User bubbles inherited bot color and Chief's white send glyph had low contrast. | Resolve color from the selected or speaking bot; use it for bot avatars, soft bot reply surfaces, and composer edge/fill. Keep Send neutral and user bubbles neutral; adjust small bot-colored text for contrast. |
| P0 | A white selection check was difficult to see on bright bot color swatches such as yellow and teal. | Choose a black or white check from the swatch's luminance. |
| P0 | Mac captions and supporting labels were unusually small. | Raise the Mac text scale and keep semantic text styles so the app's text-size preference and Dynamic Type continue to work. |
| P1 | The sidebar had two-line rows, 42 pt avatars, dates, and a colored Working pill. | Use compact one-line Mac rows and a small neutral Working indicator. Retain richer rows on iPhone, where the full-width list can support them. |
| P1 | The Mac sidebar blended into the window; startup used decorative colored glows. | Add opaque neutral surfaces, a subtly inset reading pane, and a calm sign-in card on a solid background. |
| P2 | Details replaces the chat on Mac, even though the ChatGPT example keeps compact context beside the conversation. | Keep full-width editing and destructive actions in Details. A future compact activity/files pane could sit beside the chat without moving those complex flows into a narrow rail. |

## Visual rules

- **Light:** white reading canvas, soft gray sidebar and composer, dark text and primary controls.
- **Dark:** charcoal reading canvas, slightly lighter sidebar and composer, near-white text and primary controls.
- **Bot color:** exact color on a sufficiently large bot icon; low-opacity color on the composer and bot reply background; adjusted shade for small text and thin outlines. Send and group-wide actions remain neutral.
- **People and general UI:** neutral avatars, navigation, settings, status, links, approval cards, and user messages. Errors and destructive actions retain semantic red; warning states and multi-series charts may use color when the icon or label also explains it.
- **Hierarchy:** one primary action per local task, 720–820 pt reading measure on Mac, clear section labels, and fewer competing pills and badges.

The base colors are design tokens, not pixels sampled from either screenshot. Text and controls must remain legible in light and dark appearances, with larger text sizes, Increase Contrast, and Reduce Transparency enabled. Apple's [Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode), [Color](https://developer.apple.com/design/human-interface-guidelines/color), and [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) guidance supports adaptive semantic colors and appearance testing. WCAG's [non-text contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html) sets a 3:1 target for meaningful control boundaries; small colored text should reach 4.5:1 against its background.

Chief yellow (`#FFBC3B`) is only about 1.68:1 against white, and a white glyph on that yellow is also about 1.68:1. Its exact hue works as a large icon or faint surface tint, while small labels and composer outlines need the darker light-mode shade calculated by the theme. Neutral Send avoids a yellow button altogether.

## Implementation and verification

The shared theme, app accent asset, sign-in, sidebar, transcript, composer, Markdown quote rail, and generic button tints were updated as part of this pass. The theme derives a readable bot shade for small copy and face details in bot avatars. The website was left outside this Apple app audit.

Verification gate: run `./scripts/apple-app.sh build` and `./scripts/apple-app.sh verify` for both Apple destinations, then inspect sign-in, an empty chat, Chief yellow, a cool-colored bot, and a shared group in both appearances. Check the Mac sidebar and canvas during window resize, and the iPhone composer at larger text sizes.
