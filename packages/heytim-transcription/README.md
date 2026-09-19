# HeyTim Nemotron transcription

This Swift package runs NVIDIA Nemotron 3.5 ASR Streaming 0.6B entirely on the
device through sherpa-onnx. `apps/iOS` uses the same core for iPhone and native
macOS. The former Expo/TypeScript bridge is preserved in the external reference
archive; no Expo runtime is needed to build or use this package.

Native artifacts and the model are verified, generated build inputs and are
therefore excluded from Git. Prepare an iOS checkout with:

```sh
./scripts/prepare-apple.sh apple
swift test
```

The model is approximately 683 MB unpacked, so this feature substantially
increases the native app download and installed size.
