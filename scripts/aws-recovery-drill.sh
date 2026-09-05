#!/usr/bin/env bash

set -euo pipefail

drill_region="${AWS_REGION:-us-east-1}"
outputs_file="${FROGBOT_OUTPUTS_FILE:-apps/mobile/amplify_outputs.json}"

if ! command -v aws >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  echo "The recovery drill requires the AWS CLI and jq." >&2
  exit 1
fi
if [[ ! -f "$outputs_file" ]]; then
  echo "Cannot find $outputs_file. Deploy the backend first or set FROGBOT_OUTPUTS_FILE." >&2
  exit 1
fi

drill_bucket="${FROGBOT_FILES_BUCKET_NAME:-$(jq -r '.custom.filesBucketName // empty' "$outputs_file")}"
drill_source_table="${FROGBOT_DATA_TABLE_NAME:-$(jq -r '.custom.dataTableName // empty' "$outputs_file")}"
if [[ ! "$drill_bucket" =~ ^frogbot-user-files-[0-9]{12}-[a-z0-9-]+$ ]]; then
  echo "Refusing to run: the resolved bucket is not a FroggyBot user-files bucket." >&2
  exit 1
fi
if [[ ! "$drill_source_table" =~ ^amplify-frogbot-.*-Data[[:alnum:]-]+$ ]]; then
  echo "Refusing to run: the resolved table is not a FroggyBot data table." >&2
  exit 1
fi

drill_stamp="$(date -u '+%Y%m%d%H%M%S')"
drill_id="$(uuidgen | tr '[:upper:]' '[:lower:]')"
drill_key="recovery-drills/${drill_stamp}-${drill_id}.txt"
drill_restore_table="FroggyBotRecoveryDrill-${drill_stamp}"
drill_dir="$(mktemp -d)"
drill_v1_file="$drill_dir/version-one.txt"
drill_v2_file="$drill_dir/version-two.txt"
drill_restored_file="$drill_dir/restored.txt"
drill_v1_id=""
drill_v2_id=""
drill_restored_id=""
drill_table_created=0

cleanup() {
  set +e
  for version_id in "$drill_restored_id" "$drill_v2_id" "$drill_v1_id"; do
    if [[ -n "$version_id" ]]; then
      aws s3api delete-object \
        --region "$drill_region" \
        --bucket "$drill_bucket" \
        --key "$drill_key" \
        --version-id "$version_id" >/dev/null
    fi
  done
  if [[ "$drill_table_created" == "1" ]]; then
    if aws dynamodb delete-table \
      --region "$drill_region" \
      --table-name "$drill_restore_table" >/dev/null 2>&1; then
      aws dynamodb wait table-not-exists \
        --region "$drill_region" \
        --table-name "$drill_restore_table"
    else
      echo "AWS is still using temporary table $drill_restore_table; delete it after it becomes ACTIVE." >&2
    fi
  fi
  rm -f "$drill_v1_file" "$drill_v2_file" "$drill_restored_file"
  rmdir "$drill_dir" 2>/dev/null || true
}
trap cleanup EXIT

aws sts get-caller-identity >/dev/null
if [[ "${FROGBOT_SKIP_DYNAMODB_RESTORE:-0}" != "1" ]]; then
  aws dynamodb describe-continuous-backups \
    --region "$drill_region" \
    --table-name "$drill_source_table" \
    --query 'ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus' \
    --output text | grep -qx ENABLED

  aws dynamodb restore-table-to-point-in-time \
    --region "$drill_region" \
    --source-table-name "$drill_source_table" \
    --target-table-name "$drill_restore_table" \
    --use-latest-restorable-time >/dev/null
  drill_table_created=1

  drill_table_ready=0
  for _attempt in $(seq 1 120); do
    restored_table_status="$(aws dynamodb describe-table \
      --region "$drill_region" \
      --table-name "$drill_restore_table" \
      --query 'Table.TableStatus' \
      --output text 2>/dev/null || true)"
    if [[ "$restored_table_status" == "ACTIVE" ]]; then
      drill_table_ready=1
      break
    fi
    sleep 15
  done
  if [[ "$drill_table_ready" != "1" ]]; then
    echo "The temporary DynamoDB restore did not become active within 30 minutes." >&2
    exit 1
  fi

  restored_table_status="$(aws dynamodb describe-table \
    --region "$drill_region" \
    --table-name "$drill_restore_table" \
    --query 'Table.TableStatus' \
    --output text)"
  if [[ "$restored_table_status" != "ACTIVE" ]]; then
    echo "The restored DynamoDB table did not become active." >&2
    exit 1
  fi
fi

printf 'FroggyBot recovery drill version one\n' >"$drill_v1_file"
printf 'FroggyBot recovery drill version two\n' >"$drill_v2_file"
drill_v1_hash="$(shasum -a 256 "$drill_v1_file" | awk '{print $1}')"

drill_v1_id="$(aws s3api put-object \
  --region "$drill_region" \
  --bucket "$drill_bucket" \
  --key "$drill_key" \
  --body "$drill_v1_file" \
  --query VersionId \
  --output text)"
drill_v2_id="$(aws s3api put-object \
  --region "$drill_region" \
  --bucket "$drill_bucket" \
  --key "$drill_key" \
  --body "$drill_v2_file" \
  --query VersionId \
  --output text)"
drill_restored_id="$(aws s3api copy-object \
  --region "$drill_region" \
  --bucket "$drill_bucket" \
  --key "$drill_key" \
  --copy-source "${drill_bucket}/${drill_key}?versionId=${drill_v1_id}" \
  --query VersionId \
  --output text)"
aws s3api get-object \
  --region "$drill_region" \
  --bucket "$drill_bucket" \
  --key "$drill_key" \
  "$drill_restored_file" >/dev/null
drill_restored_hash="$(shasum -a 256 "$drill_restored_file" | awk '{print $1}')"
if [[ "$drill_restored_hash" != "$drill_v1_hash" ]]; then
  echo "The restored S3 object did not match the selected version." >&2
  exit 1
fi

if [[ "${FROGBOT_SKIP_DYNAMODB_RESTORE:-0}" != "1" ]]; then
  echo "DynamoDB point-in-time restore: passed"
fi
echo "S3 version restore: passed"
echo "Temporary recovery resources will now be removed."
