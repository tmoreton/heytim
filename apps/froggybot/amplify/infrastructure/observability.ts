import { Duration, type Stack } from 'aws-cdk-lib';
import { CfnBudget } from 'aws-cdk-lib/aws-budgets';
import {
  Alarm,
  AlarmStatusWidget,
  ComparisonOperator,
  Dashboard,
  GraphWidget,
  MathExpression,
  PeriodOverride,
  TextWidget,
  TreatMissingData,
} from 'aws-cdk-lib/aws-cloudwatch';
import { SnsAction } from 'aws-cdk-lib/aws-cloudwatch-actions';
import { Effect, PolicyStatement, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import type { Key } from 'aws-cdk-lib/aws-kms';
import type { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';
import { FilterPattern, MetricFilter, type LogGroup } from 'aws-cdk-lib/aws-logs';
import type { Queue } from 'aws-cdk-lib/aws-sqs';
import { Topic } from 'aws-cdk-lib/aws-sns';

type ObservabilityResources = {
  stack: Stack;
  apiFunction: LambdaFunction;
  workerFunction: LambdaFunction;
  workerLogGroup: LogGroup;
  jobs: Queue;
  deadLetterQueue: Queue;
  logsKey: Key;
  monthlyBudgetUsd: number;
  workerConcurrencyLimit: number;
};

export function addObservability({
  stack,
  apiFunction,
  workerFunction,
  workerLogGroup,
  jobs,
  deadLetterQueue,
  logsKey,
  monthlyBudgetUsd,
  workerConcurrencyLimit,
}: ObservabilityResources) {
  const lambdaErrorRate = (fn: LambdaFunction, label: string) =>
    new MathExpression({
      expression: 'IF(invocations > 0, errors * 100 / invocations, 0)',
      label: `${label} error rate`,
      period: Duration.minutes(1),
      usingMetrics: {
        errors: fn.metricErrors({ period: Duration.minutes(1) }),
        invocations: fn.metricInvocations({ period: Duration.minutes(1) }),
      },
    });

  const apiErrorAlarm = new Alarm(stack, 'ApiErrorRateAlarm', {
    metric: lambdaErrorRate(apiFunction, 'API'),
    threshold: 5,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 3,
    datapointsToAlarm: 2,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const workerErrorAlarm = new Alarm(stack, 'WorkerErrorRateAlarm', {
    metric: lambdaErrorRate(workerFunction, 'Worker'),
    threshold: 5,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 3,
    datapointsToAlarm: 2,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const apiLatencyAlarm = new Alarm(stack, 'ApiLatencyP99Alarm', {
    metric: apiFunction.metricDuration({ statistic: 'p99', period: Duration.minutes(1) }),
    threshold: Duration.seconds(5).toMilliseconds(),
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 3,
    datapointsToAlarm: 2,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const workerLatencyAlarm = new Alarm(stack, 'WorkerLatencyP99Alarm', {
    metric: workerFunction.metricDuration({ statistic: 'p99', period: Duration.minutes(1) }),
    threshold: Duration.minutes(13).toMilliseconds(),
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const workerJobFailureMetric = new MetricFilter(stack, 'WorkerJobFailureMetric', {
    logGroup: workerLogGroup,
    filterPattern: FilterPattern.literal('"Job failed for message"'),
    metricNamespace: `${stack.stackName}/Worker`,
    metricName: 'JobFailures',
    metricValue: '1',
    defaultValue: 0,
  }).metric({ statistic: 'Sum', period: Duration.minutes(1) });
  const workerJobFailureAlarm = new Alarm(stack, 'WorkerJobFailureAlarm', {
    metric: workerJobFailureMetric,
    threshold: 0,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const apiThrottleAlarm = new Alarm(stack, 'ApiThrottleAlarm', {
    metric: apiFunction.metricThrottles({ period: Duration.minutes(1) }),
    threshold: 0,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 3,
    datapointsToAlarm: 1,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const workerThrottleAlarm = new Alarm(stack, 'WorkerThrottleAlarm', {
    metric: workerFunction.metricThrottles({ period: Duration.minutes(1) }),
    threshold: 0,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 3,
    datapointsToAlarm: 1,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const workerConcurrencyAlarm = new Alarm(stack, 'WorkerConcurrencyAlarm', {
    metric: workerFunction.metric('ConcurrentExecutions', { period: Duration.minutes(1) }),
    threshold: Math.max(1, Math.floor(workerConcurrencyLimit * 0.8)),
    comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    evaluationPeriods: 3,
    datapointsToAlarm: 2,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const queueAgeAlarm = new Alarm(stack, 'QueueAgeAlarm', {
    metric: jobs.metricApproximateAgeOfOldestMessage({ period: Duration.minutes(1) }),
    threshold: Duration.minutes(10).toSeconds(),
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 3,
    datapointsToAlarm: 2,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const deadLetterAlarm = new Alarm(stack, 'DeadLetterQueueAlarm', {
    metric: deadLetterQueue.metricApproximateNumberOfMessagesVisible({ period: Duration.minutes(1) }),
    threshold: 0,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    treatMissingData: TreatMissingData.NOT_BREACHING,
  });
  const alarmTopic = new Topic(stack, 'ServiceAlarms', {
    displayName: 'FroggyBot service alarms',
    masterKey: logsKey,
  });
  alarmTopic.addToResourcePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      principals: [new ServicePrincipal('budgets.amazonaws.com')],
      actions: ['sns:Publish'],
      resources: [alarmTopic.topicArn],
      conditions: { StringEquals: { 'aws:SourceAccount': stack.account } },
    }),
  );
  logsKey.addToResourcePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      principals: [new ServicePrincipal('budgets.amazonaws.com')],
      actions: ['kms:Decrypt', 'kms:GenerateDataKey*'],
      resources: ['*'],
      conditions: { StringEquals: { 'aws:SourceAccount': stack.account } },
    }),
  );

  const monthlyBudgetName = `${stack.stackName}-monthly-cost`;
  new CfnBudget(stack, 'MonthlyCostBudget', {
    budget: {
      budgetName: monthlyBudgetName,
      budgetType: 'COST',
      timeUnit: 'MONTHLY',
      budgetLimit: { amount: monthlyBudgetUsd, unit: 'USD' },
    },
    notificationsWithSubscribers: [
      {
        notification: {
          comparisonOperator: 'GREATER_THAN',
          notificationType: 'ACTUAL',
          threshold: 50,
          thresholdType: 'PERCENTAGE',
        },
        subscribers: [{ address: alarmTopic.topicArn, subscriptionType: 'SNS' }],
      },
      {
        notification: {
          comparisonOperator: 'GREATER_THAN',
          notificationType: 'ACTUAL',
          threshold: 80,
          thresholdType: 'PERCENTAGE',
        },
        subscribers: [{ address: alarmTopic.topicArn, subscriptionType: 'SNS' }],
      },
      {
        notification: {
          comparisonOperator: 'GREATER_THAN',
          notificationType: 'FORECASTED',
          threshold: 100,
          thresholdType: 'PERCENTAGE',
        },
        subscribers: [{ address: alarmTopic.topicArn, subscriptionType: 'SNS' }],
      },
    ],
  });
  for (const alarm of [
    apiErrorAlarm,
    workerErrorAlarm,
    workerJobFailureAlarm,
    apiLatencyAlarm,
    workerLatencyAlarm,
    apiThrottleAlarm,
    workerThrottleAlarm,
    workerConcurrencyAlarm,
    queueAgeAlarm,
    deadLetterAlarm,
  ]) {
    alarm.addAlarmAction(new SnsAction(alarmTopic));
    alarm.addOkAction(new SnsAction(alarmTopic));
  }

  const dashboard = new Dashboard(stack, 'ServiceDashboard', {
    dashboardName: `${stack.stackName}-health`,
    start: '-PT8H',
    periodOverride: PeriodOverride.INHERIT,
  });
  dashboard.addWidgets(
    new TextWidget({ width: 24, height: 1, markdown: '# FroggyBot service health' }),
    new AlarmStatusWidget({
      width: 24,
      height: 6,
      title: 'Service alarms',
      alarms: [
        apiErrorAlarm,
        workerErrorAlarm,
        workerJobFailureAlarm,
        apiLatencyAlarm,
        workerLatencyAlarm,
        apiThrottleAlarm,
        workerThrottleAlarm,
        workerConcurrencyAlarm,
        queueAgeAlarm,
        deadLetterAlarm,
      ],
    }),
    new GraphWidget({
      width: 12,
      title: 'Lambda requests and errors',
      left: [apiFunction.metricInvocations(), workerFunction.metricInvocations()],
      right: [
        apiFunction.metricErrors(),
        workerFunction.metricErrors(),
        apiFunction.metricThrottles(),
        workerFunction.metricThrottles(),
      ],
    }),
    new GraphWidget({
      width: 12,
      title: 'Worker latency and queue age',
      left: [workerFunction.metricDuration({ statistic: 'p99' })],
      right: [jobs.metricApproximateAgeOfOldestMessage()],
    }),
    new GraphWidget({
      width: 12,
      title: 'Worker concurrency',
      left: [workerFunction.metric('ConcurrentExecutions')],
    }),
  );

  return { alarmTopic, monthlyBudgetName };
}
