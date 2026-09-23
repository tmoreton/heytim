# Third-party notices

HeyTim's PolyForm license applies only to first-party work. Third-party software,
models, and generated artifacts retain their original licenses.

## Vendored source distribution

The repository includes this Python wheel so deployment can reproduce the
reviewed runtime without substituting an unverified package:

- `services/API/amplify/functions/vendor/websocket_client-1.9.0-py3-none-any.whl`
  — websocket-client 1.9.0, Apache License 2.0. The wheel contains its complete
  `LICENSE` file.

The vendored wheel is an unmodified package archive. Its SHA-256 checksum is
validated by the repository's dependency and packaging checks.

## Native transcription distribution

The native transcription build prepares the following components without
committing the generated model and frameworks:

- NVIDIA Nemotron 3.5 ASR Streaming 0.6B under OpenMDW 1.1;
- sherpa-onnx 1.13.8 under Apache License 2.0; and
- ONNX Runtime 1.28.2 under the MIT License.

Pinned revisions, source links, and distribution details are recorded in
[`packages/heytim-transcription/ios/Notices/THIRD_PARTY_NOTICES.md`](packages/heytim-transcription/ios/Notices/THIRD_PARTY_NOTICES.md).
The preparation script bundles the complete applicable license texts with the
generated application resources.

## Package-manager dependencies

The directly distributed Mac app additionally links Sparkle 2.10.0 under its
BSD-style license for signed application updates.

JavaScript and Python dependencies are identified in their lockfiles and are not
relicensed by HeyTim. A distributed binary or hosted build must continue to
include every notice required by those dependencies. Run
`scripts/audit-dependencies.sh` and the native transcription preparation checks
before a release that changes dependency versions.
