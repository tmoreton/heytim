# AgentCore configuration ownership

`agentcore.json` and `aws-targets.json` are the maintained sources of truth. Files under `cdk/lib` and
`cdk/bin` are generated adapters and must not be edited to change runtime behavior. Use the AgentCore
CLI to validate, package, add, or remove resources; a deployment is a separate reviewed operation.

`.cli/deployed-state.json` is intentionally versioned deployment metadata. It contains resource IDs
and ARNs, not secret values, and generated CDK uses it to bind deployed resources. Do not hand-edit it:
only a successful CLI deployment should update it. A config-only removal therefore remains pending in
AWS until a later reviewed deployment updates both infrastructure and state.

## Environment posture

Development is deployed, and the stable production target uses the dedicated organization member account
`820323452649`. Their `PUBLIC` runtime network mode is
intentional because the runtime needs outbound access to OpenRouter and reviewed remote MCP endpoints.
Moving production into a VPC requires a reviewed NAT egress path and service endpoints; do not switch the
network mode without that path or rename either existing target.

The current AgentCore project schema does not own the runtime CloudWatch log group's KMS key or
retention. `scripts/harden-agentcore-logs.sh` manages 30-day retention and customer-managed encryption
after deployment. Keep that ownership outside generated CDK until the schema exposes supported fields.

## Platform-owned provider keys

OpenRouter, X, and YouTube use company-owned API keys. End users never enter, receive, or manage these
keys. Their immutable AgentCore provider names live in `agentcore.json`; secret values belong only in
operator-controlled secret storage and are passed to the deployment process as environment variables.

Create these environment secrets once under the GitHub `production` environment:

- `AGENTCORE_CREDENTIAL_FROGBOT_OPENROUTER`
- `AGENTCORE_CREDENTIAL_FROGBOTXAPI`
- `AGENTCORE_CREDENTIAL_FROGBOTYOUTUBEAPI`

To rotate a provider key, replace that GitHub environment secret and rerun **Deploy FroggyBot production
release**. The AgentCore CLI updates the existing credential provider by name, so never rename a
provider to perform a rotation. The workflow never writes or prints the secret values.

AgentCore credential providers are scoped to an account and Region rather than to a target stack. Production uses a
separate AWS account so the same stable provider names have independent values. `scripts/check-production-config.mjs`
and the release workflow reject placeholder and development-account reuse.

The recurring GitHub deployment role can read the existing default token vault and create or rotate only
these three named providers. It deliberately cannot create the vault encryption key or call
`SetTokenVaultCMK`. In a new account or Region, perform that one-time bootstrap with a separate reviewed
principal whose KMS create/tag permissions require the `agentcore:project=FrogBot` request tag, then
remove that bootstrap access before enabling routine deployments.

## Package boundary

The CodeZip source is `services/agent-runtime/runtime/`. The toolkit locates the parent
`services/agent-runtime/pyproject.toml` for dependency installation, while only the production source
directory is copied into the archive. Run the source and archive checks documented in the runtime
README before deployment.
