#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
line_limit=600
baseline_file="$repository_root/scripts/source-size-baseline.txt"
oversized=()

allowed_lines() {
  local file="$1"
  local baseline_path baseline_limit
  while read -r baseline_path baseline_limit; do
    [[ -n "$baseline_path" && "$baseline_path" != \#* ]] || continue
    if [[ "$baseline_path" == "$file" ]]; then
      printf '%s\n' "$baseline_limit"
      return
    fi
  done < "$baseline_file"
  printf '%s\n' "$line_limit"
}

cd "$repository_root"
while IFS= read -r file; do
  [[ -f "$file" ]] || continue
  case "$file" in
    services/runtime/vendor/*|*/node_modules/*|*/.amplify/*|*/dist/*|agentcore/cdk/*)
      continue
      ;;
    services/runtime/*|services/API/amplify/functions/*|services/API/amplify/infrastructure/*|services/API/amplify/backend.ts|services/API/scripts/*|apps/website/src/*|apps/website/scripts/*|apps/iOS/App/*|apps/iOS/Sources/*|catalog/scripts/*|packages/*/src/*|scripts/*)
      ;;
    *)
      continue
      ;;
  esac
  case "$file" in
    *.generated.swift)
      continue
      ;;
    *.py|*.swift|*.ts|*.tsx|*.js|*.mjs|*.sh)
      lines="$(wc -l < "$file" | tr -d ' ')"
      file_limit="$(allowed_lines "$file")"
      if (( lines > file_limit )); then
        oversized+=("$file ($lines lines; maximum $file_limit)")
      fi
      ;;
  esac
done < <(git ls-files --cached --others --exclude-standard)

if (( ${#oversized[@]} > 0 )); then
  echo "Authored source files must stay at or below $line_limit lines:"
  printf '  %s\n' "${oversized[@]}"
  exit 1
fi

echo "Source-size check passed (maximum $line_limit lines; legacy files may not grow)."
