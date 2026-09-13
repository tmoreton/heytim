#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/run.sh [--build-only] <ios|macos>

Environment:
  FROGGYBOT_DERIVED_DATA  Optional DerivedData directory.
  FROGGYBOT_SIMULATOR_ID  Optional iPhone simulator UUID.
EOF
}

build_only=false
if [[ "${1:-}" == "--build-only" ]]; then
  build_only=true
  shift
fi

platform="${1:-}"
if [[ -z "$platform" || $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The FroggyBot SwiftUI app requires macOS and Xcode." >&2
  exit 1
fi

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="$apple_root/FroggyBotApple.xcodeproj"
derived_data="${FROGGYBOT_DERIVED_DATA:-/tmp/FroggyBotAppleDerivedData}"

"$apple_root/scripts/prepare-transcription.sh"

case "$platform" in
  macos)
    xcodebuild build -quiet \
      -project "$project" \
      -scheme FroggyBotApple \
      -configuration Debug \
      -destination 'platform=macOS' \
      -derivedDataPath "$derived_data" \
      CODE_SIGNING_ALLOWED=NO

    app_path="$derived_data/Build/Products/Debug/FroggyBot.app"
    if [[ "$build_only" == false ]]; then
      open "$app_path"
      echo "Opened $app_path"
    else
      echo "Built $app_path"
    fi
    ;;
  ios)
    simulator_id="${FROGGYBOT_SIMULATOR_ID:-}"
    if [[ -z "$simulator_id" ]]; then
      simulator_id="$(xcrun simctl list devices available | sed -nE '/iPhone/ s/.*\(([0-9A-F-]{36})\).*/\1/p' | head -1)"
    fi
    if [[ -z "$simulator_id" ]]; then
      echo "No available iPhone simulator was found." >&2
      exit 1
    fi

    xcrun simctl boot "$simulator_id" 2>/dev/null || true
    xcrun simctl bootstatus "$simulator_id" -b
    xcodebuild build -quiet \
      -project "$project" \
      -scheme FroggyBotApple \
      -configuration Debug \
      -destination "id=$simulator_id" \
      -derivedDataPath "$derived_data" \
      ONLY_ACTIVE_ARCH=YES \
      CODE_SIGNING_ALLOWED=NO

    app_path="$derived_data/Build/Products/Debug-iphonesimulator/FroggyBot.app"
    if [[ "$build_only" == false ]]; then
      open -a Simulator
      xcrun simctl install "$simulator_id" "$app_path"
      xcrun simctl launch "$simulator_id" com.frogbot.app
      echo "Launched FroggyBot on iPhone simulator $simulator_id"
    else
      echo "Built $app_path"
    fi
    ;;
  *)
    echo "Unsupported platform: $platform" >&2
    usage >&2
    exit 2
    ;;
esac
