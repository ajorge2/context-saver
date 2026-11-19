"""Exercise semantic fit geometry without opening retained user data."""

from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from _support import PACKAGE_ROOT
import thread_tree_clustering as clustering
import thread_tree_pipeline as pipeline
import thread_tree_runtime as runtime


def rows_for(vectors):
    return [{"id": f"evidence-{index}", "text": f"Evidence {index}", "embedding": list(vector)}
            for index, vector in enumerate(vectors)]


class DensityContractTests(unittest.TestCase):
    def test_exact_line_preserves_every_pairwise_distance_across_original_dimensions(self):
        for dimension in (1, 2, 32, 384, 1024):
            with self.subTest(dimension=dimension):
                left = [1.0 / math.sqrt(dimension)] * dimension
                right = [-1.0] if dimension == 1 else [1.0] + [0.0] * (dimension - 1)
                vectors = [left, right, left, right, right, left]
                positions = clustering._two_direction_positions(vectors, [tuple(left), tuple(right)])
                for first in range(len(vectors)):
                    for second in range(len(vectors)):
                        self.assertEqual(math.dist(vectors[first], vectors[second]),
                                         abs(positions[first] - positions[second]))

    def test_exact_directional_duplicates_form_one_explicit_cohesion_group(self):
        with patch.object(clustering, "_load_runtime", side_effect=AssertionError("no invented projection")):
            result = clustering.cluster_embeddings([[1.0, 0.0], [2.0, 0.0]], min_cluster_size=2)
        self.assertEqual(result.labels, [0, 0])
        self.assertEqual(result.confidences, [1.0, 1.0])
        self.assertEqual(result.persistence, {0: 1.0})
        self.assertEqual(result.provider, "exact-embedding-cohesion")

    def test_below_formation_minimum_and_nonidentical_pair_remain_unassigned(self):
        for vectors, minimum in (([[1.0, 0.0]], 2), ([[1.0, 0.0], [0.0, 1.0]], 2),
                                 ([[1.0, 0.0]] * 3, 4)):
            with self.subTest(vectors=vectors, minimum=minimum):
                result = clustering.cluster_embeddings(vectors, min_cluster_size=minimum)
                self.assertEqual(result.labels, [-1] * len(vectors))
                self.assertEqual(result.confidences, [0.0] * len(vectors))

    def test_invalid_embeddings_fail_instead_of_switching_clustering_geometry(self):
        for vectors in (([1, 0], [1, 0, 0]), ([1, 0], [math.nan, 1]),
                        ([1, 0], [math.inf, 1]), ([1, 0], [0, 0]), ([1, 0], []),
                        ([1, 0], ["broken", 1])):
            with self.subTest(vectors=vectors), self.assertRaises(clustering.DensityClusteringError):
                clustering.cluster_embeddings(vectors, min_cluster_size=2)

    def test_required_runtime_failure_is_explicit_for_normal_embedded_fit(self):
        rows = rows_for([[1, index / 10, 0] for index in range(8)])
        with patch.object(clustering, "_load_runtime", side_effect=clustering.DensityClusteringError("runtime missing")), \
             patch.object(pipeline, "_deterministic_cluster_groups", side_effect=AssertionError("no silent fallback")):
            with self.assertRaisesRegex(clustering.DensityClusteringError, "runtime missing"):
                pipeline._cluster_groups(rows, "span")

    def test_noise_stays_unassigned_at_span_and_has_only_structural_upper_wrappers(self):
        rows = rows_for([[1, index / 10, 0] for index in range(8)])
        fitted = clustering.DensityResult([-1] * 8, [0.0] * 8, {})
        with patch.object(clustering, "cluster_embeddings", return_value=fitted):
            self.assertEqual(pipeline._cluster_groups(rows, "span"), [])
            for layer in ("specific", "broad"):
                groups = pipeline._cluster_groups(rows, layer)
                self.assertEqual([group["rows"] for group in groups], [[row] for row in rows])
                self.assertTrue(all(group["persistence"] == 0.0 for group in groups))
                self.assertTrue(all(group["provider"] == "umap+hdbscan-outlier-wrapper" for group in groups))

    def test_native_labels_map_persistence_and_confidence_without_frequency_remapping(self):
        rows = rows_for([[1, index / 10, 0] for index in range(5)])
        fitted = clustering.DensityResult([1, 1, 1, 0, -1], [.8, .7, .6, .9, 0], {0: .25, 1: .85})
        with patch.object(clustering, "cluster_embeddings", return_value=fitted):
            groups = pipeline._cluster_groups(rows, "specific")
        self.assertEqual([group["persistence"] for group in groups], [.85, .25, 0.0])
        self.assertEqual(groups[0]["confidences"], {"evidence-0": .8, "evidence-1": .7, "evidence-2": .6})
        self.assertEqual(groups[1]["confidences"], {"evidence-3": .9})

    def test_only_entirely_unembedded_input_uses_explicit_lexical_mode(self):
        rows = [{"id": str(index), "text": "same lexical evidence", "embedding": None} for index in range(8)]
        with patch.object(clustering, "_load_runtime", side_effect=AssertionError("lexical mode needs no native runtime")):
            groups = pipeline._cluster_groups(rows, "span")
        self.assertTrue(groups)
        self.assertEqual({group["provider"] for group in groups}, {"lexical-no-embeddings"})
        rows[0]["embedding"] = [1, 0]
        with self.assertRaises(clustering.DensityClusteringError):
            pipeline._cluster_groups(rows, "span")

    def test_all_launchers_and_requirements_use_same_pinned_clustering_runtime(self):
        args = json.loads((PACKAGE_ROOT / ".mcp.json").read_text())["mcpServers"]["thread-tree"]["args"]
        with patch.object(runtime.shutil, "which", return_value="uv"):
            worker = runtime.worker_command(Path("synthetic-worker.py"), "project-synthetic")
        for requirement in runtime.SEMANTIC_REQUIREMENTS:
            self.assertIn(requirement, args)
            self.assertIn(requirement, worker)
            for path in (PACKAGE_ROOT / "requirements.txt", PACKAGE_ROOT / "server" / "requirements.txt"):
                self.assertIn(requirement, path.read_text().splitlines())
        self.assertNotIn("bertopic", (PACKAGE_ROOT / "requirements.txt").read_text().lower())

    def test_rebuild_selects_density_runtime_without_initializing_embedding_model(self):
        import thread_tree
        for missing in ("umap", "hdbscan"):
            with self.subTest(missing=missing), \
                 patch.object(thread_tree.importlib.util, "find_spec", side_effect=lambda name: None if name == missing else object()), \
                 patch.object(thread_tree.shutil, "which", return_value="uv"), \
                 patch.object(thread_tree, "SemanticProvider", side_effect=AssertionError("runtime selection must not load a model")):
                command = thread_tree._connection_rebuild_command(Path("synthetic-rebuild.py"), "refresh-synthetic", ["project-synthetic"])
                self.assertEqual(command[0], "uv")
                for requirement in runtime.SEMANTIC_REQUIREMENTS:
                    self.assertIn(requirement, command)


class NativeDensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [name for name in ("numpy", "umap", "hdbscan") if importlib.util.find_spec(name) is None]
        if missing:
            if os.environ.get("CONTEXT_SAVER_REQUIRE_NATIVE_MODEL"):
                raise AssertionError(f"Native clustering release runtime missing: {missing}")
            raise unittest.SkipTest(f"Pinned native clustering runtime not installed: {missing}")
        import numpy as np
        cls.np = np

    def test_real_umap_and_hdbscan_recover_separated_families_reproducibly(self):
        np = self.np
        rng = np.random.default_rng(428)
        vectors = np.concatenate([rng.normal(0, .03, (30, 16)) + np.eye(16)[index] for index in range(3)])
        first = clustering.cluster_embeddings(vectors, min_cluster_size=2)
        second = clustering.cluster_embeddings(vectors, min_cluster_size=2)
        self.assertEqual(first, second)
        family_labels = [set(first.labels[start:start + 30]) for start in (0, 30, 60)]
        self.assertTrue(all(len(labels) == 1 and -1 not in labels for labels in family_labels))
        self.assertEqual(len(set.union(*family_labels)), 3)
        self.assertEqual(first.provider, "umap+hdbscan")
        self.assertTrue(all(0 <= value <= 1 for value in first.confidences))

    def test_imbalanced_native_families_preserve_all_five_known_topics(self):
        np = self.np
        rng = np.random.default_rng(287)
        sizes = [400, 30, 30, 30, 30]
        vectors = np.concatenate([rng.normal(0, .025, (size, 16)) + np.eye(16)[index]
                                  for index, size in enumerate(sizes)])
        result = clustering.cluster_embeddings(vectors, min_cluster_size=2)
        self.assertEqual(len(result.persistence), 5)
        self.assertNotIn(-1, result.labels)
        observed = []
        start = 0
        for size in sizes:
            labels = set(result.labels[start:start + size])
            self.assertEqual(len(labels), 1)
            observed.extend(labels)
            start += size
        self.assertEqual(len(set(observed)), 5)

    def test_real_tiny_fits_cannot_invent_undersized_clusters(self):
        for vectors in ([[1, 0], [0, 1]], [[1, 0], [0, 1], [-1, 0]]):
            with self.subTest(count=len(vectors)):
                result = clustering.cluster_embeddings(vectors, min_cluster_size=2)
                self.assertEqual(result.labels, [-1] * len(vectors))
                self.assertEqual(result.persistence, {})
                self.assertEqual(result.confidences, [0.0] * len(vectors))

    def test_four_points_can_form_two_native_density_pairs(self):
        result = clustering.cluster_embeddings([[1, 0], [1, .01], [0, 1], [.01, 1]], min_cluster_size=2)
        self.assertEqual(len(set(result.labels)), 2)
        self.assertNotIn(-1, result.labels)
        self.assertEqual(result.labels[0], result.labels[1])
        self.assertEqual(result.labels[2], result.labels[3])
        self.assertTrue(all(math.isfinite(value) and 0 <= value <= 1 for value in result.confidences))

    def test_tiny_cohesive_root_uses_valid_native_membership_strengths(self):
        for count in (3, 4):
            with self.subTest(count=count):
                result = clustering.cluster_embeddings([[1, index * .01] for index in range(count)], min_cluster_size=2)
                self.assertEqual(len(result.labels), count)
                self.assertEqual(set(result.labels) - {-1}, {0})
                self.assertTrue(all(math.isfinite(value) and 0 <= value <= 1 for value in result.confidences))

    def test_duplicate_families_keep_identical_points_together_with_native_strengths(self):
        np = self.np
        for family_count, provider in ((2, "hdbscan-degenerate-geometry"), (3, "umap+hdbscan")):
            with self.subTest(families=family_count):
                vectors = np.repeat(np.eye(family_count), 8, axis=0)
                result = clustering.cluster_embeddings(vectors, min_cluster_size=2)
                family_labels = [set(result.labels[start:start + 8]) for start in range(0, len(vectors), 8)]
                self.assertTrue(all(len(labels) == 1 and -1 not in labels for labels in family_labels))
                self.assertEqual(len(set.union(*family_labels)), family_count)
                self.assertEqual(result.confidences, [1.0] * len(vectors))
                self.assertEqual(result.provider, provider)

    def test_large_high_dimension_duplicate_families_use_exact_one_dimension_native_fit(self):
        np = self.np
        loaded = clustering._load_runtime()
        shapes = []

        class RecordingHDBSCAN(loaded[2]):
            def fit_predict(self, matrix):
                shapes.append(matrix.shape)
                return super().fit_predict(matrix)

        vectors = np.repeat(np.eye(384)[:2], 600, axis=0)
        with patch.object(clustering, "_load_runtime", return_value=(np, loaded[1], RecordingHDBSCAN)):
            result = clustering.cluster_embeddings(vectors, min_cluster_size=2)
        self.assertEqual(shapes, [(1200, 1)])
        self.assertEqual(len(set(result.labels[:600])), 1)
        self.assertEqual(len(set(result.labels[600:])), 1)
        self.assertNotEqual(result.labels[0], result.labels[600])
        self.assertNotIn(-1, result.labels)
        self.assertEqual(result.confidences, [1.0] * 1200)
        self.assertEqual(sorted(result.persistence.values()), [1.0, 1.0])
        self.assertEqual(result.provider, "hdbscan-degenerate-geometry")

    def test_cohesive_single_family_can_select_one_native_cluster(self):
        np = self.np
        vectors = np.random.default_rng(428).normal(0, .02, (80, 16)) + np.eye(16)[0]
        result = clustering.cluster_embeddings(vectors, min_cluster_size=2)
        self.assertEqual(set(result.labels) - {-1}, {0})
        self.assertGreaterEqual(result.labels.count(0), 75)
        self.assertEqual(result.provider, "umap+hdbscan")
        self.assertTrue(all(value == 0 for label, value in zip(result.labels, result.confidences) if label < 0))

    def test_diffuse_simplex_keeps_native_all_noise_option(self):
        np = self.np
        # Six distinct directions cannot form two size-four clusters. The
        # original-space guard must not permit one synthetic root cluster.
        result = clustering.cluster_embeddings(np.eye(6), min_cluster_size=4)
        self.assertEqual(result.labels, [-1] * 6)
        self.assertEqual(result.provider, "umap+hdbscan")
        self.assertEqual(result.persistence, {})

    def test_one_outlier_disables_single_root_guard_without_losing_native_scores(self):
        np = self.np
        vectors = np.concatenate([
            np.random.default_rng(428).normal(0, .02, (30, 16)) + np.eye(16)[0],
            [np.eye(16)[8]],
        ])
        loaded = clustering._load_runtime()
        calls = []
        def record_clusterer(**kwargs):
            calls.append(kwargs)
            return loaded[2](**kwargs)
        with patch.object(clustering, "_load_runtime", return_value=(*loaded[:2], record_clusterer)):
            result = clustering.cluster_embeddings(vectors, min_cluster_size=2)
        self.assertFalse(calls[0]["allow_single_cluster"])
        self.assertEqual(len(result.labels), 31)
        # A single outlier can leave the remaining family fragmented: the
        # guard is deliberately strict and does not promise semantic accuracy.
        self.assertTrue(all(math.isfinite(value) and 0 <= value <= 1 for value in result.confidences))

    def test_bridge_chain_does_not_merge_distinct_dense_families(self):
        np = self.np
        rng = np.random.default_rng(428)
        left = np.array([1., 0., 0., 0., 0., 0.])
        right = np.array([np.cos(1.8), np.sin(1.8), 0., 0., 0., 0.])
        bridge = np.array([[np.cos(angle), np.sin(angle), 0., 0., 0., 0.]
                           for angle in np.linspace(.08, 1.72, 12)])
        vectors = np.concatenate([
            rng.normal(0, .008, (30, 6)) + left,
            rng.normal(0, .008, (30, 6)) + right,
            bridge,
        ])
        rows = rows_for(vectors)
        # Neighbor-to-neighbor similarity chains the two cores together under
        # the former transitive connected-component rule.
        self.assertEqual(len(pipeline._components(rows, pipeline.SIMILARITY_THRESHOLDS["span"])), 1)
        result = clustering.cluster_embeddings(vectors, min_cluster_size=2)
        left_labels = set(result.labels[:30]) - {-1}
        right_labels = set(result.labels[30:60]) - {-1}
        self.assertTrue(left_labels and right_labels)
        self.assertFalse(left_labels & right_labels)

    def test_native_hierarchy_consumes_child_centroids_and_preserves_outlier_children(self):
        np = self.np
        rng = np.random.default_rng(428)
        vectors = np.concatenate([rng.normal(0, .03, (30, 16)) + np.eye(16)[index] for index in range(3)])
        children = rows_for(vectors)
        sizes = []
        for layer in ("span", "specific", "broad"):
            sizes.append(len(children))
            groups = pipeline._cluster_groups(children, layer)
            ids = [row["id"] for group in groups for row in group["rows"]]
            self.assertEqual(sorted(ids), sorted(row["id"] for row in children))
            children = [{
                "id": f"{layer}-{index}", "text": f"{layer} child centroid {index}",
                "embedding": pipeline._normalize(np.mean([row["embedding"] for row in group["rows"]], axis=0).tolist()),
            } for index, group in enumerate(groups)]
        self.assertEqual(sizes, [90, 3, 3])

    def test_fit_failure_surfaces_without_connected_components(self):
        np = self.np
        class BrokenReducer:
            def __init__(self, **kwargs):
                pass
            def fit_transform(self, matrix):
                raise ValueError("synthetic native fit failure")
        loaded = clustering._load_runtime()
        with patch.object(clustering, "_load_runtime", return_value=(np, BrokenReducer, loaded[2])):
            with self.assertRaisesRegex(clustering.DensityClusteringError, "synthetic native fit failure"):
                clustering.cluster_embeddings([[1, index / 10] for index in range(8)], min_cluster_size=2)


if __name__ == "__main__":
    unittest.main()
