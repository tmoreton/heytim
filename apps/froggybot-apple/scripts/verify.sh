#!/usr/bin/env bash
set -euo pipefail

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="$apple_root/FroggyBotApple.xcodeproj"
derived_data="$(mktemp -d /tmp/FroggyBotAppleVerification.XXXXXX)"
temporary_simulator=false

cleanup() {
  if [[ "$temporary_simulator" == true ]]; then
    xcrun simctl shutdown "$simulator_id" >/dev/null 2>&1 || true
    xcrun simctl delete "$simulator_id" >/dev/null 2>&1 || true
  fi
  find "$derived_data" -depth -delete 2>/dev/null || true
}
trap cleanup EXIT

"$apple_root/scripts/prepare-transcription.sh"

(
  cd "$apple_root/../../packages/frogbot-transcription"
  swift test
)

xcodebuild test -quiet \
  -project "$project" \
  -scheme FroggyBotApple \
  -destination 'platform=macOS' \
  -derivedDataPath "$derived_data" \
  -parallel-testing-enabled NO \
  -maximum-parallel-testing-workers 1 \
  -only-testing:FroggyBotAppleTests \
  CODE_SIGNING_ALLOWED=NO

# The speech model is intentionally embedded in the application, but Xcode also
# copies it into test bundles. Release the completed Mac test products before
# building the iPhone UI runner so verification stays bounded on disk without
# skipping either platform or test suite.
if [[ -d "$derived_data/Build" ]]; then
  find "$derived_data/Build" -depth -delete
fi

simulator_id="${FROGGYBOT_SIMULATOR_ID:-}"
if [[ -z "$simulator_id" ]]; then
  runtime_id="$(xcrun simctl list runtimes available | sed -nE '/^iOS / s/.* - (com\.apple\.CoreSimulator\.SimRuntime\.[^ ]+)$/\1/p' | tail -1)"
  device_type="$(xcrun simctl list devicetypes | sed -nE '/^iPhone/ s/.*\((com\.apple\.CoreSimulator\.SimDeviceType\.[^)]+)\)$/\1/p' | head -1)"
  if [[ -z "$runtime_id" || -z "$device_type" ]]; then
    echo "No available iOS simulator runtime and iPhone device type were found." >&2
    exit 1
  fi
  simulator_id="$(xcrun simctl create "FroggyBot Verification $$" "$device_type" "$runtime_id")"
  temporary_simulator=true
fi
if [[ -z "$simulator_id" ]]; then
  echo "No available Apple simulator was found." >&2
  exit 1
fi
xcrun simctl boot "$simulator_id" 2>/dev/null || true
xcrun simctl bootstatus "$simulator_id" -b
xcodebuild test -quiet \
  -project "$project" \
  -scheme FroggyBotAppleUI \
  -destination "id=$simulator_id" \
  -derivedDataPath "$derived_data" \
  -parallel-testing-enabled NO \
  -maximum-parallel-testing-workers 1 \
  ONLY_ACTIVE_ARCH=YES
