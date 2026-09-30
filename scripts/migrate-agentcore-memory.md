# AgentCore Memory migration utility

`migrate-agentcore-memory.py` copies the approved short-term events and long-term
facts, preferences, and summaries between two AgentCore Memory resources. It does
not write to the source account. It keeps payloads in process memory and never
prints or saves their text. The destination must be empty on the first apply.

Use `services/runtime/.venv/bin/python` so boto3 includes the current AgentCore
API model. The command verifies both AWS profiles with STS, checks memory ARNs,
status, strategy names, types, and namespace templates, and validates all source
payloads against the destination SDK model before writing.

## 1. Read-only inventory

```sh
services/runtime/.venv/bin/python scripts/migrate-agentcore-memory.py \
  --source-profile frogbot-release \
  --source-account 188757775631 \
  --source-memory-id HeyTimProduction_HeyTimMemory-xeQPMmBQGC \
  --destination-profile frogbot-production-org \
  --destination-account 820323452649 \
  --destination-memory-id HeyTim_HeyTimMemory-6ltsOWEt5B
```

Record the `source.snapshotSha256` value. A fresh read-only 2026-09-30 source
inventory had 4 actors, 16 sessions, 192 events, and 417 records; the destination
had zero. The source remains live, so these counts can change.
Rerun immediately before apply after the write freeze. If the digest changes,
stop and investigate before moving traffic.

The source Memory was created 2026-09-25 01:37:26 UTC with 30-day event expiry.
CloudTrail Event History showed its exact successful creation request and no
`UpdateMemory` at the time of the 2026-09-30 audit. Because expiry is applied at write
time and the resource did not exist earlier, 2026-10-25 01:37:26 UTC is the
earliest possible raw-event expiry under that observed history. Recheck the
history and margin before apply. Do not infer expiry from `eventTimestamp`:
some source events were backdated before the resource existed. This retention
proof does not establish that built-in long-term extraction has settled; use
the [source freeze runbook](../docs/source-write-freeze-runbook.md) for that gate.

## 2. Generate an exhaustive identifier map

Run the read-only generator, using the source table name from the current
`services/API/amplify_outputs.json`. It matches one unique verified email in
both Cognito pools, scans only source DynamoDB keys, and derives IDs in process
memory. It writes a `0600` file outside Git containing hashed identifiers only.
It never writes Cognito subjects, email addresses, event payloads, or record
content to the file or terminal.

```sh
services/runtime/.venv/bin/python scripts/migrate-agentcore-memory.py \
  --source-profile frogbot-release \
  --source-account 188757775631 \
  --source-memory-id HeyTimProduction_HeyTimMemory-xeQPMmBQGC \
  --destination-profile frogbot-production-org \
  --destination-account 820323452649 \
  --destination-memory-id HeyTim_HeyTimMemory-6ltsOWEt5B \
  --source-user-pool-id us-east-1_N22obdhLi \
  --destination-user-pool-id us-east-1_biJejrNQF \
  --source-table-name SOURCE_DATA_TABLE_FROM_OUTPUTS \
  --expect-orphan-actors 1 \
  --expect-historical-sessions 2 \
  --generate-identity-map /private/path/map.json
```

The generated file has this shape:

```json
{
  "actors": {
    "source-actor-hash": "destination-actor-hash"
  },
  "sessions": {
    "source-actor-hash": {
      "source-session-hash": "destination-session-hash"
    }
  },
  "decisions": {
    "orphanPreservedUnmapped": [],
    "historicalSessionsPreservedUnmapped": []
  }
}
```

The app derives personal IDs as `SHA256("user:" + sub)` and
`SHA256(sub + ":" + botId)`. Group actor/session IDs derive from the unchanged
group ID and map to themselves. The generator cross-checks all actors and
sessions in the source memory inventory; an unknown or missing ID stops it.
The approved September 29 snapshot has one personal actor that no longer
matches a current Cognito user or DynamoDB key. It has exactly one session,
one event, and one summary. The generator preserves that actor and session
under their original IDs and records the decision in the private map. Two
historical sessions of the current user no longer match a bot key; it keeps
their session IDs under the mapped new personal actor and records their exact
event and summary counts. The command flags bound these exceptions and fail if
the snapshot shape or count changes.

Run the read-only command again with `--identity-map /private/path/map.json`,
`--expect-orphan-actors 1`, and `--expect-historical-sessions 2` to validate
coverage and namespace transformations. Store this file outside Git.

## 3. Apply inside the write freeze

Use the digest from step 1. Choose a new manifest path outside Git; the utility
creates it with mode `0600` before the first destination write. The manifest
contains identifier mappings and hashes only. It is checkpointed after every
event and record batch.

