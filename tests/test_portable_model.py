"""Verify unsigned weight conversion with optional offline authoring tools."""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("onnx"), "optional model conversion requires onnx==1.23.2")
class PortableModelConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        import numpy as np
        import onnx
        from onnx import TensorProto, helper, numpy_helper

        self.np = np
        self.onnx = onnx
        tool_path = Path(__file__).resolve().parents[1] / "tools/convert_portable_model.py"
        specification = importlib.util.spec_from_file_location("portable_model_converter", tool_path)
        self.tool = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(self.tool)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="context-saver-model-conversion-")))
        self.source = self.root / "original.onnx"
        self.destination = self.root / "candidate.onnx"
        weights = np.arange(-128, 128, dtype=np.int16).astype(np.int8).reshape(64, 4)
        zero_points = np.asarray([-128, -1, 0, 127], dtype=np.int8)
        self.weights = weights
        self.zero_points = zero_points
        graph = helper.make_graph(
            [helper.make_node("MatMulInteger", ["input", "weights", "input_zero", "weight_zero"], ["output"])],
            "signed-fixture",
            [helper.make_tensor_value_info("input", TensorProto.UINT8, [1, 64])],
            [helper.make_tensor_value_info("output", TensorProto.INT32, [1, 4])],
            initializer=[
                numpy_helper.from_array(weights, "weights"),
                numpy_helper.from_array(zero_points, "weight_zero"),
                numpy_helper.from_array(np.asarray(128, dtype=np.uint8), "input_zero"),
            ],
        )
        self.model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        onnx.save(self.model, self.source)

    def convert_fixture(self) -> dict:
        with patch.object(self.tool, "SOURCE_SHA256", self.tool.checksum(self.source)), contextlib.redirect_stdout(io.StringIO()):
            return self.tool.convert(self.source, self.destination)

    def test_every_signed_value_and_extreme_zero_points_preserve_integer_result(self) -> None:
        np = self.np
        result = self.convert_fixture()
        converted = self.onnx.load(self.destination)
        arrays = {value.name: self.onnx.numpy_helper.to_array(value) for value in converted.graph.initializer}
        self.assertEqual(arrays["weights"].dtype, np.uint8)
        self.assertEqual(arrays["weight_zero"].dtype, np.uint8)
        original_centered = self.weights.astype(np.int32) - self.zero_points.astype(np.int32)
        converted_centered = arrays["weights"].astype(np.int32) - arrays["weight_zero"].astype(np.int32)
        np.testing.assert_array_equal(converted_centered, original_centered)
        for input_value in (0, 127, 128, 255):
            inputs = np.full((1, 64), input_value, dtype=np.int32) - 128
            np.testing.assert_array_equal(inputs @ converted_centered, inputs @ original_centered)
        self.assertEqual(result["matmul_integer_pairs"], 1)
        self.assertEqual(result["converted_initializers"], 2)
        self.assertEqual(self.tool.checksum(self.source), result["source_sha256"])

    def test_extra_signed_tensor_consumer_is_rejected_before_output(self) -> None:
        self.model.graph.node.append(self.onnx.helper.make_node("Identity", ["weights"], ["extra_signed_consumer"]))
        self.onnx.save(self.model, self.source)
        with self.assertRaisesRegex(ValueError, "unsupported consumers"):
            self.convert_fixture()
        self.assertFalse(self.destination.exists())

    def test_unrecognized_source_and_overwrite_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unexpected input model checksum"):
            self.tool.convert(self.source, self.destination)
        with self.assertRaisesRegex(ValueError, "separate output path"):
            self.tool.convert(self.source, self.source)
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
