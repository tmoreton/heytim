import * as path from 'node:path';
import { existsSync } from 'node:fs';
import {
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  aws_cloudwatch as cloudwatch,
  aws_iam as iam,
  aws_kinesis as kinesis,
  aws_kms as kms,
  aws_lambda as lambda,
  aws_logs as logs,
  aws_s3 as s3,
} from 'aws-cdk-lib';
import { Construct } from 'constructs';

export const SOURCE_ACCOUNT = '188757775631';
export const SOURCE_REGION = 'us-east-1';
export const SOURCE_MEMORY_ID = 'HeyTimProduction_HeyTimMemory-xeQPMmBQGC';
export const SOURCE_MEMORY_ARN =
  `arn:aws:bedrock-agentcore:${SOURCE_REGION}:${SOURCE_ACCOUNT}:memory/${SOURCE_MEMORY_ID}`;

export interface MemoryCaptureStackProps extends StackProps {
  readonly memoryRoleArn: string;
  readonly captureEnabled?: boolean;
}

export class MemoryCaptureStack extends Stack {
  constructor(scope: Construct, id: string, props: MemoryCaptureStackProps) {
    super(scope, id, props);
    if (this.account !== SOURCE_ACCOUNT || this.region !== SOURCE_REGION) {
      throw new Error('Memory capture may only be synthesized for the exact source account and region');
    }
    if (!props.memoryRoleArn.startsWith(`arn:aws:iam::${SOURCE_ACCOUNT}:role/`)) {
      throw new Error('Memory execution role must belong to the exact source account');
    }

    const streamKey = new kms.Key(this, 'CaptureStreamKey', {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const archiveKey = new kms.Key(this, 'CaptureArchiveKey', {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const archive = new s3.Bucket(this, 'CaptureArchive', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      bucketKeyEnabled: true,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: archiveKey,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      versioned: true,
      objectLockEnabled: true,
      objectLockDefaultRetention: s3.ObjectLockRetention.governance(Duration.days(30)),
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const logGroup = new logs.LogGroup(this, 'CaptureConsumerLogs', {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    new CfnOutput(this, 'StreamKeyArn', { value: streamKey.keyArn });
    new CfnOutput(this, 'ArchiveBucketName', { value: archive.bucketName });
    new CfnOutput(this, 'ArchiveKeyArn', { value: archiveKey.keyArn });
    new CfnOutput(this, 'MemoryRoleArn', { value: props.memoryRoleArn });

    // The fresh account launch did not use migration capture. Keep retained data
    // and keys, but require an explicit opt-in before recreating billable capture.
    if (!props.captureEnabled) return;

    const stream = new kinesis.Stream(this, 'MemoryRecordStream', {
      streamName: 'heytim-memory-record-capture',
      streamMode: kinesis.StreamMode.ON_DEMAND,
      retentionPeriod: Duration.days(7),
      encryption: kinesis.StreamEncryption.KMS,
      encryptionKey: streamKey,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // Keep the existing Memory execution role: replacing it would interrupt
    // built-in strategy processing. This stack adds only stream permissions.
    const memoryRole = iam.Role.fromRoleArn(
      this,
      'ExistingMemoryExecutionRole',
      props.memoryRoleArn,
      { mutable: true },
    );
    memoryRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['kinesis:PutRecords', 'kinesis:DescribeStream'],
      resources: [stream.streamArn],
    }));
    streamKey.grant(memoryRole, 'kms:GenerateDataKey');

    const sourceConsumer = path.join(__dirname, '..', 'consumer');
    const consumerPath = existsSync(sourceConsumer) ? sourceConsumer : path.join(__dirname, '..', '..', 'consumer');
    const consumer = new lambda.Function(this, 'CaptureConsumer', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset(consumerPath, { exclude: ['test_*.py', '__pycache__/**'] }),
      timeout: Duration.seconds(30),
      memorySize: 256,
      logGroup,
      environment: {
        SOURCE_ACCOUNT,
        SOURCE_REGION,
        SOURCE_MEMORY_ID,
        SOURCE_STREAM_ARN: stream.streamArn,
        ARCHIVE_BUCKET: archive.bucketName,
      },
    });
    stream.grantRead(consumer);
    consumer.addToRolePolicy(new iam.PolicyStatement({
      actions: ['s3:PutObject', 's3:GetObject'],
      resources: [archive.arnForObjects('records/*')],
    }));
    archiveKey.grantEncryptDecrypt(consumer);

    new lambda.EventSourceMapping(this, 'CaptureStreamMapping', {
      target: consumer,
      eventSourceArn: stream.streamArn,
      startingPosition: lambda.StartingPosition.TRIM_HORIZON,
      batchSize: 1,
      maxBatchingWindow: Duration.seconds(0),
      parallelizationFactor: 1,
      // Omitted retry and age limits mean retry until Kinesis retention expires.
      // The alarms below must be acted on well before the seven-day boundary.
    });

    const memoryMetric = (name: string) => new cloudwatch.Metric({
      namespace: 'AWS/Bedrock-AgentCore',
      metricName: name,
      dimensionsMap: { Operation: 'MemoryStreamEvent', Resource: SOURCE_MEMORY_ARN },
      statistic: 'Sum',
      period: Duration.minutes(5),
    });
    for (const [name, metric] of [
      ['MemoryPublishFailures', memoryMetric('StreamPublishingFailure')],
      ['MemoryStreamUserErrors', memoryMetric('StreamUserError')],
      ['CaptureConsumerErrors', consumer.metricErrors({ period: Duration.minutes(5), statistic: 'Sum' })],
    ] as const) {
      new cloudwatch.Alarm(this, name, {
        metric,
        threshold: 1,
        evaluationPeriods: 1,
        treatMissingData: cloudwatch.TreatMissingData.MISSING,
      });
    }
    new cloudwatch.Alarm(this, 'CaptureIteratorLag', {
      metric: new cloudwatch.Metric({
        namespace: 'AWS/Lambda',
        metricName: 'IteratorAge',
        dimensionsMap: { FunctionName: consumer.functionName },
        statistic: 'Maximum',
        period: Duration.minutes(5),
      }),
      threshold: 600_000,
      evaluationPeriods: 1,
      treatMissingData: cloudwatch.TreatMissingData.MISSING,
    });

    new CfnOutput(this, 'StreamArn', { value: stream.streamArn });
    new CfnOutput(this, 'ConsumerFunctionArn', { value: consumer.functionArn });
  }
}
