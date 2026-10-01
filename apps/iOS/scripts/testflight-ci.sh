#!/usr/bin/env bash
set -euo pipefail

release_scope="${HEYTIM_RELEASE_SCOPE:-full}"
if [[ "$release_scope" != full && "$release_scope" != backend-macos \
  && "$release_scope" != ios-preflight && "$release_scope" != ios-post-migration ]]; then
  echo 'HEYTIM_RELEASE_SCOPE must be full, backend-macos, ios-preflight, or ios-post-migration.' >&2
  exit 2
fi
required_values=(
  APPLE_TEAM_ID APP_STORE_CONNECT_KEY_ID APP_STORE_CONNECT_ISSUER_ID
  APP_STORE_CONNECT_PRIVATE_KEY
  HEYTIM_BUILD_NUMBER HEYTIM_MARKETING_VERSION
)
if [[ "$release_scope" == full || "$release_scope" == backend-macos ]]; then
  required_values+=(
    DEVELOPER_ID_APPLICATION_CERTIFICATE_BASE64
    DEVELOPER_ID_APPLICATION_CERTIFICATE_PASSWORD
    HEYTIM_MAC_DEVELOPER_ID_PROFILE_BASE64
    APPLE_DEVELOPMENT_CERTIFICATE_BASE64 APPLE_DEVELOPMENT_CERTIFICATE_PASSWORD
    HEYTIM_SPARKLE_PUBLIC_KEY SPARKLE_PRIVATE_KEY
  )
fi
if [[ "$release_scope" == full || "$release_scope" == ios-preflight \
  || "$release_scope" == ios-post-migration ]]; then
  required_values+=(
    APPLE_DISTRIBUTION_CERTIFICATE_BASE64 APPLE_DISTRIBUTION_CERTIFICATE_PASSWORD
    APPLE_DEVELOPMENT_CERTIFICATE_BASE64 APPLE_DEVELOPMENT_CERTIFICATE_PASSWORD
  )
fi
missing=()
for name in "${required_values[@]}"; do
  [[ -n "${!name:-}" ]] || missing+=("$name")
