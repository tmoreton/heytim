# AgentCore configuration ownership

`agentcore.json` and `aws-targets.json` are the maintained sources of truth. Files under `cdk/lib` and
`cdk/bin` are generated adapters and must not be edited to change runtime behavior. Use the AgentCore
CLI to validate, package, add, or remove resources; a deployment is a separate reviewed operation.

`.cli/deployed-state.json` is intentionally versioned deployment metadata. It contains resource IDs
and ARNs, not secret values, and generated CDK uses it to bind deployed resources. Do not hand-edit it:
only a successful CLI deployment should update it. A config-only removal therefore remains pending in
AWS until a later reviewed deployment updates both infrastructure and state.

## Environment posture

Development and production are separate stable deployment targets. Their `PUBLIC` runtime network mode is
intentional because the runtime needs outbound access to OpenRouter and reviewed remote MCP endpoints.
Moving production into a VPC requires a reviewed NAT egress path and service endpoints; do not switch the
network mode without that path or rename either existing target.

The current AgentCore project schema does not own the runtime CloudWatch log group's KMS key or
retention. `scripts/harden-agentcore-logs.sh` manages 30-day retention and customer-managed encryption
after deployment. Keep that ownership outside generated CDK until the schema exposes supported fields.

## Package boundary

The CodeZip source is `services/agent-runtime/runtime/`. The toolkit locates the parent
`services/agent-runtime/pyproject.toml` for dependency installation, while only the production source
directory is copied into the archive. Run the source and archive checks documented in the runtime
README before deployment.
