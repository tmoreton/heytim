#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: APPLE_TEAM_ID=TEAMID ./scripts/testflight.sh [--dry-run] ios

This creates a release archive from the SwiftUI project and normally uploads
it to App Store Connect for TestFlight processing. With
HEYTIM_RELEASE_SCOPE=ios-preflight, it exports a signed IPA locally and does
not contact App Store Connect for upload. The manual
HEYTIM_RELEASE_SCOPE=ios-post-migration scope uploads an internal-only build
after the migration operator has checked the private migration manifests and
live destination state. Xcode can use the signed-in developer
account, or all three optional API-key variables below:

  APP_STORE_CONNECT_KEY_PATH
  APP_STORE_CONNECT_KEY_ID
  APP_STORE_CONNECT_ISSUER_ID

HEYTIM_BUILD_NUMBER may set an explicit numeric build number.
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

release_scope="${HEYTIM_RELEASE_SCOPE:-full}"
case "$release_scope" in
  full|ios-preflight|ios-post-migration) ;;
  *)
    echo 'HEYTIM_RELEASE_SCOPE must be full, ios-preflight, or ios-post-migration.' >&2
    exit 2
    ;;
esac

case "$platform" in
  ios) platforms=(ios) ;;
  macos|all)
    echo 'macOS is distributed as a notarized direct download, not through TestFlight.' >&2
    echo 'Use ./scripts/apple-app.sh distribute-macos instead.' >&2
    exit 2
    ;;
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

build_number="${HEYTIM_BUILD_NUMBER:-$(date -u +%Y%m%d%H%M%S)}"
if [[ ! "$build_number" =~ ^[0-9]+$ ]]; then
  echo "HEYTIM_BUILD_NUMBER must contain only digits." >&2
  exit 2
fi

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repository_root="$(cd "$apple_root/../.." && pwd)"
export_options="$apple_root/Resources/TestFlightExportOptions.plist"
if [[ "$release_scope" == ios-preflight ]]; then
  # Pre-cutover candidates are exported locally; uploading can automatically
  # expose the build to internal testers before customer state is migrated.
  export_options="$apple_root/Resources/TestFlightCandidateExportOptions.plist"
  if [[ "$(plutil -extract destination raw -o - "$export_options")" != export ]]; then
    echo 'The iOS preflight must export locally without uploading.' >&2
    exit 1
  fi
  if [[ "$(plutil -extract testFlightInternalTestingOnly raw -o - "$export_options")" != true ]]; then
    echo 'The iOS preflight export must be restricted to internal TestFlight.' >&2
    exit 1
  fi
  if [[ "$(xcodebuild -help 2>&1)" != *testFlightInternalTestingOnly* ]]; then
    echo 'This Xcode version cannot enforce internal-only TestFlight uploads.' >&2
    exit 1
  fi
elif [[ "$release_scope" == ios-post-migration ]]; then
  export_options="$apple_root/Resources/TestFlightInternalUploadOptions.plist"
  if [[ "$(plutil -extract destination raw -o - "$export_options")" != upload \
    || "$(plutil -extract testFlightInternalTestingOnly raw -o - "$export_options")" != true ]]; then
    echo 'The post-migration iOS upload must be restricted to internal TestFlight.' >&2
    exit 1
  fi
  if [[ "$(xcodebuild -help 2>&1)" != *testFlightInternalTestingOnly* ]]; then
    echo 'This Xcode version cannot enforce internal-only TestFlight uploads.' >&2
    exit 1
  fi
fi

if [[ "$dry_run" == true ]]; then
  for release_platform in "${platforms[@]}"; do
    HEYTIM_BUILD_NUMBER="$build_number" "$apple_root/scripts/archive.sh" --dry-run "$release_platform"
  done
  if [[ "$release_scope" == ios-preflight ]]; then
    echo "Export destination: local signed IPA; no App Store Connect upload"
  else
    echo "Upload destination: App Store Connect / TestFlight"
  fi
  exit 0
fi

"$repository_root/scripts/assert-release-ready.sh" --post-deploy

(
  cd "$repository_root/services/API"
  npm run outputs:apple:production:check
)
"$repository_root/scripts/verify.sh" apple

# The model/framework cache and downloaded client configuration become app
# resources. A cache saved under a restrictive umask must not make Mac package
# contents unreadable after App Store installation.
chmod -R a+rX "$repository_root/packages/heytim-transcription/ios/Generated"
chmod a+r "$apple_root/Resources/amplify_outputs.json"

if [[ -n "${HEYTIM_SIGNING_KEYCHAIN:-}" ]]; then
  if [[ ! -f "$HEYTIM_SIGNING_KEYCHAIN" ]]; then
    echo "CI signing keychain not found: $HEYTIM_SIGNING_KEYCHAIN" >&2
    exit 1
  fi
  # Keep local development identities out of the release archive's search path.
  security list-keychains -d user -s "$HEYTIM_SIGNING_KEYCHAIN"
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

for release_platform in "${platforms[@]}"; do
  case "$release_platform" in
    ios) platform_label="iOS" ;;
    macos) platform_label="macOS" ;;
  esac
  archive_path="$apple_root/Archives/HeyTim-$platform_label-$build_number.xcarchive"
  if [[ "$release_scope" == ios-preflight ]]; then
    export_path="$apple_root/Archives/Preflight-$platform_label-$build_number"
  else
    export_path="$apple_root/Archives/TestFlight-$platform_label-$build_number"
  fi

  HEYTIM_BUILD_NUMBER="$build_number" "$apple_root/scripts/archive.sh" "$release_platform"

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

  if [[ "$release_scope" == ios-preflight ]]; then
    echo "$platform_label build $build_number was exported locally to $export_path."
  else
    echo "$platform_label build $build_number was uploaded to App Store Connect."
  fi
done
if [[ "$release_scope" == ios-preflight ]]; then
  echo 'No build was uploaded to App Store Connect or made available in TestFlight.'
else
  echo "Apple will show the iPhone build in TestFlight after processing completes."
fi
