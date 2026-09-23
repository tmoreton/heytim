#!/usr/bin/env bash
set -euo pipefail

# Offline intent fixtures only. This never reads Accessibility or changes a Mac app.
derived_data="${HEYTIM_DERIVED_DATA:-/tmp/HeyTimAppleDerivedData}"
model_dir="${LAYA_MODEL_DIR:-$(dirname "$0")/../Generated/Laya/laya-coreml}"
laya_cli="${LAYA_CLI:-$derived_data/SourcePackages/checkouts/FluidUse/.build/out/Products/Release/FluidUseLaya}"

if [[ ! -x "$laya_cli" || ! -f "$model_dir/tokenizer.json" ]]; then
  echo 'Prepare the offline Laya model and CLI, or set LAYA_CLI and LAYA_MODEL_DIR.' >&2
  exit 2
fi
if ! command -v jq >/dev/null; then
  echo 'jq is required to score the offline fixtures.' >&2
  exit 2
fi

instructions='Which local tool, if any, should handle this request? Choose bot_reply for questions or private bot memory, and uncertain when unclear.'
options='apple_notes=Create a new note in Apple Notes|mac_app=Operate another visible Mac application|bot_reply=Answer in the bot conversation or save bot memory|uncertain=Unclear destination'
fixtures=(
  'note-with-text|add a note saying Hello World|apple_notes|yes|no'
  'named-notes-no-text|Add to Apple Notes|apple_notes|yes|no'
  'speech-typo|add a note to hellow orld|apple_notes|yes|no'
  'visible-calendar|Click Next in Calendar on my Mac|mac_app|no|yes'
  'notes-question|Tell me about Apple Notes|bot_reply|no|no'
  'ambiguous-note|write a note about today’s meeting|bot_reply|yes|no'
  'bot-memory|remember this for later|bot_reply|no|no'
  'home-light|turn off the bedroom light|bot_reply|no|no'
)

mismatches=0
for fixture in "${fixtures[@]}"; do
  IFS='|' read -r case_name request expected notes_eligible mac_explicit <<< "$fixture"
  answer="$("$laya_cli" answer \
    --model-dir "$model_dir" --precision e8 --lengths 128 \
    --state "user request: $request" --type choice \
    --instructions "$instructions" --options "$options" --json | awk '
      BEGIN { started = 0 }
      !started {
        opening = index($0, "{")
        if (opening > 0) { print substr($0, opening); started = 1 }
        next
      }
      { print }
    ')"
  if [[ -z "$answer" ]]; then
    echo "Laya returned no JSON for $case_name." >&2
    exit 1
  fi
  route=bot_reply
  if [[ "$notes_eligible" == yes ]] && jq -e \
    '.selected == "apple_notes" and .confidence >= 0.60 and .action_probability >= 0.85 and .tokens < .bucket' \
    <<< "$answer" >/dev/null; then
    route=apple_notes
  elif [[ "$mac_explicit" == yes ]] && jq -e \
    '.selected == "mac_app" and .confidence >= 0.70 and .action_probability >= 0.85 and .tokens < .bucket' \
    <<< "$answer" >/dev/null; then
    route=mac_app
  fi
  printf '%-20s gated=%-11s expected=%-11s confidence=%s\n' \
    "$case_name" "$route" "$expected" "$(jq -r '.confidence' <<< "$answer")"
  if [[ "$route" != "$expected" ]]; then
    mismatches=$((mismatches + 1))
  fi
done

if (( mismatches > 0 )); then
  echo "$mismatches offline Mac intent fixture(s) failed." >&2
  exit 1
fi
echo 'All offline Mac intent fixtures passed. No real app action was invoked.'
