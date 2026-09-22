#!/usr/bin/env bash
set -euo pipefail

# Offline routing fixture only. This never connects to Home Assistant or runs a tool.
derived_data="${HEYTIM_DERIVED_DATA:-/tmp/HeyTimAppleDerivedData}"
model_dir="${LAYA_MODEL_DIR:-$derived_data/Build/Products/Debug/HeyTim.app/Contents/Resources/laya-coreml}"
laya_cli="${LAYA_CLI:-$derived_data/SourcePackages/checkouts/FluidUse/.build/out/Products/Release/FluidUseLaya}"

if [[ ! -x "$laya_cli" ]]; then
  echo "Build FluidUseLaya or set LAYA_CLI to its executable: $laya_cli" >&2
  exit 2
fi
if [[ ! -f "$model_dir/tokenizer.json" ]]; then
  echo "Bundled Laya model not found: $model_dir" >&2
  exit 2
fi
if ! command -v jq >/dev/null; then
  echo 'jq is required to score the offline fixtures.' >&2
  exit 2
fi

options='turn_on=Turn on a known device|turn_off=Turn off a known device|read_state=Read device state|main_model=Unclear or needs reasoning'
instructions='Choose the safe Home Assistant tool for this request, or ask the main model when unclear.'
fixtures=(
  'turn-on|User: Turn on the living room lights. Known entity: light.living_room.|turn_on'
  'turn-off|User: Turn off the bedroom lights. Known entity: light.bedroom.|turn_off'
  'read-state|User: What lights are currently on? Known entity: light.living_room.|main_model'
  'bedroom-read|User: What is the bedroom light status? Known entity: light.bedroom.|main_model'
  'out-of-scope|User: What is the weather today?|main_model'
)

mismatches=0
for fixture in "${fixtures[@]}"; do
  IFS='|' read -r case_name state expected <<< "$fixture"
  answer="$("$laya_cli" answer \
    --model-dir "$model_dir" --precision e8 --lengths 128 \
    --state "$state" --type choice --instructions "$instructions" \
    --options "$options" --json | awk '
      BEGIN { started = 0 }
      !started {
        opening = index($0, "{")
        if (opening > 0) {
          print substr($0, opening)
          started = 1
        }
        next
      }
      { print }
    ')"
  if [[ -z "$answer" ]]; then
    echo "Laya returned no JSON for $case_name." >&2
    exit 1
  fi
  selected="$(jq -r '.selected' <<< "$answer")"
  confidence="$(jq -r '.confidence' <<< "$answer")"
  action_probability="$(jq -r '.action_probability' <<< "$answer")"
  latency="$(jq -r '.median_ms' <<< "$answer")"
  route="$selected"
  if [[ "$selected" != main_model ]] && ! jq -e \
    '.confidence >= 0.75 and .action_probability >= 0.85 and .tokens < .bucket' \
    <<< "$answer" >/dev/null; then
    route=main_model
  fi
  printf '%-13s selected=%-10s gated=%-10s expected=%-10s confidence=%s action=%s warm_ms=%s\n' \
    "$case_name" "$selected" "$route" "$expected" "$confidence" "$action_probability" "$latency"
  if [[ "$route" != "$expected" ]]; then
    mismatches=$((mismatches + 1))
  fi
done

if (( mismatches > 0 )); then
  echo "$mismatches offline Home Assistant routing fixture(s) failed." >&2
  exit 1
fi
echo 'All offline Home Assistant routing fixtures passed. No real tool was invoked.'
