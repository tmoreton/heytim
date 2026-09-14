#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: APPLE_TEAM_ID=TEAMID ./scripts/testflight.sh [--dry-run] <ios|macos|all>

This creates a release archive from the SwiftUI project and uploads it to App
Store Connect for TestFlight processing. Xcode can use the signed-in developer
account, or all three optional API-key variables below:

  APP_STORE_CONNECT_KEY_PATH
  APP_STORE_CONNECT_KEY_ID
  APP_STORE_CONNECT_ISSUER_ID

FROGGYBOT_BUILD_NUMBER may set an explicit numeric build number.
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

case "$platform" in
  ios) platforms=(ios) ;;
  macos) platforms=(macos) ;;
  all) platforms=(ios macos) ;;
  *)
    echo "Unsupported platform: $platform" >&2
    usage >&2
    exit 2
    ;;
esac

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

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repository_root="$(cd "$apple_root/../.." && pwd)"
export_options="$apple_root/Resources/TestFlightExportOptions.plist"

if [[ "$dry_run" == true ]]; then
  for release_platform in "${platforms[@]}"; do
    FROGGYBOT_BUILD_NUMBER="$build_number" "$apple_root/scripts/archive.sh" --dry-run "$release_platform"
  done
  echo "Upload destination: App Store Connect / TestFlight"
  exit 0
fi

"$repository_root/scripts/assert-release-ready.sh" --post-deploy

(
  cd "$repository_root/services/froggybot-api"
  npm run outputs:apple:production:check
)
"$repository_root/scripts/verify.sh" apple

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

for release_platform in "${platforms[@]}"; do
  case "$release_platform" in
    ios) platform_label="iOS" ;;
    macos) platform_label="macOS" ;;
  esac
  archive_path="$apple_root/Archives/FroggyBot-$platform_label-$build_number.xcarchive"
  export_path="$apple_root/Archives/TestFlight-$platform_label-$build_number"

  FROGGYBOT_BUILD_NUMBER="$build_number" "$apple_root/scripts/archive.sh" "$release_platform"

  if [[ -e "$export_path" ]]; then
    echo "TestFlight export directory already exists: $export_path" >&2
    exit 1
  fi

  export_args=(
    -exportArchive
    -archivePath "$archive_path"
    -exportPath "$export_path"
    -exportOptionsPlist "$export_options"
    -allowProvisioningUpdates
  )
  if [[ -n "$key_path" ]]; then
    export_args+=(
      -authenticationKeyPath "$key_path"
      -authenticationKeyID "$key_id"
      -authenticationKeyIssuerID "$issuer_id"
    )
  fi
  xcodebuild "${export_args[@]}"

  echo "$platform_label build $build_number was uploaded to App Store Connect."
done
echo "Apple will show the selected build or builds in TestFlight after processing completes."
