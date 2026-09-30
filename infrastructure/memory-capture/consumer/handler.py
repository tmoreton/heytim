"""Archive exact AgentCore Memory Kinesis payloads before Lambda checkpoints them.

No payload or identifier from a customer memory record is written to logs.
"""

import base64
import hashlib
import json
import os
import re

import boto3
from botocore.exceptions import ClientError


SHARD_ID = re.compile(r"^shardId-\d{12}$")
RECORD_TYPES = {"MemoryRecordCreated", "MemoryRecordUpdated", "MemoryRecordDeleted"}


def archive_key(stream_arn, shard_id, sequence_number):
    value = f"{stream_arn}:{shard_id}:{sequence_number}".encode("utf-8")
    return f"records/{hashlib.sha256(value).hexdigest()}.json"


def validate_record(record, account, region, memory_id, stream_arn):
    if record.get("eventSourceARN") != stream_arn or record.get("awsRegion") != region:
        raise ValueError("Wrong Kinesis source")
    event_id = record.get("eventID", "")
    shard_id, separator, sequence = event_id.partition(":")
    envelope = record.get("kinesis", {})
    if not separator or not SHARD_ID.fullmatch(shard_id) or sequence != envelope.get("sequenceNumber"):
        raise ValueError("Invalid Kinesis identity")
    encoded = envelope.get("data")
    if not isinstance(encoded, str):
        raise ValueError("Missing Kinesis data")
    try:
        raw = base64.b64decode(encoded, validate=True)
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError, TypeError) as error:
        raise ValueError("Invalid Kinesis payload") from error
    if not isinstance(body, dict) or not isinstance(body.get("memoryStreamEvent"), dict):
        raise ValueError("Invalid Memory stream envelope")
    event = body["memoryStreamEvent"]
    if event.get("memoryId") != memory_id:
        raise ValueError("Wrong Memory identity")
    event_type = event.get("eventType")
    if event_type in RECORD_TYPES:
        if not isinstance(event.get("memoryRecordId"), str) or not event["memoryRecordId"]:
            raise ValueError("Missing record identity")
        if event_type != "MemoryRecordDeleted" and not isinstance(event.get("memoryRecordText"), str):
            raise ValueError("FULL_CONTENT payload missing")
    elif event_type != "StreamingEnabled":
        raise ValueError("Unknown Memory event type")
    return archive_key(stream_arn, shard_id, sequence), raw


def archive_record(s3, bucket, account, key, raw):
    digest = hashlib.sha256(raw).hexdigest()
    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=raw,
            ContentType="application/json",
            ChecksumSHA256=base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii"),
            Metadata={"sha256": digest},
            IfNoneMatch="*",
            ExpectedBucketOwner=account,
        )
        return
    except ClientError as error:
        if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
            raise
    existing = s3.get_object(Bucket=bucket, Key=key, ExpectedBucketOwner=account)
    try:
        if existing["Body"].read() != raw:
            raise ValueError("Conflicting archived Kinesis identity")
    finally:
        existing["Body"].close()


def lambda_handler(event, context):
    account = os.environ["SOURCE_ACCOUNT"]
    region = os.environ["SOURCE_REGION"]
    memory_id = os.environ["SOURCE_MEMORY_ID"]
    stream_arn = os.environ["SOURCE_STREAM_ARN"]
    bucket = os.environ["ARCHIVE_BUCKET"]
    if not context.invoked_function_arn.startswith(f"arn:aws:lambda:{region}:{account}:function:"):
        raise ValueError("Wrong Lambda account")
    if stream_arn != f"arn:aws:kinesis:{region}:{account}:stream/heytim-memory-record-capture":
        raise ValueError("Wrong configured Kinesis stream")
    records = event.get("Records")
    if not isinstance(records, list) or not records:
        raise ValueError("No Kinesis records")
    s3 = boto3.client("s3", region_name=region)
    for record in records:
        key, raw = validate_record(record, account, region, memory_id, stream_arn)
        archive_record(s3, bucket, account, key, raw)
    return {"archived": len(records)}
