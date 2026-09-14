#!/usr/bin/env bash
set -euo pipefail

feedback_role_arn="${FROGBOT_NATIVE_PUSH_FEEDBACK_ROLE_ARN:-}"
production_arn="${FROGBOT_APNS_APPLICATION_ARN:-}"
sandbox_arn="${FROGBOT_APNS_SANDBOX_APPLICATION_ARN:-}"
aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"

if [[ -z "$feedback_role_arn" || -z "$production_arn" || -z "$aws_region" ]]; then
  echo 'FROGBOT_NATIVE_PUSH_FEEDBACK_ROLE_ARN, FROGBOT_APNS_APPLICATION_ARN, and AWS_REGION are required.' >&2
  exit 2
fi

configure_application() {
  local application_arn="$1"
  aws sns set-platform-application-attributes \
    --platform-application-arn "$application_arn" \
    --attributes \
      "SuccessFeedbackRoleArn=$feedback_role_arn,FailureFeedbackRoleArn=$feedback_role_arn,SuccessFeedbackSampleRate=5" \
    --region "$aws_region"
}

configure_application "$production_arn"
if [[ -n "$sandbox_arn" ]]; then configure_application "$sandbox_arn"; fi
echo 'APNs delivery-status feedback is configured.'
