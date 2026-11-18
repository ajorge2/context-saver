# Portable embedding model provenance

The model derives from `ibm-granite/granite-embedding-small-english-r2`, licensed under Apache 2.0. The original ONNX graph came from `onnx-community/granite-embedding-small-english-r2-ONNX` at revision `1dc7835ba0cb9c76a3618d0bf0c427c97671b3c8`. Context Saver initially applied ONNX Runtime dynamic per-channel signed 8-bit weight quantization. The bundled v2 artifact re-encodes those existing weights in unsigned 8-bit form.

| Artifact | SHA-256 |
|---|---|
| Original signed v1 | `38842c5f27286dbe97d0674f1618def6cc7adf20d70e66923cbd7e34767155b4` |
| Portable unsigned v2 | `0a65b9f383a5da3833a7ecb16778bf27e04373f45a3af1c5919a4b87f51a4422` |

The v2 model contains 52,464,089 bytes. Its 84 `MatMulInteger` nodes consume 84 quantized weight tensors and 84 weight zero-point tensors. For every signed weight value `w` and zero point `z`, conversion applies `w_unsigned = w + 128` and `z_unsigned = z + 128`. The centered coefficient is exactly preserved because `(w + 128) - (z + 128) = w - z`. Every existing scale remains unchanged. This conversion requires no retraining or additional training data.

The conversion checks every signed initializer's consumers before changing it, verifies centered coefficients element by element, and runs the full ONNX checker with shape and type inference. Unsupported consumers cause conversion to fail. The unsigned form avoids the saturating signed-weight multiplication path documented for some x86 CPUs. [ONNX Runtime quantization guidance](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html#when-and-why-do-i-need-to-try-u8u8)

## Reproduction

Retrieve the original v1 model from the `v0.1.19` release. Run the conversion from this repository root with the optional conversion dependencies. The plugin runtime uses its existing inference dependencies.

```sh
uv run --no-project --python 3.12 \
  --with onnx==1.23.2 --with numpy==2.5.5 \
  python tools/convert_portable_model.py \
  --source /absolute/path/to/original-v1-model.onnx \
  --output /absolute/path/to/portable-v2-model.onnx
```

The tool verifies the original input checksum and writes a companion JSON report containing output checksum, byte size, converted pair count and dependency versions. It requires a separate output path.

## Validation recorded November 18, 2026

On arm64 macOS 26.5.1 with Python 3.12, FastEmbed 0.9.1 and ONNX Runtime 1.32.0, all 50 synthetic document embeddings and 50 query embeddings were bitwise identical between the signed and unsigned artifacts. Direct cosine search and native USearch each achieved 100% paraphrase Recall@5 on that diagnostic corpus. The existing bundled-model checksum and complete retrieval-gate tests both passed against a temporary copy of the v2 artifact.

Native Linux and Windows validation is pending at the time of this provenance entry. The native platform reports establish their platform-specific quality results.

[Base model](https://huggingface.co/ibm-granite/granite-embedding-small-english-r2) · [Pinned ONNX source](https://huggingface.co/onnx-community/granite-embedding-small-english-r2-ONNX/tree/1dc7835ba0cb9c76a3618d0bf0c427c97671b3c8) · [Apache 2.0 license](LICENSE-APACHE-2.0.txt)
