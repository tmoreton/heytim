import { App } from 'aws-cdk-lib';
import { MemoryCaptureStack, SOURCE_ACCOUNT, SOURCE_REGION } from '../lib/memory-capture-stack';

const app = new App();
const captureEnabled = app.node.tryGetContext('captureEnabled');
if (captureEnabled !== undefined && !['true', 'false', true, false].includes(captureEnabled)) {
  throw new Error('captureEnabled must be true or false');
}
const memoryRoleArn = app.node.tryGetContext('memoryRoleArn');
if (typeof memoryRoleArn !== 'string') {
  throw new Error('Pass the existing source Memory execution role with -c memoryRoleArn=<arn>');
}

new MemoryCaptureStack(app, 'HeyTimMemoryCapture', {
  env: { account: SOURCE_ACCOUNT, region: SOURCE_REGION },
  memoryRoleArn,
  captureEnabled: captureEnabled === true || captureEnabled === 'true',
  terminationProtection: true,
});
