import { CfnCondition, Fn, Stack } from 'aws-cdk-lib';
import { CfnManagedPolicy, CfnPolicy } from 'aws-cdk-lib/aws-iam';
import { CfnAlias, CfnKey, Key } from 'aws-cdk-lib/aws-kms';
import { Bucket, CfnBucket } from 'aws-cdk-lib/aws-s3';

/** Keep file access separate from memory access while reusing its existing key. */
export function consolidateFileEncryption(stack: Stack, dedicated: Key, retainedKeyArn: string, buckets: Bucket[], fileAlias: string): void {
  if (!/^arn:[^:]+:kms:[^:]+:\d{12}:key\/[a-zA-Z0-9-]+$/.test(retainedKeyArn)) {
    throw new Error('An existing memory encryption key ARN is required for file storage.');
  }
  const key = dedicated.node.defaultChild as CfnKey;
  const oldResource = JSON.stringify(stack.resolve(dedicated.keyArn));
  const disabled = new CfnCondition(stack, 'DedicatedFileKeyDisabled', {
    expression: Fn.conditionEquals('existing-memory-key', 'dedicated-file-key'),
  });
  key.cfnOptions.condition = disabled;
  for (const node of dedicated.node.findAll()) {
    if (node instanceof CfnAlias) node.cfnOptions.condition = disabled;
  }
  for (const bucket of buckets) {
    const resource = bucket.node.defaultChild as CfnBucket;
    resource.bucketEncryption = {
      serverSideEncryptionConfiguration: [{
        bucketKeyEnabled: true,
        serverSideEncryptionByDefault: { sseAlgorithm: 'aws:kms', kmsMasterKeyId: retainedKeyArn },
      }],
    };
  }
  const contexts = buckets.flatMap(bucket => [bucket.bucketArn, bucket.arnForObjects('*')]);
  for (const node of stack.node.findAll()) {
    if (!(node instanceof CfnPolicy || node instanceof CfnManagedPolicy)) continue;
    const document = stack.resolve(node.policyDocument);
    const statements = document.Statement;
    if (!Array.isArray(statements)) continue;
    document.Statement = statements.flatMap((entry: Record<string, any>) => {
      const resources = Array.isArray(entry.Resource) ? entry.Resource : [entry.Resource];
      const oldKey = resources.filter(resource => JSON.stringify(resource) === oldResource);
      const aliasCondition = entry.Condition?.['ForAnyValue:StringEquals'];
      const usesFileAlias = aliasCondition?.['kms:ResourceAliases'] === fileAlias;
      if (!oldKey.length && !usesFileAlias) return [entry];
      const actions = Array.isArray(entry.Action) ? entry.Action : [entry.Action];
      if (entry.Effect !== 'Allow' || !actions.every(action => typeof action === 'string' && action.startsWith('kms:'))) {
        throw new Error('Review the policy referencing the dedicated file key.');
      }
      if (usesFileAlias && Object.keys(aliasCondition).length !== 1) {
        throw new Error('Review the combined file key alias condition.');
      }
      const remaining = usesFileAlias ? [] : resources.filter(resource => JSON.stringify(resource) !== oldResource);
      const conditions = { ...entry.Condition };
      if (usesFileAlias) delete conditions['ForAnyValue:StringEquals'];
      const scoped = {
        ...entry,
        Resource: retainedKeyArn,
        Condition: {
          ...conditions,
          StringEquals: { ...conditions.StringEquals, 'kms:ViaService': `s3.${stack.region}.amazonaws.com` },
          ArnLike: { ...conditions.ArnLike, 'kms:EncryptionContext:aws:s3:arn': contexts },
        },
      };
      return [...(remaining.length ? [{ ...entry, Resource: remaining }] : []), scoped];
    });
    node.policyDocument = document;
  }
}
