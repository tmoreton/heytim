#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
outputs_file="$repository_root/services/API/amplify_outputs.json"
target_file="$repository_root/agentcore/aws-targets.json"
runtime_arn="${HEYTIM_AGENT_RUNTIME_ARN:-}"
gateway_arn="${HEYTIM_AGENT_GATEWAY_ARN:-}"
gateway_id="${HEYTIM_AGENT_GATEWAY_ID:-}"
aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"

"$repository_root/scripts/assert-release-ready.sh" --aws --post-deploy

if [[ -z "$runtime_arn" || -z "$gateway_arn" || -z "$gateway_id" || -z "$aws_region" ]]; then
  echo 'Runtime ARN, gateway ARN, gateway ID, and AWS Region are required for production verification.' >&2
  exit 2
fi

expected_account="$(jq -r '.[] | select(.name == "production") | .account' "$target_file")"
actual_account="$(aws sts get-caller-identity --query Account --output text)"
if [[ "$actual_account" != "$expected_account" ]]; then
  echo "AWS identity is in account $actual_account; production expects $expected_account." >&2
  exit 1
fi

if [[ "$(jq -r '.custom.environment // empty' "$outputs_file")" != production ]]; then
  echo 'Amplify outputs are not from the production environment.' >&2
  exit 1
fi

api_url="$(jq -r '.custom.apiUrl // empty' "$outputs_file")"
table_name="$(jq -r '.custom.dataTableName // empty' "$outputs_file")"
invite_table_name="$(jq -r '.custom.inviteTableName // empty' "$outputs_file")"
bucket_name="$(jq -r '.custom.filesBucketName // empty' "$outputs_file")"
alarm_topic_arn="$(jq -r '.custom.alarmTopicArn // empty' "$outputs_file")"
feedback_role_arn="$(jq -r '.custom.nativePushFeedbackRoleArn // empty' "$outputs_file")"
logs_key_arn="$(jq -r '.custom.logsKeyArn // empty' "$outputs_file")"

