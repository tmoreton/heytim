#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
generated_paths=(
  "$repository_root/agentcore/cdk/dist"
  "$repository_root/apps/froggybot/.amplify"
  "$repository_root/apps/froggybot/.expo"
  "$repository_root/apps/froggybot/dist"
  "$repository_root/services/agent-runtime/.pytest_cache"
  "$repository_root/services/agent-runtime/.ruff_cache"
  "$repository_root/services/agent-runtime/evals/results"
)

python3 "$repository_root/services/agent-runtime/scripts/codezip.py" clean --apply

for generated_path in "${generated_paths[@]}"; do
  if [[ -e "$generated_path" ]]; then
    rm -rf -- "$generated_path"
    printf 'Removed %s\n' "${generated_path#"$repository_root/"}"
  fi
done

printf 'Generated outputs removed. Installed dependencies and virtual environments were preserved.\n'
