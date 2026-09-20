#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/run.sh [--build-only] <ios|macos|all>

The `all` destination is build-only and compiles iOS and macOS in one run.

Environment:
  HEYTIM_DERIVED_DATA  Optional DerivedData directory.
  HEYTIM_SIMULATOR_ID  Optional iPhone simulator UUID.
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
  echo "The HeyTim SwiftUI app requires macOS and Xcode." >&2
  exit 1
fi

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="$apple_root/HeyTimApple.xcodeproj"
derived_data="${HEYTIM_DERIVED_DATA:-/tmp/HeyTimAppleDerivedData}"

"$apple_root/scripts/prepare-transcription.sh"

build_macos() {
    xcodebuild build -quiet \
      -project "$project" \
      -scheme HeyTimApple \
      -configuration Debug \
      -destination 'platform=macOS' \
      -derivedDataPath "$derived_data" \
      CODE_SIGNING_ALLOWED=NO

    app_path="$derived_data/Build/Products/Debug/HeyTim.app"
    if [[ "$build_only" == false ]]; then
      open "$app_path"
      echo "Opened $app_path"
    else
      echo "Built $app_path"
    fi
}

build_ios() {
    simulator_id="${HEYTIM_SIMULATOR_ID:-}"
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
      -scheme HeyTimApple \
      -configuration Debug \
      -destination "id=$simulator_id" \
      -derivedDataPath "$derived_data" \
      ONLY_ACTIVE_ARCH=YES \
      CODE_SIGNING_ALLOWED=NO

    app_path="$derived_data/Build/Products/Debug-iphonesimulator/HeyTim.app"
    if [[ "$build_only" == false ]]; then
      open -a Simulator
      xcrun simctl install "$simulator_id" "$app_path"
      xcrun simctl launch "$simulator_id" ai.heytim.app
      echo "Launched HeyTim on iPhone simulator $simulator_id"
    else
      echo "Built $app_path"
    fi
}

case "$platform" in
  macos)
    build_macos
    ;;
  ios)
    build_ios
    ;;
  all)
    if [[ "$build_only" != true ]]; then
      echo "The all destination is build-only; run each platform separately to launch it." >&2
      usage >&2
      exit 2
    fi
    build_ios
    build_macos
    ;;
  *)
    echo "Unsupported platform: $platform" >&2
    usage >&2
    exit 2
    ;;
esac
