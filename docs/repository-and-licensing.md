# Repository and licensing model

## Decision

`tmoreton/heytim` is the single canonical source repository for the HeyTim
product. The Apple app, public website, backend, AgentCore runtime, reviewed bot
catalog, shared packages, infrastructure, tests, and operating documentation
change together and are released from one history.

The repository is **source-available**, not OSI open source. HeyTim's first-party
work is offered under PolyForm Noncommercial 1.0.0, while commercial use requires
a separate license from the copyright holder. See [`LICENSE`](../LICENSE),
[`NOTICE`](../NOTICE), and [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).

## Monorepo boundaries

| Path | Responsibility |
| --- | --- |
| `apps/iOS/` | Shared SwiftUI iPhone and macOS application |
| `apps/website/` | Public Vite and React website and catalog browser |
| `services/API/` | Amplify backend, API contract, authentication, jobs, and storage |
| `services/runtime/` | AgentCore runtime, models, tools, and runtime tests |
| `packages/heytim-contract/` | Generated cross-client API contract |
| `packages/heytim-transcription/` | Native transcription package and its third-party notices |
| `catalog/` | Reviewed bots, skills, evaluations, and tool definitions |
| `agentcore/` | Declarative AgentCore resources and deployment wrapper |
| `evaluators/` | Custom evaluation code |
| `docs/`, `examples/`, `scripts/` | Product decisions, examples, verification, and operations |

These are ownership boundaries inside one product, not candidates for separate
source repositories. A change that crosses client, contract, backend, runtime,
or catalog boundaries should remain one reviewable commit or pull request.

## Publishing model

- `tmoreton/heytim` is the only source of truth.
- `tmoreton/heytim-web` is a retiring artifact mirror. `tmoreton/heytim-bots`
  remains a compatibility archive for immutable catalog tags and the temporary
  `app.heytim.ai` Pages alias. Neither is independently maintained source.
- Built website or catalog artifacts may be pushed to a deployment mirror, but
  maintainers never edit that mirror directly or merge it back as source.
- Production credentials, customer data, signing material, and secret values do
  not belong in any source repository.

## License scope

The root PolyForm license covers first-party source and documentation unless a
file or directory carries different terms. Dependency downloads, vendored code,
binary frameworks, models, generated artifacts, and other third-party material
retain their original licenses. The root license must not be presented as
relicensing those materials.

Every distributed copy must include the PolyForm terms and the plain-text
`Required Notice:` line from [`NOTICE`](../NOTICE). Product pages and repository
descriptions should say **source-available** and **noncommercial**, not merely
"open source."

## Contribution policy

External ideas and issue reports are welcome. Until a contributor agreement is
in place, outside pull requests are not accepted. This keeps the copyright chain
clear enough for the project to grant commercial licenses for the same
first-party code. The policy applies to catalog bots and skills as well as code.

## Publication review

- The complete Git history is scanned with Gitleaks before publication. Two
  historical Chromium extension manifest signing keys are allowlisted by exact
  finding fingerprint because they are public identifiers, not credentials.
- Versioned Amplify client outputs and AgentCore deployment state contain public
  client configuration, resource identifiers, and ARNs, but no secret values.
  They remain versioned because native builds and declarative deployments consume
  them. Credentials and signing material remain in protected secret stores.
- [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) records the vendored wheels
  and native transcription components; their complete license texts travel with
  the applicable archives or generated application resources.
- The renamed repository keeps historic OIDC subjects temporarily while the live
  production role also trusts the immutable `heytim` repository identity.

Before selling commercial licenses, have qualified counsel review the commercial
agreement and the chosen copyright owner. Add a contributor agreement workflow
before accepting outside pull requests.
