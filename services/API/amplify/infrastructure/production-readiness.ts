import { Duration, RemovalPolicy, type Stack } from 'aws-cdk-lib';
import { Rule, Schedule } from 'aws-cdk-lib/aws-events';
import { LambdaFunction as LambdaTarget } from 'aws-cdk-lib/aws-events-targets';
import type { Key } from 'aws-cdk-lib/aws-kms';
import { Code, Function as LambdaFunction, Runtime, Tracing } from 'aws-cdk-lib/aws-lambda';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';

type AvailabilityProbeResources = {
  stack: Stack;
  apiEndpoint: string;
  logsKey: Key;
  enabled: boolean;
};

export function addPublicAvailabilityProbe({
  stack,
  apiEndpoint,
  logsKey,
  enabled,
}: AvailabilityProbeResources): LambdaFunction | undefined {
  if (!enabled) return undefined;
  const logGroup = new LogGroup(stack, 'PublicAvailabilityProbeLogs', {
    encryptionKey: logsKey,
    retention: RetentionDays.ONE_MONTH,
    removalPolicy: RemovalPolicy.RETAIN,
  });
  const probe = new LambdaFunction(stack, 'PublicAvailabilityProbe', {
    runtime: Runtime.PYTHON_3_14,
    handler: 'index.handler',
    code: Code.fromInline(`
import os
from urllib.request import Request, urlopen

def handler(_event, _context):
    request = Request(os.environ["PROBE_URL"], headers={"User-Agent": "HeyTimAvailabilityProbe/1"})
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected public catalog status: {response.status}")
    return {"statusCode": 200}
`),
    environment: { PROBE_URL: `${apiEndpoint}/public/catalog` },
    logGroup,
    memorySize: 128,
    timeout: Duration.seconds(15),
    tracing: Tracing.ACTIVE,
  });
  const schedule = new Rule(stack, 'PublicAvailabilitySchedule', {
    schedule: Schedule.rate(Duration.minutes(5)),
  });
  schedule.addTarget(new LambdaTarget(probe, { retryAttempts: 0 }));
  return probe;
}
