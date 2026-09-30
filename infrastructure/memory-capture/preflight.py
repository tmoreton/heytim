"""Read-only, bounded validation of retained Memory capture records.

This checks observable Kinesis-to-S3 parity. It cannot certify that AgentCore
published every managed record update or that future extraction has stopped.
"""

import argparse
import hashlib
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError
from consumer.handler import archive_key

ACCOUNT = "188757775631"
REGION = "us-east-1"
MEMORY_ID = "HeyTimProduction_HeyTimMemory-xeQPMmBQGC"
MEMORY_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:memory/{MEMORY_ID}"
STREAM_ARN = f"arn:aws:kinesis:{REGION}:{ACCOUNT}:stream/heytim-memory-record-capture"
STACK_NAME = "HeyTimMemoryCapture"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_configuration(session):
    identity = session.client("sts").get_caller_identity()
    require(identity["Account"] == ACCOUNT, "Wrong AWS account")
    stack = session.client("cloudformation").describe_stacks(StackName=STACK_NAME)["Stacks"]
    require(len(stack) == 1 and stack[0]["StackStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"},
            "Capture stack is not complete")
    require(stack[0].get("EnableTerminationProtection") is True, "Capture stack lacks termination protection")
    outputs = {entry["OutputKey"]: entry["OutputValue"] for entry in stack[0].get("Outputs", [])}
    require(outputs.get("StreamArn") == STREAM_ARN, "Stack stream identity mismatch")
    bucket = outputs.get("ArchiveBucketName")
    consumer_arn = outputs.get("ConsumerFunctionArn")
    require(isinstance(bucket, str) and bucket, "Missing archive bucket output")
    require(isinstance(consumer_arn, str) and consumer_arn.startswith(f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:"),
            "Wrong consumer account")
    stream_key_arn = outputs.get("StreamKeyArn")
    archive_key_arn = outputs.get("ArchiveKeyArn")
    require(isinstance(stream_key_arn, str) and stream_key_arn.startswith(f"arn:aws:kms:{REGION}:{ACCOUNT}:key/"),
            "Wrong stream KMS key account")
    require(isinstance(archive_key_arn, str) and archive_key_arn.startswith(f"arn:aws:kms:{REGION}:{ACCOUNT}:key/"),
            "Wrong archive KMS key account")

    memory = session.client("bedrock-agentcore-control").get_memory(memoryId=MEMORY_ID, view="full")["memory"]
    require(memory.get("id") == MEMORY_ID and memory.get("arn") == MEMORY_ARN and
            memory.get("status") == "ACTIVE", "Source Memory identity or status mismatch")
    role_arn = memory.get("memoryExecutionRoleArn")
    require(isinstance(role_arn, str) and role_arn.startswith(f"arn:aws:iam::{ACCOUNT}:role/"),
            "Source Memory execution role mismatch")
    require(role_arn == outputs.get("MemoryRoleArn"), "Deployed stream permission role differs from Memory role")
    iam = session.client("iam")
    role_name = role_arn.rsplit("/", 1)[-1]
    role = iam.get_role(RoleName=role_name)["Role"]
    require(role.get("Arn") == role_arn, "Source Memory role not found")
    stream_actions = set()
    kms_actions = set()
    inline = iam.list_role_policies(RoleName=role_name)
    require(not inline.get("IsTruncated"), "Source Memory role policy list was truncated")
    for policy_name in inline.get("PolicyNames", []):
        policy = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)["PolicyDocument"]
        for statement in policy.get("Statement", []):
            if statement.get("Effect") != "Allow":
                continue
            resources = statement.get("Resource", [])
            if isinstance(resources, str):
                resources = [resources]
            granted = statement.get("Action", [])
            if isinstance(granted, str):
                granted = [granted]
            if STREAM_ARN in resources:
                stream_actions.update(granted)
            if stream_key_arn in resources:
                kms_actions.update(granted)
    require({"kinesis:PutRecords", "kinesis:DescribeStream"} <= stream_actions and
            "kms:GenerateDataKey" in kms_actions,
            "Source Memory role lacks capture stream permissions")
    resources = (memory.get("streamDeliveryResources") or {}).get("resources", [])
    require(len(resources) == 1 and resources[0].get("kinesis", {}).get("dataStreamArn") == STREAM_ARN,
            "Memory stream attachment missing or changed")
    config = resources[0]["kinesis"].get("contentConfigurations", [])
    require(config == [{"type": "MEMORY_RECORDS", "level": "FULL_CONTENT"}],
            "Memory stream is not FULL_CONTENT")
    require(memory.get("eventExpiryDuration") == 30, "Source event expiry changed")

    kin = session.client("kinesis")
    summary = kin.describe_stream_summary(StreamARN=STREAM_ARN)["StreamDescriptionSummary"]
    require(summary.get("StreamARN") == STREAM_ARN and summary.get("StreamStatus") == "ACTIVE", "Kinesis not active")
    require(summary.get("EncryptionType") == "KMS" and summary.get("RetentionPeriodHours", 0) >= 168,
            "Kinesis encryption or retention changed")
    require(summary.get("KeyId") == stream_key_arn,
            "Kinesis KMS key identity mismatch")

    s3 = session.client("s3")
    s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
    versioning = s3.get_bucket_versioning(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
    require(versioning.get("Status") == "Enabled", "Archive bucket versioning disabled")
    lock = s3.get_object_lock_configuration(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
    lock_config = lock.get("ObjectLockConfiguration", {})
    require(lock_config.get("ObjectLockEnabled") == "Enabled" and
            lock_config.get("Rule", {}).get("DefaultRetention", {}).get("Mode") == "GOVERNANCE" and
            lock_config.get("Rule", {}).get("DefaultRetention", {}).get("Days", 0) >= 30,
            "Archive object lock disabled")
    public = s3.get_public_access_block(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
    require(all(public.get("PublicAccessBlockConfiguration", {}).get(key) is True for key in
                ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")),
            "Archive public access block changed")
    try:
        lifecycle = s3.get_bucket_lifecycle_configuration(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
        require(not any(rule.get("Status") == "Enabled" for rule in lifecycle.get("Rules", [])),
                "Archive bucket has active lifecycle rules")
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "NoSuchLifecycleConfiguration":
            raise
    encryption = s3.get_bucket_encryption(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
    rules = encryption["ServerSideEncryptionConfiguration"]["Rules"]
    require(any(rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") == "aws:kms" and
                rule.get("ApplyServerSideEncryptionByDefault", {}).get("KMSMasterKeyID") == archive_key_arn
                for rule in rules), "Archive KMS encryption disabled")

    lam = session.client("lambda")
    function = lam.get_function_configuration(FunctionName=consumer_arn)
    env = function.get("Environment", {}).get("Variables", {})
    require(function.get("State") == "Active" and function.get("FunctionArn") == consumer_arn,
            "Consumer Lambda not active")
    require(all(env.get(key) == value for key, value in {
        "SOURCE_ACCOUNT": ACCOUNT, "SOURCE_REGION": REGION, "SOURCE_MEMORY_ID": MEMORY_ID,
        "SOURCE_STREAM_ARN": STREAM_ARN, "ARCHIVE_BUCKET": bucket,
    }.items()), "Consumer configuration mismatch")
    mappings = lam.list_event_source_mappings(EventSourceArn=STREAM_ARN, FunctionName=consumer_arn)
    matching = mappings.get("EventSourceMappings", [])
    require(len(matching) == 1, "Expected one Kinesis consumer mapping")
    mapping = matching[0]
    require(mapping.get("State") == "Enabled" and mapping.get("StartingPosition") == "TRIM_HORIZON" and
            mapping.get("BatchSize") == 1 and mapping.get("ParallelizationFactor", 1) == 1 and
            mapping.get("MaximumRetryAttempts", -1) == -1 and
            mapping.get("MaximumRecordAgeInSeconds", -1) == -1,
            "Consumer checkpoint or retry settings changed")
    require(not mappings.get("NextMarker"), "Additional consumer mappings were not checked")

    cloudwatch = session.client("cloudwatch")
    from datetime import datetime, timedelta, timezone
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    for name in ("StreamPublishingFailure", "StreamUserError"):
        points = cloudwatch.get_metric_statistics(
            Namespace="AWS/Bedrock-AgentCore", MetricName=name,
            Dimensions=[{"Name": "Operation", "Value": "MemoryStreamEvent"},
                        {"Name": "Resource", "Value": MEMORY_ARN}],
            StartTime=start, EndTime=end, Period=300, Statistics=["Sum"],
        )["Datapoints"]
        require(not any(point.get("Sum", 0) > 0 for point in points),
                "Observed AgentCore Memory stream publishing failure")
    return kin, s3, bucket


def verify_retained(kin, s3, bucket, max_records, max_seconds):
    deadline = time.monotonic() + max_seconds
    checked = 0
    enabled = 0
    def all_shards():
        found = []
        token = None
        while True:
            require(time.monotonic() < deadline, "Retained-record scan time limit reached")
            args = {"NextToken": token} if token else {"StreamARN": STREAM_ARN}
            page = kin.list_shards(**args)
            found.extend(page.get("Shards", []))
            token = page.get("NextToken")
            if not token:
                return found

    shards = all_shards()
    require(len(shards) == len({item["ShardId"] for item in shards}), "Duplicate Kinesis shard listing")
    checkpoint = []
    closed_count = 0
    for shard in shards:
        shard_id = shard["ShardId"]
        if shard.get("SequenceNumberRange", {}).get("EndingSequenceNumber"):
            closed_count += 1
        iterator = kin.get_shard_iterator(StreamARN=STREAM_ARN, ShardId=shard_id,
                                           ShardIteratorType="TRIM_HORIZON").get("ShardIterator")
        last_sequence = ""
        shard_records = 0
        while iterator:
            require(time.monotonic() < deadline, "Retained-record scan time limit reached")
            page_records = kin.get_records(ShardIterator=iterator, Limit=1000)
            records = page_records["Records"]
            for record in records:
                checked += 1
                shard_records += 1
                require(checked <= max_records, "Retained-record scan count limit reached")
                raw = record["Data"]
                last_sequence = record["SequenceNumber"]
                key = archive_key(STREAM_ARN, shard_id, last_sequence)
                archived = s3.get_object(Bucket=bucket, Key=key, ExpectedBucketOwner=ACCOUNT)
                try:
                    require(archived["Body"].read() == raw, "Archive mismatch for retained record")
                finally:
                    archived["Body"].close()
                try:
                    payload = json.loads(raw)["memoryStreamEvent"]
                except (ValueError, KeyError, TypeError) as error:
                    raise RuntimeError("Invalid retained Memory stream payload") from error
                require(payload.get("memoryId") == MEMORY_ID, "Wrong Memory record in stream")
                if payload.get("eventType") == "StreamingEnabled":
                    enabled += 1
            iterator = page_records.get("NextShardIterator")
            if not records:
                require(page_records.get("MillisBehindLatest") == 0,
                        "Shard scan has not reached stream tip")
                break
        checkpoint.append((shard_id, last_sequence, shard_records))
    require({item["ShardId"] for item in all_shards()} == {item["ShardId"] for item in shards},
            "Kinesis shards changed during scan; retry")
    require(shards and enabled > 0, "No retained streaming activation evidence")
    digest = hashlib.sha256(json.dumps(checkpoint, separators=(",", ":")).encode()).hexdigest()
    return {"retainedRecordsArchived": checked, "streamingEnabledEvents": enabled,
            "shardsScanned": len(shards), "closedShardsScanned": closed_count,
            "shardCheckpointSha256": digest, "strictNoLossProven": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--max-records", type=int, default=50000)
    parser.add_argument("--max-seconds", type=int, default=300)
    args = parser.parse_args()
    require(args.max_records > 0 and args.max_seconds > 0, "Bounds must be positive")
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    kin, s3, bucket = check_configuration(session)
    result = verify_retained(kin, s3, bucket, args.max_records, args.max_seconds)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - every failure must report NO_GO
        print(json.dumps({"status": "NO_GO", "reason": str(error)}), file=sys.stderr)
        sys.exit(2)
