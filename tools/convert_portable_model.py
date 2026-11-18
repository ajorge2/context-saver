"""Re-encode signed MatMulInteger weights as equivalent unsigned weights.

Run with onnx==1.23.2 and numpy==2.5.5. The unsigned representation avoids
the saturating U8S8 matrix multiplication path on older x86 CPUs. Every
centered integer weight is preserved exactly, along with its original scale.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, numpy_helper


SOURCE_SHA256 = "38842c5f27286dbe97d0674f1618def6cc7adf20d70e66923cbd7e34767155b4"


def checksum(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def convert(source: Path, destination: Path) -> dict:
    if source.resolve() == destination.resolve():
        raise ValueError("Choose a separate output path for the portable candidate")
    source_digest = checksum(source)
    if source_digest != SOURCE_SHA256:
        raise ValueError(f"Unexpected input model checksum {source_digest}")
    model = onnx.load(source)
    initializers = {tensor.name: tensor for tensor in model.graph.initializer}
    signed = {name for name, tensor in initializers.items() if tensor.data_type == TensorProto.INT8}
    consumers = defaultdict(list)
    approved = defaultdict(set)
    pairs = []
    for node_index, node in enumerate(model.graph.node):
        for input_index, name in enumerate(node.input):
            consumers[name].append((node_index, input_index))
        if node.op_type != "MatMulInteger" or node.domain or len(node.input) != 4:
            continue
        weight, zero_point = node.input[1], node.input[3]
        if weight in signed and zero_point in signed:
            approved[weight].add((node_index, 1))
            approved[zero_point].add((node_index, 3))
            pairs.append((weight, zero_point))
    if set(approved) != signed:
        raise ValueError(f"Signed tensors outside supported MatMulInteger pairs: {signed - set(approved)}")
    for name, allowed in approved.items():
        if set(consumers[name]) != allowed:
            raise ValueError(f"Initializer has unsupported consumers: {name}")

    converted = {}
    for name in signed:
        values = numpy_helper.to_array(initializers[name])
        converted[name] = (values.astype(np.int16) + 128).astype(np.uint8)
    for weight, zero_point in pairs:
        before = numpy_helper.to_array(initializers[weight]).astype(np.int16) - numpy_helper.to_array(initializers[zero_point]).astype(np.int16)
        after = converted[weight].astype(np.int16) - converted[zero_point].astype(np.int16)
        np.testing.assert_array_equal(after, before)
    for name, values in converted.items():
        initializers[name].CopyFrom(numpy_helper.from_array(values, name=name))
    for value in (*model.graph.input, *model.graph.value_info):
        if value.name in signed:
            value.type.tensor_type.elem_type = TensorProto.UINT8
    onnx.checker.check_model(model, full_check=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, destination)
    result = {
        "source_sha256": source_digest,
        "output_sha256": checksum(destination),
        "output_bytes": destination.stat().st_size,
        "matmul_integer_pairs": len(pairs),
        "converted_initializers": len(converted),
        "centered_integer_weights_preserved": True,
        "onnx_checker": "passed with full shape/type inference",
        "onnx_version": onnx.__version__,
        "numpy_version": np.__version__,
    }
    destination.with_suffix(destination.suffix + ".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="original signed v1 model with the pinned source SHA-256")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    convert(arguments.source, arguments.output)
