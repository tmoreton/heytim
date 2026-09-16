#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
check_aws=false
allow_post_deploy_outputs=false

for argument in "$@"; do
  case "$argument" in
    --aws) check_aws=true ;;
    --post-deploy) allow_post_deploy_outputs=true ;;
    *)
      printf 'Unknown release preflight option: %s\n' "$argument" >&2
      exit 2
      ;;
  esac
done

release_changes="$({
  git -C "$repository_root" status --porcelain --untracked-files=all \
    | grep -Ev '^.. agentcore/\.cli/deployed-state\.json$'
} || true)"
if $allow_post_deploy_outputs; then
  release_changes="$(printf '%s\n' "$release_changes" \
    | grep -Ev '^.. (services/API|apps/iOS/Resources)/amplify_outputs\.json$' || true)"
fi

if [ -n "$release_changes" ]; then
  printf 'Refusing to deploy: the repository has uncommitted or untracked changes.\n' >&2
  exit 1
fi

if $check_aws; then
  identity_arn="$(aws sts get-caller-identity --query Arn --output text)"
  if [[ "$identity_arn" == *:root ]]; then
    printf 'Refusing to deploy with AWS account-root credentials. Use the production deployment role.\n' >&2
    exit 1
  fi
fi

printf 'Release preflight passed.\n'