```sh
services/runtime/.venv/bin/python scripts/migrate-agentcore-memory.py \
  --source-profile frogbot-release \
  --source-account 188757775631 \
  --source-memory-id HeyTimProduction_HeyTimMemory-xeQPMmBQGC \
  --destination-profile frogbot-production-org \
  --destination-account 820323452649 \
  --destination-memory-id HeyTim_HeyTimMemory-6ltsOWEt5B \
  --identity-map /private/path/map.json \
  --source-user-pool-id us-east-1_N22obdhLi \
  --destination-user-pool-id us-east-1_biJejrNQF \
  --source-table-name SOURCE_DATA_TABLE_FROM_OUTPUTS \
  --expect-orphan-actors 1 \
  --expect-historical-sessions 2 \
  --expect-source-digest SOURCE_SHA256_FROM_DRY_RUN \
  --manifest /private/path/memory-id-map.json \
  --apply
```

Before either a first apply or a resume, the utility regenerates the identity
map from the live verified Cognito pools and source table keys. It stops if the
private map differs, even when that map is structurally valid and all memory
content checksums would otherwise match.

Events keep their original timestamp, payload, metadata, actor/session mapping,
and branch information. `extractionMode=SKIP` prevents duplicate long-term
extraction. Long-term records keep their content, user-supplied metadata,
namespace, and timestamp, using destination strategy IDs. AgentCore regenerates
its reserved `x-amz-agentcore-memory-*` metadata in the destination; the source
snapshot digest still includes those fields, while content parity ignores them.
Deterministic client tokens protect
retries. The utility verifies destination actor/session counts and canonical
content hashes before reporting `verified`, then inventories the source again to
detect writes during the transfer. A failed or incomplete transfer is a no-go
for the account cutover.

The post-write check also retrieves the orphan actor by its preserved actor and
session IDs, expecting exactly one event and one summary. It retrieves each
historical user session through the mapped personal actor and preserved session
ID, checking their recorded event and summary counts. The full inventory hash
check confirms their content as part of the complete migration.

If an apply is interrupted, rerun the exact command with `--resume`. It checks
the 0600 manifest and matches existing destination objects to the source
snapshot before continuing. It stops if destination data is extra or ambiguous.
Do not delete destination memory or re-run a fresh apply to work around that
stop condition; inspect the manifest and destination state first.

The source memory has a 30-day event expiry. Preserving historical timestamps
does not extend that retention period. Run and verify the migration within the
approved maintenance window.

## 4. Plan late managed-record changes without writing

The verified manifest now stores a SHA-256 baseline for each copied record, keyed
by its source record ID. It contains no record text. If a verified manifest was
created before this field existed, the read-only planner can derive that baseline
only while the destination still matches the manifest's **entire** original
aggregate digest and contains no destination-only records. If that exact match is
gone, the baseline cannot be recovered safely from the aggregate hash: NO-GO.

Run the read-only planner with the same private identity map and verified
manifest. Keep its optional ID-and-hash plan outside Git with mode `0600`:

```sh
services/runtime/.venv/bin/python scripts/plan-agentcore-memory-reconciliation.py \
  --source-profile frogbot-release \
  --destination-profile frogbot-production-org \
  --identity-map /private/path/map.json \
  --manifest /private/path/memory-id-map.json \
  --plan-out /private/path/memory-late-plan.json
```

The planner binds exact source/destination accounts and Memory ARNs, verifies the
strategy map and every mapped raw event, and reads full record sets twice. It
compares each mapped destination record with its initial hash and the current
source state. It reports source creates, updates, and deletions, flags destination
edits or ambiguous unmapped copies, and fails if either Memory changes during
planning. It uses full-state comparison so no order across Kinesis shards is
assumed. Its stdout contains counts only; the private plan contains IDs and
hashes, never customer content. Re-running the same unchanged state verifies
an existing identical private plan; a changed plan requires a new path. It makes
no AWS changes.

**The planner has no apply mode.** AgentCore `BatchUpdateMemoryRecords` and
`BatchDeleteMemoryRecords` have no conditional version or compare-and-swap input.
`BatchCreateMemoryRecords` has a client token, but AWS does not publish a
durability window for that token or a bound for list visibility after an
uncertain response. A destination user edit or managed consolidation can occur
between the pre-write read and update/delete, so a live replay could overwrite
or remove newer destination data. An interrupted create can also be ambiguous
if the record is not yet visible. The current manifest stores per-record hashes
for planning, but cannot solve those service-level atomicity gaps. Consequently
**late-change apply and live traffic cutover remain NO-GO** until an independently
verified destination write fence and a tested write-ahead, resumable apply path
exist, or AWS supplies conditional record writes. Repeated quiet windows or
the stream alone do not remove this constraint.

API references: [update](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_BatchUpdateMemoryRecords.html),
[delete](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_BatchDeleteMemoryRecords.html),
[create](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_BatchCreateMemoryRecords.html).
