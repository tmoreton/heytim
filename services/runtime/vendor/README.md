# Vendored Stan wheel

`strands_agents_stan-0.0.1.dev53+g325058d51-py3-none-any.whl` is a development build of
[`strands-agents/stan`](https://github.com/strands-agents/stan), distributed under Apache-2.0.

- Package: `strands-agents-stan`
- Version: `0.0.1.dev53+g325058d51`
- Source commit fragment: `325058d51`
- SHA-256: `77b428ad3df81c865ff4738c4180e6c8b2e49992e7e1f07fcfde974df8bd7e8a`
- Runtime contract: Python 3.14, verified by this repository's locked tests and package checks

The wheel remains vendored because the required harness build is not published as a stable package.
To update it, obtain a wheel from the upstream source, verify its license and source revision, replace
the file and this checksum, run `uv lock`, and complete the runtime and CodeZip verification suites.
Do not copy the wheel itself into the deployed archive; AgentCore installs the locked dependency into
the staging tree before copying the production-only runtime source.
