#!/usr/bin/env bash
set -euo pipefail

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repository_root="$(cd "$apple_root/../.." && pwd)"
project_file="$apple_root/HeyTimApple.xcodeproj/project.pbxproj"

if rg -n '^import (SwiftUI|AuthenticationServices|Security|UserNotifications|HealthKit|AppKit|UIKit)$' \
  "$apple_root/Sources/HeyTimCore" --glob '*.swift'; then
  echo 'HeyTimCore must remain framework-neutral and must not import UI/platform frameworks.' >&2
  exit 1
fi
if rg -n '^import SwiftUI$' "$apple_root/Sources/HeyTimPlatform" --glob '*.swift'; then
  echo 'HeyTimPlatform must expose adapters without depending on SwiftUI.' >&2
  exit 1
fi
if rg -n 'HeyTimAPI\(|AuthSession\(' "$apple_root/Sources/HeyTimUI" --glob '*.swift'; then
  echo 'HeyTimUI must receive application state and cannot construct service/auth clients.' >&2
  exit 1
fi
if ! rg -q 'PlatformContract\.generated\.swift in Sources' "$project_file"; then
  echo 'The generated platform contract must be registered in the Apple application target.' >&2
  exit 1
fi

node "$repository_root/services/API/scripts/generate-api-contract.mjs" --check
node "$repository_root/services/API/scripts/generate-platform-contract.mjs" --check
"$repository_root/scripts/check-source-size.sh"

echo 'Verified Apple Core, Platform, UI, generated-contract, and source-size boundaries.'
