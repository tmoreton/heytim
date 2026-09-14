# Native Apple end-to-end review

Date: 2026-09-13

## iPhone

- Built the current SwiftUI source for an iPhone 16 Pro simulator.
- Native XCTest UI result: 16 passed, 0 failed, 0 skipped.
- Computer-use review passed message composition, send-button state, send/reply rendering, Settings, Tools & Skills, and Connected Accounts.
- Result bundle: `iOSNativeUI.xcresult`.

## macOS

- Built the current SwiftUI source under a temporary review-only bundle identifier so the installed app was not replaced.
- Computer-use review passed sign-in validation, message composition and reply rendering, Settings, Tools & Skills, built-in tools, Connected Accounts, the conversation inspector, scheduled tasks, schedule creation, custom-bot validation and prompt editing, Save/dismiss behavior, and the attachment menu.
- The macOS XCTest UI runner could not initialize because macOS timed out while enabling automation mode. This is a host authorization limitation; no Mac test assertion ran or failed.

## Boundary

Both apps used the deterministic `--ui-testing` fixtures. This validates native SwiftUI behavior and layout without writing to the live account. Cognito OTP, deployed API/runtime, OAuth providers, APNs, microphone hardware, and real file/photo pickers still require a separate live-device pass.
