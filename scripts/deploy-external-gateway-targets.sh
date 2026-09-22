#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
catalog_file="$repository_root/catalog/catalog.json"
schema_root="$repository_root/catalog/tools"
gateway_id="${HEYTIM_AGENT_GATEWAY_ID:-}"
aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"

if [[ -z "$gateway_id" || -z "$aws_region" ]]; then
  echo 'HEYTIM_AGENT_GATEWAY_ID and AWS_REGION are required.' >&2
  exit 2
fi

release="$(jq -r '.release // empty' "$catalog_file")"
if [[ ! "$release" =~ ^skills-v[1-9][0-9]*$ ]]; then
  echo "Catalog release is not a valid immutable Skills release: $release" >&2
  exit 1
fi

account_id="$(aws sts get-caller-identity --query Account --output text)"
schema_bucket="${HEYTIM_GATEWAY_SCHEMA_BUCKET:-bedrock-agentcore-gateway-heytim-${account_id}-use1}"
gateway_json="$(aws bedrock-agentcore-control get-gateway \
  --gateway-identifier "$gateway_id" \
  --region "$aws_region" \
  --output json)"
gateway_role_arn="$(jq -r '.roleArn // empty' <<<"$gateway_json")"
gateway_role_name="${gateway_role_arn##*/}"
aws_partition="$(cut -d: -f2 <<<"$gateway_role_arn")"
if [[ "$gateway_role_arn" != arn:aws:iam::*:role/* || -z "$gateway_role_name" ]]; then
  echo 'The deployed gateway did not return a valid execution role.' >&2
  exit 1
fi

x_provider_json="$(aws bedrock-agentcore-control get-api-key-credential-provider \
  --name FrogBotXApi --region "$aws_region" --output json)"
youtube_provider_json="$(aws bedrock-agentcore-control get-api-key-credential-provider \
  --name FrogBotYouTubeApi --region "$aws_region" --output json)"
x_provider_arn="$(jq -r '.credentialProviderArn // empty' <<<"$x_provider_json")"
youtube_provider_arn="$(jq -r '.credentialProviderArn // empty' <<<"$youtube_provider_json")"
x_secret_arn="$(jq -r '.apiKeySecretArn.secretArn // empty' <<<"$x_provider_json")"
youtube_secret_arn="$(jq -r '.apiKeySecretArn.secretArn // empty' <<<"$youtube_provider_json")"
for resolved_arn in "$x_provider_arn" "$youtube_provider_arn" "$x_secret_arn" "$youtube_secret_arn"; do
  if [[ "$resolved_arn" != arn:aws:* ]]; then
    echo 'A managed external-research credential could not be resolved.' >&2
    exit 1
  fi
done

x_key="releases/$release/x/openapi.yaml"
youtube_key="releases/$release/youtube/openapi.yaml"
aws s3api put-object \
  --bucket "$schema_bucket" \
  --key "$x_key" \
  --body "$schema_root/x/openapi.yaml" \
  --content-type application/yaml \
  --region "$aws_region" >/dev/null
aws s3api put-object \
  --bucket "$schema_bucket" \
  --key "$youtube_key" \
  --body "$schema_root/youtube/openapi.yaml" \
  --content-type application/yaml \
  --region "$aws_region" >/dev/null

role_policy="$(mktemp)"
request_file="$(mktemp)"
trap 'find "$role_policy" "$request_file" -delete 2>/dev/null || true' EXIT
jq -n \
  --arg partition "$aws_partition" \
  --arg region "$aws_region" \
  --arg account "$account_id" \
  --arg gateway "$gateway_id" \
  --arg bucket "$schema_bucket" \
  --arg x_key "$x_key" \
  --arg youtube_key "$youtube_key" \
  --arg x_provider "$x_provider_arn" \
  --arg youtube_provider "$youtube_provider_arn" \
  --arg x_secret "$x_secret_arn" \
  --arg youtube_secret "$youtube_secret_arn" '
  {
    Version: "2012-10-17",
    Statement: [
      {
        Sid: "ReadReviewedSchemas",
        Effect: "Allow",
        Action: "s3:GetObject",
        Resource: [
          "arn:\($partition):s3:::\($bucket)/\($x_key)",
          "arn:\($partition):s3:::\($bucket)/\($youtube_key)"
        ]
      },
      {
        Sid: "GetGatewayWorkloadToken",
        Effect: "Allow",
        Action: "bedrock-agentcore:GetWorkloadAccessToken",
        Resource: [
          "arn:\($partition):bedrock-agentcore:\($region):\($account):workload-identity-directory/default",
          "arn:\($partition):bedrock-agentcore:\($region):\($account):workload-identity-directory/default/workload-identity/\($gateway)"
        ]
      },
      {
        Sid: "UseReviewedApiKeys",
        Effect: "Allow",
        Action: "bedrock-agentcore:GetResourceApiKey",
        Resource: [
          "arn:\($partition):bedrock-agentcore:\($region):\($account):workload-identity-directory/default",
          "arn:\($partition):bedrock-agentcore:\($region):\($account):workload-identity-directory/default/workload-identity/\($gateway)",
          "arn:\($partition):bedrock-agentcore:\($region):\($account):token-vault/default",
          $x_provider,
          $youtube_provider
        ]
      },
      {
        Sid: "ReadReviewedAgentCoreSecrets",
        Effect: "Allow",
        Action: "secretsmanager:GetSecretValue",
        Resource: [$x_secret, $youtube_secret]
      }
    ]
  }
' > "$role_policy"
aws iam put-role-policy \
  --role-name "$gateway_role_name" \
  --policy-name HeyTimExternalResearchTargets \
  --policy-document "file://$role_policy"

deploy_target() {
  local name="$1"
  local description="$2"
  local schema_uri="$3"
  local provider_arn="$4"
  local parameter_name="$5"
  local location="$6"
  local prefix="$7"
  local target_id

  target_id="$(aws bedrock-agentcore-control list-gateway-targets \
    --gateway-identifier "$gateway_id" \
    --region "$aws_region" \
    --output json \
    | jq -r --arg name "$name" '.items[] | select(.name == $name) | .targetId' \
    | head -n 1)"

  jq -n \
    --arg gateway "$gateway_id" \
    --arg target_id "$target_id" \
    --arg name "$name" \
    --arg description "$description" \
    --arg uri "$schema_uri" \
    --arg account "$account_id" \
    --arg provider "$provider_arn" \
    --arg parameter "$parameter_name" \
    --arg location "$location" \
    --arg prefix "$prefix" '
    {
      gatewayIdentifier: $gateway,
      name: $name,
      description: $description,
      targetConfiguration: {
        mcp: {openApiSchema: {s3: {uri: $uri, bucketOwnerAccountId: $account}}}
      },
      credentialProviderConfigurations: [{
        credentialProviderType: "API_KEY",
        credentialProvider: {apiKeyCredentialProvider: (
          {
            providerArn: $provider,
            credentialParameterName: $parameter,
            credentialLocation: $location
          }
          + if $prefix == "" then {} else {credentialPrefix: $prefix} end
        )}
      }]
    }
    + if $target_id == "" then {} else {targetId: $target_id} end
  ' > "$request_file"

  if [[ -z "$target_id" ]]; then
    target_id="$(aws bedrock-agentcore-control create-gateway-target \
      --cli-input-json "file://$request_file" \
      --region "$aws_region" \
      --query targetId \
      --output text)"
  else
    aws bedrock-agentcore-control update-gateway-target \
      --cli-input-json "file://$request_file" \
      --region "$aws_region" >/dev/null
  fi

  for attempt in {1..40}; do
    target_json="$(aws bedrock-agentcore-control get-gateway-target \
      --gateway-identifier "$gateway_id" \
      --target-id "$target_id" \
      --region "$aws_region" \
      --output json)"
    status="$(jq -r '.status' <<<"$target_json")"
    case "$status" in
      READY)
        printf '%s=%s\n' "$name" "$target_id"
        return 0
        ;;
      FAILED|UPDATE_UNSUCCESSFUL|SYNCHRONIZE_UNSUCCESSFUL)
        jq -r '.statusReasons[]? // empty' <<<"$target_json" >&2
        echo "$name entered terminal status $status." >&2
        return 1
        ;;
    esac
    sleep $((attempt < 6 ? 5 : 15))
  done
  echo "$name did not become ready before the deployment timeout." >&2
  return 1
}

deploy_target \
  HeyTimXSearch \
  'Read-only search of recent public X posts.' \
  "s3://$schema_bucket/$x_key" \
  "$x_provider_arn" \
  Authorization \
  HEADER \
  Bearer
deploy_target \
  HeyTimYouTube \
  'Read-only YouTube search, public metadata, and comments.' \
  "s3://$schema_bucket/$youtube_key" \
  "$youtube_provider_arn" \
  key \
  QUERY_PARAMETER \
  ''

echo "External research gateway targets are ready for $release."
