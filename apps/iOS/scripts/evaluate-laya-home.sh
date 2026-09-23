#!/usr/bin/env bash
set -euo pipefail

# Offline routing fixture only. This never connects to Home Assistant or runs a tool.
# Its action names are abstract; a live implementation must discover and validate
# the actual tools and schemas from the user's Assist MCP server.
derived_data="${HEYTIM_DERIVED_DATA:-/tmp/HeyTimAppleDerivedData}"
model_dir="${LAYA_MODEL_DIR:-$(dirname "$0")/../Generated/Laya/laya-coreml}"
laya_cli="${LAYA_CLI:-$derived_data/SourcePackages/checkouts/FluidUse/.build/out/Products/Release/FluidUseLaya}"

if [[ ! -x "$laya_cli" ]]; then
  echo "Build FluidUseLaya or set LAYA_CLI to its executable: $laya_cli" >&2
  exit 2
fi
if [[ ! -f "$model_dir/tokenizer.json" ]]; then
  echo "Offline Laya model not found: $model_dir" >&2
  exit 2
fi
if ! command -v jq >/dev/null; then
  echo 'jq is required to score the offline fixtures.' >&2
  exit 2
fi

options='turn_on=Turn on light.bedroom|turn_off=Turn off light.bedroom|read_state=Read light.bedroom state|main_model=No action or unclear request'
instructions='Choose a present action for light.bedroom. Negated, hypothetical, quoted, or ambiguous requests must use main_model.'
fixtures=(
  'turn-on|Turn on the bedroom light. Target: light.bedroom.|turn_on'
  'turn-off|Turn off the bedroom light. Target: light.bedroom.|turn_off'
  'read-state|Is the bedroom light on? Target: light.bedroom.|read_state'
  'negated-off|Do not turn off the bedroom light. Target: light.bedroom.|main_model'
  'negated-on|Do not turn on the bedroom light. Target: light.bedroom.|main_model'
  'hypothetical|What if I turn off the bedroom light? Target: light.bedroom.|main_model'
  'quoted-command|My note says "turn off the bedroom light". Target: light.bedroom.|main_model'
  'different-room|Turn off the kitchen light. Target: light.bedroom.|main_model'
  'out-of-scope|What is the weather today? Target: light.bedroom.|main_model'
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
    '.tokens < .bucket and .action_probability >= 0.85' \
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
