import { App } from 'aws-cdk-lib';
import { MemoryCaptureStack, SOURCE_ACCOUNT, SOURCE_REGION } from '../lib/memory-capture-stack';

const app = new App();
const memoryRoleArn = app.node.tryGetContext('memoryRoleArn');
if (typeof memoryRoleArn !== 'string') {
  throw new Error('Pass the existing source Memory execution role with -c memoryRoleArn=<arn>');
}

new MemoryCaptureStack(app, 'HeyTimMemoryCapture', {
  env: { account: SOURCE_ACCOUNT, region: SOURCE_REGION },
  memoryRoleArn,
  terminationProtection: true,
});
