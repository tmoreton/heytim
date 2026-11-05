import assert from 'node:assert/strict';
import test from 'node:test';
import { App, Stack } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { Policy, PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import { Key } from 'aws-cdk-lib/aws-kms';
import { Bucket, BucketEncryption } from 'aws-cdk-lib/aws-s3';
import { consolidateFileEncryption } from '../amplify/infrastructure/file-encryption.ts';

const retained = 'arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111';

test('consolidated file encryption preserves buckets and restricts replacement grants to S3 file contexts', () => {
  const stack = new Stack(new App(), 'Files', { env: { account: '123456789012', region: 'us-east-1' } });
  const key = new Key(stack, 'DataKey');
  const alias = 'alias/heytim-production-user-files';
  key.addAlias(alias);
  const bucket = new Bucket(stack, 'Files', { bucketName: 'heytim-production-user-files-123456789012-us-east-1', encryption: BucketEncryption.KMS, encryptionKey: key, versioned: true });
  const role = new Role(stack, 'Reader', { assumedBy: new ServicePrincipal('lambda.amazonaws.com') });
  bucket.grantReadWrite(role);
  role.addToPolicy(new PolicyStatement({ actions: ['kms:Decrypt'], resources: ['*'], conditions: { 'ForAnyValue:StringEquals': { 'kms:ResourceAliases': alias } } }));
  const unrelated = 'arn:aws:kms:us-east-1:123456789012:key/22222222-2222-2222-2222-222222222222';
  const mixed = new Policy(stack, 'Mixed', { statements: [new PolicyStatement({ actions: ['kms:Decrypt'], resources: [key.keyArn, unrelated] })] });
  mixed.attachToRole(role);
  consolidateFileEncryption(stack, key, retained, [bucket], alias);
  const template = Template.fromStack(stack).toJSON();
  const resources = Object.values(template.Resources);
  for (const resource of resources.filter(r => ['AWS::KMS::Key', 'AWS::KMS::Alias'].includes(r.Type))) {
    assert.equal(resource.Condition, 'DedicatedFileKeyDisabled');
  }
  assert.deepEqual(template.Conditions.DedicatedFileKeyDisabled, { 'Fn::Equals': ['existing-memory-key', 'dedicated-file-key'] });
  const stored = resources.find(r => r.Type === 'AWS::S3::Bucket').Properties;
  assert.equal(stored.BucketName, 'heytim-production-user-files-123456789012-us-east-1');
  assert.equal(stored.VersioningConfiguration.Status, 'Enabled');
  assert.equal(stored.BucketEncryption.ServerSideEncryptionConfiguration[0].ServerSideEncryptionByDefault.KMSMasterKeyID, retained);
  const statements = resources.filter(r => r.Type === 'AWS::IAM::Policy').flatMap(r => r.Properties.PolicyDocument.Statement);
  const replacements = statements.filter(s => s.Resource === retained);
  assert.equal(replacements.length, 3);
  for (const statement of replacements) {
    assert.equal(statement.Condition.StringEquals['kms:ViaService'], 's3.us-east-1.amazonaws.com');
    assert.equal(statement.Condition.ArnLike['kms:EncryptionContext:aws:s3:arn'].length, 2);
    assert.equal(statement.Condition['ForAnyValue:StringEquals'], undefined);
  }
  assert.ok(statements.some(s => [s.Resource].flat().includes(unrelated) && !s.Condition));
});

test('a mixed non-KMS grant referencing the retired key requires review', () => {
  const stack = new Stack(new App(), 'Unsafe', { env: { account: '123456789012', region: 'us-east-1' } });
  const key = new Key(stack, 'DataKey');
  const role = new Role(stack, 'Reader', { assumedBy: new ServicePrincipal('lambda.amazonaws.com') });
  role.addToPolicy(new PolicyStatement({ actions: ['kms:Decrypt', 's3:GetObject'], resources: [key.keyArn] }));
  assert.throws(() => consolidateFileEncryption(stack, key, retained, [], 'alias/heytim-production-user-files'), /Review the policy/);
});
