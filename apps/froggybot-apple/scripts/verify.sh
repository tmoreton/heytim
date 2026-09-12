#!/usr/bin/env bash
set -euo pipefail

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="$apple_root/FroggyBotApple.xcodeproj"

"$apple_root/scripts/prepare-transcription.sh"

(
  cd "$apple_root/../../packages/frogbot-transcription"
  swift test
)

xcodebuild build -quiet \
  -project "$project" \
  -scheme FroggyBotApple \
  -destination 'platform=macOS' \
  CODE_SIGNING_ALLOWED=NO

simulator_id="${FROGGYBOT_SIMULATOR_ID:-}"
if [[ -z "$simulator_id" ]]; then
  simulator_id="$(xcrun simctl list devices available | sed -nE '/iPhone/ s/.*\(([0-9A-F-]{36})\).*/\1/p' | head -1)"
fi
if [[ -z "$simulator_id" ]]; then
  echo "No available Apple simulator was found." >&2
  exit 1
fi
xcrun simctl boot "$simulator_id" 2>/dev/null || true
xcrun simctl bootstatus "$simulator_id" -b
xcodebuild test -quiet \
  -project "$project" \
  -scheme FroggyBotApple \
  -destination "id=$simulator_id" \
  ONLY_ACTIVE_ARCH=YES
