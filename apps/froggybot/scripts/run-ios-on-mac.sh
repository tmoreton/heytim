#!/usr/bin/env bash

set -euo pipefail

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "FroggyBot's Designed for iPad build requires an Apple silicon Mac." >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
app_root="$(cd "$script_dir/.." && pwd)"
cd "$app_root"

npm run nemotron:prepare:ios

if [[ ! -d ios/FroggyBot.xcworkspace ]]; then
  npx expo prebuild --platform ios --no-install
fi

(
  cd ios
  pod install
)

open ios/FroggyBot.xcworkspace

echo
echo "Xcode is open. Select 'My Mac (Designed for iPad)' as the FroggyBot run destination, then click Run."
echo "Metro will stay attached here; press Ctrl-C when you are finished."
echo

exec npx expo start
