# Application functions map

```text
api/       Authenticated HTTP routing and one module per application domain
worker/    Queue routing and focused modules for long-running work
shared/    Pure or reusable rules used by more than one function
tests/     Fast unit tests with local AWS fakes
```

`api/handler.py` and `worker/handler.py` are entrypoints, not places for domain logic.
`api/authenticated_routes.py` groups HTTP dispatch by domain; the focused API modules authorize and
persist requests. Worker modules claim durable work and complete it safely. Shared modules do not
depend on either entrypoint.

`api/bot_roles.py` defines Chief's protected application role and reserved branding, but not its bot content.
Chief and every specialist come from the public catalog; setup requires and installs Chief as a user-owned,
version-pinned copy.

The whole `amplify/functions` directory is packaged for each Lambda, so relative package imports are
available in AWS and in the local test command.

Run `npm test` from `services/API`. The command uses the locked
runtime Python environment through `uv`, including its pinned AWS SDK. Do not
substitute the operating system's Python packages: older runner-provided SDKs
do not include AgentCore browser/profile APIs, and missing SDKs skip those
contract checks.
