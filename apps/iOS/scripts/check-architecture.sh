#!/usr/bin/env bash
set -euo pipefail

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repository_root="$(cd "$apple_root/../.." && pwd)"
project_file="$apple_root/HeyTimApple.xcodeproj/project.pbxproj"
ios_info_plist="$apple_root/Resources/Info.plist"

search_swift_sources() {
  local pattern="$1"
  local directory="$2"
  if command -v rg >/dev/null 2>&1; then
    rg -n "$pattern" "$directory" --glob '*.swift'
  else
    grep -R -n -E --include='*.swift' "$pattern" "$directory"
  fi
}

if search_swift_sources \
  '^import (SwiftUI|AuthenticationServices|Security|UserNotifications|HealthKit|AppKit|UIKit)$' \
  "$apple_root/Sources/HeyTimCore"; then
  echo 'HeyTimCore must remain framework-neutral and must not import UI/platform frameworks.' >&2
  exit 1
fi
if search_swift_sources '^import SwiftUI$' "$apple_root/Sources/HeyTimPlatform"; then
  echo 'HeyTimPlatform must expose adapters without depending on SwiftUI.' >&2
  exit 1
fi
if search_swift_sources 'HeyTimAPI\(|AuthSession\(' "$apple_root/Sources/HeyTimUI"; then
  echo 'HeyTimUI must receive application state and cannot construct service/auth clients.' >&2
  exit 1
fi
if ! grep -q 'PlatformContract\.generated\.swift in Sources' "$project_file"; then
  echo 'The generated platform contract must be registered in the Apple application target.' >&2
  exit 1
fi
for health_usage_key in NSHealthShareUsageDescription NSHealthUpdateUsageDescription; do
  if ! grep -q "<key>$health_usage_key</key><string>[^<]" "$ios_info_plist"; then
    echo "$health_usage_key must contain a user-facing purpose string." >&2
    exit 1
  fi
done

node "$repository_root/services/API/scripts/generate-api-contract.mjs" --check
node "$repository_root/services/API/scripts/generate-platform-contract.mjs" --check
"$repository_root/scripts/check-source-size.sh"

echo 'Verified Apple Core, Platform, UI, generated-contract, and source-size boundaries.'
