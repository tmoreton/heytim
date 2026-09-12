import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';

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
  apiFunction.addToRolePolicy(new PolicyStatement({
    actions: ['sns:CreatePlatformEndpoint'],
    resources: applications,
  }));
  apiFunction.addToRolePolicy(new PolicyStatement({
    actions: ['sns:DeleteEndpoint', 'sns:GetEndpointAttributes', 'sns:SetEndpointAttributes'],
    resources: endpoints,
  }));
  workerFunction.addToRolePolicy(new PolicyStatement({
    actions: ['sns:DeleteEndpoint', 'sns:Publish'],
    resources: endpoints,
  }));
}
