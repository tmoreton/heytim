#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: APPLE_TEAM_ID=TEAMID ./scripts/archive.sh [--dry-run] <ios|macos>

Environment:
  APPLE_TEAM_ID             Required Apple Developer team identifier.
  FROGGYBOT_BUILD_NUMBER    Optional numeric override. Defaults to a UTC timestamp.
  FROGGYBOT_MARKETING_VERSION  Optional MAJOR.MINOR.PATCH app version override.
  APP_STORE_CONNECT_KEY_PATH, APP_STORE_CONNECT_KEY_ID, and
  APP_STORE_CONNECT_ISSUER_ID may be supplied together for API-key signing.
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

marketing_version="${FROGGYBOT_MARKETING_VERSION:-}"
if [[ -n "$marketing_version" && ! "$marketing_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "FROGGYBOT_MARKETING_VERSION must be MAJOR.MINOR.PATCH." >&2
  exit 2
fi

key_path="${APP_STORE_CONNECT_KEY_PATH:-}"
key_id="${APP_STORE_CONNECT_KEY_ID:-}"
issuer_id="${APP_STORE_CONNECT_ISSUER_ID:-}"
if [[ -n "$key_path" || -n "$key_id" || -n "$issuer_id" ]]; then
  if [[ -z "$key_path" || -z "$key_id" || -z "$issuer_id" ]]; then
    echo "Set all three App Store Connect API-key variables, or none of them." >&2
    exit 2
  fi
  if [[ ! -f "$key_path" ]]; then
    echo "App Store Connect API key not found: $key_path" >&2
    exit 2
  fi
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
if [[ -n "$marketing_version" ]]; then
  echo "App version: $marketing_version"
fi
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

archive_args=(
  archive
  -project "$apple_root/FroggyBotApple.xcodeproj"
  -scheme FroggyBotApple
  -configuration Release
  -destination "$destination"
  -archivePath "$archive_path"
  DEVELOPMENT_TEAM="$team_id"
  CODE_SIGN_STYLE=Automatic
  CURRENT_PROJECT_VERSION="$build_number"
  -allowProvisioningUpdates
)
if [[ -n "${FROGGYBOT_SIGNING_KEYCHAIN:-}" ]]; then
  archive_args+=(CODE_SIGN_IDENTITY="Apple Distribution")
fi
if [[ -n "$marketing_version" ]]; then
  archive_args+=(MARKETING_VERSION="$marketing_version")
fi
if [[ -n "$key_path" ]]; then
  archive_args+=(
    -authenticationKeyPath "$key_path"
    -authenticationKeyID "$key_id"
    -authenticationKeyIssuerID "$issuer_id"
  )
fi
xcodebuild "${archive_args[@]}"

echo "Archive created at $archive_path"
echo "This script does not upload it. Review and distribute the archive with Xcode Organizer."
