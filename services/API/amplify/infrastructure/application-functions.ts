import { Duration, Stack } from 'aws-cdk-lib';
import {
  Function as LambdaFunction,
  RecursiveLoop,
  Runtime,
  Tracing,
} from 'aws-cdk-lib/aws-lambda';
import { LogGroup } from 'aws-cdk-lib/aws-logs';

import { applicationPythonCode } from './python-code';

type ApplicationFunctionsProps = {
  stack: Stack;
  environment: Record<string, string>;
  workerEnvironment: Record<string, string>;
  apiLogGroup: LogGroup;
  publicApiLogGroup: LogGroup;
  workerLogGroup: LogGroup;
  workerConcurrency: number;
};

export function createApplicationFunctions({
  stack,
  environment,
  workerEnvironment,
  apiLogGroup,
  publicApiLogGroup,
  workerLogGroup,
  workerConcurrency,
}: ApplicationFunctionsProps): {
  apiFunction: LambdaFunction;
  publicApiFunction: LambdaFunction;
  workerFunction: LambdaFunction;
} {
  const defaults = {
    runtime: Runtime.PYTHON_3_14,
    memorySize: 512,
    tracing: Tracing.ACTIVE,
  };
  const apiFunction = new LambdaFunction(stack, 'ApiFunction', {
    ...defaults,
    handler: 'api.handler.handler',
    code: applicationPythonCode(),
    logGroup: apiLogGroup,
    timeout: Duration.seconds(29),
    environment,
  });
  const publicApiFunction = new LambdaFunction(stack, 'PublicApiFunction', {
    ...defaults,
    handler: 'api.public_handler.handler',
    code: applicationPythonCode(),
    logGroup: publicApiLogGroup,
    timeout: Duration.seconds(29),
    environment,
  });
  const workerFunction = new LambdaFunction(stack, 'WorkerFunction', {
    ...defaults,
    handler: 'worker.handler.handler',
    code: applicationPythonCode(),
    logGroup: workerLogGroup,
    timeout: Duration.minutes(14),
    // Runtime jobs can return bounded watchdog messages to the same queue.
    // Application deadlines and reserved concurrency remain the guardrails.
    recursiveLoop: RecursiveLoop.ALLOW,
    reservedConcurrentExecutions: workerConcurrency,
    environment: { ...environment, ...workerEnvironment },
  });
  return { apiFunction, publicApiFunction, workerFunction };
}
