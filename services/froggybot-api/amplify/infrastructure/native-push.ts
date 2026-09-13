import { ArnFormat, Stack } from 'aws-cdk-lib';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';

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
