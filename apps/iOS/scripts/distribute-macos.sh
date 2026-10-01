#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: APPLE_TEAM_ID=TEAMID ./scripts/distribute-macos.sh [--dry-run]

Creates a Developer ID signed Mac app, notarizes and staples it, and generates
a notarized drag-to-Applications DMG plus a Sparkle-signed ZIP and appcast.
Required for a real release:

  HEYTIM_MARKETING_VERSION
  NOTARY_KEYCHAIN_PROFILE, APPLE_ID and APPLE_APP_SPECIFIC_PASSWORD, or all three
  App Store Connect API key variables below, for notarization.

Optional:
  HEYTIM_SPARKLE_PUBLIC_KEY  Overrides the checked-in public update key.
  SPARKLE_KEYCHAIN_ACCOUNT   Defaults to heytim for local appcast signing.
  SPARKLE_PRIVATE_KEY       CI-only alternative to a Keychain private key.
  NOTARY_KEYCHAIN_PROFILE   Local notarytool credential profile name.
  APP_STORE_CONNECT_KEY_PATH, APP_STORE_CONNECT_KEY_ID,
  APP_STORE_CONNECT_ISSUER_ID
  HEYTIM_BUILD_NUMBER       Numeric build number; defaults to a UTC timestamp.
  HEYTIM_DEVELOPER_ID_PROFILE_PATH  Developer ID profile for ai.heytim.app.
  HEYTIM_DEVELOPER_ID_IDENTITY      SHA-1 identity to use for export; CI sets this.
  HEYTIM_REUSE_ARCHIVE      Set true to export an existing archive with that build number.
  HEYTIM_REUSE_EXPORT       Set true to notarize an existing Developer ID export.
  HEYTIM_RELEASE_TAG        Defaults to v<marketing version>.
  HEYTIM_RELEASE_BASE_URL   Defaults to the HeyTim GitHub Release tag URL.
  SPARKLE_GENERATE_APPCAST  Explicit Sparkle generate_appcast executable.
EOF
}

dry_run=false
if [[ "${1:-}" == --dry-run ]]; then
  dry_run=true
  shift
fi
if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

