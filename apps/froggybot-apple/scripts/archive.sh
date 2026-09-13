#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: APPLE_TEAM_ID=TEAMID ./scripts/archive.sh [--dry-run] <ios|macos>

Environment:
  APPLE_TEAM_ID             Required Apple Developer team identifier.
  FROGGYBOT_BUILD_NUMBER    Optional numeric override. Defaults to a UTC timestamp.
EOF
}

dry_run=false
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=true
  shift
fi

platform="${1:-}"
if [[ -z "$platform" || $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

team_id="${APPLE_TEAM_ID:-}"
if [[ -z "$team_id" ]]; then
  echo "APPLE_TEAM_ID is required; choose the Apple Developer team explicitly." >&2
  exit 2
fi
if [[ ! "$team_id" =~ ^[[:alnum:]]+$ ]]; then
  echo "APPLE_TEAM_ID must contain only letters and numbers." >&2
  exit 2
fi

build_number="${FROGGYBOT_BUILD_NUMBER:-$(date -u +%Y%m%d%H%M%S)}"
if [[ ! "$build_number" =~ ^[0-9]+$ ]]; then
  echo "FROGGYBOT_BUILD_NUMBER must contain only digits." >&2
  exit 2
fi

case "$platform" in
  ios)
    platform_label="iOS"
    destination="generic/platform=iOS"
    ;;
  macos)
    platform_label="macOS"
    destination="generic/platform=macOS"
    ;;
  *)
    echo "Unsupported platform: $platform" >&2
    usage >&2
    exit 2
    ;;
esac

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
archives_root="$apple_root/Archives"
archive_path="$archives_root/FroggyBot-$platform_label-$build_number.xcarchive"

echo "Platform: $platform_label"
echo "Build number: $build_number"
echo "Archive: $archive_path"

if [[ "$dry_run" == true ]]; then
  exit 0
fi

if [[ -e "$archive_path" ]]; then
  echo "Archive already exists: $archive_path" >&2
  echo "Wait for a new UTC timestamp or set FROGGYBOT_BUILD_NUMBER explicitly." >&2
  exit 1
fi

"$apple_root/scripts/prepare-transcription.sh"
mkdir -p "$archives_root"

xcodebuild archive \
  -project "$apple_root/FroggyBotApple.xcodeproj" \
  -scheme FroggyBotApple \
  -configuration Release \
  -destination "$destination" \
  -archivePath "$archive_path" \
  DEVELOPMENT_TEAM="$team_id" \
  CODE_SIGN_STYLE=Automatic \
  CURRENT_PROJECT_VERSION="$build_number" \
  -allowProvisioningUpdates

echo "Archive created at $archive_path"
echo "This script does not upload it. Review and distribute the archive with Xcode Organizer."
