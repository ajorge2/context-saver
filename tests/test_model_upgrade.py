"""Upgrade embedding spaces without exposing a partial or destructive migration."""

from __future__ import annotations

from _support import SCRIPTS_ROOT

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state


OLD_MODEL = "granite-small-english-r2-int8-pc-v1"
OLD_SHA = "38842c5f27286dbe97d0674f1618def6cc7adf20d70e66923cbd7e34767155b4"
NEW_MODEL = "synthetic-upgrade-model-v2"


class UpgradeProvider:
    can_embed = True
    embedding_model = NEW_MODEL
    embedding_dimension = 3

    def __init__(self, *, fail_on: int | None = None, action=None):
        self.calls = 0
        self.fail_on = fail_on
        self.action = action

    def embed(self, texts, *, task):
        self.calls += 1
        if self.action is not None:
            self.action(self.calls)
        if self.calls == self.fail_on:
            raise RuntimeError("Synthetic model interruption")
        return [[0.0, 1.0, 0.0] for _ in texts]


class ModelUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="context-saver-model-upgrade-")
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / "data"
        self.data.mkdir()
        self.environment = patch.dict(os.environ, {"THREAD_HISTORY_TREE_DATA": str(self.data)})
        self.environment.start()
        (self.data / "config.json").write_text(json.dumps({
            "ollama_url": "fixture-no-network:",
            "fit_thresholds": {layer: 10_000 for layer in state.LAYERS},
        }), encoding="utf-8")
        thread_tree.save_scope_config({"configured": True, "projects": [{
            "path": str(self.root), "includeNewChats": True,
        }]})
        self.db = thread_tree.connect_db()
        self.project = state.project_id_for(str(self.root))
        state.ensure_project(self.db, self.project, str(self.root),
                             fit_thresholds={layer: 10_000 for layer in state.LAYERS})
        state.queue_turn(self.db, turn_id="old-turn", project_id=self.project,
                         thread_id="old-chat", content_hash="old-source")
        state.claim_next_turn(self.db, self.project)
        state.complete_turn_ingestion(self.db, "old-turn", [
            {"id": f"old-{number}", "text": f"Original deploy decision {number}",
             "embedding": [1.0, 0.0, 0.0], "embedding_model": OLD_MODEL,
             "source_message_ids": [f"source-{number}"], "line_start": number + 1, "line_end": number + 1}
            for number in range(65)
        ])
        pipeline.rebuild_project(self.db, self.project, reason="original model fixture")

    def tearDown(self) -> None:
        self.db.close()
        self.environment.stop()
        self.temporary.cleanup()

    def vectors(self) -> list[tuple]:
        return [tuple(row) for row in self.db.execute(
            "SELECT id, embedding, embedding_model, evicted FROM turn_chunks ORDER BY id",
        )]

    def sources(self) -> list[tuple]:
        return [tuple(row) for row in self.db.execute(
            """SELECT id, seq, project_id, thread_id, turn_id, text, content_hash, byte_count,
               source_message_ids, line_start, line_end, chunker_version, created_at
               FROM turn_chunks ORDER BY id""",
        )]

    def tree(self) -> list[tuple]:
        return [tuple(row) for row in self.db.execute("SELECT * FROM semantic_nodes ORDER BY id")]

    def test_failed_second_batch_preserves_all_old_vectors_sources_tree_and_fts(self) -> None:
        vectors, sources, tree = self.vectors(), self.sources(), self.tree()
        fts = [tuple(row) for row in self.db.execute("SELECT * FROM turn_chunks_fts ORDER BY rowid")]
        provider = UpgradeProvider(fail_on=2)
        with self.assertRaisesRegex(RuntimeError, "Synthetic model interruption"):
            pipeline._backfill_project_embeddings(self.db, self.project, provider)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(self.vectors(), vectors)
        self.assertEqual(self.sources(), sources)
        self.assertEqual(self.tree(), tree)
        self.assertEqual([tuple(row) for row in self.db.execute("SELECT * FROM turn_chunks_fts ORDER BY rowid")], fts)
        self.assertFalse(self.db.execute(
            "SELECT 1 FROM sqlite_temp_master WHERE name='embedding_upgrade_staging'",
        ).fetchone())

    def test_incomplete_or_invalid_model_output_never_publishes_partial_vectors(self) -> None:
        vectors = self.vectors()
        for replacement in ([], [[0.0, 1.0]] * 32, [[0.0, 0.0, 0.0]] * 32,
                            [[float("nan"), 1.0, 0.0]] * 32):
            with self.subTest(replacement=replacement):
                provider = UpgradeProvider()
                with patch.object(provider, "embed", return_value=replacement), self.assertRaises(RuntimeError):
                    pipeline._backfill_project_embeddings(self.db, self.project, provider)
                self.assertEqual(self.vectors(), vectors)

    def test_normal_worker_reports_a_failed_upgrade_and_preserves_the_previous_tree(self) -> None:
        vectors, sources, tree = self.vectors(), self.sources(), self.tree()
        with patch.object(thread_tree, "SemanticProvider", return_value=UpgradeProvider(fail_on=2)), \
             patch.object(pipeline.vector_index, "available", return_value=False):
            result = pipeline.process_project(self.project, max_turns=0)
        self.assertEqual(result["embedded_chunks"], 0)
        self.assertEqual(len(result["failures"]), 1)
        self.assertIn("embedding model upgrade", result["failures"][0])
        self.assertEqual(self.vectors(), vectors)
        self.assertEqual(self.sources(), sources)
        self.assertEqual(self.tree(), tree)

    def test_publication_failure_rolls_back_vectors_and_centroids_together(self) -> None:
        vectors, sources, tree = self.vectors(), self.sources(), self.tree()
        self.db.execute("""CREATE TEMP TRIGGER fail_centroid_upgrade
            BEFORE UPDATE OF embedding ON semantic_nodes BEGIN
            SELECT RAISE(ABORT, 'synthetic publication failure'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic publication failure"):
            pipeline._backfill_project_embeddings(self.db, self.project, UpgradeProvider())
        self.assertEqual(self.vectors(), vectors)
        self.assertEqual(self.sources(), sources)
        self.assertEqual(self.tree(), tree)
        self.db.execute("DROP TRIGGER fail_centroid_upgrade")
        self.assertEqual(pipeline._backfill_project_embeddings(self.db, self.project, UpgradeProvider()), 65)

    def test_success_publishes_one_space_and_keeps_evidence_while_scheduling_full_fit(self) -> None:
        vectors, sources = self.vectors(), self.sources()
        tree_fields = [tuple(row) for row in self.db.execute(
            "SELECT id, title, summary, generation_id FROM semantic_nodes ORDER BY id",
        )]
        prior_fit = state.schedule_global_rebuild(self.db, self.project, reason="old queued fit")

        def observe(call: int) -> None:
            self.assertEqual(self.vectors(), vectors)
            self.assertEqual(self.sources(), sources)

        self.assertEqual(pipeline._backfill_project_embeddings(
            self.db, self.project, UpgradeProvider(action=observe)), 65)
        self.assertEqual({row[2] for row in self.vectors()}, {NEW_MODEL})
        self.assertEqual({row[1] for row in self.vectors()}, {json.dumps([0.0, 1.0, 0.0])})
        self.assertEqual(self.sources(), sources)
        self.assertEqual([tuple(row) for row in self.db.execute(
            "SELECT id, title, summary, generation_id FROM semantic_nodes ORDER BY id",
        )], tree_fields)
        self.assertFalse(self.db.execute("SELECT 1 FROM semantic_nodes WHERE embedding IS NOT NULL").fetchone())
        self.assertEqual(self.db.execute("SELECT state FROM fit_runs WHERE id=?", (prior_fit["id"],)).fetchone()[0], "cancelled")
        pending = state._active_fit(self.db, self.project)
        self.assertEqual((pending["kind"], pending["state"]), ("rebalance", "queued"))
        self.assertIn(NEW_MODEL, pending["reason"])

    def test_process_project_upgrades_before_assigning_a_new_turn(self) -> None:
        transcript = self.root / "new-chat.jsonl"
        transcript.write_text("\n".join(json.dumps(row) for row in [
            {"type": "session_meta", "payload": {"session_id": "new-chat", "cwd": str(self.root)}},
            {"type": "response_item", "payload": {"type": "message", "id": "new-user", "role": "user",
                "content": [{"type": "input_text", "text": "Retain the new deploy decision."}]}},
            {"type": "response_item", "payload": {"type": "message", "id": "new-assistant", "role": "assistant",
                "content": [{"type": "output_text", "text": "The new deploy decision is violet."}]}},
        ]) + "\n", encoding="utf-8")
        pipeline.enqueue_transcript(transcript)
        initial = pipeline._initial_states
        observed = []

        def check_assignment(db, project_id, chunks):
            self.assertEqual({row[0] for row in db.execute(
                "SELECT DISTINCT embedding_model FROM turn_chunks WHERE evicted=0",
            )}, {NEW_MODEL})
            self.assertFalse(db.execute("SELECT 1 FROM semantic_nodes WHERE embedding IS NOT NULL").fetchone())
            self.assertEqual({chunk["embedding_model"] for chunk in chunks}, {NEW_MODEL})
            observed.append(True)
            initial(db, project_id, chunks)

        with patch.object(thread_tree, "SemanticProvider", return_value=UpgradeProvider()), \
             patch.object(pipeline.vector_index, "available", return_value=False), \
             patch.object(pipeline, "_initial_states", side_effect=check_assignment):
            result = pipeline.process_project(self.project)
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["processed_turns"], 1)
        self.assertEqual(result["embedded_chunks"], 65)
        self.assertEqual(observed, [True])
        self.assertFalse(state._active_fit(self.db, self.project))
        self.assertEqual({row[2] for row in self.vectors()}, {NEW_MODEL})

    def test_concurrent_deletion_eviction_and_changed_content_are_not_resurrected(self) -> None:
        def change(call: int) -> None:
            if call != 2:
                return
            with closing(thread_tree.connect_db()) as other, other:
                other.execute("DELETE FROM turn_chunks WHERE id='old-0'")
                other.execute("UPDATE turn_chunks SET evicted=1 WHERE id='old-2'")
                other.execute("UPDATE turn_chunks SET text='Corrected decision', content_hash='corrected' WHERE id='old-1'")

        pipeline._backfill_project_embeddings(self.db, self.project, UpgradeProvider(action=change))
        self.assertFalse(self.db.execute("SELECT 1 FROM turn_chunks WHERE id='old-0'").fetchone())
        self.assertEqual(tuple(self.db.execute(
            "SELECT evicted, embedding_model FROM turn_chunks WHERE id='old-2'",
        ).fetchone()), (1, OLD_MODEL))
        self.assertEqual(tuple(self.db.execute(
            "SELECT text, content_hash, embedding_model FROM turn_chunks WHERE id='old-1'",
        ).fetchone()), ("Corrected decision", "corrected", NEW_MODEL))
        self.assertEqual({row[0] for row in self.db.execute(
            "SELECT DISTINCT embedding_model FROM turn_chunks WHERE evicted=0",
        )}, {NEW_MODEL})

    def test_concurrent_project_removal_does_not_recreate_the_project_or_fit(self) -> None:
        def remove(call: int) -> None:
            if call == 2:
                with closing(thread_tree.connect_db()) as other, other:
                    other.execute("DELETE FROM projects WHERE id=?", (self.project,))

        self.assertEqual(pipeline._backfill_project_embeddings(
            self.db, self.project, UpgradeProvider(action=remove)), 0)
        for table in ("projects", "turn_chunks", "semantic_nodes", "fit_runs"):
            self.assertFalse(self.db.execute(f"SELECT 1 FROM {table}").fetchone(), table)

    def test_abrupt_worker_exit_preserves_old_generation_and_retry_finishes(self) -> None:
        vectors, sources, tree = self.vectors(), self.sources(), self.tree()
        code = """import os,sys
sys.path.insert(0, sys.argv[1])
import thread_tree
import thread_tree_pipeline as pipeline
class InterruptedProvider:
    can_embed = True
    embedding_model = 'synthetic-upgrade-model-v2'
    embedding_dimension = 3
    calls = 0
    def embed(self, texts, *, task):
        self.calls += 1
        if self.calls == 2:
            os._exit(37)
        return [[0.0, 1.0, 0.0] for text in texts]
db = thread_tree.connect_db()
pipeline._backfill_project_embeddings(db, sys.argv[2], InterruptedProvider())
"""
        child = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(SCRIPTS_ROOT), self.project],
                               env=dict(os.environ), capture_output=True, text=True, timeout=20)
        self.assertEqual(child.returncode, 37, child.stderr)
        self.assertEqual(self.vectors(), vectors)
        self.assertEqual(self.sources(), sources)
        self.assertEqual(self.tree(), tree)
        self.assertEqual(pipeline._backfill_project_embeddings(self.db, self.project, UpgradeProvider()), 65)
        self.assertEqual({row[2] for row in self.vectors()}, {NEW_MODEL})


class BuiltinConfigUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="context-saver-config-upgrade-")
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"THREAD_HISTORY_TREE_DATA": str(self.root)})
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def effective(self, config: dict) -> dict:
        path = self.root / "config.json"
        serialized = json.dumps(config)
        path.write_text(serialized, encoding="utf-8")
        result = thread_tree.load_config()
        self.assertEqual(path.read_text(encoding="utf-8"), serialized)
        return result

    def assert_current(self, config: dict) -> None:
        self.assertEqual(config["fastembed_model_version"], thread_tree.FASTEMBED_MODEL_VERSION)
        self.assertEqual(config["fastembed_model_sha256"], thread_tree.FASTEMBED_MODEL_SHA256)
        self.assertEqual(config["fastembed_model_path"], str(thread_tree.DEFAULT_FASTEMBED_MODEL_PATH))

    def test_persisted_old_builtin_defaults_follow_the_upgraded_bundle(self) -> None:
        self.assert_current(self.effective({"fastembed_model_version": OLD_MODEL, "fastembed_model_sha256": OLD_SHA}))

    def test_legacy_builtin_settings_follow_provider_case_and_empty_default_semantics(self) -> None:
        for provider in ("FastEmbed", "AUTO", None, ""):
            for empty in (None, ""):
                with self.subTest(provider=provider, empty=empty):
                    self.assert_current(self.effective({
                        "embedding_provider": provider, "fastembed_model": empty,
                        "fastembed_model_version": OLD_MODEL, "fastembed_model_sha256": empty,
                    }))

    def test_non_string_custom_provider_remains_selected_without_breaking_config_load(self) -> None:
        custom = ["custom-provider"]
        effective = self.effective({"embedding_provider": custom, "fastembed_model_version": OLD_MODEL})
        self.assertEqual(effective["embedding_provider"], custom)
        self.assertEqual(effective["fastembed_model_version"], OLD_MODEL)

    def test_recognized_old_bundle_path_and_pruned_native_cache_follow_current_bundle(self) -> None:
        old_bundle = self.root / "old-package" / "assets" / "models" / thread_tree.DEFAULT_FASTEMBED_MODEL_PATH.name
        old_bundle.mkdir(parents=True)
        (old_bundle / "MODEL.json").write_text(json.dumps({"name": OLD_MODEL, "model_sha256": OLD_SHA}), encoding="utf-8")
        self.assert_current(self.effective({"fastembed_model_path": str(old_bundle)}))
        old_cache = self.root / "plugins" / "cache" / "market" / "thread-tree" / "0.1.19" / "assets" / "models" / thread_tree.DEFAULT_FASTEMBED_MODEL_PATH.name
        self.assert_current(self.effective({"fastembed_model_path": str(old_cache), "fastembed_model_version": OLD_MODEL}))

    def test_genuine_custom_name_version_hash_or_path_remains_selected(self) -> None:
        for key, value in (
            ("fastembed_model", "my-custom-model"),
            ("fastembed_model_version", "custom-v1"),
            ("fastembed_model_sha256", "my-custom-checksum"),
            ("fastembed_model_path", str(self.root / "my-custom-model")),
        ):
            with self.subTest(key=key):
                config = {"fastembed_model_version": OLD_MODEL, "fastembed_model_sha256": OLD_SHA, key: value}
                effective = self.effective(config)
                for field, expected in config.items():
                    self.assertEqual(effective[field], expected)


if __name__ == "__main__":
    unittest.main()