required=(APPLE_TEAM_ID HEYTIM_MARKETING_VERSION)
missing=()
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || missing+=("$name")
done
if (( ${#missing[@]} > 0 )); then
  printf 'Missing direct Mac release configuration: %s\n' "${missing[*]}" >&2
  exit 2
fi
if [[ ! "$APPLE_TEAM_ID" =~ ^[[:alnum:]]+$ ]]; then
  echo 'APPLE_TEAM_ID must contain only letters and numbers.' >&2
  exit 2
fi
if [[ ! "$HEYTIM_MARKETING_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo 'HEYTIM_MARKETING_VERSION must be MAJOR.MINOR.PATCH.' >&2
  exit 2
fi
sparkle_public_key="${HEYTIM_SPARKLE_PUBLIC_KEY:-bh9EUBu0gc+V/RonsZAGbcF+/uwvBCP19T3agE7T83A=}"
if ! public_key_size="$(printf '%s' "$sparkle_public_key" \
  | base64 -D 2>/dev/null | wc -c | tr -d ' ')" \
  || [[ "$public_key_size" != 32 ]]; then
  echo 'HEYTIM_SPARKLE_PUBLIC_KEY must be a base64-encoded 32-byte Ed25519 public key.' >&2
  exit 2
fi
if [[ "$dry_run" == false ]]; then
  if [[ -n "${NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
    : # The named Keychain profile is validated by notarytool before submission.
  elif [[ -n "${APP_STORE_CONNECT_KEY_PATH:-}" || -n "${APP_STORE_CONNECT_KEY_ID:-}" || -n "${APP_STORE_CONNECT_ISSUER_ID:-}" ]]; then
    for name in APP_STORE_CONNECT_KEY_PATH APP_STORE_CONNECT_KEY_ID APP_STORE_CONNECT_ISSUER_ID; do
      [[ -n "${!name:-}" ]] || missing+=("$name")
    done
    if (( ${#missing[@]} > 0 )); then
      printf 'Missing notarization configuration: %s\n' "${missing[*]}" >&2
      exit 2
    fi
    if [[ ! -f "$APP_STORE_CONNECT_KEY_PATH" ]]; then
      echo "App Store Connect API key not found: $APP_STORE_CONNECT_KEY_PATH" >&2
      exit 2
    fi
  elif [[ -z "${APPLE_ID:-}" || -z "${APPLE_APP_SPECIFIC_PASSWORD:-}" ]]; then
    echo 'Set NOTARY_KEYCHAIN_PROFILE, APPLE_ID and APPLE_APP_SPECIFIC_PASSWORD, or all three App Store Connect API key variables.' >&2
    exit 2
  fi
fi

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_number="${HEYTIM_BUILD_NUMBER:-$(date -u +%Y%m%d%H%M%S)}"
release_tag="${HEYTIM_RELEASE_TAG:-v$HEYTIM_MARKETING_VERSION}"
release_base_url="${HEYTIM_RELEASE_BASE_URL:-https://github.com/tmoreton/heytim/releases/download/$release_tag}"
archive_path="$apple_root/Archives/HeyTim-macOS-$build_number.xcarchive"
output="$apple_root/Archives/Direct-macOS-$build_number"
export_options="$apple_root/Resources/DeveloperIDExportOptions.plist"

if [[ ! "$build_number" =~ ^[0-9]+$ ]]; then
  echo 'HEYTIM_BUILD_NUMBER must contain only digits.' >&2
  exit 2
fi
if [[ "$release_tag" != "v$HEYTIM_MARKETING_VERSION" ]]; then
  echo "HEYTIM_RELEASE_TAG must equal v$HEYTIM_MARKETING_VERSION." >&2
  exit 2
fi
if [[ "$release_base_url" != https://* ]]; then
  echo 'HEYTIM_RELEASE_BASE_URL must use HTTPS.' >&2
  exit 2
fi

profile_temporary_root=''
installed_profile=''
profile_installed_here=false
temporary_root=''
mounted=false
cleanup() {
  if [[ "$mounted" == true ]]; then
    hdiutil detach "$mount_point" >/dev/null 2>&1 || true
  fi
  if [[ "$profile_installed_here" == true ]]; then
    rm -f -- "$installed_profile" || true
  fi
  if [[ -n "$profile_temporary_root" ]]; then
    find "$profile_temporary_root" -depth -delete 2>/dev/null || true
  fi
  if [[ -n "$temporary_root" ]]; then
    find "$temporary_root" -depth -delete 2>/dev/null || true
  fi
}
trap cleanup EXIT

reuse_export="${HEYTIM_REUSE_EXPORT:-false}"
if [[ "$dry_run" == false && "$reuse_export" != true ]]; then
  profile_path="${HEYTIM_DEVELOPER_ID_PROFILE_PATH:-}"
  if [[ -z "$profile_path" || ! -f "$profile_path" ]]; then
    echo 'Set HEYTIM_DEVELOPER_ID_PROFILE_PATH to the HeyTim Mac Developer ID profile.' >&2
    exit 2
  fi
  developer_id_identity="${HEYTIM_DEVELOPER_ID_IDENTITY:-}"
  if [[ -z "$developer_id_identity" ]]; then
    developer_id_identity="$(security find-identity -v -p codesigning \
      | awk '/"Developer ID Application:/ { print $2; exit }')"
  fi
  if [[ ! "$developer_id_identity" =~ ^[[:xdigit:]]{40}$ ]]; then
    echo 'A valid local Developer ID Application signing identity is required.' >&2
    exit 2
  fi

  original_umask="$(umask)"
  umask 077
  profile_temporary_root="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/HeyTimMacProfile.XXXXXX")"
  profile_plist="$profile_temporary_root/profile.plist"
  if ! openssl cms -verify -inform DER -in "$profile_path" -noverify \
    -out "$profile_plist" >/dev/null 2>&1; then
    echo 'The HeyTim Mac Developer ID profile has an invalid CMS signature.' >&2
    exit 1
  fi
  if ! profile_metadata="$(python3 - "$profile_plist" "$APPLE_TEAM_ID" "$developer_id_identity" <<'PY'
import datetime
import hashlib
import plistlib
import re
import sys

with open(sys.argv[1], 'rb') as file:
    profile = plistlib.load(file)
team_id, identity = sys.argv[2], sys.argv[3].upper()
entitlements = profile.get('Entitlements', {})
app_id = (entitlements.get('com.apple.application-identifier')
          or entitlements.get('application-identifier'))
expires = profile.get('ExpirationDate')
if isinstance(expires, datetime.datetime) and expires.tzinfo is None:
    expires = expires.replace(tzinfo=datetime.timezone.utc)
expiry_floor = (datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=1))
if (profile.get('TeamIdentifier') != [team_id]
        or app_id != f'{team_id}.ai.heytim.app'
        or 'OSX' not in profile.get('Platform', [])
        or not isinstance(expires, datetime.datetime)
        or expires <= expiry_floor):
    raise SystemExit('The Developer ID profile has the wrong team, app, platform, or expiry.')
certificates = profile.get('DeveloperCertificates', [])
if identity not in (hashlib.sha1(cert).hexdigest().upper()
                    for cert in certificates):
    raise SystemExit('The Developer ID profile does not contain the imported signing certificate.')
name, uuid = profile.get('Name'), profile.get('UUID')
if (not isinstance(name, str) or not name or '\n' in name
        or not isinstance(uuid, str)
        or not re.fullmatch(r'[0-9a-fA-F-]{36}', uuid)):
    raise SystemExit('The Developer ID profile name or UUID is invalid.')
print(name)
print(uuid)
PY
  )"; then
    exit 1
  fi
  profile_name="${profile_metadata%%$'\n'*}"
  profile_uuid="${profile_metadata#*$'\n'}"
  profile_store="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
  mkdir -p "$profile_store"
  installed_profile="$profile_store/$profile_uuid.provisionprofile"
  if [[ -e "$installed_profile" ]]; then
    if ! cmp -s "$profile_path" "$installed_profile"; then
      echo 'A different Developer ID profile with the same UUID is already installed.' >&2
      exit 1
    fi
  else
    if ! install -m 600 "$profile_path" "$installed_profile"; then
      rm -f -- "$installed_profile" || true
      exit 1
    fi
    profile_installed_here=true
  fi
  export_options="$profile_temporary_root/DeveloperIDExportOptions.plist"
  cp "$apple_root/Resources/DeveloperIDExportOptions.plist" "$export_options"
  /usr/libexec/PlistBuddy -c 'Set :signingStyle manual' "$export_options"
  /usr/libexec/PlistBuddy -c "Set :signingCertificate $developer_id_identity" "$export_options"
  /usr/libexec/PlistBuddy -c "Add :teamID string $APPLE_TEAM_ID" "$export_options"
  /usr/libexec/PlistBuddy -c 'Add :provisioningProfiles dict' "$export_options"
  /usr/libexec/PlistBuddy -c \
    "Add :provisioningProfiles:ai.heytim.app string $profile_name" "$export_options"
  plutil -lint "$export_options" >/dev/null
  umask "$original_umask"
fi

echo "Mac direct release: $release_tag (build $build_number)"
echo "Sparkle downloads: $release_base_url"
echo "Output: $output"
if [[ "$dry_run" == true ]]; then
  HEYTIM_BUILD_NUMBER="$build_number" \
    HEYTIM_MARKETING_VERSION="$HEYTIM_MARKETING_VERSION" \
    "$apple_root/scripts/archive.sh" --dry-run macos
  exit 0
fi
if [[ -e "$output" && "$reuse_export" != true ]]; then
  echo "Direct release directory already exists: $output" >&2
  exit 1
fi

if [[ "${HEYTIM_REUSE_ARCHIVE:-false}" == true ]]; then
  archive_app="$archive_path/Products/Applications/HeyTim.app"
  archive_info="$archive_app/Contents/Info.plist"
  if [[ ! -f "$archive_info" ]]; then
    echo "Existing Mac archive not found: $archive_path" >&2
    exit 1
  fi
  read_info() { /usr/libexec/PlistBuddy -c "Print :$1" "$archive_info"; }
  if [[ "$(read_info CFBundleShortVersionString)" != "$HEYTIM_MARKETING_VERSION" \
    || "$(read_info CFBundleVersion)" != "$build_number" \
    || "$(read_info SUPublicEDKey)" != "$sparkle_public_key" ]]; then
    echo 'Existing archive does not match the requested version or Sparkle key.' >&2
    exit 1
  fi
else
  HEYTIM_BUILD_NUMBER="$build_number" \
    HEYTIM_MARKETING_VERSION="$HEYTIM_MARKETING_VERSION" \
    HEYTIM_SPARKLE_PUBLIC_KEY="$sparkle_public_key" \
    "$apple_root/scripts/archive.sh" macos
fi

if [[ "$reuse_export" != true ]]; then
  mkdir -p "$output"
  export_args=(
    -exportArchive
    -archivePath "$archive_path"
    -exportPath "$output"
    -exportOptionsPlist "$export_options"
  )
  xcodebuild "${export_args[@]}"
fi

app_path="$output/HeyTim.app"
if [[ ! -d "$app_path" ]]; then
  echo "Developer ID export did not produce $app_path" >&2
  exit 1
fi
if [[ "$reuse_export" != true ]]; then
  embedded_profile="$app_path/Contents/embedded.provisionprofile"
  if [[ ! -f "$embedded_profile" ]] || ! cmp -s "$profile_path" "$embedded_profile"; then
    echo 'Developer ID export did not embed the selected HeyTim profile.' >&2
    exit 1
  fi
fi
export_info="$app_path/Contents/Info.plist"
read_export_info() { /usr/libexec/PlistBuddy -c "Print :$1" "$export_info"; }
if [[ "$(read_export_info CFBundleShortVersionString)" != "$HEYTIM_MARKETING_VERSION" \
  || "$(read_export_info CFBundleVersion)" != "$build_number" \
  || "$(read_export_info SUPublicEDKey)" != "$sparkle_public_key" ]]; then
  echo 'Export does not match the requested version or Sparkle key.' >&2
  exit 1
fi
codesign --verify --deep --strict --verbose=2 "$app_path"
if [[ ! -f "$app_path/Contents/Frameworks/Sparkle.framework/Versions/B/Sparkle" ]] \
  || ! otool -l "$app_path/Contents/MacOS/HeyTim" \
    | grep -F 'path @executable_path/../Frameworks' >/dev/null; then
  echo 'The exported app cannot resolve its bundled Sparkle framework.' >&2
  exit 1
fi

temporary_root="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/HeyTimNotary.XXXXXX")"
notary_zip="$temporary_root/HeyTim-notary.zip"

ditto -c -k --keepParent "$app_path" "$notary_zip"
notary_auth=()
if [[ -n "${NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
  notary_auth=(--keychain-profile "$NOTARY_KEYCHAIN_PROFILE")
elif [[ -n "${APP_STORE_CONNECT_KEY_PATH:-}" ]]; then
  notary_auth=(--key "$APP_STORE_CONNECT_KEY_PATH" --key-id "$APP_STORE_CONNECT_KEY_ID" --issuer "$APP_STORE_CONNECT_ISSUER_ID")
else
  notary_auth=(--apple-id "$APPLE_ID" --password "$APPLE_APP_SPECIFIC_PASSWORD" --team-id "$APPLE_TEAM_ID")
fi
xcrun notarytool submit "$notary_zip" "${notary_auth[@]}" --wait
xcrun stapler staple "$app_path"
xcrun stapler validate "$app_path"
spctl --assess --type execute --verbose=2 "$app_path"

archive_name="HeyTim-$HEYTIM_MARKETING_VERSION-macOS.zip"
archive_file="$output/$archive_name"
ditto -c -k --sequesterRsrc --keepParent "$app_path" "$archive_file"
appcast_source="$temporary_root/AppcastSource"
mkdir -p "$appcast_source"
ln "$archive_file" "$appcast_source/$archive_name" \
  || ditto "$archive_file" "$appcast_source/$archive_name"

generate_appcast="${SPARKLE_GENERATE_APPCAST:-}"
if [[ -z "$generate_appcast" ]]; then
  generate_appcast="$(find /tmp "$HOME/Library/Developer/Xcode/DerivedData" \
    -path '*/SourcePackages/artifacts/sparkle/Sparkle/bin/generate_appcast' \
    -type f -print -quit 2>/dev/null || true)"
fi
if [[ -z "$generate_appcast" || ! -x "$generate_appcast" ]]; then
  echo 'Sparkle generate_appcast was not found. Set SPARKLE_GENERATE_APPCAST.' >&2
  exit 1
fi
appcast_args=(
  --download-url-prefix "${release_base_url%/}/"
  --link https://heytim.ai
  --maximum-versions 1
  --maximum-deltas 0
  -o "$output/appcast.xml"
  "$appcast_source"
)
if [[ -n "${SPARKLE_PRIVATE_KEY:-}" ]]; then
  printf '%s' "$SPARKLE_PRIVATE_KEY" | "$generate_appcast" --ed-key-file - "${appcast_args[@]}"
else
  "$generate_appcast" --account "${SPARKLE_KEYCHAIN_ACCOUNT:-heytim}" "${appcast_args[@]}"
fi
xmllint --noout "$output/appcast.xml"

dmg_file="$output/HeyTim-$HEYTIM_MARKETING_VERSION-macOS.dmg"
if [[ -e "$dmg_file" ]]; then
  echo "Direct Mac disk image already exists: $dmg_file" >&2
  exit 1
fi
dmg_source="$temporary_root/DMGSource"
mkdir -p "$dmg_source"
ditto "$app_path" "$dmg_source/HeyTim.app"
ln -s /Applications "$dmg_source/Applications"
hdiutil create -quiet -volname 'Hey Tim' -srcfolder "$dmg_source" \
  -format UDZO -imagekey zlib-level=9 "$dmg_file"
hdiutil verify "$dmg_file"
xcrun notarytool submit "$dmg_file" "${notary_auth[@]}" --wait
xcrun stapler staple "$dmg_file"
xcrun stapler validate "$dmg_file"

mount_point="$temporary_root/DMGMount"
mkdir -p "$mount_point"
hdiutil attach -quiet -readonly -nobrowse -mountpoint "$mount_point" "$dmg_file"
mounted=true
if [[ ! -d "$mount_point/HeyTim.app" \
  || "$(readlink "$mount_point/Applications")" != /Applications ]]; then
  echo 'The disk image is missing HeyTim.app or its Applications shortcut.' >&2
  exit 1
fi
hdiutil detach -quiet "$mount_point"
mounted=false

echo "Notarized Mac disk image: $dmg_file"
echo "Notarized Mac update ZIP: $archive_file"
echo "Signed Sparkle feed: $output/appcast.xml"
