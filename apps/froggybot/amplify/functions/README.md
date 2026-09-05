# Application functions map

```text
api/       Authenticated HTTP routing and one module per application domain
worker/    Queue routing and focused modules for long-running work
shared/    Pure or reusable rules used by more than one function
tests/     Fast unit tests with local AWS fakes
```

`api/handler.py` and `worker/handler.py` are entrypoints, not places for domain logic. API modules
authorize and persist requests. Worker modules claim durable work and complete it safely. Shared
modules do not depend on either entrypoint.

The whole `amplify/functions` directory is packaged for each Lambda, so relative package imports are
available in AWS and in the local test command.
