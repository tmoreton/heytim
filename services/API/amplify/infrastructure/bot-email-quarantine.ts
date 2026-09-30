import { CfnOutput, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { BlockPublicAccess, Bucket, BucketEncryption } from 'aws-cdk-lib/aws-s3';

/** Raw MIME spool used only when the receipt rule is in store-only mode. */
export function addBotEmailQuarantine(stack: Stack): Bucket {
  const bucket = new Bucket(stack, 'BotEmailQuarantine', {
    blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
    encryption: BucketEncryption.S3_MANAGED,
    enforceSSL: true,
    lifecycleRules: [{ expiration: Duration.days(14) }],
    removalPolicy: RemovalPolicy.RETAIN,
  });
  new CfnOutput(stack, 'BotEmailQuarantineBucketName', { value: bucket.bucketName });
  return bucket;
}
