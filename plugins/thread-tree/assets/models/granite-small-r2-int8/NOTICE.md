# Model notice

This directory contains a locally quantized derivative of
`ibm-granite/granite-embedding-small-english-r2`, distributed under the Apache
License 2.0. The ONNX input artifact came from
`onnx-community/granite-embedding-small-english-r2-ONNX` at revision
`1dc7835ba0cb9c76a3618d0bf0c427c97671b3c8`.

Thread Tree changed the ONNX weights through ONNX Runtime dynamic per-channel
QInt8 quantization. On 2026-11-18, the signed weights and zero points were
re-encoded as unsigned 8-bit values while preserving every centered integer
coefficient. The conversion is recorded in `PROVENANCE.md`.
The base model's authors and upstream project are not
responsible for this modified artifact.

- Base model: https://huggingface.co/ibm-granite/granite-embedding-small-english-r2
- ONNX source: https://huggingface.co/onnx-community/granite-embedding-small-english-r2-ONNX
- License text: `LICENSE-APACHE-2.0.txt`

