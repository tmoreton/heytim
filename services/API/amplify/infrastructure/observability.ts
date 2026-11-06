import { Duration, RemovalPolicy, type Stack } from 'aws-cdk-lib';
import { CfnBudget } from 'aws-cdk-lib/aws-budgets';
import {
  Alarm,
  AlarmStatusWidget,
  ComparisonOperator,
  Dashboard,
  GraphWidget,
  PeriodOverride,
  TextWidget,
  TreatMissingData,
} from 'aws-cdk-lib/aws-cloudwatch';
import { SnsAction } from 'aws-cdk-lib/aws-cloudwatch-actions';
import { Effect, PolicyStatement, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import type { Key } from 'aws-cdk-lib/aws-kms';
import type { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';
import { FilterPattern, LogGroup, MetricFilter, RetentionDays } from 'aws-cdk-lib/aws-logs';
import type { Queue } from 'aws-cdk-lib/aws-sqs';
import { Topic } from 'aws-cdk-lib/aws-sns';

type ObservabilityResources = {
  stack: Stack;
  apiFunction: LambdaFunction;
  publicApiFunction: LambdaFunction;
  workerFunction: LambdaFunction;
  workerLogGroup: LogGroup;
  apiAccessLogGroup: LogGroup;
  jobs: Queue;
  deadLetterQueue: Queue;
  logsKey: Key;
  monthlyBudgetUsd: number;
  workerConcurrencyLimit: number;
  availabilityProbe?: LambdaFunction;
};

export function createApplicationLogGroups(stack: Stack, logsKey: Key) {
  const create = (id: string) => new LogGroup(stack, id, {
    retention: RetentionDays.ONE_MONTH,
    removalPolicy: RemovalPolicy.RETAIN,
  });
  return {
    apiLogGroup: create('ApiLogs'),
    publicApiLogGroup: create('PublicApiLogs'),
    workerLogGroup: create('WorkerLogs'),
    plaidWebhookLogGroup: create('PlaidWebhookLogs'),
    apiAccessLogGroup: create('ApiAccessLogs'),
  };
}

export function addObservability({
  stack,
  apiFunction,
  publicApiFunction,
  workerFunction,
  workerLogGroup,
  apiAccessLogGroup,
  jobs,
  deadLetterQueue,
  logsKey,
  monthlyBudgetUsd,
}: ObservabilityResources) {
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
  // The API adapter intentionally catches domain and unexpected errors to return
  // useful JSON. Those 5xx responses are successful Lambda invocations, so the
  // Lambda Errors metric alone cannot detect the failures users actually see.
  const apiServerErrorMetric = new MetricFilter(stack, 'ApiServerErrorMetric', {
    logGroup: apiAccessLogGroup,
    filterPattern: FilterPattern.stringValue('$.status', '=', '5*'),
    metricNamespace: `${stack.stackName}/Api`,
    metricName: 'ServerErrors',
    metricValue: '1',
    defaultValue: 0,
  }).metric({ statistic: 'Sum', period: Duration.minutes(1) });
  const apiServerErrorAlarm = new Alarm(stack, 'ApiServerErrorAlarm', {
    metric: apiServerErrorMetric,
    threshold: 0,
    comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
    evaluationPeriods: 3,
    datapointsToAlarm: 1,
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
    displayName: 'HeyTim service alarms',
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
  // Keep the alarms that detect failed customer work. Provider/runtime failure
  // alarms are managed by the AgentCore stack. Diagnostic metrics remain available
  // for investigations without a paid alarm for every latency or error category.
  for (const alarm of [apiServerErrorAlarm, workerJobFailureAlarm, deadLetterAlarm  ]) {
    alarm.addAlarmAction(new SnsAction(alarmTopic));
    alarm.addOkAction(new SnsAction(alarmTopic));
  }

  const dashboard = new Dashboard(stack, 'ServiceDashboard', {
    dashboardName: `${stack.stackName}-health`,
    start: '-PT8H',
    periodOverride: PeriodOverride.INHERIT,
  });
  // Stay within ten built-in metrics per dashboard. Custom error filters are
  // evaluated by the alarms above rather than duplicated on the dashboard.
  dashboard.addWidgets(
    new TextWidget({ width: 24, height: 1, markdown: '# HeyTim service health' }),
    new AlarmStatusWidget({
      width: 24,
      height: 4,
      title: 'Failed work',
      alarms: [apiServerErrorAlarm, workerJobFailureAlarm, deadLetterAlarm],
    }),
    new GraphWidget({
      width: 12,
      title: 'Requests and errors',
      left: [apiFunction.metricInvocations(), publicApiFunction.metricInvocations(), workerFunction.metricInvocations()],
      right: [apiFunction.metricErrors(), publicApiFunction.metricErrors(), workerFunction.metricErrors()],
    }),
    new GraphWidget({
      width: 12,
      title: 'Job queue',
      left: [jobs.metricApproximateNumberOfMessagesVisible(), jobs.metricApproximateAgeOfOldestMessage()],
      right: [deadLetterQueue.metricApproximateNumberOfMessagesVisible(), workerFunction.metric('ConcurrentExecutions')],
    }),
  );

  return { alarmTopic, monthlyBudgetName };
}
