#!/usr/bin/env bash
set -euo pipefail

required_values=(
  APPLE_TEAM_ID APP_STORE_CONNECT_KEY_ID APP_STORE_CONNECT_ISSUER_ID
  APP_STORE_CONNECT_PRIVATE_KEY APPLE_DISTRIBUTION_CERTIFICATE_BASE64
  APPLE_DISTRIBUTION_CERTIFICATE_PASSWORD FROGGYBOT_BUILD_NUMBER
)
missing=()
for name in "${required_values[@]}"; do
  [[ -n "${!name:-}" ]] || missing+=("$name")
done
if (( ${#missing[@]} > 0 )); then
  printf 'Missing Apple release configuration: %s\n' "${missing[*]}" >&2
  exit 2
fi

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/FroggyBotSigning.XXXXXX")"
keychain="$temporary_root/froggybot-signing.keychain-db"
certificate="$temporary_root/distribution.p12"
signing_intermediate="$temporary_root/AppleWWDRCAG3.cer"
api_key="$temporary_root/AuthKey_${APP_STORE_CONNECT_KEY_ID}.p8"
keychain_password="$(uuidgen | tr -d '-')"
original_keychains=()
while IFS= read -r existing_keychain; do
  original_keychains+=("${existing_keychain//\"/}")
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
printf '%s' "$APPLE_DISTRIBUTION_CERTIFICATE_BASE64" | base64 -D > "$certificate"
printf '%s' "$APP_STORE_CONNECT_PRIVATE_KEY" > "$api_key"
curl --fail --location --silent --show-error \
  https://www.apple.com/certificateauthority/AppleWWDRCAG3.cer \
  --output "$signing_intermediate"
if [[ "$(shasum -a 256 "$signing_intermediate" | awk '{print $1}')" \
  != dcf21878c77f4198e4b4614f03d696d89c66c66008d4244e1b99161aac91601f ]]; then
  echo 'Apple signing intermediate did not match the expected certificate.' >&2
  exit 1
fi

security create-keychain -p "$keychain_password" "$keychain"
security set-keychain-settings -lut 7200 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
security add-certificates -k "$keychain" "$signing_intermediate"
security import "$certificate" -k "$keychain" -P "$APPLE_DISTRIBUTION_CERTIFICATE_PASSWORD" \
  -T /usr/bin/codesign -T /usr/bin/security
security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
  -k "$keychain_password" "$keychain" >/dev/null
security list-keychains -d user -s "$keychain" "${original_keychains[@]}"
if ! security find-identity -v -p codesigning "$keychain" | grep -q 'Apple Distribution'; then
  echo 'The imported Apple Distribution signing identity is not valid in the CI keychain.' >&2
  exit 1
fi

APP_STORE_CONNECT_KEY_PATH="$api_key" \
  "$apple_root/scripts/testflight.sh" all
