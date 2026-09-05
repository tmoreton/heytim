#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
line_limit=600
oversized=()

cd "$repository_root"
while IFS= read -r file; do
  case "$file" in
    app/FrogBot/vendor/*|*/node_modules/*|*/.amplify/*|*/dist/*|agentcore/cdk/*)
      continue
      ;;
    app/FrogBot/*|apps/mobile/src/*|apps/mobile/amplify/functions/*|apps/mobile/amplify/infrastructure/*|apps/mobile/amplify/backend.ts|apps/mobile/scripts/*|scripts/*)
      ;;
    *)
      continue
      ;;
  esac
  case "$file" in
    *.py|*.ts|*.tsx|*.js|*.mjs|*.sh)
      lines="$(wc -l < "$file" | tr -d ' ')"
      if (( lines > line_limit )); then
        oversized+=("$file ($lines lines)")
      fi
      ;;
  esac
done < <(git ls-files --cached --others --exclude-standard)

if (( ${#oversized[@]} > 0 )); then
  echo "Authored source files must stay at or below $line_limit lines:"
  printf '  %s\n' "${oversized[@]}"
  exit 1
fi

echo "Source-size check passed (maximum $line_limit lines)."
