# Production account-isolation cutover plan

**Status:** Draft — not approved for execution  
**Observed:** 2026-09-25 in `us-east-1`  
**Source account:** `188757775631`  
**Destination account:** `820323452649`

This plan covers moving the live HeyTim service out of the development/shared account. It does not authorize a
deployment, traffic cutover, deletion, resource rename, or secret disclosure. Set
`HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED=true` only after the decisions and pre-cutover evidence below are reviewed.

## Read-only inventory

The counts below are deployment-planning metadata. No customer record or object body was read.

| Area | Source production | Destination readiness |
| --- | --- | --- |
| AgentCore | HeyTim runtime, memory, gateway, evaluator, online evaluation, regression dataset, and three API-key credential providers | A retained legacy `AgentCore-FrogBot-production` stack is ready, but the current HeyTim target is not deployed or adopted |
| Cognito | One user in the production pool | No user pool |
| DynamoDB | Application table: approximately 610 items / 1,008,905 bytes; invite table: 0 items; deletion protection and SSE enabled | No application tables |
| S3 | 251 current objects / 65,094,560 bytes; 557 object versions / 65,252,597 bytes; 6 delete markers | No application file bucket |
| Queues and schedules | Production job queue/DLQ and bot-email delivery queues are deployed; schedules can be active | No application queues; only the default Scheduler group |
| Secrets and connections | Production OAuth, billing, finance, and per-connection secrets exist | Legacy FrogBot OAuth secrets and AgentCore credential backing secrets exist; current HeyTim secrets are not provisioned |
| Push | Production and sandbox APNs applications exist | Production and sandbox APNs applications exist under retained legacy physical names |
| Operations | Application and AgentCore alarms, encrypted logs, budget, and a confirmed alert path are required | No application alarms, AgentCore alarms, budget, or recurring GitHub OIDC deployment role |
| Amplify | Live app `d1tu46ki1836w1` with API/client outputs | Empty app `d17sj7dvhx07c`; no backend stacks |

The checked-in production deployment state still contains source-account ARNs. CDK synthesis now rejects that state
when authenticated to the destination account, so it cannot be silently reused across accounts.

## Decisions requiring approval

Record an owner and decision for every row before the maintenance window is scheduled.

| Decision | Recommended default | Approved choice / owner |
| --- | --- | --- |
| Cognito identity | Require the single user to sign in again in the destination. Do not attempt to move passwords or refresh tokens. Recreate the synthetic release-test user and token separately. | Pending |
| Application records | Export the two source tables after the write freeze, validate counts and a canonical-record checksum, import into destination tables, then validate indexes, TTL fields, ownership keys, and representative reads. | Pending |
| File history | Copy all object versions and delete markers because the versioned history is small; re-encrypt with the destination key and validate key/version counts, total bytes, and metadata checksums. | Pending |
| AgentCore memory | Decide explicitly whether to preserve user facts, summaries, and preferences or start fresh. Do not claim memory migration until an export/import path and count validation have been exercised. | Pending |
| Provider connections | Prefer reconnecting the single user and rotating production OAuth/App credentials in the destination. If any token is copied, preserve its owning record mapping, encrypt it under the destination key, and prove revoke/delete behavior before cutover. | Pending |
| Billing and finance | Recreate/rotate Stripe and Plaid secrets in the destination, register destination webhook URLs, replay signed test events, and reconcile entitlement state before enabling live mode. | Pending |
| Bot email and DNS | Deploy identity-only first, validate SES ownership and the existing receipt-rule set, then stage receive resources and change MX/API bindings only inside the window. | Pending |
| Client cutover | Publish destination Amplify outputs only after authenticated smoke tests pass. Release iPhone and Mac builds from the same commit and preserve the prior configuration for rollback. | Pending |
| Rollback window | Keep source stacks, keys, logs, backups, and provider callbacks recoverable and read-only for an agreed period. Cleanup is a separate review. | Pending |

## Execution phases

### 1. Prepare without traffic

- Merge a reviewed clean commit and require passing application, runtime, AgentCore, dependency, security, website,
  iOS, and macOS checks.
- Create the destination HeyTim AgentCore state deliberately: archive the source deployment-state record for audit,
  then adopt or create only destination-owned identifiers. Review `cdk diff`; stop on stateful replacement.
- Deploy the destination Amplify backend with email receive and public availability disabled. Capture its outputs and
  recurring GitHub OIDC deployment-role ARN, but do not update production clients, DNS, provider callbacks, or APNs.
- Create the destination log encryption, alarms, budget, confirmed alarm subscription, backups, and recovery evidence.
- Rotate/copy approved secrets through protected channels. Never commit secret values or place them in ordinary
  environment variables.

### 2. Rehearse

- Import a scrubbed or temporary copy of the approved state and run authentication, attachment, scheduling, sharing,
  approval, deletion, OAuth connect/read/revoke, provider webhook replay, and recovery tests.
- Run the managed five-scenario AgentCore evaluation with no failures and an average score of at least 0.80 for both
  release evaluators.
- Validate source/destination item counts, object-version counts, byte totals, and canonical checksums. Record every
  accepted exclusion.
- Confirm runtime and gateway authentication, least-privilege roles, 30-day encrypted logs, alarms, and a real alert
  delivery.

### 3. Cut over in a bounded maintenance window

1. Announce the write freeze and named rollback owner.
2. Stop new schedules and paid-work admission, drain queues, and verify no in-flight job remains.
3. Capture final DynamoDB backups/exports and S3 inventory; record source counts and checksums.
4. Import the approved data, files, secrets, and connection state; run destination validation again.
5. Update provider webhooks, bot-email/DNS, GitHub production variables, and client configuration in the reviewed order.
6. Run the authenticated workflow, managed evaluation, provider callbacks, push smoke, and bounded concurrency test.
7. End the freeze only after all acceptance checks pass. Otherwise restore the prior client/API bindings and resume the
   retained source environment.

### 4. Retain and clean up

- Keep the source account read-only and monitored through the approved rollback and retention period.
- Record commit SHA, workflow run, resource IDs, counts/checksums, alarms, recovery drill, test evidence, and owners in
  `docs/verification-history.md`.
- Delete or disable source resources only in a separate reviewed cleanup. Preserve legacy physical identifiers until
  their data, signing, audit, rollback, and compatibility obligations are closed.

## Go/no-go checklist

- [ ] Every decision above has an accountable owner and an approved outcome.
- [ ] Destination AgentCore and Amplify diffs contain no unintended replacement or deletion.
- [ ] Destination state is complete and all count/checksum exceptions are documented.
- [ ] Production synthetic user/token and all destination provider credentials are ready.
- [ ] GitHub production variables reference only account `820323452649`; obsolete shared-account overrides are removed.
- [ ] Developer ID release certificate secrets are present for notarized Mac delivery.
- [ ] Alarm subscription, recovery drill, provider evidence, physical-device push smoke, and rollback exercise pass.
- [ ] Maintenance window, freeze operator, cutover operator, and rollback owner are named.
- [ ] `HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED=true` is set only after all preceding items pass.

**Approval record:** Pending.
