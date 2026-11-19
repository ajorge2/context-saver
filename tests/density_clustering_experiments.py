"""Regenerate synthetic density-policy evidence without reading retained data.

Run from the repository root with the pinned production requirements. One
actual production UMAP projection is captured per fixture and reused across
all HDBSCAN candidates; no candidate receives a different geometry.
"""

from __future__ import annotations

import argparse
from collections import Counter
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
from unittest.mock import patch

from _support import PACKAGE_ROOT
import thread_tree_clustering as clustering


def synthetic_fixtures(np):
    specs = [
        ("three_families_1200", 12846, [400, 400, 400], .025),
        ("three_families_90", 428, [30, 30, 30], .03),
        ("imbalanced_520", 287, [400, 30, 30, 30, 30], .025),
    ]
    for name, seed, sizes, deviation in specs:
        rng = np.random.default_rng(seed)
        matrix = np.concatenate([rng.normal(0, deviation, (size, 16)) + np.eye(16)[index]
                                 for index, size in enumerate(sizes)])
        yield name, matrix, np.repeat(np.arange(len(sizes)), sizes), {
            "seed": seed, "dimension": 16, "family_sizes": sizes,
            "center": "orthogonal unit basis vectors", "normal_stddev": deviation,
        }
    one = np.random.default_rng(428).normal(0, .02, (80, 16)) + np.eye(16)[0]
    spec = {"seed": 428, "dimension": 16, "family_sizes": [80],
            "center": "first unit basis vector", "normal_stddev": .02}
    yield "one_family_80", one, np.zeros(80, dtype=int), spec
    yield "one_family_80_plus_outlier", np.concatenate([one, [np.eye(16)[8]]]), np.array([0] * 80 + [1]), {
        **spec, "outlier": "one exact ninth unit basis vector",
    }
    yield "diffuse_120", np.random.default_rng(639).normal(0, 1, (120, 16)), None, {
        "seed": 639, "dimension": 16, "rows": 120, "normal_stddev": 1,
        "center": "zero; no semantic family ground truth",
    }


