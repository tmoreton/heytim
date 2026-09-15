# Cost-efficient deployment architecture

FroggyBot remains a monorepo while its clients and services share API contracts, generated routes, production client
configuration, and coordinated releases. Separate repositories would make those changes harder to review atomically
without reducing the largest build cost. Reconsider a split only when the Apple client, browser client, or backend has
an independent owner and release cadence with a versioned contract between repositories.

## Current execution model

| Work | Trigger | Compute |
| --- | --- | --- |
| Apple verification | Apple, transcription, or generated-route changes on a pull request or `main` | Repository-scoped `frogbot-macmini` runner |
| Browser/backend/runtime/AgentCore verification | Pull requests and `main`, classified by changed path | GitHub-hosted Linux runners for affected suites only |
| CodeQL | Relevant JavaScript, TypeScript, or Python changes and the weekly schedule | GitHub-hosted Linux runner |
| Production backend | Manual production workflow from `main` | GitHub-hosted Linux runner using GitHub OIDC, never stored AWS keys |
| TestFlight | Dependent step of a successful full production release | Repository-scoped `frogbot-macmini` runner |
| Provider contract probe | Daily and manual | GitHub-hosted Linux runner |

The Mac mini is intentionally limited to this private repository and has the custom `frogbot-apple` label. Apple
jobs also require the default `self-hosted`, `macOS`, and `ARM64` labels. Pull requests from forks cannot execute on
the persistent runner. The runner is installed as the `homelab` user's launch agent and updates itself using the
standard GitHub runner update channel.

## Why AWS deployment stays in GitHub for now

The existing production job is manually invoked, assumes a narrowly scoped AWS role through OIDC, and runs only for
a release. Moving that low-frequency control plane into CodePipeline and CodeBuild would add a persistent pipeline,
a CodeConnection, another IAM surface, and a second place to diagnose releases. The first optimization target is the
frequent Apple verification job and unrelated test suites, not the manual backend deployment.

If Linux runner usage remains material after measuring the path filters, the next step is an AWS CodeBuild project
for server verification. Use a queued build, GitHub CodeConnection restricted to this repository and branch, no
long-lived access token, and Secrets Manager or Parameter Store for any build secret. Keep the production deployment
manual until CodeBuild verification has been stable long enough to replace the current gate.

## Mac mini operations

The runner is installed at `/Users/homelab/ActionsRunners/frogbot`. From the Mac mini:

```bash
cd /Users/homelab/ActionsRunners/frogbot
./svc.sh status
./svc.sh stop
./svc.sh start
```

GitHub reports the machine as `frogbot-macmini`. A healthy idle runner is online and not busy. The machine must keep
automatic login or an active `homelab` GUI session available for Simulator work, remain awake, and retain the Xcode
and iOS runtime versions required by the project.

The Apple verification script creates and deletes a temporary simulator and derived-data directory for every run.
Do not delete `/Library/Developer/CoreSimulator/Volumes`; that is the installed runtime. Generated transcription
assets are restored through the repository cache and verified by checksum before use.

## Release boundaries

- A push to `main` verifies code; it does not deploy production.
- Production deployment remains a manual `workflow_dispatch` operation protected by the `production` environment.
- `backend-only` deploys AgentCore and Amplify but does not occupy the Mac mini.
- `full` deploys the backend first, transfers the generated public client configuration as a short-lived artifact,
  then verifies, signs, and uploads both Apple builds on the Mac mini.
- The Expo project remains a browser client and is not an Apple release source.

Review GitHub Actions usage after several normal development cycles. If hosted Linux minutes are still significant,
move server verification to CodeBuild before considering repository separation.
