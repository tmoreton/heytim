# Browser connection dependency

`websocket_client-1.9.0-py3-none-any.whl` is the unmodified, pure-Python PyPI
wheel (Apache-2.0 license included in the wheel). It is zip-imported only by
the browser handoff API; no browser engine or extra runtime is installed.

SHA256: `af248a825037ef591efbf6ed20cc5faa03d3b47b9e5a2230a529eeee1c1fc3ef`

To update, download a pinned wheel with `pip download --no-deps --only-binary=:all:`,
verify its PyPI digest, update the import path, and run backend and browser tests.
Never enable WebSocket trace logging: the handshake contains a signed credential.
