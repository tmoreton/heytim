import { App, assertions } from 'aws-cdk-lib';
import { MemoryCaptureStack, SOURCE_ACCOUNT, SOURCE_REGION } from '../lib/memory-capture-stack';

const ROLE_ARN = `arn:aws:iam::${SOURCE_ACCOUNT}:role/ExistingMemoryRole`;

function template() {
  const app = new App();
  const stack = new MemoryCaptureStack(app, 'HeyTimMemoryCapture', {
    env: { account: SOURCE_ACCOUNT, region: SOURCE_REGION },
    memoryRoleArn: ROLE_ARN,
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
  const stack = template();
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
