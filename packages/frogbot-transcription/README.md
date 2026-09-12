# FroggyBot Nemotron transcription

This local Expo module runs NVIDIA Nemotron 3.5 ASR Streaming 0.6B entirely on
the device through sherpa-onnx. Its Swift core contains no SwiftUI or Expo APIs.

- iOS 17+: CocoaPods builds the Expo bridge and the shared core.
- Apple silicon Mac compatibility mode: the Designed for iPad build uses that
  same iOS bridge and bundled model without a separate desktop implementation.
  Its app delegate subscriber also removes the redundant native title bar and
  lets the React Native layout continue behind the Mac window controls.
- macOS 14+: `Package.swift` exposes the same core to a future native desktop
  app after `npm run nemotron:prepare:apple` has prepared both platforms.
- Web and Android: the TypeScript module reports `isAvailable = false`; it does
  not upload or transcribe audio.

Native artifacts and the model are verified, generated build inputs and are
therefore excluded from Git. Prepare an iOS checkout with:

```sh
npm run nemotron:prepare:ios
```

The model is approximately 683 MB unpacked, so this feature substantially
increases the native app download and installed size.
