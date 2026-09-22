#!/usr/bin/env bash
set -euo pipefail

apple_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
revision=7b8d7a2b7e28e746c6ecaad44bbcd5cf251a4fcc
base_url="https://huggingface.co/FluidInference/laya-coreml/resolve/$revision"
generated_root="$apple_root/Generated/Laya"
model_root="$generated_root/laya-coreml"

verify_file() {
  local file="$1" expected_size="$2" expected_digest="$3"
  [[ -f "$file" ]] || return 1
  local actual_size actual_digest
  actual_size="$(stat -f %z "$file")"
  [[ "$actual_size" == "$expected_size" ]] || return 1
  actual_digest="$(shasum -a 256 "$file" | cut -d ' ' -f 1)"
  [[ "$actual_digest" == "$expected_digest" ]]
}

manifest=$(cat <<'EOF'
tokenizer.json|34363188|609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f
laya_multilingual_e8_L128_options32.mlmodelc/analytics/coremldata.bin|243|5cabcada4e3adc09e026c4b37a48d71e828bb3f80d12de0356b3369375ba1da6
laya_multilingual_e8_L128_options32.mlmodelc/coremldata.bin|1115|4fb10774cd0860881220a37c80b416f465e3a9b5636f83c740647bafc14fbce5
laya_multilingual_e8_L128_options32.mlmodelc/model.mil|384857|bcdb6102dacea9581875b3e8bc0f05e0b568d437bc20a8cf35b11f06edfa919a
laya_multilingual_e8_L128_options32.mlmodelc/weights/weight.bin|448093696|ca1e5da71f1498eac7b68722c9f5c3d43d1ce299aaf0c29743585749f3cc9677
LICENSE|11358|cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30
NOTICE.md|1001|ed1adf26b2bde26b13e5d07a940c6752898d462bc4f5e39f310b00cc1da37265
EOF
)

verify_directory() {
  local root="$1" path size digest
  while IFS='|' read -r path size digest; do
    verify_file "$root/$path" "$size" "$digest" || return 1
  done <<< "$manifest"
}

if verify_directory "$model_root"; then
  echo 'Pinned Laya model is ready for bundling.'
  exit 0
fi
if [[ -e "$model_root" ]]; then
  echo "Existing Laya cache is incomplete or failed verification: $model_root" >&2
  echo 'Move it aside and rerun preparation; it will not be overwritten automatically.' >&2
  exit 1
fi

mkdir -p "$generated_root"
staging="$(mktemp -d "$generated_root/.laya-staging.XXXXXX")"
cleanup() { find "$staging" -depth -delete 2>/dev/null || true; }
trap cleanup EXIT

while IFS='|' read -r path size digest; do
  destination="$staging/$path"
  mkdir -p "$(dirname "$destination")"
  echo "Preparing Laya asset: $path"
  curl --fail --location --silent --show-error --retry 3 \
    --connect-timeout 30 "$base_url/$path" -o "$destination"
  if ! verify_file "$destination" "$size" "$digest"; then
    echo "Laya asset failed size or SHA-256 verification: $path" >&2
    exit 1
  fi
done <<< "$manifest"

verify_directory "$staging"
mv "$staging" "$model_root"
trap - EXIT
echo 'Pinned Laya model is ready for bundling.'
