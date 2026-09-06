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

`api/starter_bots.py` is the only local definition of the small new-account starter set. It points to
public skill IDs but does not duplicate skill instructions.

The whole `amplify/functions` directory is packaged for each Lambda, so relative package imports are
available in AWS and in the local test command.
