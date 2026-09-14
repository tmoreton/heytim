import { ArnFormat, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import type { Key } from 'aws-cdk-lib/aws-kms';
import { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';

type NativePushApplicationArns = {
  production: string;
  sandbox: string;
};

export function resolveNativePushApplicationArns(
  stack: Stack,
  applicationArn: string,
  sandboxApplicationArn: string,
): NativePushApplicationArns {
  const namedApplicationArn = (platform: 'APNS' | 'APNS_SANDBOX') => stack.formatArn({
    service: 'sns',
    resource: `app/${platform}`,
    resourceName: 'FroggyBot',
    arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
  });
  return {
    production: applicationArn || namedApplicationArn('APNS'),
    sandbox: sandboxApplicationArn || namedApplicationArn('APNS_SANDBOX'),
  };
}

export function nativePushEnvironment(
  applicationArn: string,
  sandboxApplicationArn: string,
): Record<string, string> {
  return {
    APNS_PLATFORM_APPLICATION_ARN: applicationArn,
    APNS_SANDBOX_PLATFORM_APPLICATION_ARN: sandboxApplicationArn,
  };
}

export function addNativePushAccess(
  apiFunction: LambdaFunction,
  workerFunction: LambdaFunction,
  applicationArns: string[],
): void {
  const applications = applicationArns.filter(Boolean);
  if (!applications.length) return;
  const endpoints = applications.map((arn) => `${arn.replace(':app/', ':endpoint/')}/*`);
  // SNS mobile endpoint-management actions do not support resource-level permissions.
  // AWS therefore requires "*" even when a call receives an application or endpoint ARN.
  apiFunction.addToRolePolicy(new PolicyStatement({
    actions: [
      'sns:CreatePlatformEndpoint',
      'sns:DeleteEndpoint',
      'sns:SetEndpointAttributes',
    ],
    resources: ['*'],
  }));
  workerFunction.addToRolePolicy(new PolicyStatement({
    actions: ['sns:DeleteEndpoint'],
    resources: ['*'],
  }));
  workerFunction.addToRolePolicy(new PolicyStatement({
    actions: ['sns:Publish'],
    resources: endpoints,
  }));
}

export function addNativePushFeedbackRole(
  stack: Stack,
  applicationArns: string[],
  logsKey: Key,
): Role | undefined {
  const applications = applicationArns.filter(Boolean);
  if (applications.length === 0) return undefined;
  const applicationNames = [...new Set(applications.map(arn => arn.split('/').at(-1) ?? 'FroggyBot'))];
  for (const [index, applicationName] of applicationNames.entries()) {
    for (const status of ['Success', 'Failure'] as const) {
      new LogGroup(stack, `NativePush${index}${status}Logs`, {
        logGroupName: `/aws/sns/${stack.region}/${stack.account}/${applicationName}/${status}`,
        encryptionKey: logsKey,
        retention: RetentionDays.ONE_MONTH,
        removalPolicy: RemovalPolicy.RETAIN,
      });
    }
  }
  const role = new Role(stack, 'NativePushFeedbackRole', {
    description: 'Lets Amazon SNS publish APNs delivery status to target-scoped CloudWatch Logs.',
    assumedBy: new ServicePrincipal('sns.amazonaws.com', {
      conditions: {
        StringEquals: { 'aws:SourceAccount': stack.account },
        ArnLike: { 'aws:SourceArn': applications },
      },
    }),
  });
  role.addToPolicy(new PolicyStatement({
    actions: ['logs:CreateLogGroup'],
    resources: [stack.formatArn({
      service: 'logs',
      resource: 'log-group',
      resourceName: '/aws/sns/*',
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    })],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: [
      'logs:CreateLogStream',
      'logs:PutLogEvents',
      'logs:PutMetricFilter',
      'logs:PutRetentionPolicy',
    ],
    resources: [stack.formatArn({
      service: 'logs',
      resource: 'log-group',
      resourceName: '/aws/sns/*:*',
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    })],
  }));
  return role;
}
