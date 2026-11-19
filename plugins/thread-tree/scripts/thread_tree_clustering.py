#!/usr/bin/env python3
"""Density clustering of supplied local embeddings, without another model.

Policy density-sqrt-v1 uses minimum support max(formation minimum, ceil(sqrt(n)))
and min_samples ceil(sqrt(n)/3), capped at five, at the current layer's grain.
Reused-projection synthetic experiments recover equal and unequal families
without the fixed size-two policy's hundreds of tiny groups or a target count.
See docs/density-clustering-experiments.json for evidence and reproduction.

Single-root selection requires every original vector's centroid cosine >=0.90.
A 90%-of-points relaxation swallowed a synthetic outlier and was rejected.
This strict guard can fragment a family with an outlier. Density projections
can also produce groups from diffuse input, and the adaptive support floor can
exclude minority families. Density and membership are not semantic guarantees.

Labels stay in HDBSCAN's native order so persistence and membership scores
cannot become detached when the presentation layer renames topics.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence


PROVIDER = "umap+hdbscan"
POLICY_VERSION = "density-sqrt-v1"
RANDOM_STATE = 42
SINGLE_CLUSTER_MIN_COSINE = 0.90


class DensityClusteringError(RuntimeError):
    """The required semantic fit runtime could not produce a valid result."""


@dataclass(frozen=True)
class DensityResult:
    labels: list[int]
    confidences: list[float]
    persistence: dict[int, float]
    provider: str = PROVIDER


def _load_runtime() -> tuple[Any, Any, Any]:
    try:
        import numpy as np
        from hdbscan import HDBSCAN
        from umap import UMAP
    except Exception as error:
        raise DensityClusteringError(
            "UMAP+HDBSCAN clustering is unavailable; install the pinned "
            "umap-learn and hdbscan runtime before fitting embedded evidence."
        ) from error
    return np, UMAP, HDBSCAN


def _probability(value: Any) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise DensityClusteringError("UMAP+HDBSCAN returned a non-finite confidence score.")
    return max(0.0, min(1.0, value))


def _two_direction_positions(
    vectors: Sequence[Sequence[float]], directions: Sequence[tuple[float, ...]],
) -> list[float]:
    """Embed exactly two directions on a line without changing any distance.

    Each pair is either identical (distance zero) or consists of the two
    prototypes (distance d). Coordinates 0 and d therefore preserve all
    Euclidean distances, multiplicities, and native density support. Keeping
    this geometry one-dimensional avoids HDBSCAN's >60D Prim backend.
    """

    if len(directions) != 2:
        raise ValueError("Exact line geometry requires two unique directions.")
    positions = {directions[0]: 0.0, directions[1]: math.dist(*directions)}
    return [positions[tuple(vector)] for vector in vectors]


def cluster_embeddings(
    vectors: Sequence[Sequence[float]], *, min_cluster_size: int,
) -> DensityResult:
    """Reduce supplied vectors with UMAP and fit native HDBSCAN once.

    Directionally identical samples have exact geometric cohesion and bypass
    UMAP, whose optimization would otherwise add artificial separation. Their
    score records that exact cohesion, rather than a native density estimate.
    HDBSCAN may select its single root only when every original unit vector is
    within cosine 0.90 of the batch centroid. This prevents UMAP's expansion of
    a cohesive family from requiring artificial subtopics, while diffuse input
    retains HDBSCAN's usual all-noise option. This is a conservative fit policy,
    not a calibrated semantic-quality threshold or required cluster count.
    UMAP embeds unique directions and restores duplicates to the same position.
    If only two directions remain, its neighborhood graph is undefined: run
    native HDBSCAN on an exact distance-preserving line embedding and name that
    provider. Every original normalized pairwise distance remains unchanged.
    Confidence is HDBSCAN's strength for the assigned cluster (probabilities_),
    rather than a full point-by-cluster soft-membership matrix.
    Invalid or incomplete vectors and native failures are explicit errors.
    """

    if min_cluster_size < 2:
        raise ValueError("min_cluster_size must be at least two")
    checked: list[list[float]] = []
    dimension: int | None = None
    for index, vector in enumerate(vectors):
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError, OverflowError) as error:
            raise DensityClusteringError(f"Invalid embedding at row {index}.") from error
        if not values or any(not math.isfinite(value) for value in values):
            raise DensityClusteringError(f"Empty or non-finite embedding at row {index}.")
        if dimension is not None and len(values) != dimension:
            raise DensityClusteringError("Cannot cluster embeddings with mixed dimensions.")
        dimension = len(values)
        magnitude = math.hypot(*values)
        if magnitude == 0 or not math.isfinite(magnitude):
            raise DensityClusteringError(f"Zero or invalid embedding magnitude at row {index}.")
        # Cosine UMAP uses direction. Normalization also detects equal-direction
        # evidence whose magnitude happened to differ at a centroid boundary.
        checked.append([value / magnitude for value in values])
    count = len(checked)
    noise = DensityResult([-1] * count, [0.0] * count, {})
    if count < min_cluster_size:
        return DensityResult(noise.labels, noise.confidences, {}, PROVIDER + "-insufficient-evidence")
    if all(all(abs(a - b) <= 1e-12 for a, b in zip(checked[0], vector)) for vector in checked[1:]):
        return DensityResult([0] * count, [1.0] * count, {0: 1.0}, "exact-embedding-cohesion")
    # UMAP truncates a two-point neighborhood to one, leaving no graph edges.
    if count < 3:
        return DensityResult(noise.labels, noise.confidences, {}, PROVIDER + "-insufficient-evidence")

    centroid = [math.fsum(vector[index] for vector in checked) for index in range(dimension or 0)]
    centroid_magnitude = math.hypot(*centroid)
    allow_single_cluster = bool(centroid_magnitude) and all(
        math.fsum(a * b for a, b in zip(vector, centroid)) / centroid_magnitude >= SINGLE_CLUSTER_MIN_COSINE
        for vector in checked
    )

    directions = list(dict.fromkeys(tuple(vector) for vector in checked))
    unique_count = len(directions)
    line_positions = _two_direction_positions(checked, directions) if unique_count == 2 else None
    del directions
    root_count = math.sqrt(count)
    density_minimum = max(min_cluster_size, math.ceil(root_count))
    density_samples = max(1, min(5, math.ceil(root_count / 3)))
    np, UMAP, HDBSCAN = _load_runtime()
    provider = PROVIDER
    try:
        if line_positions is not None:
            reduced = np.asarray(line_positions, dtype=np.float64).reshape(-1, 1)
            provider = "hdbscan-degenerate-geometry"
        else:
            reducer = UMAP(
                n_neighbors=min(15, unique_count - 1),
                # Spectral initialization needs components + 1 < sample count.
                n_components=max(2, min(5, unique_count - 2)),
                min_dist=0.0,
                metric="cosine",
                init="random" if unique_count <= 6 else "spectral",
                unique=True,
                random_state=RANDOM_STATE,
                n_jobs=1,
            )
            reduced = reducer.fit_transform(np.asarray(checked, dtype=np.float64))
        if not np.isfinite(reduced).all():
            raise DensityClusteringError("UMAP returned non-finite reduced embeddings.")
        model = HDBSCAN(
            min_cluster_size=density_minimum,
            min_samples=density_samples,
            metric="euclidean",
            cluster_selection_method="eom",
            allow_single_cluster=allow_single_cluster,
            prediction_data=True,
            approx_min_span_tree=False,
            core_dist_n_jobs=1,
        )
        labels = [int(value) for value in model.fit_predict(reduced)]
        if len(labels) != count:
            raise DensityClusteringError("HDBSCAN returned an incomplete assignment.")
        native_labels = sorted(set(labels) - {-1})
        persistences = model.cluster_persistence_
        persistence = {label: _probability(persistences[label]) for label in native_labels}
        if not native_labels:
            return DensityResult(noise.labels, noise.confidences, {}, provider)
        # This is strength for the assigned native label. It remains defined
        # for zero-radius duplicate clusters and tiny allowed root clusters,
        # and avoids allocating a dense point-by-cluster membership matrix.
        strengths = model.probabilities_
        if len(strengths) != count:
            raise DensityClusteringError("HDBSCAN returned incomplete membership strengths.")
        confidences = [_probability(strengths[index]) if label >= 0 else 0.0
                       for index, label in enumerate(labels)]
        return DensityResult(labels, confidences, persistence, provider)
    except DensityClusteringError:
        raise
    except Exception as error:
        raise DensityClusteringError(f"UMAP+HDBSCAN fit failed: {error}") from error
