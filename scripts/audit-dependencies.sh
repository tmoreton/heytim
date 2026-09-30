#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
audit_directory="$(mktemp -d)"
requirements_file="$audit_directory/runtime-requirements.txt"

trap 'rm -rf "$audit_directory"' EXIT

npm audit --prefix "$repository_root/apps/website" --omit=dev --audit-level=high
npm audit --prefix "$repository_root/services/API" --omit=dev --audit-level=high

# aws-cdk-lib bundles brace-expansion 5.0.9, which npm cannot override or
# update independently. Keep auditing the full CDK dependency tree and allow
# only that exact upstream-reported advisory while the vendor prepares a fix.
# https://github.com/aws/aws-cdk/issues/38932
cdk_audit_exit=0
npm audit --prefix "$repository_root/agentcore/cdk" --omit=dev --json \
  > "$audit_directory/cdk-audit.json" || cdk_audit_exit=$?
if (( cdk_audit_exit > 1 )); then
  echo "CDK dependency audit failed to complete (exit $cdk_audit_exit)" >&2
  exit "$cdk_audit_exit"
fi
node "$repository_root/scripts/check-cdk-audit.mjs" \
  "$audit_directory/cdk-audit.json" \
  "$repository_root/agentcore/cdk/package-lock.json"

uv export \
  --project "$repository_root/services/runtime" \
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
uvx pip-audit@2.10.0 \
  --cache-dir "$audit_directory/cache" \
  --progress-spinner off \
  -r "$repository_root/services/API/amplify/functions/requirements.txt"
