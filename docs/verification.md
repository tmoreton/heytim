# FroggyBot verification

This is the single source of truth for local and continuous verification. The checks are read-only with respect to AWS:
they validate source, build local artifacts, and run tests, but do not deploy infrastructure or publish the app.

## Prerequisites

- Node.js `22.23.2` (the version used by CI)
- Python 3.14
- `uv`
- AgentCore CLI `0.29.0`
- npm dependencies installed in `apps/website`, `services/API`, and `agentcore/cdk`

## Complete local verification

From the repository root:

```bash
scripts/verify.sh
```

The script validates the declarative AgentCore configuration, checks and tests the locked runtime environment,
checks the runtime deployment-package manifest, verifies the public catalog, Vite website and Amplify backend,
prerenders the public pages, audits backend Python, and builds/tests the generated AgentCore CDK wrapper. On macOS,
the complete command also runs the SwiftUI application suites; focused `application` verification remains limited to
the website, catalog and API contract.

## Focused checks

Use a focused command while iterating, then run the complete script before merging.

```bash
scripts/verify.sh application
scripts/verify.sh backend
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

Trusted pull requests and pushes to `main` classify changed paths, then run only the affected application, backend,
runtime, AgentCore, and dependency jobs on the repository-scoped Mac mini. Native Apple changes run the separate
iPhone and Mac workflow. Unrecognized source areas fail open to every non-Apple suite; documentation-only changes can
skip product verification. The application job exports web output, and the backend job checks Amplify TypeScript and
audits backend Python.

## Deployed verification

Local checks cannot prove IAM, quotas, AWS integration behavior, or production latency. After a controlled deployment,
use the disposable-account workflow, load check, recovery drill, dashboard, and alarms described in
[operations.md](operations.md). Record dated results in [verification-history.md](verification-history.md), not in
architecture or roadmap documents.
