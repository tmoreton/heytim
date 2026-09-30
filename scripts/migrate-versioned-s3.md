# Versioned S3 migration utility

`migrate_versioned_s3.py` inventories one explicit source bucket and selected
prefixes, then writes a private dry-run manifest. Only `--apply` writes to the
destination. It never calls a source-side write API. It verifies both AWS
profiles with STS, bucket ownership and versioning, and the destination KMS key.
The CLI stays in `migrate_versioned_s3.py`; inventory and checkpoint rules live
in `_s3_migration_plan.py`, and version transfer and recovery live in
`_s3_migration_transfer.py`.

The destination bucket already contains template assets. Select only reviewed
source prefixes, and keep the user actor map in a private `0600` JSON file
outside this repository:

```json
[
  {
    "sourcePrefix": "users/<old-actor-sha256>/",
    "destinationPrefix": "users/<new-actor-sha256>/"
  }
]
```

The actor hashes must be calculated from the relevant old and new Cognito user
IDs using the application's `memory_actor_id` function. Do not place raw
Cognito IDs, email addresses, or secrets in the map. Every application-visible
`users/` actor must have an explicit remap. Group keys can retain their paths
if their identities are stable.

Example dry run (replace all placeholders with verified values):

```bash
python3 scripts/migrate_versioned_s3.py \
  --source-profile <source-profile> --source-account <source-account> \
  --source-bucket <source-bucket> \
  --destination-profile <destination-profile> \
  --destination-account <destination-account> \
  --destination-bucket <destination-bucket> \
  --destination-kms-key <full-destination-key-arn> \
  --source-user-pool-id <source-pool-id> \
  --destination-user-pool-id <destination-pool-id> \
  --region us-east-1 --prefix users/ --prefix groups/ \
  --key-map-file /private/tmp/heytim-s3-key-map.json \
  --manifest /private/tmp/heytim-s3-migration.json
```

Inspect the manifest's source/destination key mapping and counts, then rerun
the exact command with `--apply` after the source write freeze. For any
application-visible `users/` key, both dry run and apply verify that every
private actor-prefix mapping equals the pair derived from the verified source
and destination Cognito users; a more specific user-prefix override also stops.
Apply requires
that existing dry-run manifest and stops if the source inventory has changed. The manifest
and version map are owner-only files and cannot be written inside this
repository. The version map records each source bucket/key/version ID and its
destination key/version ID for any DynamoDB reference migration. Object bodies
are streamed directly between S3 clients in memory; no body is written to a
local file or printed.

The utility copies metadata, content type, and object tags, and encrypts each
new version with the specified destination KMS key. It computes SHA-256 while
reading each source version, rereads the destination version to compare SHA-256
and size, then compares content settings, metadata, tags, and the destination
KMS key immediately and again in final parity. It also verifies all destination
versions, delete-marker counts, total bytes, and current object states. Source
inventory is checked again at the end.

## Stop conditions and limitations

- One invocation handles **one source bucket**. The legacy, HeyTim, and live
  AgentCore runtime source buckets overlap. Running their full histories into
  the same application-visible keys would produce conflicts; the utility stops
  on a preexisting destination version. Use the four-pass sequence below.
- Object versions and delete markers with the same S3 timestamp on one key
  have ambiguous order and stop planning. Same-type ties use S3's listing
  order. Review ambiguous histories manually; do not guess their order.
- S3 cannot preserve source VersionIds or LastModified timestamps. The version
  map must be used wherever application records refer to a source VersionId.
- An interrupted multipart upload may need separate cleanup. A crash between
  a destination write and its local checkpoint leaves the operation marked
  `pending`; the next run stops on the unrecorded version. Recovery is below.
- Archived Glacier objects, Object Lock state, bucket ACLs, and storage class
  behavior need separate treatment. This tool does not silently reproduce
  these attributes. The destination uses its own owner, KMS key, and standard
  storage behavior.
- Replaying history does not rewrite object-key or S3 URL text embedded in
  object bodies. Data migration must update application records and any
  content references as required by the identity remap.

## Reviewed four-pass sequence

An initial 2026-09-29 read-only inventory found 150 shared user/group keys,
six legacy-only keys, and 44 HeyTim-only keys. SHA-256 of all 150 shared
**latest object bodies** matched. Historical version counts differed on 62 of
those keys, so both full histories must survive. The HeyTim bucket gained
more user keys and versions while source traffic remained live; the initial
counts and manifest are stale. Re-inventory and rehash after the source write
freeze. No live-traffic snapshot is a final migration checksum.

