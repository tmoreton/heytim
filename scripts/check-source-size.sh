#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
line_limit=600
oversized=()

cd "$repository_root"
while IFS= read -r file; do
  [[ -f "$file" ]] || continue
  case "$file" in
    services/agent-runtime/vendor/*|*/node_modules/*|*/.amplify/*|*/dist/*|agentcore/cdk/*)
      continue
      ;;
    services/agent-runtime/*|services/froggybot-api/amplify/functions/*|services/froggybot-api/amplify/infrastructure/*|services/froggybot-api/amplify/backend.ts|services/froggybot-api/scripts/*|apps/froggybot/src/*|apps/froggybot/scripts/*|apps/froggybot-browser-viewer/src/*|packages/*/src/*|scripts/*)
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
