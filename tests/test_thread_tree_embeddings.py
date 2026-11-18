#!/usr/bin/env python3

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import importlib.util
import json
import os
import statistics
import tempfile
import unittest
from pathlib import Path

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state
import thread_tree_vector_index as vector_index


class ThreadTreeEmbeddingIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        os.environ["THREAD_HISTORY_TREE_DATA"] = str(self.data)
        (self.data / "config.json").write_text(
            json.dumps({"ollama_url": "fixture-no-network:"}), encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def require_runtime(self) -> thread_tree.SemanticProvider:
        if importlib.util.find_spec("fastembed") is None or not vector_index.available():
            self.skipTest("pinned FastEmbed/USearch runtime is not installed")
        provider = thread_tree.SemanticProvider(thread_tree.load_config())
        if not provider.can_embed:
            self.skipTest("bundled local embedding model is unavailable")
        return provider

    def test_bundled_model_manifest_and_checksum(self) -> None:
        model_root = thread_tree.DEFAULT_FASTEMBED_MODEL_PATH
        manifest = json.loads((model_root / "MODEL.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], thread_tree.FASTEMBED_MODEL_VERSION)
        self.assertEqual(manifest["dimension"], thread_tree.FASTEMBED_DIMENSION)
        with (model_root / manifest["model_file"]).open("rb") as handle:
            digest = __import__("hashlib").file_digest(handle, "sha256").hexdigest()
        self.assertEqual(digest, thread_tree.FASTEMBED_MODEL_SHA256)
        self.assertEqual(digest, manifest["model_sha256"])

    def test_ann_persistence_and_full_retrieval_gates(self) -> None:
        provider = self.require_runtime()
        from embedding_provider_benchmark import CASES, NEGATIVE_QUERIES

        project_id = state.project_id_for(str(self.root))
        db = thread_tree.connect_db()
        state.ensure_project(
            db,
            project_id,
            str(self.root),
            fit_thresholds={layer: 10_000 for layer in state.LAYERS},
        )
        state.queue_turn(
            db,
            turn_id="embedding-fixture-turn",
            project_id=project_id,
            thread_id="embedding-fixture-thread",
            content_hash="embedding-fixture-hash",
        )
        state.claim_next_turn(db, project_id)
        documents: list[dict[str, object]] = []
        gold: dict[str, str] = {}
        obsolete: dict[str, str] = {}
        for case in CASES:
            current_id = f"current-{case.key}"
            obsolete_id = f"obsolete-{case.key}"
            gold[case.key] = current_id
            obsolete[case.key] = obsolete_id
            documents.extend(
                [
                    {"id": current_id, "text": case.current},
                    {"id": obsolete_id, "text": case.obsolete},
                ]
            )
        vectors = provider.embed([str(document["text"]) for document in documents], task="passage")
        self.assertEqual(len(vectors), len(documents))
        for document, vector in zip(documents, vectors):
            document["embedding"] = pipeline._normalize(vector)
            document["embedding_model"] = provider.embedding_model
        state.complete_turn_ingestion(db, "embedding-fixture-turn", documents)
        index = vector_index.rebuild_project_index(
            db,
            data_directory=self.data,
            project_id=project_id,
            model=provider.embedding_model,
            dimension=provider.embedding_dimension,
        )
        self.assertEqual(index["document_count"], len(documents))
        db.close()

        exact_ranks: list[int] = []
        paraphrase_ranks: list[int] = []
        exact_misses: list[tuple[str, str, list[str]]] = []
        paraphrase_misses: list[tuple[str, str, list[str]]] = []
        exact_current_wins = 0
        for case in CASES:
            for query in case.exact_queries:
                hits = pipeline.search_project(project_id, query, limit=5)
                ids = [str(hit["id"]) for hit in hits]
                exact_ranks.append(ids.index(gold[case.key]) + 1 if gold[case.key] in ids else 0)
                if gold[case.key] not in ids:
                    expanded = pipeline.search_project(project_id, query, limit=50)
                    gold_hit = next((hit for hit in expanded if hit["id"] == gold[case.key]), None)
                    exact_misses.append(
                        (
                            case.key,
                            query,
                            ids,
                            None if gold_hit is None else {
                                "rank": [hit["id"] for hit in expanded].index(gold[case.key]) + 1,
                                "score": gold_hit["score"],
                                "diagnostics": gold_hit["retrieval_diagnostics"],
                            },
                        )
                    )
                current_rank = ids.index(gold[case.key]) if gold[case.key] in ids else 99
                obsolete_rank = ids.index(obsolete[case.key]) if obsolete[case.key] in ids else 99
                exact_current_wins += int(current_rank < obsolete_rank)
                if hits:
                    details = hits[0]["retrieval_diagnostics"]
                    self.assertLessEqual(details.get("ann_candidates_visited", 0), 100)
                    self.assertLessEqual(details.get("delta_vectors_scanned", 0), 1000)
            for query in case.paraphrases:
                hits = pipeline.search_project(project_id, query, limit=5)
                ids = [str(hit["id"]) for hit in hits]
                paraphrase_ranks.append(ids.index(gold[case.key]) + 1 if gold[case.key] in ids else 0)
                if gold[case.key] not in ids:
                    paraphrase_misses.append((case.key, query, ids))
                if hits:
                    self.assertEqual(hits[0]["retrieval_diagnostics"]["fusion_mode"], "semantic")

        exact_recall = statistics.mean(rank > 0 for rank in exact_ranks)
        paraphrase_recall = statistics.mean(rank > 0 for rank in paraphrase_ranks)
        combined_mrr = statistics.mean(
            (1 / rank) if rank else 0 for rank in exact_ranks + paraphrase_ranks
        )
        uncovered = statistics.mean(
            not pipeline.search_project(project_id, query, limit=5)
            for query in NEGATIVE_QUERIES
        )
        self.assertGreaterEqual(exact_recall, 0.99, exact_misses)
        self.assertGreaterEqual(paraphrase_recall, 0.90, paraphrase_misses)
        self.assertGreaterEqual(
            round(combined_mrr, 2),
            0.90,
            {
                "exact_mrr": statistics.mean((1 / rank) if rank else 0 for rank in exact_ranks),
                "paraphrase_mrr": statistics.mean((1 / rank) if rank else 0 for rank in paraphrase_ranks),
                "combined_mrr": combined_mrr,
                "paraphrase_ranks": paraphrase_ranks,
            },
        )
        self.assertGreaterEqual(exact_current_wins / len(exact_ranks), 0.95)
        self.assertGreaterEqual(uncovered, 0.95)


if __name__ == "__main__":
    unittest.main()
