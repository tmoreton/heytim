#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
component="${1:-all}"

section() {
  printf '\n==> %s\n' "$1"
}

verify_agentcore() {
  section "AgentCore configuration"
  (
    cd "$repository_root/agentcore"
    if command -v agentcore >/dev/null 2>&1; then
      agentcore validate
    else
      npx --yes @aws/agentcore@0.29.0 validate
    fi
  )

  section "AgentCore evaluators"
  (
    cd "$repository_root/evaluators/heytim_run_integrity"
    uv run --project "$repository_root/services/runtime" --frozen pytest -q
  )

  section "Generated AgentCore CDK wrapper"
  (
    cd "$repository_root/agentcore/cdk"
    npm run build
    npm test -- --runInBand
  )
}

verify_runtime() {
  section "Agent runtime"
  (
    cd "$repository_root/services/runtime"
    uv run --frozen ruff check .
    uv run --frozen pytest -q
  )
}

verify_backend() {
  section "HeyTim application backend"
  (
    cd "$repository_root/services/API"
    npm run verify
    uvx ruff==0.16.6 check amplify/functions
    uvx bandit==1.9.4 -q -r amplify/functions -x amplify/functions/tests
  )
}

verify_application() {
  section "Client build and release boundary"
  node "$repository_root/scripts/check-client-entrypoints.mjs"

  section "API contract"
  npm --prefix "$repository_root/packages/heytim-contract" test

  section "Public catalog"
  python3 "$repository_root/catalog/scripts/validate_catalog.py"

  section "Vite marketing website and skills library"
  (
    cd "$repository_root/apps/website"
    npm run verify
    npm run build
  )
  python3 -m unittest discover -s "$repository_root/catalog/tests"
}

verify_apple() {
  section "SwiftUI application (iPhone and Mac)"
  "$repository_root/apps/iOS/scripts/verify.sh"
}

verify_server() {
  verify_agentcore
  verify_runtime
  verify_backend
}

case "$component" in
  all)
    verify_server
    verify_application
    if [[ "$(uname -s)" == "Darwin" ]]; then
      verify_apple
    fi
    ;;
  server)
    verify_server
    ;;
  agentcore)
    verify_agentcore
    ;;
  runtime)
    verify_runtime
    ;;
  backend)
    verify_backend
    ;;
  application)
    verify_application
    ;;
  apple)
    verify_apple
    ;;
  *)
    printf 'Usage: %s [all|server|agentcore|runtime|backend|application|apple]\n' "$0" >&2
    exit 2
    ;;
esac

section "Repository verification passed"
