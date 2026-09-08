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

verify_application() {
  section "Application and Amplify backend"
  (
    cd "$repository_root/apps/froggybot"
    npm run verify
    npm run build:web
    uvx ruff==0.16.6 check amplify/functions
    uvx bandit==1.9.4 -q -r amplify/functions -x amplify/functions/tests
  )
}

case "$component" in
  all)
    verify_agentcore
    verify_runtime
    verify_application
    ;;
  agentcore)
    verify_agentcore
    ;;
  runtime)
    verify_runtime
    ;;
  application)
    verify_application
    ;;
  *)
    printf 'Usage: %s [all|agentcore|runtime|application]\n' "$0" >&2
    exit 2
    ;;
esac

section "Repository verification passed"
