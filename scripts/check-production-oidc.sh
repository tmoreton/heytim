#!/usr/bin/env bash
set -euo pipefail

profile="${AWS_PROFILE:-frogbot-production-org}"
account="$(aws sts get-caller-identity --profile "$profile" --query Account --output text)"
if [[ "$account" != 820323452649 ]]; then
  echo "Expected HeyTim production account 820323452649; got $account." >&2
  exit 1
fi

provider_arn="arn:aws:iam::$account:oidc-provider/token.actions.githubusercontent.com"
provider="$(aws iam get-open-id-connect-provider \
  --profile "$profile" \
  --open-id-connect-provider-arn "$provider_arn" \
  --output json)"
if ! jq -e '
  .Url == "token.actions.githubusercontent.com"
  and .ClientIDList == ["sts.amazonaws.com"]
  and (.ThumbprintList | length > 0)
' <<< "$provider" > /dev/null; then
  echo 'GitHub OIDC provider URL, audience, or thumbprint configuration is wrong.' >&2
  exit 1
fi

role_name="amplify-d17sj7dvhx07c-mai-GitHubProductionDeployRol-qBVEffTWiSXJ"
role="$(aws iam get-role --profile "$profile" --role-name "$role_name" --output json)"
if ! jq -e --arg provider_arn "$provider_arn" '
  .Role.AssumeRolePolicyDocument.Statement
  | any(.[];
    .Effect == "Allow"
    and .Principal.Federated == $provider_arn
    and .Action == "sts:AssumeRoleWithWebIdentity"
    and .Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    and .Condition.StringEquals["token.actions.githubusercontent.com:sub"] ==
      "repo:tmoreton@5090418/heytim@1356546597:environment:production"
  )
' <<< "$role" > /dev/null; then
  echo 'GitHub production deploy role trust does not match the reviewed repository and environment.' >&2
  exit 1
fi

echo "GitHub OIDC provider and production deploy role trust verified in account $account."
