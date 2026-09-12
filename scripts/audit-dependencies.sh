#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
audit_directory="$(mktemp -d)"
requirements_file="$audit_directory/runtime-requirements.txt"

trap 'rm -rf "$audit_directory"' EXIT

npm audit --prefix "$repository_root/apps/froggybot" --omit=dev --audit-level=high
npm audit --prefix "$repository_root/apps/froggybot-browser-viewer" --omit=dev --audit-level=high
npm audit --prefix "$repository_root/services/froggybot-api" --omit=dev --audit-level=high
npm audit --prefix "$repository_root/agentcore/cdk" --omit=dev --audit-level=high

uv export \
  --project "$repository_root/services/agent-runtime" \
  --frozen \
  --no-dev \
  --no-emit-project \
  --no-emit-local \
  --no-hashes \
  --quiet \
  --output-file "$requirements_file"
uvx pip-audit@2.10.0 \
  --cache-dir "$audit_directory/cache" \
  --progress-spinner off \
  -r "$requirements_file"
