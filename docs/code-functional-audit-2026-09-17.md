# Code and functionality audit — 2026-09-17

## Scope and evidence

Reviewed the SwiftUI iPhone/Mac app, public website and catalog, Amplify API and worker, AgentCore runtime/configuration, deployment checks, and dependency state. Ran local verification, a browser preview of public routes, and read-only checks of the deployed catalog and AWS resources. No production code, catalog, or infrastructure was deployed during this audit.

This is a point-in-time review, not proof that every authenticated or provider-dependent production flow works. The live checks did not exercise a disposable account, OAuth providers, physical-device push notifications, or a new production release.

## Changes made in the checkout

1. **Made CodeZip packaging reproducible.** Pinned three dependencies that had drifted from `uv.lock` during AgentCore CodeZip resolution: `aws-opentelemetry-distro`, `cyclopts`, and `wcwidth`. Updated the lock metadata without upgrading packages. The five CodeZip integration tests now pass.
2. **Kept new file writes under the bucket's default KMS encryption.** Removed explicit `AES256` overrides from attachment uploads, group attachment copies, and generated artifacts. The deployed bucket currently defaults to `aws:kms`; an explicit SSE-S3 request overrides that default. Added a production check for the KMS default and updated the existing tests. See [AWS S3 encryption request behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/specifying-kms-encryption.html) and [default encryption semantics](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ServerSideEncryptionByDefault.html).
3. **Rejected invalid message text before attachment side effects.** Direct and group message requests now validate nonblank text before incrementing upload references or copying files. Added a regression test for invalid group messages.
4. **Read every group membership and decision page.** Group loading now uses the existing paginated partition reader instead of stopping after DynamoDB's first query page. Added a pagination regression test.
5. **Preserved published catalog versions.** Official skill and bot template version rows are now written only when the version is new; a same-version content change fails before catalog listings or version rows are written. Bumped the three locally changed skills and their three bots to version 2 and the catalog release to `skills-v27`. This prevents a refresh from silently changing content installed under an existing version.

## Verification

| Area | Result |
| --- | --- |
| AgentCore configuration, evaluators, generated CDK | Validation passed; 2 evaluator tests and 8 CDK tests passed in the full run. |
| Python runtime | Lint and 260 tests passed in the full run; 22 focused artifact/CodeZip tests passed after the file and dependency changes. |
| Amplify backend | Verification passed after the catalog changes; 416 tests passed, plus type checking, lint, security scan, and contract checks. |
| Catalog and website | Catalog validation, contract tests, website checks/build, and 13 catalog tests passed after the release changes. Local browser preview loaded the home, bot library, skill library, download, and invite handoff routes; bot search worked. |
| Dependency audit | Zero known npm or Python vulnerabilities reported. |
| Native app | Transcription tests and Mac application suite completed in the full run. The iPhone UI runner repeatedly reported host LLDB “no debugger version” and was stopped after several minutes. Its UI suite is unverified on this host. |

The browser preview verifies public website routes only. It does not establish that authenticated app workflows work against the deployed backend.

The production service-alarm topic currently has one confirmed subscriber, resolving the pending-subscription state recorded in earlier verification history.

## Remaining findings, in priority order

### 1. Publish the catalog and API changes together

The deployed public API currently lists 12 bots and 12 skills; the published site lists 15 of each. The three missing bots are `social-writer`, `trend-scout`, and `youtube-studio`, and the missing skills are `social-writer`, `trend-scout`, and `youtube-strategy`. The published catalog still enables `x_search` and `youtube_search` and its corresponding skills require them. The local catalog disables those two tools and changes the three skills' requirements, while backend catalog rules retire those tools. The deployed catalog sync itself reported `READY`; the mismatch is between published inputs and backend rules.

Release `skills-v27` with its skill documents and gateway schema assets through the normal reviewed process, deploy the matching backend, then verify that the public API, website, and installed bot/skill versions agree. Do not publish the local catalog over the old release name.

### 2. Inventory historical file encryption

The code fix affects future writes. S3 does not automatically re-encrypt existing objects when a bucket default changes. Inventory existing object versions and, if policy requires KMS for all historical data, plan a version-aware copy/migration and verify the resulting encryption metadata. See [AWS S3 default encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/serv-side-encryption.html).

### 3. Make direct-chat steering resilient to queue failure

`_send_message` interrupts existing active turns before `_start_bot_turn` persists and enqueues the replacement. If creating or queueing the replacement fails, the old turn is already interrupted. A durable handoff or recovery path would prevent a failed send from losing the running answer. This needs focused state-transition design and failure tests before changing production behavior.

### 4. Review scale and legacy paths

- Group schedule history reads all group messages and scans them again for each result. Indexing replies by `roundId` would reduce its in-process work; bounded querying would address larger histories.
- Expo token handling remains in push registration and delivery although the Expo client is archived. Check live token inventory and migration requirements before removing the compatibility path.
- `FeatureSheets.swift`, `MainView.swift`, and `AppModel.swift` are large enough that smaller feature-specific files would make future review easier. This is maintainability work, not a current functional defect.

## Operational follow-up

Rerun the iPhone UI suite on a healthy Xcode runner, then exercise an authenticated disposable-account workflow against the coordinated production release, including attachment upload/read, direct and group messages, scheduled turns, and account cleanup. Verify provider OAuth and APNs on approved accounts/devices when those dependencies are available. The AWS read-only session used for this audit identified as account root, so no production writes were made with it.
