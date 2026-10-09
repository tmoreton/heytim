import { App, assertions } from 'aws-cdk-lib';
import { MemoryCaptureStack, SOURCE_ACCOUNT, SOURCE_REGION } from '../lib/memory-capture-stack';

const ROLE_ARN = `arn:aws:iam::${SOURCE_ACCOUNT}:role/ExistingMemoryRole`;

function template(captureEnabled?: boolean) {
  const app = new App();
  const stack = new MemoryCaptureStack(app, 'HeyTimMemoryCapture', {
    env: { account: SOURCE_ACCOUNT, region: SOURCE_REGION },
    memoryRoleArn: ROLE_ARN,
    captureEnabled,
    terminationProtection: true,
  });
  return assertions.Template.fromStack(stack);
}

test('exact-account source role and region are mandatory', () => {
  const app = new App();
  expect(() => new MemoryCaptureStack(app, 'WrongAccount', {
    env: { account: '820323452649', region: SOURCE_REGION }, memoryRoleArn: ROLE_ARN,
  })).toThrow('exact source account');
  expect(() => new MemoryCaptureStack(app, 'WrongRole', {
    env: { account: SOURCE_ACCOUNT, region: SOURCE_REGION },
    memoryRoleArn: 'arn:aws:iam::820323452649:role/wrong',
  })).toThrow('exact source account');
});

test('retained encrypted stream and locked archive are synthesized', () => {
  const stack = template(true);
  stack.hasResourceProperties('AWS::Kinesis::Stream', {
    Name: 'heytim-memory-record-capture', RetentionPeriodHours: 168,
    StreamEncryption: { EncryptionType: 'KMS' },
  });
  stack.hasResourceProperties('AWS::S3::Bucket', {
    VersioningConfiguration: { Status: 'Enabled' },
    ObjectLockEnabled: true,
    ObjectLockConfiguration: { ObjectLockEnabled: 'Enabled' },
  });
  stack.hasResourceProperties('AWS::Lambda::EventSourceMapping', {
    StartingPosition: 'TRIM_HORIZON', BatchSize: 1,
  });
  stack.hasResourceProperties('AWS::IAM::Policy', {
    Roles: ['ExistingMemoryRole'],
  });
});

test('default retirement preserves archive and keys without recreating capture', () => {
  const stack = template();
  for (const type of ['AWS::Kinesis::Stream', 'AWS::Lambda::Function',
    'AWS::Lambda::EventSourceMapping', 'AWS::CloudWatch::Alarm', 'AWS::IAM::Policy']) {
    stack.resourceCountIs(type, 0);
  }
  stack.resourceCountIs('AWS::KMS::Key', 2);
  stack.resourceCountIs('AWS::S3::Bucket', 1);
  stack.resourceCountIs('AWS::Logs::LogGroup', 1);
  for (const type of ['AWS::KMS::Key', 'AWS::S3::Bucket', 'AWS::Logs::LogGroup']) {
    for (const resource of Object.values(stack.findResources(type))) {
      expect(resource.DeletionPolicy).toBe('Retain');
      expect(resource.UpdateReplacePolicy).toBe('Retain');
    }
  }
  expect(stack.toJSON().Outputs.StreamArn).toBeUndefined();
  expect(stack.toJSON().Outputs.ConsumerFunctionArn).toBeUndefined();
});
