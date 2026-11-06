#!/usr/bin/env bash
set -euo pipefail

runtime_arn="${HEYTIM_AGENT_RUNTIME_ARN:-}"
gateway_arn="${HEYTIM_AGENT_GATEWAY_ARN:-}"
alarm_topic_arn="${HEYTIM_ALARM_TOPIC_ARN:-}"
aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"

for required in runtime_arn gateway_arn alarm_topic_arn aws_region; do
  if [[ -z "${!required}" ]]; then
    echo "${required} is required to configure AgentCore observability." >&2
    exit 2
  fi
done

put_error_rate_alarm() {
  local name="$1"
  local resource_arn="$2"
  local metrics_file
  metrics_file="$(mktemp /tmp/heytim-agentcore-metrics.XXXXXX.json)"
  trap 'rm -f "$metrics_file"' RETURN
  jq -n --arg resource "$resource_arn" '[
    {
      Id: "system_errors",
      MetricStat: {
        Metric: {
          Namespace: "AWS/Bedrock-AgentCore",
          MetricName: "SystemErrors",
          Dimensions: [{Name: "Resource", Value: $resource}]
        },
        Period: 60,
        Stat: "Sum"
      },
      ReturnData: false
    },
    {
      Id: "invocations",
      MetricStat: {
        Metric: {
          Namespace: "AWS/Bedrock-AgentCore",
          MetricName: "Invocations",
          Dimensions: [{Name: "Resource", Value: $resource}]
        },
        Period: 60,
        Stat: "Sum"
      },
      ReturnData: false
    },
    {
      Id: "error_rate",
      Expression: "IF(invocations > 0, system_errors * 100 / invocations, 0)",
      Label: "System error rate",
      ReturnData: true
    }
  ]' > "$metrics_file"
  aws cloudwatch put-metric-alarm \
    --alarm-name "$name" \
    --alarm-description 'AgentCore system errors exceed five percent of invocations.' \
    --metrics "file://$metrics_file" \
    --threshold 5 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 3 \
    --datapoints-to-alarm 2 \
    --treat-missing-data notBreaching \
    --alarm-actions "$alarm_topic_arn" \
    --ok-actions "$alarm_topic_arn" \
    --region "$aws_region"
}

# Default service metrics remain available for investigations. Two failure-rate
# alarms cover the runtime and gateway without separate latency/throttle charges.
put_error_rate_alarm HeyTim-production-runtime-error-rate "$runtime_arn"
put_error_rate_alarm HeyTim-production-gateway-error-rate "$gateway_arn"

echo 'Essential AgentCore production alarms are configured.'
