# September 2026 monorepo consolidation

## Maintained layout

| Path | Owns |
| --- | --- |
| `apps/iOS` | Shared SwiftUI iPhone and macOS app, Xcode project, signing and TestFlight scripts |
| `apps/website` | Vite + React marketing site, bot and skills directory, native invite handoff |
| `services/API` | Amplify application backend, API contract, public client configuration |
| `services/runtime` | AgentCore Python agent loop, tools, evaluations and packaging |
| `catalog` | Reviewed bots, skills, tool schemas, validation, and gateway-target definitions |
| `packages/froggybot-contract` | Generated TypeScript API contract and contract tests |
| `packages/frogbot-transcription` | Native Swift transcription core and pinned model preparation |
| `agentcore` | Declarative AWS resources and generated deployment wrapper |

The directory name `apps/iOS` is intentional: one SwiftUI project still builds
**both iOS and macOS**. AWS names, bundle identifiers, Cognito pools, API endpoints,
memory identities and catalog versions are not renamed as part of this move.

## Preserved reference code

The retired Expo app is outside Git in
`/Users/tmoreton/Code/FrogBot-Expo-archive-20260915`.
It includes the original Expo application, browser-only client/preview packages,
isolated browser viewer, and Expo transcription bridge. Source at the starting
commit `cad69c2` is also recoverable from this repository's history. Existing
local cleanup changes were retained. No cloud data or credentials were removed.

The public catalog was imported from `/Users/tmoreton/Code/frogbot-skills`,
repository `tmoreton/frog-bots`, commit `62a1f53`. That checkout matched remote
`main` at import time and remains untouched for history/reference. The monorepo
is now the maintained source. The protocol field `tmoreton/frogbot-skills` and
release `skills-v26` remain stable; they are trusted catalog identities, not
filesystem paths. Bump versions for future behavior changes as before.

## Verification and release

```sh
./scripts/verify.sh application  # Vite site, public catalog and API contract
./scripts/verify.sh server       # API, runtime, AgentCore schema and wrapper
./scripts/verify.sh apple        # Native speech, macOS unit tests, iPhone UI tests
APPLE_TEAM_ID=GVXC5FQ2RP ./scripts/apple-app.sh testflight all
```

`services/API/amplify_outputs.json` is the source for the reduced native client
configuration. Generate it from the backend directory with `ampx ...
--outputs-out-dir .`, then run `npm run outputs:apple`. TestFlight's preflight
checks production settings and refuses uncommitted changes. Private signing
keys stay outside Git.

Migration checks completed before the Apple release: website type checking and
production prerender/build; three website tests; two contract tests; 13 catalog
tests; nine workflow-selection tests; 399 API tests; 246 runtime tests including
production CodeZip packaging; two evaluator tests; eight CDK wrapper tests;
AgentCore schema validation; lint/security checks. Browser checks covered desktop
and mobile, search, and native invitation handoff. Native verification and uploads
are performed by the release command above and reported separately.

## Public hosting

The existing `froggybot.com` GitHub Pages repository can remain a **deployment
mirror**, without being a second source repository. The website deployment
script publishes only the checked Vite output to its `gh-pages` branch. No
backend, Apple source, private configuration, or credentials are copied there.
Historic public source and tagged skill releases remain available on its
existing branches. Pages serves the same catalog and association-file URLs.
The existing Expo-hosted `app.froggybot.com` deployment is not automatically
deleted; retiring its hosting/DNS is a separate cutover so old links aren't
silently broken.
