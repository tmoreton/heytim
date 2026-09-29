# Transient provider result retention

Large connected-tool responses are temporarily offloaded under a private
`users/.../tool-results/.../result_*` or `groups/.../tool-results/.../result_*`
key. The result reference is scoped to one authorized turn and can survive a
runtime restart. The user-facing chat transcript and any explicitly requested
export are separate records. Exports use `/artifacts/` or workspace keys and
are outside this policy.

## New writes

The prepared runtime change makes `ResultStorage.store` write the object with
the S3 tag `heytim-retention=transient-tool-result`. The prepared bucket change
adds a tag-filtered lifecycle rule in each account: expire the current version
seven days after creation, then permanently expire its noncurrent version one
day after it becomes noncurrent. These changes have not yet been deployed to
AWS. S3 lifecycle runs asynchronously, so these are
eligibility times rather than exact deletion deadlines. The existing general
30-day noncurrent-version rule remains in place for other files. The prepared
runtime role adds `s3:PutObjectTagging` for scoped user and group objects so
tagging is atomic with each versioned `PutObject` request after deployment.

The seven-day window exceeds the current eight-hour maximum background job
lifetime and permits short interruption recovery. A reference from an older
turn may cease to resolve after that window; a retained export or workspace
file remains available. Connected-provider data that was quoted or summarized
in a saved chat, generated file, or memory follows that record's separate
retention and deletion behavior.

## Existing untagged versions

An S3 tag filter does not match old untagged result versions. The lifecycle
deployment alone leaves those versions as they are. Use
`scripts/tag_transient_tool_results.py` only after the live cutover, S3 version
copy and parity verification, and the source-account rollback window. Applying
the tag to an old current version makes it eligible for expiration immediately
if it is already over seven days old. Review that old references are no longer
needed before applying; this is an irreversible retention change after S3
permanently removes versions.

The script reads every version under `users/` and `groups/`, but matches only
the exact `tool-results/.../result_*` shape. It includes noncurrent versions,
preserves unrelated tags, skips saved artifacts and exports, and records delete
marker counts. It requires an explicit AWS profile, account, region, and a
known user-files bucket name. A read-only dry run writes a private mode-0600
manifest. Apply requires the same manifest plus its reviewed `toTag` count;
before any write, it compares the complete live version inventory, metadata,
tags, and delete-marker count with the manifest. It tags individual version
IDs and verifies each tag readback. An interrupted apply can be rerun with the
same manifest if S3 has not changed; already tagged versions are skipped.

From the repository root, prepare one manifest per bucket. The active source
and destination HeyTim buckets are:

```bash
uv run --project services/runtime --frozen python scripts/tag_transient_tool_results.py \
  --profile frogbot-release --account 188757775631 --region us-east-1 \
  --bucket heytim-production-user-files-188757775631-us-east-1 \
  --manifest /private/tmp/heytim-source-tool-results.json

uv run --project services/runtime --frozen python scripts/tag_transient_tool_results.py \
  --profile frogbot-production-org --account 820323452649 --region us-east-1 \
  --bucket heytim-production-user-files-820323452649-us-east-1 \
  --manifest /private/tmp/heytim-production-tool-results.json
```

Inspect each manifest's `versionCount`, `deleteMarkers`, `toTag`, keys, version
IDs, and existing tags. If the migration inventory finds matching result keys
in a retained legacy physical bucket, run a separate dry run for that exact
bucket; do not assume it is empty. The script accepts those existing bucket
names only so historical data can be handled deliberately.

After the rollback window and owner review, apply each manifest separately.
Replace `REVIEWED_INTEGER` with that manifest's integer `toTag` value:

```bash
uv run --project services/runtime --frozen python scripts/tag_transient_tool_results.py \
  --profile frogbot-production-org --account 820323452649 --region us-east-1 \
  --bucket heytim-production-user-files-820323452649-us-east-1 \
  --manifest /private/tmp/heytim-production-tool-results.json \
  --apply --confirm-count REVIEWED_INTEGER
```

Use the source profile, account, bucket, and source manifest for the source
account after its rollback use has ended. The script never copies or deletes
object contents; S3 lifecycle performs the eventual expiration. If the
inventory changes between dry run and apply, generate and review a new
manifest. Do not use a broad prefix lifecycle rule on the shared user-files
bucket.

AWS documents [tag-filtered lifecycle rules](https://docs.aws.amazon.com/AmazonS3/latest/userguide/intro-lifecycle-filters.html)
and [versioned-object expiration](https://docs.aws.amazon.com/AmazonS3/latest/userguide/DeletingObjectVersions.html).
