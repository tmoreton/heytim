#!/usr/bin/env bash
set -euo pipefail

# Read-only, full-backend Amplify synthesis and CloudFormation template diff.
# Requires destination-only configuration supplied through the environment.
if [[ $# -ne 1 || -z "$1" ]]; then
  echo 'Usage: preview_destination_mail_capture.sh <destination-aws-profile>' >&2
  exit 2
fi
profile="$1"
account='820323452649'
region='us-east-1'
app_id='d17sj7dvhx07c'
branch='main'
stack='amplify-d17sj7dvhx07c-main-branch-9753991d3b'
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

actual_account="$(aws --profile "$profile" --region "$region" sts get-caller-identity --query Account --output text)"
if [[ "$actual_account" != "$account" ]]; then
  echo 'AWS profile is not the exact destination account.' >&2
  exit 1
fi
actual_app="$(aws --profile "$profile" --region "$region" amplify get-app \
  --app-id "$app_id" --query 'app.appId' --output text)"
actual_branch="$(aws --profile "$profile" --region "$region" amplify get-branch \
  --app-id "$app_id" --branch-name "$branch" --query 'branch.branchName' --output text)"
aws --profile "$profile" --region "$region" cloudformation describe-stacks \
  --stack-name "$stack" --query 'Stacks[0].StackId' --output text >/dev/null
if [[ "$actual_app" != "$app_id" || "$actual_branch" != "$branch" ]]; then
  echo 'Destination Amplify app or branch differs from the reviewed target.' >&2
  exit 1
fi

if [[ "${HEYTIM_ENVIRONMENT:-}" != production \
   || "${HEYTIM_AUTH_EMAIL_PROVIDER:-}" != ses \
   || "${HEYTIM_BOT_EMAIL_STAGE:-}" != receive \
   || "${HEYTIM_BOT_EMAIL_CAPTURE_ONLY:-}" != true \
   || "${HEYTIM_BOT_EMAIL_KEEP_HELD_SUBSCRIBER:-}" != true \
   || "${HEYTIM_BOT_EMAIL_AVAILABLE:-}" != false \
   || -n "${HEYTIM_SES_RULE_SET_NAME:-}" ]]; then
  echo 'Destination backend must be production receive-stage store-only mail capture.' >&2
  exit 1
fi

required=(
  HEYTIM_AGENT_RUNTIME_ARN HEYTIM_MEMORY_ID
  HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN
  HEYTIM_LEGACY_TOKEN_VAULT_KMS_KEY_ARN
  HEYTIM_GOOGLE_OAUTH_SECRET_ARN HEYTIM_GITHUB_APP_SECRET_ARN
  HEYTIM_X_OAUTH_SECRET_ARN HEYTIM_SLACK_OAUTH_SECRET_ARN
  HEYTIM_NOTION_OAUTH_SECRET_ARN HEYTIM_APNS_APPLICATION_ARN
  HEYTIM_MONTHLY_BUDGET_USD HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT
)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing destination production configuration: $name" >&2
    exit 1
  fi
done

arn_vars=(
  HEYTIM_AGENT_RUNTIME_ARN HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN
  HEYTIM_LEGACY_TOKEN_VAULT_KMS_KEY_ARN HEYTIM_GOOGLE_OAUTH_SECRET_ARN
  HEYTIM_GITHUB_APP_SECRET_ARN HEYTIM_X_OAUTH_SECRET_ARN
  HEYTIM_SLACK_OAUTH_SECRET_ARN HEYTIM_NOTION_OAUTH_SECRET_ARN
  HEYTIM_MICROSOFT_OAUTH_SECRET_ARN HEYTIM_HUBSPOT_OAUTH_SECRET_ARN
  HEYTIM_JIRA_OAUTH_SECRET_ARN HEYTIM_ZOOM_OAUTH_SECRET_ARN
  HEYTIM_QUICKBOOKS_OAUTH_SECRET_ARN HEYTIM_PLAID_SECRET_ARN
  HEYTIM_APNS_APPLICATION_ARN HEYTIM_APNS_SANDBOX_APPLICATION_ARN
)
for name in "${arn_vars[@]}"; do
  value="${!name:-}"
  if [[ -n "$value" && "$value" != arn:aws:*:"$region":"$account":* ]]; then
    echo "$name does not belong to the exact destination account and region." >&2
    exit 1
  fi
done
if [[ "${HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN}" != arn:aws:kms:"$region":"$account":key/* ]]; then
  echo 'The memory encryption key is not a destination KMS key.' >&2
  exit 1
fi
if [[ -n "${HEYTIM_STRIPE_SECRET_ID:-}" \
   || -n "${HEYTIM_STRIPE_PLUS_PRICE_ID:-}" \
   || "${HEYTIM_STRIPE_LIVE_MODE:-false}" != false ]]; then
  echo 'The fresh destination preview must leave billing disabled.' >&2
  exit 1
fi
if [[ "${HEYTIM_FREE_ONLY_MODE:-}" != true ]]; then
  echo 'The fresh destination preview requires the 30-credit Free plan.' >&2
  exit 1
fi

# The separate, already-deployed stack owns both the mail notification queue
# and MIME quarantine bucket. Resolve the exact bucket from that stack so the
# full backend cannot silently create a second capture path.
capture_stack='HeyTimDestinationMailCapture'
capture_status="$(aws --profile "$profile" --region "$region" cloudformation describe-stacks \
  --stack-name "$capture_stack" --query 'Stacks[0].StackStatus' --output text)"
capture_bucket="$(aws --profile "$profile" --region "$region" cloudformation describe-stacks \
  --stack-name "$capture_stack" \
  --query 'Stacks[0].Outputs[?OutputKey==`BotEmailQuarantineBucketName`].OutputValue | [0]' \
  --output text)"
if [[ "$capture_status" != CREATE_COMPLETE && "$capture_status" != UPDATE_COMPLETE ]] \
  || [[ ! "$capture_bucket" =~ ^heytimdestinationmailcapt-botemailquarantine[a-z0-9-]+$ ]]; then
  echo 'The exact destination standalone mail capture stack is not ready.' >&2
  exit 1
fi
if [[ -n "${HEYTIM_BOT_EMAIL_STANDALONE_CAPTURE_BUCKET:-}" \
   && "${HEYTIM_BOT_EMAIL_STANDALONE_CAPTURE_BUCKET}" != "$capture_bucket" ]]; then
  echo 'The supplied standalone mail bucket differs from CloudFormation.' >&2
  exit 1
fi
export HEYTIM_BOT_EMAIL_STANDALONE_CAPTURE_BUCKET="$capture_bucket"

# The current CloudFormation-owned subscriber remains present in the private
# deployment. Require exact live SNS/Lambda hold proof before any synthesis.
if ! python3 -c 'import boto3' >/dev/null 2>&1; then
  echo 'Python boto3 is required; run this preview with uv run --with boto3.' >&2
  exit 2
fi
python3 "$repo_root/scripts/_destination_mail_hold.py" --profile "$profile"

umask 077
preview_dir="$(mktemp -d /private/tmp/heytim-destination-mail-preview.XXXXXX)"
chmod 0700 "$preview_dir"
export CDK_DEFAULT_ACCOUNT="$account"
export CDK_DEFAULT_REGION="$region"
cd "$repo_root/services/API"
app_command='node --import tsx scripts/private-amplify-capture-synth.mjs'
if ! cdk synth --profile "$profile" --region "$region" \
  -a "$app_command" \
  -c "amplify-backend-name=$branch" \
  -c "amplify-backend-namespace=$app_id" \
  -c amplify-backend-type=branch \
  --output "$preview_dir/cdk.out" --quiet \
  >"$preview_dir/synth.log" 2>&1; then
  echo "Amplify synthesis failed; inspect private log in $preview_dir" >&2
  exit 1
fi
if ! cdk diff --profile "$profile" --region "$region" \
  -a "$preview_dir/cdk.out" --method template --no-color \
  >"$preview_dir/diff.txt" 2>&1; then
  echo "Read-only template diff failed; inspect private log in $preview_dir" >&2
  exit 1
fi
find "$preview_dir/cdk.out" -name '*.template.json' -type f -print0 \
  | sort -z | xargs -0 shasum -a 256 >"$preview_dir/template-hashes.txt"
if [[ ! -s "$preview_dir/template-hashes.txt" ]]; then
  echo 'No synthesized CloudFormation templates were produced.' >&2
  exit 1
fi
digest="$(shasum -a 256 "$preview_dir/template-hashes.txt" | cut -d ' ' -f 1)"
printf 'Destination capture-only preview: %s\nTemplate set SHA-256: %s\n' "$preview_dir" "$digest"
guard_status=0
python3 "$repo_root/scripts/_destination_mail_diff_guard.py" \
  "$preview_dir/diff.txt" "$preview_dir/guard.json" || guard_status=$?
if [[ "$guard_status" -ne 0 ]]; then
  printf 'NO-GO: review private guard.json and diff.txt for the exact blockers.\n' >&2
  exit "$guard_status"
fi
printf 'Review required before deployment; this command made no AWS changes.\n'
