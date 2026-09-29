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

- One invocation handles **one source bucket**. The legacy and HeyTim source
  buckets overlap. Running them into the same application-visible keys would
  produce conflicts; the utility stops on a preexisting destination version.
  Preserve both histories using the three-pass sequence below.
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

## Reviewed three-pass sequence

The 2026-09-29 read-only inventory found 150 shared user/group keys, six
legacy-only keys, and 44 HeyTim-only keys. SHA-256 of all 150 shared **latest
object bodies** matched. Historical version counts differed on 62 of those
keys, so both full histories must survive. Re-run this equality check after
the source write freeze; the result above is a planning checkpoint, not the
final migration checksum.

1. Select `--prefix users/ --prefix groups/` from the HeyTim source bucket.
   Also select `--prefix meme-templates/` and add a mapping from that source
   prefix to `migration-archive/heytim/meme-templates/` in the private key map.
   The user actor mapping creates the canonical application-visible user/group
   history; the template mapping preserves HeyTim's prior template versions
   separately because the destination templates are already staged and have
   different total bytes. All 455 HeyTim object versions must appear in this
   pass's dry-run manifest.
2. Select `--all-keys` from the legacy source bucket with
   `--archive-prefix migration-archive/legacy/`. This preserves **every**
   legacy version and delete marker, including template history, away from
   application-visible paths. This pass needs no Cognito key map.
3. Put the six legacy-only user/group keys in a private `0600` JSON array and
   select it with `--exact-key-file`. Reuse the user actor mapping from pass 1;
   the template mapping is unnecessary. The exact-key selector excludes prefix neighbors, and destination
   collision checks stop a key already created by pass 1.

Use a separate owner-only manifest and version-map path for each pass. Dry-run
all three before any apply. Check that the chosen source totals equal the
manifest totals for each pass, and that every pass has no destination collision.
After applying, the union of pass 1's user/group keys and pass 3 is the
application-visible user/group key set; both source template histories and the
full legacy bucket history are archived. Validate every version/marker count,
total bytes, source-to-destination SHA-256, metadata, and tags from all three
manifests. Recheck current object bodies and referenced keys against the
migrated DynamoDB records before client or traffic cutover. Archive paths
must remain excluded from normal application reads and cleanup jobs.

### Reproducible dry-run commands and observed counts

These commands were run read-only on 2026-09-29 with STS confirming source
account `188757775631` and destination account `820323452649`. The private
files under `/private/tmp` contain only hashed actor prefixes or an exact
object-key allowlist; they are `0600`, outside the repository, and may need to
be regenerated from the two verified Cognito pools if the local machine is
reset. Never substitute a raw Cognito `sub` or email address.

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
`migration-archive/heytim/meme-templates/`.

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

Together, these plans replay **1,012 object versions, 13 delete markers, and
131,006,884 version bytes**, exactly the sum of both source buckets' object
version bytes. The destination's 101 staged template versions remain
untouched. All 150 shared user/group keys had equal latest-body SHA-256 at
this checkpoint. Re-inventory and rehash after the write freeze before
adding `--apply` to each command, in order; never treat these dry-run counts
as final cutover evidence.

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
