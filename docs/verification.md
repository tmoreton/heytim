# FroggyBot verification

This is the single source of truth for local and continuous verification. The checks are read-only with respect to AWS:
they validate source, build local artifacts, and run tests, but do not deploy infrastructure or publish the app.

## Prerequisites

- Node.js `22.23.2` (the version used by CI)
- Python 3.14
- `uv`
- AgentCore CLI `0.28.1`
- npm dependencies installed in `apps/froggybot`, `apps/froggybot/amplify`, and `agentcore/cdk`

## Complete local verification

From the repository root:

```bash
scripts/verify.sh
```

The script validates the declarative AgentCore configuration, checks and tests the locked runtime environment,
checks the runtime deployment-package manifest, verifies the Expo application and Amplify backend,
exports the web application, audits backend Python, and builds/tests the generated AgentCore CDK wrapper.

## Focused checks

Use a focused command while iterating, then run the complete script before merging.

```bash
scripts/verify.sh application
scripts/verify.sh runtime
scripts/verify.sh agentcore
```

The 600-line source-size guard is intentionally part of the application verification command. Split files by cohesive
responsibility instead of raising the limit.

Ignored build and cache output can be removed without reinstalling dependencies:

```bash
scripts/clean-generated.sh
```

## Continuous integration

Pull requests run application, runtime, and AgentCore jobs independently. A push to `main` can publish only after all
three jobs pass. The application job also exports web output and audits backend Python; the runtime job uses the lockfile
and checks the deployable archive boundary.

## Deployed verification

Local checks cannot prove IAM, quotas, AWS integration behavior, or production latency. After a controlled deployment,
use the disposable-account workflow, load check, recovery drill, dashboard, and alarms described in
[operations.md](operations.md). Record dated results in [verification-history.md](verification-history.md), not in
architecture or roadmap documents.
