#!/usr/bin/env bash
# Prepares pinned, generated Apple ASR frameworks and Parakeet model resources.

set -euo pipefail

module_root="$(cd "$(dirname "$0")/.." && pwd)"
repository_root="$(cd "$module_root/../.." && pwd)"
generated_root="$module_root/ios/Generated"
requested_platform="${1:-ios}"

yaprflow_revision="dc9e1b3f8725614b1a3f56165dc3dc3d4e0ffac5"
sherpa_tag="v1.13.8"
sherpa_revision="11afbd009a7f8c08f4bcf2fc1b265d0df4670fbf"
onnxruntime_version="1.28.2"
onnxruntime_ios_sha="2c2299acbb461d26d4bac4bc85985d40e7c7177ed6072703ae0846d88b0b4599"
onnxruntime_macos_sha="cb0b0bec912c77229517c463e28a3fac9674c521f9599919efff1ef2b42f3da0"

model_archive="sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
model_url="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$model_archive"
model_archive_sha="5793d0fd397c5778d2cf2126994d58e9d56b1be7c04d13c7a15bb1b4eafb16bf"
model_name="parakeet-tdt-0.6b-v3"
upstream_model_name="${model_archive%.tar.bz2}"
model_destination="$generated_root/Models/$model_name"

fail() {
  echo "error: $*" >&2
  exit 1
}

hash_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

require_tools() {
  local tool_name
  for tool_name in awk cmp curl diff ditto du find git grep ln mkdir mv nm perl readlink shasum tar unzip xcodebuild; do
    command -v "$tool_name" >/dev/null 2>&1 || fail "required command is unavailable: $tool_name"
  done
}

verify_model() {
  local directory="$1"
  [[ -f "$directory/decoder.int8.onnx" ]] || return 1
  [[ -f "$directory/encoder.int8.onnx" ]] || return 1
  [[ -f "$directory/joiner.int8.onnx" ]] || return 1
  [[ -f "$directory/tokens.txt" ]] || return 1
  [[ "$(hash_file "$directory/decoder.int8.onnx")" == "179e50c43d1a9de79c8a24149a2f9bac6eb5981823f2a2ed88d655b24248db4e" ]] || return 1
  [[ "$(hash_file "$directory/encoder.int8.onnx")" == "acfc2b4456377e15d04f0243af540b7fe7c992f8d898d751cf134c3a55fd2247" ]] || return 1
  [[ "$(hash_file "$directory/joiner.int8.onnx")" == "3164c13fc2821009440d20fcb5fdc78bff28b4db2f8d0f0b329101719c0948b3" ]] || return 1
  [[ "$(hash_file "$directory/tokens.txt")" == "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d" ]] || return 1
}

find_yaprflow_checkout() {
  local candidate="${HEYTIM_YAPRFLOW_ROOT:-$(cd "$repository_root/.." && pwd)/yaprflow}"
  [[ -d "$candidate/.git" || -f "$candidate/.git" ]] || return 1
  [[ "$(git -C "$candidate" rev-parse HEAD 2>/dev/null)" == "$yaprflow_revision" ]] || return 1
  printf '%s\n' "$candidate"
}

