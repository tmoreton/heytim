#!/usr/bin/env bash
set -euo pipefail
package_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
destination="${1:?Usage: stage-macos.sh DESTINATION}"
runtime_root="$package_root/.runtime"
python_root="$runtime_root/python/cpython-3.12.12-macos-aarch64-none"
if [[ ! -x "$python_root/bin/python3.12" || ! -f "$runtime_root/requirements.sha256" ]]; then
  echo 'Run apps/iOS/scripts/prepare-decider.sh before building the Mac app.' >&2
  exit 1
fi
if [[ -z "$destination" || "$destination" == / || "$destination" != */Helpers/HeyTimDecider ]]; then
  echo 'Refusing an unexpected helper destination.' >&2
  exit 1
fi
identity="${HEYTIM_DEVELOPER_ID_IDENTITY:-${EXPANDED_CODE_SIGN_IDENTITY:--}}"
if [[ "${CODE_SIGNING_ALLOWED:-YES}" == NO ]]; then identity=-; fi
contents_root="$(dirname "$(dirname "$destination")")"
runtime_destination="$contents_root/Resources/HeyTimDeciderRuntime"
stamp="$(
  {
    cat "$runtime_root/requirements.sha256"
    shasum -a 256 "$package_root/native/launcher.c" "$package_root"/src/heytim_decider/*.py "$0"
    printf '%s\n' "$identity"
  } | shasum -a 256 | awk '{print $1}'
)"
if [[ -f "$runtime_destination/.heytim-build.sha256" \
      && "$(cat "$runtime_destination/.heytim-build.sha256")" == "$stamp" \
      && -x "$destination/bin/heytim-decider" && -x "$runtime_destination/bin/python3.12" ]]; then
  exit 0
fi
mkdir -p "$destination/bin"
rm -f -- "$destination/build.sha256"
# Python's console scripts belong in Resources, where the app signature seals
# them as resources. Under Helpers they are misidentified as unsigned nested code.
if [[ -d "$destination/runtime" ]]; then
  find "$destination/runtime" -depth -delete
fi
ditto "$python_root" "$runtime_destination"
ditto "$package_root/src/heytim_decider" \
  "$runtime_destination/lib/python3.12/site-packages/heytim_decider"
xcrun clang -arch arm64 -mmacosx-version-min=14.0 -O2 -Wall -Wextra -Werror \
  "$package_root/native/launcher.c" -o "$destination/bin/heytim-decider"
# Every native dependency is signed with the app's identity before Xcode signs
# the containing app. Model downloads never modify this immutable runtime.
sign_args=(--force --sign "$identity")
if [[ "$identity" != - ]]; then
  sign_args+=(--options runtime --timestamp)
else
  # Ad-hoc signatures have no Team ID, so Hardened Runtime's library validation
  # cannot match Python with its dylib. Release builds use the real app identity.
  sign_args+=(--options 0)
fi
while IFS= read -r -d '' binary; do
  if [[ "$(file -b "$binary")" == Mach-O* ]]; then
    codesign "${sign_args[@]}" "$binary"
  fi
done < <(find "$destination" "$runtime_destination" -type f -print0)
printf '%s\n' "$stamp" > "$runtime_destination/.heytim-build.sha256"