The live source AgentCore runtime reports `HEYTIM_FILES_BUCKET` as
`frogbot-user-files-188757775631-us-east-1`, a third versioned source file
bucket. Its 99 keys shared with each earlier source bucket are all templates.
Latest-body SHA-256 matches on only 3 of those 99 shared keys and differs on
96, so its template history needs a separate archive. Its other eight keys
are two templates and six deleted user/group keys. The five user keys belong
to an actor absent from the verified current source Cognito identities and
private actor map. The group key's UUID is absent from current source DynamoDB
group records. Keep all six historical user/group paths in the archive; a
canonical replay needs a separate historical identity review.

1. Select `--prefix users/ --prefix groups/` from the HeyTim source bucket.
   Also select `--prefix meme-templates/` and add a mapping from that source
   prefix to `migration-archive/heytim/meme-templates/` in the private key map.
   The user actor mapping creates the canonical application-visible user/group
   history; the template mapping preserves HeyTim's prior template versions
   separately because the destination templates are already staged and have
   different total bytes. Every version and marker in the frozen HeyTim source
   inventory must appear in a fresh dry-run manifest.
2. Select `--all-keys` from the legacy source bucket with
   `--archive-prefix migration-archive/legacy/`. This preserves **every**
   legacy version and delete marker, including template history, away from
   application-visible paths. This pass needs no Cognito key map.
3. Put the six legacy-only user/group keys in a private `0600` JSON array and
   select it with `--exact-key-file`. Reuse the user actor mapping from pass 1;
   the template mapping is unnecessary. The exact-key selector excludes prefix
   neighbors, and destination collision checks stop a key already created by
   pass 1.
4. Select `--all-keys` from the live AgentCore runtime file bucket with
   `--archive-prefix migration-archive/agentcore-runtime/`. Preserve its entire
   version and marker history away from application-visible paths. This pass
   needs no Cognito key map and must include the six historical user/group
   tombstones. Do not replay them at canonical paths while their identities
   remain unverified.

Use a separate owner-only manifest and version-map path for each pass. Dry-run
all four before any apply. Check that the chosen source totals equal the
manifest totals for each pass, and that every pass has no destination collision.
After applying, the union of pass 1's user/group keys and pass 3 is the
application-visible user/group key set; all three source template histories and
the full legacy and runtime bucket histories are archived. Validate every
version/marker count, total bytes, source-to-destination SHA-256, metadata,
and tags from all four manifests. Recheck current object bodies and referenced
keys against the migrated DynamoDB records before client or traffic cutover.
Archive paths must remain excluded from normal application reads and cleanup
jobs.

### Reproducible dry-run commands and observed counts

These commands were run read-only on 2026-09-29 with STS confirming source
account `188757775631` and destination account `820323452649`. The private
files under `/private/tmp` contain only hashed actor prefixes or an exact
object-key allowlist; they are `0600`, outside the repository, and may need to
be regenerated from the two verified Cognito pools if the local machine is
reset. Never substitute a raw Cognito `sub` or email address. The first three
commands document the earlier reviewed plans. Pass 1's manifest no longer
matches the live source and cannot be used for apply. After the source freeze,
rerun it with a new owner-only manifest path and use that path for apply.

**Pass 1: full HeyTim source, canonical user/group keys and archived HeyTim templates**

```bash
services/runtime/.venv/bin/python scripts/migrate_versioned_s3.py \
  --source-profile default --source-account 188757775631 \
  --source-bucket heytim-production-user-files-188757775631-us-east-1 \
  --destination-profile frogbot-production-org --destination-account 820323452649 \
  --destination-bucket heytim-production-user-files-820323452649-us-east-1 \
  --destination-kms-key arn:aws:kms:us-east-1:820323452649:key/d90ef69b-ed9c-44a4-9230-744c3fdf8701 \
  --source-user-pool-id us-east-1_N22obdhLi \
  --destination-user-pool-id us-east-1_biJejrNQF \
  --region us-east-1 --prefix users/ --prefix groups/ --prefix meme-templates/ \
  --key-map-file /private/tmp/heytim-s3-full-key-map-20260929.json \
  --manifest /private/tmp/heytim-s3-heytim-full-plan-20260929.json
```

Observed: **295 keys, 455 object versions, 1 delete marker, 65,754,287
version bytes**. All 101 HeyTim source template versions are mapped under
`migration-archive/heytim/meme-templates/`. A later read-only refresh produced
**349 keys, 644 versions, 1 marker, 70,238,744 version bytes** with verified
Cognito mapping and no destination collision at that checkpoint; its private
manifest is `/private/tmp/heytim-s3-heytim-full-plan-refresh-20260929.json`.
Source traffic was still adding versions, so create another manifest after the
freeze and do not apply either September 29 snapshot without matching it to a
fresh frozen inventory.

**Pass 2: complete legacy bucket history under an archival prefix**

