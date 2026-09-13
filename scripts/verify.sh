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
      npx --yes @aws/agentcore@0.28.1 validate
    fi
  )

  section "AgentCore evaluators"
  (
    cd "$repository_root/evaluators/frogbot_run_integrity"
    uv run --project "$repository_root/services/agent-runtime" --frozen pytest -q
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
    cd "$repository_root/services/agent-runtime"
    uv run --frozen ruff check .
    uv run --frozen pytest -q
  )
}

verify_backend() {
  section "FroggyBot application backend"
  (
    cd "$repository_root/services/froggybot-api"
    npm run verify
    uvx ruff==0.16.6 check amplify/functions
    uvx bandit==1.9.4 -q -r amplify/functions -x amplify/functions/tests
  )
}

verify_application() {
  section "Client build and release boundary"
  node "$repository_root/scripts/check-client-entrypoints.mjs"

  section "Shared application packages"
  npm --prefix "$repository_root/packages/froggybot-contract" test
  npm --prefix "$repository_root/packages/froggybot-client" test
  npm --prefix "$repository_root/packages/froggybot-expo-client" test
  npm --prefix "$repository_root/packages/froggybot-preview" test
  npm --prefix "$repository_root/packages/frogbot-transcription" test

  section "Isolated browser viewer"
  npm --prefix "$repository_root/apps/froggybot-browser-viewer" test
  npm --prefix "$repository_root/apps/froggybot-browser-viewer" run typecheck

  section "Preserved Expo browser client"
  (
    cd "$repository_root/apps/froggybot"
    npm run verify
    npm run build:web
  )

  if [[ "$(uname -s)" == "Darwin" ]]; then
    verify_apple
  fi
}

verify_apple() {
  section "SwiftUI application (iPhone and Mac)"
  "$repository_root/apps/froggybot-apple/scripts/verify.sh"
}

case "$component" in
  all)
    verify_agentcore
    verify_runtime
    verify_backend
    verify_application
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
    printf 'Usage: %s [all|agentcore|runtime|backend|application|apple]\n' "$0" >&2
    exit 2
    ;;
esac

section "Repository verification passed"
