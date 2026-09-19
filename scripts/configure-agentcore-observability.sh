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

put_metric_alarm() {
  local name="$1"
  local description="$2"
  local resource_arn="$3"
  local metric="$4"
  local statistic_option="$5"
  local statistic_value="$6"
  local threshold="$7"
  local periods="$8"
  local datapoints="$9"
  shift 9
  aws cloudwatch put-metric-alarm \
    --alarm-name "$name" \
    --alarm-description "$description" \
    --namespace AWS/Bedrock-AgentCore \
    --metric-name "$metric" \
    --dimensions "Name=Resource,Value=$resource_arn" \
    --period 60 \
    "$statistic_option" "$statistic_value" \
    --threshold "$threshold" \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods "$periods" \
    --datapoints-to-alarm "$datapoints" \
    --treat-missing-data notBreaching \
    --alarm-actions "$alarm_topic_arn" \
    --ok-actions "$alarm_topic_arn" \
    --region "$aws_region" \
    "$@"
}

put_error_rate_alarm HeyTim-production-runtime-error-rate "$runtime_arn"
put_metric_alarm HeyTim-production-runtime-throttles \
  'AgentCore runtime throttled an invocation.' "$runtime_arn" Throttles --statistic Sum 0 3 1
put_metric_alarm HeyTim-production-runtime-latency-p99 \
  'AgentCore runtime p99 latency exceeded two minutes.' "$runtime_arn" Latency --extended-statistic p99 120000 3 2 \
  --evaluate-low-sample-count-percentile ignore
put_error_rate_alarm HeyTim-production-gateway-error-rate "$gateway_arn"
put_metric_alarm HeyTim-production-gateway-throttles \
  'AgentCore gateway throttled a request.' "$gateway_arn" Throttles --statistic Sum 0 3 1

echo 'AgentCore production alarms are configured.'