done
if (( ${#missing[@]} > 0 )); then
  printf 'Missing Apple release configuration: %s\n' "${missing[*]}" >&2
  exit 2
fi

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/HeyTimSigning.XXXXXX")"
keychain="$temporary_root/heytim-signing.keychain-db"
signing_intermediate="$temporary_root/AppleWWDRCAG3.cer"
developer_id_intermediate_g1="$temporary_root/DeveloperIDCA.cer"
developer_id_intermediate_g2="$temporary_root/DeveloperIDG2CA.cer"
api_key="$temporary_root/AuthKey_${APP_STORE_CONNECT_KEY_ID}.p8"
keychain_password="$(uuidgen | tr -d '-')"
original_keychains=()
while IFS= read -r existing_keychain; do
  existing_keychain="$(printf '%s' "$existing_keychain" \
    | sed -E 's/^[[:space:]]*"//; s/"[[:space:]]*$//')"
  if [[ -n "$existing_keychain" ]]; then
    original_keychains+=("$existing_keychain")
  fi
done < <(security list-keychains -d user)

cleanup() {
  if (( ${#original_keychains[@]} > 0 )); then
    security list-keychains -d user -s "${original_keychains[@]}" >/dev/null 2>&1 || true
  fi
  security delete-keychain "$keychain" >/dev/null 2>&1 || true
  find "$temporary_root" -depth -delete 2>/dev/null || true
}
trap cleanup EXIT

umask 077
if [[ "$release_scope" == full || "$release_scope" == backend-macos ]]; then
  developer_id_certificate="$temporary_root/developer-id-application.p12"
  printf '%s' "$DEVELOPER_ID_APPLICATION_CERTIFICATE_BASE64" | base64 -D > "$developer_id_certificate"
  developer_id_profile="$temporary_root/heytim-developer-id.provisionprofile"
  if ! printf '%s' "$HEYTIM_MAC_DEVELOPER_ID_PROFILE_BASE64" \
    | base64 -D > "$developer_id_profile" || [[ ! -s "$developer_id_profile" ]]; then
    echo 'The HeyTim Mac Developer ID provisioning profile is not valid base64.' >&2
    exit 1
  fi
fi
if [[ "$release_scope" == full || "$release_scope" == ios-preflight \
  || "$release_scope" == ios-post-migration ]]; then
  certificate="$temporary_root/distribution.p12"
  printf '%s' "$APPLE_DISTRIBUTION_CERTIFICATE_BASE64" | base64 -D > "$certificate"
fi
if [[ "$release_scope" == full || "$release_scope" == backend-macos \
  || "$release_scope" == ios-preflight || "$release_scope" == ios-post-migration ]]; then
  development_certificate="$temporary_root/development.p12"
  printf '%s' "$APPLE_DEVELOPMENT_CERTIFICATE_BASE64" | base64 -D > "$development_certificate"
fi
printf '%s' "$APP_STORE_CONNECT_PRIVATE_KEY" > "$api_key"
curl --fail --location --silent --show-error \
  https://www.apple.com/certificateauthority/AppleWWDRCAG3.cer \
  --output "$signing_intermediate"
if [[ "$(shasum -a 256 "$signing_intermediate" | awk '{print $1}')" \
  != dcf21878c77f4198e4b4614f03d696d89c66c66008d4244e1b99161aac91601f ]]; then
  echo 'Apple signing intermediate did not match the expected certificate.' >&2
  exit 1
fi
if [[ "$release_scope" == full || "$release_scope" == backend-macos ]]; then
  # Developer ID identities chain through a different Apple intermediate than
  # Apple Development and Apple Distribution identities. Import both generations
  # so an existing G1 or G2 signing certificate remains valid in an empty CI keychain.
  curl --fail --location --silent --show-error \
    https://www.apple.com/certificateauthority/DeveloperIDCA.cer \
    --output "$developer_id_intermediate_g1"
  curl --fail --location --silent --show-error \
    https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer \
    --output "$developer_id_intermediate_g2"
  if [[ "$(shasum -a 256 "$developer_id_intermediate_g1" | awk '{print $1}')" \
    != 7afc9d01a62f03a2de9637936d4afe68090d2de18d03f29c88cfb0b1ba63587f \
    || "$(shasum -a 256 "$developer_id_intermediate_g2" | awk '{print $1}')" \
    != f16cd3c54c7f83cea4bf1a3e6a0819c8aaa8e4a1528fd144715f350643d2df3a ]]; then
    echo 'Apple Developer ID intermediates did not match the expected certificates.' >&2
    exit 1
  fi
fi

security create-keychain -p "$keychain_password" "$keychain"
# Uncached native transcription builds can run for more than two hours before
# Xcode first signs embedded frameworks. Keep this short-lived CI keychain
# unlocked for the full five-hour job; the EXIT trap still deletes it.
security set-keychain-settings -lut 21600 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
security add-certificates -k "$keychain" "$signing_intermediate"
if [[ "$release_scope" == full || "$release_scope" == backend-macos ]]; then
  security add-certificates -k "$keychain" \
    "$developer_id_intermediate_g1" "$developer_id_intermediate_g2"
fi
if [[ "$release_scope" == full || "$release_scope" == ios-preflight \
  || "$release_scope" == ios-post-migration ]]; then
  security import "$certificate" -k "$keychain" -P "$APPLE_DISTRIBUTION_CERTIFICATE_PASSWORD" \
    -T /usr/bin/codesign -T /usr/bin/security
fi
if [[ "$release_scope" == full || "$release_scope" == backend-macos \
  || "$release_scope" == ios-preflight || "$release_scope" == ios-post-migration ]]; then
  security import "$development_certificate" -k "$keychain" \
    -P "$APPLE_DEVELOPMENT_CERTIFICATE_PASSWORD" \
    -T /usr/bin/codesign -T /usr/bin/security
fi
if [[ "$release_scope" == full || "$release_scope" == backend-macos ]]; then
  security import "$developer_id_certificate" -k "$keychain" \
    -P "$DEVELOPER_ID_APPLICATION_CERTIFICATE_PASSWORD" \
    -T /usr/bin/codesign -T /usr/bin/security
fi
security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
  -k "$keychain_password" "$keychain" >/dev/null
# Keep Xcode from silently choosing a stale identity in the runner's login
# keychain. Every identity needed for this release must be imported and probed.
security list-keychains -d user -s "$keychain"
cp /usr/bin/true "$temporary_root/signing-probe"
if [[ "$release_scope" == full || "$release_scope" == ios-preflight \
  || "$release_scope" == ios-post-migration ]]; then
  signing_identity="$(security find-identity -v -p codesigning "$keychain" \
    | awk '/"Apple Distribution:/ { print $2; exit }')"
  if [[ -z "$signing_identity" ]]; then
    echo 'The CI distribution identity is not valid.' >&2
    exit 1
  fi
  codesign --force --sign "$signing_identity" --keychain "$keychain" \
    "$temporary_root/signing-probe"
fi
if [[ "$release_scope" == full || "$release_scope" == backend-macos \
  || "$release_scope" == ios-preflight || "$release_scope" == ios-post-migration ]]; then
  development_identity="$(security find-identity -v -p codesigning "$keychain" \
    | awk '/"Apple Development:/ { print $2; exit }')"
  if [[ -z "$development_identity" ]]; then
    echo 'The CI development identity is not valid.' >&2
    exit 1
  fi
  codesign --force --sign "$development_identity" --keychain "$keychain" \
    "$temporary_root/signing-probe"
fi
if [[ "$release_scope" == full || "$release_scope" == backend-macos ]]; then
  developer_id_identity="$(security find-identity -v -p codesigning "$keychain" \
    | awk '/"Developer ID Application:/ { print $2; exit }')"
  if [[ -z "$developer_id_identity" ]]; then
    echo 'The CI Developer ID identity is not valid.' >&2
    exit 1
  fi
  codesign --force --sign "$developer_id_identity" --keychain "$keychain" \
    --timestamp "$temporary_root/signing-probe"
fi

# Secrets were written under the private umask above. Release artifacts must
# remain readable by the non-root user who installs and runs the Mac app.
umask 022

if [[ "$release_scope" == full || "$release_scope" == ios-preflight \
  || "$release_scope" == ios-post-migration ]]; then
  APP_STORE_CONNECT_KEY_PATH="$api_key" \
    HEYTIM_SIGNING_KEYCHAIN="$keychain" \
    HEYTIM_ALLOW_GENERIC_IOS_BUILD=true \
    "$apple_root/scripts/testflight.sh" ios
fi

if [[ "$release_scope" == full || "$release_scope" == backend-macos ]]; then
  APP_STORE_CONNECT_KEY_PATH="$api_key" \
    HEYTIM_SIGNING_KEYCHAIN="$keychain" \
    HEYTIM_DEVELOPER_ID_IDENTITY="$developer_id_identity" \
    HEYTIM_DEVELOPER_ID_PROFILE_PATH="$developer_id_profile" \
    HEYTIM_RELEASE_TAG="${HEYTIM_RELEASE_TAG:-v$HEYTIM_MARKETING_VERSION}" \
    "$apple_root/scripts/distribute-macos.sh"
fi