def run_experiments():
    np, UMAP, HDBSCAN = clustering._load_runtime()
    from sklearn.metrics import adjusted_rand_score

    report = {
        "schemaVersion": 1, "policyVersion": clustering.POLICY_VERSION,
        "evidence": "Synthetic vectors only; no retained history or private project data.",
        "method": "Capture one production UMAP projection per fixture; reuse it for every candidate.",
        "reproduce": "uv run --no-project --python 3.12 --with-requirements plugins/thread-tree/server/requirements.txt python tests/density_clustering_experiments.py --output docs/density-clustering-experiments.json",
        "runtime": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine(),
                    **{name: version(name) for name in ("umap-learn", "hdbscan", "numpy", "scipy", "scikit-learn", "numba", "pynndescent")}},
        "policies": {
            "old": "min_cluster_size=2; min_samples=1",
            "sqrt_proposed": "min_cluster_size=max(2,ceil(sqrt(n))); min_samples=max(1,min(10,ceil(sqrt(n)/2)))",
            "recommended": "min_cluster_size=max(formation_min,ceil(sqrt(n))); min_samples=max(1,min(5,ceil(sqrt(n)/3)))",
            "double_sqrt": "min_cluster_size=max(2,ceil(2*sqrt(n))); min_samples=max(1,min(10,ceil(sqrt(n)/2)))",
            "robust_guard_rejected": "Recommended sizes; allow_single_cluster when at least 90% have original centroid cosine >=0.90",
        },
        "two_direction_geometry_review": {
            "projection": "Place the first normalized prototype at 0 and the second at their original Euclidean distance d; expand by original row identity.",
            "distance_proof": "Every original pair is identical (distance 0) or contains both prototypes (distance d). The line preserves both values and every multiplicity.",
            "native_source": "https://hdbscan.readthedocs.io/en/latest/_modules/hdbscan/hdbscan_.html",
            "backend_evidence": "Pinned HDBSCAN chooses Prim KDTree above 60 dimensions and Boruvka KDTree for the exact one-dimensional geometry.",
            "measurement": "Historical bounded fit-only measurement on Darwin arm64, Python 3.12.13 and HDBSCAN 0.8.44; machine-specific observations, not performance assertions.",
            "fixture": "Two 384-dimensional normal prototypes from NumPy seed 819, normalized and repeated equally; approved adaptive parameters and exact spanning tree.",
            "observed_fits": [
                {"rows": 800, "original_384d_ms": 226.49, "exact_1d_ms": 6.05, "family_sizes": [400, 400], "strengths": [1.0], "persistences": [1.0, 1.0]},
                {"rows": 1600, "original_384d_ms": 823.4, "exact_1d_ms": 12.58, "family_sizes": [800, 800], "strengths": [1.0], "persistences": [1.0, 1.0]},
            ],
            "regressions": [
                "All pairwise distances preserved exactly across original dimensions 1, 2, 32, 384, 1024.",
                "Native production fit of 1200 duplicate 384D vectors receives one dimension, preserves two pure 600-row families and native unit strengths/persistence.",
            ],
        },
        "limitations": [
            "The strict single-root guard can fragment a coherent family when one outlier is present.",
            "The robust 90%-of-points guard absorbs the synthetic outlier; it is not adopted.",
            "Diffuse vectors still form density groups; neither density nor membership proves semantic meaning.",
            "An adaptive support floor can omit or merge smaller minority families as input size grows.",
            "These fixtures justify defaults, not a universal optimum or private-corpus quality claim.",
        ],
        "fixtures": [],
    }
    for name, vectors, truth, spec in synthetic_fixtures(np):
        captured = {}

        class CaptureUMAP:
            def __init__(self, **kwargs):
                captured["umap_parameters"] = kwargs
                self.model = UMAP(**kwargs)

            def fit_transform(self, matrix):
                captured["original"] = matrix
                captured["reduced"] = self.model.fit_transform(matrix)
                return captured["reduced"]

        def capture_hdbscan(**kwargs):
            captured["hdbscan_parameters"] = kwargs
            return HDBSCAN(**kwargs)

        with patch.object(clustering, "_load_runtime", return_value=(np, CaptureUMAP, capture_hdbscan)):
            clustering.cluster_embeddings(vectors, min_cluster_size=2)
        count = len(vectors)
        root = math.sqrt(count)
        parameters = captured["hdbscan_parameters"]
        centroid = captured["original"].sum(axis=0)
        centroid /= np.linalg.norm(centroid)
        cohesive_fraction = float(np.mean(captured["original"] @ centroid >= .90))
        candidates = [
            ("old", 2, 1, parameters["allow_single_cluster"]),
            ("sqrt_proposed", max(2, math.ceil(root)), max(1, min(10, math.ceil(root / 2))), parameters["allow_single_cluster"]),
            ("recommended", max(2, math.ceil(root)), max(1, min(5, math.ceil(root / 3))), parameters["allow_single_cluster"]),
            ("double_sqrt", max(2, math.ceil(root * 2)), max(1, min(10, math.ceil(root / 2))), parameters["allow_single_cluster"]),
            ("robust_guard_rejected", max(2, math.ceil(root)), max(1, min(5, math.ceil(root / 3))), cohesive_fraction >= .90),
        ]
        fixture = {"name": name, "generation": spec, "original_cohesive_fraction": round(cohesive_fraction, 6),
                   "umap_parameters": captured["umap_parameters"], "results": []}
        for candidate, minimum, samples, single in candidates:
            model = HDBSCAN(**{**parameters, "min_cluster_size": minimum, "min_samples": samples, "allow_single_cluster": single})
            labels = model.fit_predict(captured["reduced"])
            sizes = Counter(int(label) for label in labels if label >= 0)
            assigned = labels >= 0
            purity = None
            ari = None
            if truth is not None and assigned.any():
                purity = sum(max(Counter(truth[labels == label]).values()) for label in sizes) / int(assigned.sum())
                if min(Counter(truth).values()) > 1 and len(set(truth)) > 1:
                    ari = float(adjusted_rand_score(truth, labels))
            fixture["results"].append({
                "candidate": candidate, "minimum": minimum, "min_samples": samples, "allow_single_cluster": bool(single),
                "groups": len(sizes), "assigned": int(assigned.sum()), "coverage": round(float(assigned.mean()), 3),
                "purity": round(purity, 3) if purity is not None else None,
                "adjusted_rand_index": round(ari, 3) if ari is not None else None,
                "group_size_histogram": dict(sorted(Counter(sizes.values()).items())),
                "outlier_is_noise": bool(labels[-1] < 0) if "outlier" in name else None,
            })
        report["fixtures"].append(fixture)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PACKAGE_ROOT.parents[1] / "test-reports" / "density-clustering-experiments.json")
    args = parser.parse_args()
    report = run_experiments()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(report['fixtures'])} synthetic fixture comparisons to {args.output}")
