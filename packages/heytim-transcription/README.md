# HeyTim Parakeet transcription

This Swift package runs NVIDIA Parakeet TDT 0.6B v3 entirely on the device
through sherpa-onnx. `apps/iOS` uses the same core for iPhone and native macOS.
Parakeet v3 supplies punctuation, capitalization, and automatic recognition for
25 European languages. Because this is an offline model, the package detects
natural pauses and decodes bounded 30-second segments once; it never repeatedly
decodes an ever-growing recording. That keeps hour-plus audio buffering bounded.

Native artifacts and the model are verified, generated build inputs and are
therefore excluded from Git. Prepare an iOS checkout with:

```sh
./scripts/prepare-apple.sh apple
swift test
```

The model is approximately 640 MB unpacked, so this feature substantially
increases the native app download and installed size.