```bash
services/runtime/.venv/bin/python scripts/migrate_versioned_s3.py \
  --source-profile default --source-account 188757775631 \
  --source-bucket frogbot-production-user-files-188757775631-us-east-1 \
  --destination-profile frogbot-production-org --destination-account 820323452649 \
  --destination-bucket heytim-production-user-files-820323452649-us-east-1 \
  --destination-kms-key arn:aws:kms:us-east-1:820323452649:key/d90ef69b-ed9c-44a4-9230-744c3fdf8701 \
  --region us-east-1 --all-keys \
  --archive-prefix migration-archive/legacy/ \
  --manifest /private/tmp/heytim-s3-legacy-archive-plan-20260929.json
```

Observed: **257 keys, 557 object versions, 6 delete markers, 65,252,597
version bytes**.

**Pass 3: exact legacy-only tombstones at canonical paths**

```bash
services/runtime/.venv/bin/python scripts/migrate_versioned_s3.py \
  --source-profile default --source-account 188757775631 \
  --source-bucket frogbot-production-user-files-188757775631-us-east-1 \
  --destination-profile frogbot-production-org --destination-account 820323452649 \
  --destination-bucket heytim-production-user-files-820323452649-us-east-1 \
  --destination-kms-key arn:aws:kms:us-east-1:820323452649:key/d90ef69b-ed9c-44a4-9230-744c3fdf8701 \
  --source-user-pool-id us-east-1_N22obdhLi \
  --destination-user-pool-id us-east-1_biJejrNQF \
  --region us-east-1 \
  --exact-key-file /private/tmp/heytim-s3-legacy-only-20260929.json \
  --key-map-file /private/tmp/heytim-s3-actor-map-20260929.json \
  --manifest /private/tmp/heytim-s3-legacy-only-plan-20260929.json
```

Observed: **6 keys, 0 object versions, 6 delete markers, 0 version bytes**.
The exact-key allowlist excludes prefix neighbors. None of the 30 currently
referenced DynamoDB `objectKey` rows points exclusively to the legacy bucket.

**Pass 4: complete live AgentCore runtime bucket history under its own archive**

```bash
services/runtime/.venv/bin/python scripts/migrate_versioned_s3.py \
  --source-profile frogbot-release --source-account 188757775631 \
  --source-bucket frogbot-user-files-188757775631-us-east-1 \
  --destination-profile frogbot-production-org --destination-account 820323452649 \
  --destination-bucket heytim-production-user-files-820323452649-us-east-1 \
  --destination-kms-key arn:aws:kms:us-east-1:820323452649:key/d90ef69b-ed9c-44a4-9230-744c3fdf8701 \
  --region us-east-1 --all-keys \
  --archive-prefix migration-archive/agentcore-runtime/ \
  --manifest /private/tmp/heytim-s3-runtime-archive-plan-20260929.json
```

Observed read-only: **107 keys, 208 object versions, 6 delete markers, and
85,341,900 version bytes**. The utility checked ownership, versioning, KMS,
source metadata and tags, and destination collisions before writing its
owner-only dry-run manifest. The destination's 101 staged template versions
remain untouched. Refresh this plan after the write freeze, even if its
September 29 inventory still appears stable.

At the latest read-only checkpoints, the four passes would replay **1,409
object versions, 19 delete markers, and 220,833,241 version bytes**. That
includes six legacy-only tombstones replayed canonically in pass 3, in
addition to their archived copies in pass 2. The source HeyTim bucket was
actively changing, so recompute these totals from four matching frozen
manifests before adding `--apply` to each command, in order.

## Interrupted-write recovery

The manifest is checkpointed as `pending` **before** each destination write.
If no new destination version exists on resume, the utility resets that
operation to `planned` and retries it. If exactly one unrecorded version
exists, it stops without another write. To reconcile it:

1. Keep the source write freeze and destination application traffic stopped.
   Inspect the pending source/destination key and source VersionId in the
   private manifest. List destination versions for that exact key and confirm
   the single unrecorded VersionId is the most recent version or delete marker.
2. Re-run the same command with `--apply --adopt-pending-version-id <id>`.
   For an object, the utility compares source and destination SHA-256, size,
   content settings, metadata, tags, and destination KMS key before recording
   the version. For a delete marker, it requires the exact reviewed VersionId
   and latest marker type. Any other unrecorded version remains a hard stop.
3. Check that the owner-only manifest and version map include the adopted
   VersionId. Run the full migration again; it verifies every copied body and
   current-state count without duplicating recorded versions.

Do not remove an unrecorded destination version to make a retry pass. A
concurrent destination writer, more than one unrecorded version, or an
ambiguous marker requires manual investigation before continuing.
