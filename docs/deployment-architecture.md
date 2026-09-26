# Cost-efficient deployment architecture

HeyTim remains a monorepo while its clients and services share API contracts, generated routes, production client
configuration, and coordinated releases. Separate repositories would make those changes harder to review atomically
without reducing the largest build cost. Reconsider a split only when the Apple client, browser client, or backend has
an independent owner and release cadence with a versioned contract between repositories.

## Current execution model

| Work | Trigger | Compute |
| --- | --- | --- |
| Apple verification | Apple, transcription, or generated-route changes on a pull request or `main` | Repository-scoped `frogbot-macmini` runner |
| Browser/backend/runtime/AgentCore verification | Trusted pull requests and `main`, classified by changed path | Repository-scoped `frogbot-macmini` runner |
| CodeQL | Relevant JavaScript, TypeScript, or Python changes and the weekly schedule | Repository-scoped `frogbot-macmini` runner |
| Production backend | Published stable GitHub Release tagged from `main`, or manual recovery workflow | GitHub-hosted Linux runner using GitHub OIDC, never stored AWS keys |
| iPhone TestFlight + direct Mac release | Dependent step of a successful release deployment | Repository-scoped `frogbot-macmini` runner |
| Provider contract probe and constrained autofix | Scheduled or explicitly trusted events | Repository-scoped `frogbot-macmini` runner |

The Mac mini is intentionally limited to this private repository and has the custom `heytim-apple` and `heytim-ci`
labels. Jobs also require the default `self-hosted`, `macOS`, and `ARM64` labels. Pull requests from forks cannot
execute on the persistent runner. The runner is installed as the `homelab` user's launch agent and updates itself
using the standard GitHub runner update channel. One runner processes jobs sequentially, avoiding concurrent builds
competing for Simulator state, memory, or disk.

## Why AWS deployment stays in GitHub for now

The existing production job is release-triggered, assumes a narrowly scoped AWS role through OIDC, and runs only for
a published stable release or manual recovery. Moving that low-frequency control plane into CodePipeline and CodeBuild would add a persistent pipeline,
a CodeConnection, another IAM surface, and a second place to diagnose releases. The first optimization target is the
frequent Apple verification job and unrelated test suites, not the release-gated backend deployment.

If Linux runtime fidelity becomes necessary, the next step is an AWS CodeBuild project for server verification. Use a
queued build, GitHub CodeConnection restricted to this repository and branch, no long-lived access token, and Secrets
Manager or Parameter Store for any build secret. Keep production deployment release-gated until CodeBuild verification
has been stable long enough to replace the current gate.

## Mac mini operations

The runner retains its legacy registered name and install path at `/Users/homelab/ActionsRunners/frogbot`. From the Mac mini:

```bash
cd /Users/homelab/ActionsRunners/frogbot
./svc.sh status
./svc.sh stop
./svc.sh start
```

GitHub reports the machine as `frogbot-macmini`. A healthy idle runner is online and not busy. The machine must keep
automatic login or an active `homelab` GUI session available for Simulator work, remain awake, and retain the Xcode
and iOS runtime versions required by the project. Its service PATH includes Homebrew Node 22, Python 3.14, `uv`,
GitHub CLI, CMake, and CocoaPods. Do not use `actions/setup-python` on this ARM64 macOS runner: GitHub's downloadable Python
package currently assumes the hosted `/Users/runner` account, while the checked machine Python is installed and
updated through Homebrew.

The Apple verification script creates and deletes a temporary simulator and derived-data directory for every run.
Do not delete `/Library/Developer/CoreSimulator/Volumes`; that is the installed runtime. Generated transcription
assets are restored through the repository cache and verified by checksum before use.

## Release boundaries

- A push to `main` verifies code; it does not deploy production.
- A published stable GitHub Release (`vMAJOR.MINOR.PATCH`) at a commit on `main` starts the protected production
  deployment. The tag version becomes `CFBundleShortVersionString` for both Apple builds; both share one numeric build
  number. Drafts and pre-releases do not deploy production.
- Manual `workflow_dispatch` from `main` remains available for recovery. Its `backend-only` scope deploys AgentCore
  and Amplify without occupying the Mac mini. `backend-macos` additionally signs, notarizes, and attaches the Mac
  download and Sparkle feed to the specified draft release without uploading an iPhone build.
- A release or manual `full` run deploys the backend first, transfers the generated public client configuration as a
  short-lived artifact, then verifies both Apple builds on the Mac mini. iPhone uploads to TestFlight; Mac is Developer
  ID signed, notarized, stapled, and packaged with a signed Sparkle appcast. Published releases receive both Mac assets.
- The Vite website and public catalog publish independently; Expo is archived outside this repository.

Review GitHub Actions usage and Mac mini queue time after several normal development cycles. If the single runner is
too slow or server tests need Linux-specific behavior, move server verification to CodeBuild before considering
repository separation.
