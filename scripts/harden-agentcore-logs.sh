#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$repository_root/scripts/assert-release-ready.sh" --aws --post-deploy

runtime_arn="${FROGBOT_AGENT_RUNTIME_ARN:?Set FROGBOT_AGENT_RUNTIME_ARN}"
logs_key_arn="${FROGBOT_LOGS_KMS_KEY_ARN:?Set FROGBOT_LOGS_KMS_KEY_ARN}"
region="${AWS_REGION:-us-east-1}"
runtime_id="${runtime_arn##*/}"

if [[ ! "$runtime_id" =~ ^[A-Za-z0-9_-]+$ ]]; then
  printf 'The AgentCore runtime ARN is invalid.\n' >&2
  exit 1
fi
if [[ ! "$logs_key_arn" =~ ^arn:aws:kms: ]]; then
  printf 'The CloudWatch Logs KMS key ARN is invalid.\n' >&2
  exit 1
fi

log_group="/aws/bedrock-agentcore/runtimes/${runtime_id}-DEFAULT"
aws logs put-retention-policy \
  --region "$region" \
  --log-group-name "$log_group" \
  --retention-in-days 30
aws logs associate-kms-key \
  --region "$region" \
  --log-group-name "$log_group" \
  --kms-key-id "$logs_key_arn"
printf 'Hardened %s with 30-day retention and customer-managed encryption.\n' "$log_group"