[[ "$api_url" == https://* ]] || { echo 'Production API URL is missing or is not HTTPS.' >&2; exit 1; }
[[ "$bucket_name" == "frogbot-production-user-files-$expected_account-$aws_region" ]] || {
  echo 'Production user files are not isolated in the expected bucket.' >&2
  exit 1
}

for protected_table in "$table_name" "$invite_table_name"; do
  [[ -n "$protected_table" ]] || { echo 'A production DynamoDB output is missing.' >&2; exit 1; }
  deletion_protection="$(aws dynamodb describe-table --table-name "$protected_table" --query 'Table.DeletionProtectionEnabled' --output text)"
  [[ "$deletion_protection" == True ]] || { echo "Deletion protection is disabled for $protected_table." >&2; exit 1; }
  pitr="$(aws dynamodb describe-continuous-backups --table-name "$protected_table" --query 'ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus' --output text)"
  [[ "$pitr" == ENABLED ]] || { echo "Point-in-time recovery is disabled for $protected_table." >&2; exit 1; }
done

aws s3api head-bucket --bucket "$bucket_name"
[[ "$(aws s3api get-bucket-versioning --bucket "$bucket_name" --query Status --output text)" == Enabled ]] || {
  echo 'Production file bucket versioning is disabled.' >&2
  exit 1
}
bucket_encryption="$(aws s3api get-bucket-encryption \
  --bucket "$bucket_name" \
  --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' \
  --output text)"
[[ "$bucket_encryption" == aws:kms ]] || {
  echo 'Production file bucket does not default to AWS KMS encryption.' >&2
  exit 1
}

meme_prefix="$(jq -r '.runtimes[] | select(.name == "FrogBot") | .envVars[] | select(.name == "HEYTIM_MEME_TEMPLATE_PREFIX") | .value' "$repository_root/agentcore/agentcore.json")"
[[ -n "$meme_prefix" ]] || { echo 'Meme template prefix is missing.' >&2; exit 1; }
meme_catalog="$(mktemp)"
trap 'find "$meme_catalog" -delete 2>/dev/null || true' EXIT
aws s3api get-object \
  --bucket "$bucket_name" \
  --key "${meme_prefix%/}/catalog.json" \
  "$meme_catalog" >/dev/null
jq -e --arg image_prefix "${meme_prefix%/}/images/" '
  .schemaVersion == 2
  and (.templates | type == "array" and length > 0)
  and all(.templates[];
    (.id | type == "string")
    and (.name | type == "string" and length > 0)
    and (.key | type == "string" and startswith($image_prefix))
  )
' "$meme_catalog" >/dev/null || {
  echo 'Production meme template catalog is invalid.' >&2
  exit 1
}
while IFS= read -r template_key; do
  aws s3api head-object --bucket "$bucket_name" --key "$template_key" >/dev/null
done < <(jq -r '.templates[].key' "$meme_catalog")
find "$meme_catalog" -delete
trap - EXIT

runtime_id="${runtime_arn##*/}"
runtime_log_group="/aws/bedrock-agentcore/runtimes/${runtime_id}-DEFAULT"
runtime_log_settings="$(aws logs describe-log-groups \
  --log-group-name-prefix "$runtime_log_group" \
  --output json | jq --arg group "$runtime_log_group" \
  '.logGroups[] | select(.logGroupName == $group) | [.retentionInDays, .kmsKeyId]')"
[[ "$(jq -r '.[0]' <<<"$runtime_log_settings")" == 30 ]] || { echo 'Runtime log retention is not 30 days.' >&2; exit 1; }
[[ "$(jq -r '.[1]' <<<"$runtime_log_settings")" == "$logs_key_arn" ]] || { echo 'Runtime logs are not using the production KMS key.' >&2; exit 1; }

confirmed_subscriptions="$(aws sns list-subscriptions-by-topic \
  --topic-arn "$alarm_topic_arn" \
  --query 'length(Subscriptions[?SubscriptionArn != `PendingConfirmation`])' \
  --output text)"
(( confirmed_subscriptions > 0 )) || { echo 'The production alarm topic has no confirmed subscriber.' >&2; exit 1; }

expected_alarms=(
  HeyTim-production-runtime-error-rate
  HeyTim-production-runtime-throttles
  HeyTim-production-runtime-latency-p99
  HeyTim-production-gateway-error-rate
  HeyTim-production-gateway-throttles
)
alarm_count="$(aws cloudwatch describe-alarms \
  --alarm-names "${expected_alarms[@]}" \
  --query 'length(MetricAlarms)' \
  --output text)"
[[ "$alarm_count" == "${#expected_alarms[@]}" ]] || { echo 'One or more AgentCore production alarms are missing.' >&2; exit 1; }

gateway_targets="$(aws bedrock-agentcore-control list-gateway-targets \
  --gateway-identifier "$gateway_id" \
  --region "$aws_region" \
  --output json)"
for target_name in HeyTimXSearch HeyTimYouTube; do
  target_status="$(jq -r --arg name "$target_name" '.items[] | select(.name == $name) | .status' <<<"$gateway_targets")"
  [[ "$target_status" == READY ]] || {
    echo "Production gateway target $target_name is not ready." >&2
    exit 1
  }
done

for application_arn in "${HEYTIM_APNS_APPLICATION_ARN:-}" "${HEYTIM_APNS_SANDBOX_APPLICATION_ARN:-}"; do
  [[ -n "$application_arn" ]] || continue
  attributes="$(aws sns get-platform-application-attributes \
    --platform-application-arn "$application_arn" \
    --query Attributes \
    --output json)"
  [[ "$(jq -r '.FailureFeedbackRoleArn // empty' <<<"$attributes")" == "$feedback_role_arn" ]] || {
    echo "APNs failure feedback is not configured for $application_arn." >&2
    exit 1
  }
done

curl --fail --silent --show-error --max-time 20 "${api_url%/}/public/catalog" >/dev/null
echo "Production deployment verified for $runtime_arn and $gateway_arn."
