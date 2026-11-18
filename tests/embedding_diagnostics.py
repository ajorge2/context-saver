"""Compare native embedding geometry, exact cosine and ANN on synthetic cases."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import tempfile

from _support import PACKAGE_ROOT
from embedding_provider_benchmark import CASES
import thread_tree
import thread_tree_vector_index as ann


def capture(output: Path, *, provider=None, source_vectors=None) -> dict:
    import numpy as np
    import onnxruntime as ort

    keys = [f"{kind}-{case.key}" for case in CASES for kind in ("current", "obsolete")]
    texts = [text for case in CASES for text in (case.current, case.obsolete)]
    queries = [(case.key, query) for case in CASES for query in case.paraphrases]
    if provider is None:
        config = thread_tree.load_config()
        config["ollama_url"] = "fixture-no-network:"
        provider = thread_tree.SemanticProvider(config)
    if not provider.can_embed:
        raise RuntimeError("Native bundled model is required for diagnostics")

    raw_documents = np.asarray(source_vectors if source_vectors is not None else provider.embed(texts), dtype=np.float32)
    raw_queries = np.asarray([provider.embed([query], task="query")[0] for _, query in queries], dtype=np.float32)
    document_norms = np.linalg.norm(raw_documents, axis=1)
    query_norms = np.linalg.norm(raw_queries, axis=1)
    documents = raw_documents / document_norms[:, None]
    query_vectors = raw_queries / query_norms[:, None]
    similarities = query_vectors @ documents.T
    document_pairs = documents @ documents.T
    index = ann._new_index(documents.shape[1])
    index.add(np.arange(len(keys), dtype=np.uint64), documents)
    exact_hits = 0
    ann_hits = 0
    records = []
    for (case_key, query), vector, scores in zip(queries, query_vectors, similarities):
        exact = np.argsort(-scores, kind="stable")[:5]
        matches = index.search(vector, 5, exact=True)
        native_keys = [int(key) for key in matches.keys]
        expected = f"current-{case_key}"
        exact_hits += expected in [keys[int(key)] for key in exact]
        ann_hits += expected in [keys[key] for key in native_keys]
        records.append({
            "query": query, "expected": expected,
            "exact": [{"id": keys[int(key)], "cosine": float(scores[key])} for key in exact],
            "ann": [{"id": keys[key], "cosine": float(scores[key])} for key in native_keys],
        })

    singleton_documents = np.asarray([provider.embed([text])[0] for text in texts[:8]], dtype=np.float32)
    singleton_documents /= np.linalg.norm(singleton_documents, axis=1)[:, None]
    batch_queries = np.asarray(provider.embed([query for _, query in queries], task="query"), dtype=np.float32)
    batch_queries /= np.linalg.norm(batch_queries, axis=1)[:, None]
    cpu_file = Path("/proc/cpuinfo")
    cpu = {}
    if cpu_file.is_file():
        for line in cpu_file.read_text().split("\n\n", 1)[0].splitlines():
            key, _, value = line.partition(":")
            if key.strip() in {"model name", "vendor_id", "flags", "cpu family", "model", "stepping"}:
                cpu[key.strip()] = value.strip()
    model = provider._load_fastembed()
    session = getattr(getattr(model, "model", None), "model", None)
    with (thread_tree.DEFAULT_FASTEMBED_MODEL_PATH / "onnx/model.onnx").open("rb") as artifact:
        model_checksum = hashlib.file_digest(artifact, "sha256").hexdigest()
    report = {
        "platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
        "cpu": cpu,
        "versions": {name: importlib.metadata.version(name) for name in ("fastembed", "onnxruntime", "numpy", "tokenizers", "usearch")},
        "available_providers": ort.get_available_providers(),
        "selected_providers": session.get_providers() if session is not None else None,
        "provider_options": session.get_provider_options() if session is not None else None,
        "provider_label": provider.label,
        "model_sha256": model_checksum,
        "finite": bool(np.isfinite(documents).all() and np.isfinite(query_vectors).all()),
        "document_norm_range": [float(document_norms.min()), float(document_norms.max())],
        "query_norm_range": [float(query_norms.min()), float(query_norms.max())],
        "document_pair_cosine_range": [float(document_pairs.min()), float(document_pairs[np.triu_indices(len(keys), 1)].max())],
        "document_pair_cosine_mean": float(document_pairs[np.triu_indices(len(keys), 1)].mean()),
        "document_batch_singleton_cosines": [float(value) for value in np.sum(documents[:8] * singleton_documents, axis=1)],
        "query_batch_singleton_cosines": [float(value) for value in np.sum(query_vectors * batch_queries, axis=1)],
        "brute_force_paraphrase_recall_at_5": exact_hits / len(queries),
        "ann_paraphrase_recall_at_5": ann_hits / len(queries),
        "records": records,
    }
    output.mkdir(parents=True, exist_ok=True)
    np.savez(output / "embedding-vectors.npz", documents=documents, queries=query_vectors,
             document_keys=np.asarray(keys), query_texts=np.asarray([query for _, query in queries]))
    (output / "embedding-diagnostics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("platform", "processor", "brute_force_paraphrase_recall_at_5", "ann_paraphrase_recall_at_5", "document_batch_singleton_cosines")}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("CONTEXT_SAVER_TEST_REPORTS", "test-reports")))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="context-saver-embedding-diagnostics-") as directory:
        os.environ["THREAD_HISTORY_TREE_DATA"] = directory
        capture(args.output)