prepare_model() {
  if verify_model "$model_destination"; then
    echo "==> Verified Parakeet model is already prepared"
    return
  fi
  [[ ! -e "$model_destination" ]] || fail "incomplete generated model exists at $model_destination"

  local yaprflow_root
  if yaprflow_root="$(find_yaprflow_checkout)" && verify_model "$yaprflow_root/Models/$model_name"; then
    echo "==> Reusing the revision-pinned Yaprflow Parakeet model"
    mkdir -p "$(dirname "$model_destination")"
    ditto "$yaprflow_root/Models/$model_name" "$model_destination"
    verify_model "$model_destination" || fail "copied Parakeet model failed verification"
    return
  fi

  local work_root archive_path extracted_root model_file member
  work_root="$(mktemp -d -t heytim-parakeet-model.XXXXXX)"
  archive_path="$work_root/$model_archive"
  extracted_root="$work_root/extracted"
  echo "==> Downloading the pinned Parakeet model (about 487 MB)"
  curl -fL --retry 3 -o "$archive_path" "$model_url"
  [[ "$(hash_file "$archive_path")" == "$model_archive_sha" ]] \
    || fail "Parakeet model archive checksum did not match"
  while IFS= read -r member; do
    [[ "$member" != /* && "/$member/" != *"/../"* ]] \
      || fail "unsafe model archive member: $member"
  done < <(tar -tjf "$archive_path")
  mkdir -p "$extracted_root" "$model_destination"
  tar -xjf "$archive_path" -C "$extracted_root"
  for model_file in decoder.int8.onnx encoder.int8.onnx joiner.int8.onnx tokens.txt; do
    mv "$extracted_root/$upstream_model_name/$model_file" "$model_destination/$model_file"
  done
  verify_model "$model_destination" || fail "downloaded Parakeet model failed verification"
  find "$work_root" -depth -delete
}

framework_ready() {
  local platform="$1"
  [[ -f "$generated_root/Frameworks/$platform/sherpa-onnx.xcframework/Info.plist" \
    && -f "$generated_root/Frameworks/$platform/onnxruntime.xcframework/Info.plist" ]]
}

copy_yaprflow_frameworks() {
  local platform="$1" yaprflow_root sherpa_source onnx_source
  yaprflow_root="$(find_yaprflow_checkout)" || return 1
  if [[ "$platform" == "iOS" ]]; then
    sherpa_source="$yaprflow_root/Vendor/SherpaOnnxASR/Artifacts/SherpaOnnxIOS.xcframework"
    onnx_source="$yaprflow_root/Vendor/SherpaOnnxASR/Artifacts/OnnxRuntimeIOS.xcframework"
  else
    sherpa_source="$yaprflow_root/Vendor/SherpaOnnxASR/Artifacts/SherpaOnnxMacOS.xcframework"
    onnx_source="$yaprflow_root/Vendor/SherpaOnnxASR/Artifacts/OnnxRuntimeMacOS.xcframework"
  fi
  [[ -f "$sherpa_source/Info.plist" && -f "$onnx_source/Info.plist" ]] || return 1
  (cd "$yaprflow_root" && shasum -a 256 -c scripts/native-asr-checksums.sha256 >/dev/null) \
    || fail "Yaprflow's generated Apple frameworks failed their reviewed checksums"

  echo "==> Reusing revision-pinned ASR-only Yaprflow frameworks for $platform"
  mkdir -p "$generated_root/Frameworks/$platform"
  ditto "$sherpa_source" "$generated_root/Frameworks/$platform/sherpa-onnx.xcframework"
  ditto "$onnx_source" "$generated_root/Frameworks/$platform/onnxruntime.xcframework"
}

normalize_macos_onnxruntime() {
  local xcframework="$1"
  local framework="$xcframework/macos-arm64_x86_64/onnxruntime.framework"
  local version="$framework/Versions/A"
  local current="$framework/Versions/Current"
  local component root_component version_component

  remove_redundant_link() {
    local path="$1" expected_target="$2"
    [[ -e "$path" || -L "$path" ]] || return 0
    [[ -L "$path" && "$(readlink "$path")" == "$expected_target" ]] \
      || fail "ONNX Runtime macOS framework has an unexpected redundant link at $path"
    find "$path" -maxdepth 0 -delete
  }

  [[ -f "$version/onnxruntime" ]] \
    || fail "ONNX Runtime macOS framework is missing its versioned binary"
  if [[ -d "$current" && ! -L "$current" ]]; then
    find "$current" -depth -delete
    ln -s A "$current"
  fi
  [[ -L "$current" && "$(readlink "$current")" == "A" ]] \
    || fail "ONNX Runtime macOS framework has an invalid Current link"

  # Some reviewed upstream archives already contain the canonical framework
  # links plus harmless duplicated links inside Versions/A. Remove only those
  # exact duplicates before validating the normalized layout.
  remove_redundant_link "$version/A" A
  remove_redundant_link "$version/Headers/Headers" Versions/Current/Headers
  remove_redundant_link "$version/Resources/Resources" Versions/Current/Resources

  for component in onnxruntime Headers Resources; do
    root_component="$framework/$component"
    version_component="$version/$component"
    [[ -e "$version_component" ]] \
      || fail "ONNX Runtime macOS framework is missing $component"
    if [[ -L "$root_component" ]]; then
      [[ "$(readlink "$root_component")" == "Versions/Current/$component" \
        && -e "$root_component" ]] \
        || fail "ONNX Runtime macOS framework has an invalid $component link"
      continue
    fi
    [[ -e "$root_component" ]] \
      || fail "ONNX Runtime macOS framework is missing $component"
    if [[ -d "$root_component" ]]; then
      diff -qr "$root_component" "$version_component" >/dev/null \
        || fail "duplicate ONNX Runtime $component directories differ"
    else
      cmp -s "$root_component" "$version_component" \
        || fail "duplicate ONNX Runtime $component files differ"
    fi
    find "$root_component" -depth -delete
    ln -s "Versions/Current/$component" "$root_component"
  done

  root_component="$framework/Modules"
  version_component="$version/Modules"
  if [[ -L "$root_component" ]]; then
    [[ "$(readlink "$root_component")" == "Versions/Current/Modules" \
      && -d "$root_component" ]] \
      || fail "ONNX Runtime macOS framework has an invalid Modules link"
  else
    [[ -d "$root_component" ]] \
      || fail "ONNX Runtime macOS framework is missing Modules"
    if [[ -d "$version_component" ]]; then
      diff -qr "$root_component" "$version_component" >/dev/null \
        || fail "duplicate ONNX Runtime Modules directories differ"
      find "$root_component" -depth -delete
    else
      mv "$root_component" "$version_component"
    fi
    ln -s Versions/Current/Modules "$root_component"
  fi

  for component in onnxruntime Headers Modules Resources; do
    [[ -L "$framework/$component" && -e "$framework/$component" ]] \
      || fail "ONNX Runtime macOS framework has an invalid $component link"
  done
}

prepare_onnxruntime() {
  local platform="$1" destination="$2" work_root archive_url expected_sha extracted
  work_root="$(mktemp -d -t heytim-onnxruntime.XXXXXX)"
  if [[ "$platform" == "iOS" ]]; then
    archive_url="https://github.com/csukuangfj/onnxruntime-libs/releases/download/v${onnxruntime_version}/onnxruntime-ios-static-xcframework-${onnxruntime_version}.xcframework.zip"
    expected_sha="$onnxruntime_ios_sha"
  else
    archive_url="https://github.com/csukuangfj/onnxruntime-libs/releases/download/v${onnxruntime_version}/onnxruntime-macos-static-xcframework-${onnxruntime_version}.xcframework.zip"
    expected_sha="$onnxruntime_macos_sha"
  fi
  curl -fL --retry 3 -o "$work_root/onnxruntime.zip" "$archive_url"
  [[ "$(hash_file "$work_root/onnxruntime.zip")" == "$expected_sha" ]] \
    || fail "ONNX Runtime $platform archive checksum did not match"
  unzip -q "$work_root/onnxruntime.zip" -d "$work_root/extracted"
  extracted="$work_root/extracted/onnxruntime.xcframework"
  [[ -f "$extracted/Info.plist" ]] || fail "ONNX Runtime $platform archive was incomplete"
  if [[ "$platform" == "macOS" ]]; then
    normalize_macos_onnxruntime "$extracted"
  fi
  mv "$extracted" "$destination"
  find "$work_root" -depth -delete
}

build_sherpa_framework() {
  local platform="$1" destination_root="$2" work_root source_root sherpa_output
  command -v cmake >/dev/null 2>&1 || fail "cmake is required to build the ASR-only sherpa runtime"
  work_root="$(mktemp -d -t heytim-sherpa.XXXXXX)"
  source_root="$work_root/sherpa-onnx"
  git clone --quiet --depth 1 --branch "$sherpa_tag" https://github.com/k2-fsa/sherpa-onnx.git "$source_root"
  [[ "$(git -C "$source_root" rev-parse HEAD)" == "$sherpa_revision" ]] \
    || fail "sherpa-onnx tag resolved to an unexpected revision"

  if [[ "$platform" == "iOS" ]]; then
    local ort_version_root="$source_root/build-ios-no-tts/ios-onnxruntime/$onnxruntime_version"
    mkdir -p "$ort_version_root"
    prepare_onnxruntime "$platform" "$ort_version_root/onnxruntime.xcframework"
    ln -s "$onnxruntime_version/onnxruntime.xcframework" \
      "$source_root/build-ios-no-tts/ios-onnxruntime/onnxruntime.xcframework"
    perl -0pi -e 's/-DSHERPA_ONNX_ENABLE_TTS=OFF \\\n/-DSHERPA_ONNX_ENABLE_TTS=OFF \\\n  -DSHERPA_ONNX_ENABLE_SPEAKER_DIARIZATION=OFF \\\n/g' "$source_root/build-ios-no-tts.sh"
    (cd "$source_root" && SHERPA_ONNX_ONNXRUNTIME_VERSION="$onnxruntime_version" ./build-ios-no-tts.sh)
    sherpa_output="$source_root/build-ios-no-tts/sherpa-onnx.xcframework"
    mv "$ort_version_root/onnxruntime.xcframework" "$destination_root/onnxruntime.xcframework"
  else
    perl -0pi -e '
      s/cmake \\\n/cmake \\\n  -DSHERPA_ONNX_ENABLE_TTS=OFF \\\n  -DSHERPA_ONNX_ENABLE_SPEAKER_DIARIZATION=OFF \\\n/;
      s/  \.\/install\/lib\/libucd\.a \\\n//;
      s/  \.\/install\/lib\/libpiper_phonemize\.a \\\n//;
      s/  \.\/install\/lib\/libespeak-ng\.a \\\n//;
    ' "$source_root/build-macos.sh"
    (cd "$source_root" && ./build-macos.sh)
    sherpa_output="$source_root/build-macos/sherpa-onnx.xcframework"
    prepare_onnxruntime "$platform" "$destination_root/onnxruntime.xcframework"
  fi

  [[ -f "$sherpa_output/Info.plist" ]] || fail "sherpa-onnx $platform build was incomplete"
  local device_binary
  if [[ "$platform" == "iOS" ]]; then
    device_binary="$sherpa_output/ios-arm64/SherpaOnnxC.framework/SherpaOnnxC"
  else
    device_binary="$sherpa_output/macos-arm64_x86_64/SherpaOnnxC.framework/SherpaOnnxC"
  fi
  if nm -gU "$device_binary" 2>/dev/null | grep -Eiq '(^|_)espeak(_|$)|espeak-ng|piper[_-]?phonemize'; then
    fail "prohibited TTS symbols were found in the ASR-only sherpa runtime"
  fi
  mv "$sherpa_output" "$destination_root/sherpa-onnx.xcframework"
  find "$work_root" -depth -delete
}

prepare_frameworks() {
  local platform="$1"
  local destination_root="$generated_root/Frameworks/$platform"
  if framework_ready "$platform"; then
    echo "==> $platform native frameworks are already prepared"
    return
  fi
  [[ ! -e "$destination_root" ]] || fail "incomplete generated frameworks exist at $destination_root"
  if copy_yaprflow_frameworks "$platform" && framework_ready "$platform"; then
    return
  fi
  echo "==> Building pinned ASR-only sherpa-onnx for $platform"
  mkdir -p "$destination_root"
  build_sherpa_framework "$platform" "$destination_root"
  framework_ready "$platform" || fail "$platform native framework preparation failed"
}

case "$requested_platform" in
  ios) platforms=("iOS") ;;
  macos) platforms=("macOS") ;;
  apple) platforms=("iOS" "macOS") ;;
  *) fail "usage: $0 [ios|macos|apple]" ;;
esac

require_tools
prepare_model
for platform_name in "${platforms[@]}"; do
  prepare_frameworks "$platform_name"
done

echo "==> HeyTim Parakeet resources are ready for $requested_platform"
du -sh "$generated_root/Models" "$generated_root/Frameworks" 2>/dev/null || true
