# Nemotron transcription third-party notices

The generated native application bundle includes the following components.
They remain under their respective licenses.

- NVIDIA Nemotron 3.5 ASR Streaming 0.6B, 1120 ms INT8 ONNX export. The
  source model was reviewed at revision
  `ea30d66debe3740a08b573244286791d423d6b3e`; the sherpa export is pinned at
  revision `cba1c96ca5ef0e8393b50584ae153a79145dc492`. Model use is governed
  by OpenMDW 1.1, whose complete text is bundled with the generated resources.
- sherpa-onnx 1.13.8 at revision
  `11afbd009a7f8c08f4bcf2fc1b265d0df4670fbf`, licensed under Apache-2.0.
  HeyTim builds the Apple runtime with TTS and speaker diarization disabled.
- ONNX Runtime 1.28.2, licensed under the MIT License.

Model: https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b

sherpa-onnx: https://github.com/k2-fsa/sherpa-onnx

ONNX Runtime: https://github.com/microsoft/onnxruntime

OpenMDW 1.1: https://openmdw.ai/license/1-1/
