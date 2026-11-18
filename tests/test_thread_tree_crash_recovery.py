#!/usr/bin/env python3
"""Restart production indexing code against a disk store after abrupt exits."""

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import errno
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_rebuild as rebuild
import thread_tree_state as state
import thread_tree_vector_index as vector_index


CRASH_EXIT = 86
HIGH_THRESHOLDS = dict.fromkeys(state.LAYERS, 1000)
TURN_CHUNKS = (
    {"id": "pending-left", "text": "faultsentinel mailbox evidence first", "source_message_ids": ["left"]},
    {"id": "pending-right", "text": "faultsentinel mailbox evidence second", "source_message_ids": ["right"]},
)


def crash_at_boundary() -> None:
    # Bypass Python stack unwinding and Connection.__exit__, like a killed worker.
    os._exit(CRASH_EXIT)


def crash_before_statement(db: sqlite3.Connection, predicate: Callable[[str], bool]) -> None:
    def observe(statement: str) -> None:
        if predicate(" ".join(statement.split())):
            crash_at_boundary()

    db.set_trace_callback(observe)


def run_child(operation: str, project_id: str, target_id: str, boundary: str) -> None:
    with closing(thread_tree.connect_db()) as db:
        if operation == "turn":
            turn = state.claim_next_turn(db, project_id, lease_seconds=-1)
            if turn is None or turn["id"] != target_id:
                raise AssertionError(f"did not claim fixture turn {target_id}")
            if boundary == "claimed":
                crash_at_boundary()
            if boundary != "committed":
                crash_before_statement(db, lambda sql: sql.startswith(boundary))
            state.complete_turn_ingestion(db, target_id, TURN_CHUNKS, lease_token=turn["lease_token"])
            if boundary == "committed":
                crash_at_boundary()
        elif operation == "fit":
            if boundary == "after_publish":
                original = pipeline._finish_fit_phase

                def finish(*args: Any, **kwargs: Any) -> None:
                    if args[2] == "commit_state":
                        crash_at_boundary()
                    original(*args, **kwargs)

                with patch.object(pipeline, "_finish_fit_phase", finish):
                    pipeline.run_fit(db, target_id)
            elif boundary == "before_commit":
                wrote_tree_pointer = False

                def at_commit(sql: str) -> bool:
                    nonlocal wrote_tree_pointer
                    if sql.startswith("INSERT INTO project_active_tree"):
                        wrote_tree_pointer = True
                    return wrote_tree_pointer and sql == "COMMIT"

                crash_before_statement(db, at_commit)
                pipeline.run_fit(db, target_id)
            else:
                crash_before_statement(db, lambda sql: sql.startswith(boundary))
                pipeline.run_fit(db, target_id)
        elif operation == "retention":
            if boundary == "after_tombstone":
                original_mark = state.mark_turns_evicted

                def mark(*args: Any, **kwargs: Any) -> list[str]:
                    original_mark(*args, **kwargs)
                    crash_at_boundary()

                with patch.object(state, "mark_turns_evicted", mark):
                    pipeline.process_project(project_id, max_turns=0)
            elif boundary == "after_retention_publish":
                original_fit = pipeline._run_fit_locked

                def fit(*args: Any, **kwargs: Any) -> dict[str, Any]:
                    original_fit(*args, **kwargs)
                    crash_at_boundary()

                with patch.object(pipeline, "_run_fit_locked", fit):
                    pipeline.process_project(project_id, max_turns=0)
            elif boundary == "between_cleanup_deletes":
                def traced_connection() -> sqlite3.Connection:
                    connection = original_connect()
                    crash_before_statement(connection, lambda sql: sql.startswith("DELETE FROM turn_chunks WHERE"))
                    return connection

                original_connect = thread_tree.connect_db
                with patch.object(thread_tree, "connect_db", traced_connection):
                    pipeline.process_project(project_id, max_turns=0)
        elif operation == "vector":
            if boundary == "after_binary":
                with patch.object(vector_index, "_atomic_json", side_effect=lambda *_: crash_at_boundary()):
                    vector_index.rebuild_project_index(
                        db, data_directory=thread_tree.data_dir(), project_id=project_id, model="fault-fixture", dimension=2,
                    )
            elif boundary == "after_manifest":
                crash_before_statement(db, lambda sql: sql.startswith("INSERT INTO index_shards"))
                vector_index.rebuild_project_index(
                    db, data_directory=thread_tree.data_dir(), project_id=project_id, model="fault-fixture", dimension=2,
                )
        elif operation == "vector-lock":
            with vector_index._write_lock(thread_tree.data_dir(), project_id):
                crash_at_boundary()
        elif operation == "connection-job":
            if boundary == "after_fit_claim":
                with patch.object(pipeline, "_fit_rows_for_layer", side_effect=lambda *_: crash_at_boundary()):
                    rebuild.main([target_id, project_id])
            if boundary == "after_fit_commit":
                original_rebuild = pipeline.rebuild_project

                def finished(*args: Any, **kwargs: Any) -> None:
                    original_rebuild(*args, **kwargs)
                    crash_at_boundary()

                with patch.object(pipeline, "rebuild_project", finished):
                    rebuild.main([target_id, project_id])
    raise AssertionError(f"requested crash boundary never ran: {operation}/{boundary}")


class ThreadTreeCrashRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="thread-tree-crash-test-")))
        self.project_path = self.root / "project"
        self.project_path.mkdir()
        self.project_id = state.project_id_for(str(self.project_path))
        data = self.root / "store"
        data.mkdir()
        self.enterContext(patch.dict(os.environ, {"THREAD_HISTORY_TREE_DATA": str(data)}))
        (data / "config.json").write_text(json.dumps({
            "ollama_url": "fixture-no-network:",
            "fastembed_model_path": str(data / "model-not-installed"),
            "fit_thresholds": HIGH_THRESHOLDS,
        }), encoding="utf-8")
        with closing(thread_tree.connect_db()) as db:
            state.ensure_project(db, self.project_id, str(self.project_path), fit_thresholds=HIGH_THRESHOLDS)

    def crash(self, operation: str, boundary: str, target_id: str = "") -> None:
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--crash-child", operation,
             self.project_id, target_id, boundary],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(child.returncode, CRASH_EXIT, f"{operation}/{boundary}: {child.stderr}{child.stdout}")

    def queue_turn(self, db: sqlite3.Connection, turn_id: str, *, protected: bool = False) -> None:
        state.queue_turn(
            db, turn_id=turn_id, project_id=self.project_id, thread_id=f"chat-{turn_id}",
            content_hash=f"content-{turn_id}", protected=protected,
        )

    def seed_turn(self, db: sqlite3.Connection, turn_id: str, marker: str, *, protected: bool = False) -> None:
        self.queue_turn(db, turn_id, protected=protected)
        claim = state.claim_next_turn(db, self.project_id)
        self.assertIsNotNone(claim)
        self.assertEqual(claim["id"], turn_id)
        state.complete_turn_ingestion(db, turn_id, [
            {
                "id": f"{turn_id}-{index}",
                "text": f"{marker} semantic memory retrieval archive evidence numbered {index}",
                "source_message_ids": [f"{turn_id}-message-{index}"],
            }
            for index in range(3)
        ])

    def assert_integrity(self, db: sqlite3.Connection) -> None:
        self.assertEqual([row[0] for row in db.execute("PRAGMA integrity_check")], ["ok"])
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        db.execute("INSERT INTO turn_chunks_fts(turn_chunks_fts) VALUES ('integrity-check')")
        db.commit()

    def turn_rows(self, db: sqlite3.Connection, turn_id: str) -> sqlite3.Row:
        return db.execute("SELECT * FROM turn_ingestion WHERE id=?", (turn_id,)).fetchone()

    def assert_pending_turn_complete(self, db: sqlite3.Connection, *, attempts: int) -> None:
        turn = self.turn_rows(db, "pending")
        self.assertEqual((turn["state"], turn["attempts"], turn["lease_token"]), ("indexed", attempts, None))
        chunks = db.execute("SELECT id, source_message_ids FROM turn_chunks WHERE turn_id='pending' ORDER BY id")
        self.assertEqual([tuple(row) for row in chunks], [("pending-left", '["left"]'), ("pending-right", '["right"]')])
        for table in ("chunk_layer_states", "fit_debt_events"):
            self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 6)
        indexed = db.execute("SELECT chunk_id FROM turn_chunks_fts WHERE turn_chunks_fts MATCH 'faultsentinel'")
        self.assertEqual({row[0] for row in indexed}, {"pending-left", "pending-right"})
        self.assert_integrity(db)

    def assert_turn_rollback_and_retry(self, boundary: str) -> None:
        with closing(thread_tree.connect_db()) as db:
            self.queue_turn(db, "pending")
        self.crash("turn", boundary, "pending")
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(self.turn_rows(db, "pending")["state"], "processing")
            for table in ("turn_chunks", "turn_chunks_fts", "chunk_layer_states", "fit_debt_events"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
            self.assert_integrity(db)
            successor = state.claim_next_turn(db, self.project_id)
            self.assertIsNotNone(successor)
            self.assertEqual(successor["id"], "pending")
            state.complete_turn_ingestion(db, "pending", TURN_CHUNKS, lease_token=successor["lease_token"])
        with closing(thread_tree.connect_db()) as db:
            self.assert_pending_turn_complete(db, attempts=2)

    def test_crash_after_turn_claim_releases_expired_lease_on_restart(self) -> None:
        self.assert_turn_rollback_and_retry("claimed")

    def test_crash_inside_turn_transaction_leaves_no_partial_chunk_indexes(self) -> None:
        self.assert_turn_rollback_and_retry("UPDATE turn_ingestion SET state = 'indexed'")

    def test_crash_after_turn_commit_preserves_exactly_once_indexing(self) -> None:
        with closing(thread_tree.connect_db()) as db:
            self.queue_turn(db, "pending")
        self.crash("turn", "committed", "pending")
        with closing(thread_tree.connect_db()) as db:
            self.assert_pending_turn_complete(db, attempts=1)
            self.queue_turn(db, "pending")
            self.assertIsNone(state.claim_next_turn(db, self.project_id))
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 0)

    def test_reclaimed_turn_rejects_stale_workers_success_and_error(self) -> None:
        with closing(thread_tree.connect_db()) as worker, closing(thread_tree.connect_db()) as successor:
            self.queue_turn(worker, "pending")
            old_claim = state.claim_next_turn(worker, self.project_id, lease_seconds=-1)
            new_claim = state.claim_next_turn(successor, self.project_id)
            self.assertNotEqual(old_claim["lease_token"], new_claim["lease_token"])
            with self.assertRaises(state.LostTurnLeaseError):
                state.complete_turn_ingestion(worker, "pending", TURN_CHUNKS, lease_token=old_claim["lease_token"])
            with self.assertRaises(state.LostTurnLeaseError):
                state.transition_turn(worker, "pending", "failed", "stale error", lease_token=old_claim["lease_token"])
            self.assertEqual(self.turn_rows(successor, "pending")["lease_token"], new_claim["lease_token"])
            self.assertEqual(successor.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0], 0)
            state.complete_turn_ingestion(successor, "pending", TURN_CHUNKS, lease_token=new_claim["lease_token"])
            with self.assertRaises(state.LostTurnLeaseError):
                state.transition_turn(worker, "pending", "failed", "late stale error", lease_token=old_claim["lease_token"])
            self.assert_pending_turn_complete(successor, attempts=2)

    def test_sqlite_full_rolls_back_turn_then_restart_recovers_lease(self) -> None:
        with closing(thread_tree.connect_db()) as db:
            self.seed_turn(db, "prior", "priormarker")
            self.queue_turn(db, "pending")
            claim = state.claim_next_turn(db, self.project_id, lease_seconds=-1)
            page_count = db.execute("PRAGMA page_count").fetchone()[0]
            original_limit = db.execute("PRAGMA max_page_count").fetchone()[0]
            limit = db.execute(f"PRAGMA max_page_count={page_count}").fetchone()[0]
            self.assertEqual(limit, page_count)
            oversized = {"id": "too-large", "text": "overflow text " * page_count * 512}
            with self.assertRaises(sqlite3.OperationalError) as failure:
                state.complete_turn_ingestion(
                    db, "pending", [TURN_CHUNKS[0], oversized], lease_token=claim["lease_token"],
                )
            self.assertEqual(failure.exception.sqlite_errorcode, sqlite3.SQLITE_FULL)
            db.execute(f"PRAGMA max_page_count={original_limit}")
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(self.turn_rows(db, "pending")["state"], "processing")
            self.assertEqual({row[0] for row in db.execute("SELECT DISTINCT turn_id FROM turn_chunks")}, {"prior"})
            self.assertFalse(list(db.execute("SELECT chunk_id FROM turn_chunks_fts WHERE turn_chunks_fts MATCH 'faultsentinel'")))
            self.assert_integrity(db)
            current = state.claim_next_turn(db, self.project_id)
            self.assertEqual(current["attempts"], 2)
            state.complete_turn_ingestion(db, "pending", TURN_CHUNKS, lease_token=current["lease_token"])
            self.assert_integrity(db)
        self.assertEqual({row["turn_id"] for row in pipeline.search_project(self.project_id, "faultsentinel")}, {"pending"})
        self.assertEqual({row["turn_id"] for row in pipeline.search_project(self.project_id, "priormarker")}, {"prior"})

    def write_rollout(self, path: Path, chat: str, text: str, project: Path | None = None) -> None:
        rows = [
            {"type": "session_meta", "payload": {"session_id": chat, "cwd": str(project or self.project_path)}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message", "id": f"{chat}-user", "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message", "id": f"{chat}-assistant", "role": "assistant",
                    "content": [{"type": "output_text", "text": "File the final decision in local memory."}],
                },
            },
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def activate_fixture_project(self) -> None:
        thread_tree.save_scope_config({
            "configured": True,
            "projects": [{"path": str(self.project_path), "includeNewChats": True}],
        })

    def test_worker_recovers_from_sqlite_full_on_its_next_pass(self) -> None:
        path = self.root / "full.jsonl"
        self.write_rollout(path, "chat-full", "recoverablesqlite " + "long text " * 40_000)
        queued = pipeline.enqueue_transcript(path)
        turn_id = queued["turn_ids"][0]
        with closing(thread_tree.connect_db()) as db:
            page_count = db.execute("PRAGMA page_count").fetchone()[0]
            original_limit = db.execute("PRAGMA max_page_count").fetchone()[0]
            self.assertEqual(db.execute(f"PRAGMA max_page_count={page_count}").fetchone()[0], page_count)
            try:
                result = pipeline._process_project(db, self.project_id, max_turns=None, thread_id=None)
                self.assertEqual(result["processed_turns"], 0)
                self.assertEqual(len(result["failures"]), 1)
                self.assertIn("database or disk is full", result["failures"][0])
                self.assertEqual(self.turn_rows(db, turn_id)["attempts"], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks_fts").fetchone()[0], 0)
            finally:
                db.execute(f"PRAGMA max_page_count={original_limit}")
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 1)
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 0)
        with closing(thread_tree.connect_db()) as db:
            turn = self.turn_rows(db, turn_id)
            self.assertEqual((turn["state"], turn["attempts"], turn["error"]), ("indexed", 2, None))
            self.assert_integrity(db)

    def test_retryable_source_is_attempted_once_per_pass_without_starving_other_chats(self) -> None:
        bad_path = self.root / "unavailable.jsonl"
        self.write_rollout(bad_path, "chat-bad", "temporarily unavailable source marker")
        bad_id = pipeline.enqueue_transcript(bad_path)["turn_ids"][0]
        original = bad_path.read_bytes()
        bad_path.unlink()
        good_path = self.root / "available.jsonl"
        self.write_rollout(good_path, "chat-good", "available source marker")
        pipeline.enqueue_transcript(good_path)

        for expected_attempts, expected_processed in ((1, 1), (2, 0), (3, 0)):
            outcome = pipeline.process_project(self.project_id)
            self.assertEqual((outcome["processed_turns"], len(outcome["failures"])), (expected_processed, 1))
            with closing(thread_tree.connect_db()) as db:
                self.assertEqual(self.turn_rows(db, bad_id)["attempts"], expected_attempts)
        bad_path.write_bytes(original)
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 1)

    def test_terminal_ingestion_error_is_not_retried_by_workers_or_replays(self) -> None:
        path = self.root / "terminal.jsonl"
        self.write_rollout(path, "chat-terminal", "terminal source marker")
        turn_id = pipeline.enqueue_transcript(path)["turn_ids"][0]
        with patch.object(pipeline, "semantic_chunks", side_effect=ValueError("invalid chunk implementation")):
            self.assertEqual(len(pipeline.process_project(self.project_id)["failures"]), 1)
        self.assertEqual(pipeline.enqueue_transcript(path)["queued_turns"], 0)
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 0)
        with closing(thread_tree.connect_db()) as db:
            turn = self.turn_rows(db, turn_id)
            self.assertEqual((turn["state"], turn["attempts"]), ("failed", 1))

    def test_source_drift_never_publishes_wrong_chat_or_empty_turn(self) -> None:
        self.activate_fixture_project()
        path = self.root / "original.jsonl"
        self.write_rollout(path, "allowed-chat", "approvedmoth migration decision")
        original = path.read_bytes()
        queued = pipeline.enqueue_transcript(path, enforce_scope=True)
        turn_id = queued["turn_ids"][0]
        denied_project = self.root / "private"
        denied_project.mkdir()
        self.write_rollout(path, "denied-chat", "privateaardvark personal journal", denied_project)

        for edited in (path.read_bytes(), original.splitlines(keepends=True)[0]):
            path.write_bytes(edited)
            outcome = pipeline.process_project(self.project_id)
            self.assertEqual((outcome["processed_turns"], len(outcome["failures"])), (0, 1))
            self.assertEqual(pipeline.search_project(self.project_id, "privateaardvark"), [])
            with closing(thread_tree.connect_db()) as db:
                self.assertEqual(self.turn_rows(db, turn_id)["state"], "failed")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0], 0)
        path.write_bytes(original)
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 1)
        hits = pipeline.search_project(self.project_id, "approvedmoth")
        self.assertEqual({hit["thread_id"] for hit in hits}, {"allowed-chat"})

    def test_same_content_with_different_rollout_identity_is_not_indexed(self) -> None:
        self.activate_fixture_project()
        path = self.root / "identity.jsonl"
        self.write_rollout(path, "allowed-chat", "samewords unique provenance marker")
        turn_id = pipeline.enqueue_transcript(path, enforce_scope=True)["turn_ids"][0]
        self.write_rollout(path, "other-chat", "samewords unique provenance marker")
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 0)
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(self.turn_rows(db, turn_id)["state"], "failed")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0], 0)

    def test_same_chat_same_words_cannot_substitute_message_ids(self) -> None:
        path = self.root / "message-id.jsonl"
        self.write_rollout(path, "chat-original", "provenance key phrase")
        original = path.read_bytes()
        pipeline.enqueue_transcript(path)
        path.write_bytes(original.replace(b'"chat-original-user"', b'"replacement-message"'))
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 0)
        path.write_bytes(original)
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 1)
        with closing(thread_tree.connect_db()) as db:
            messages = " ".join(row[0] for row in db.execute("SELECT source_message_ids FROM turn_chunks"))
            self.assertIn("chat-original-user", messages)
            self.assertNotIn("replacement-message", messages)

    def test_replay_recovers_legacy_failed_and_empty_indexed_turns_after_relocation(self) -> None:
        for legacy_state in ("failed", "indexed"):
            with self.subTest(legacy_state=legacy_state):
                chat = f"legacy-{legacy_state}"
                path = self.root / f"{chat}.jsonl"
                self.write_rollout(path, chat, f"recover previously recorded {chat} evidence")
                turn_id = pipeline.enqueue_transcript(path)["turn_ids"][0]
                with closing(thread_tree.connect_db()) as db:
                    claim = state.claim_next_turn(db, self.project_id, thread_id=chat)
                    if legacy_state == "failed":
                        state.transition_turn(db, turn_id, "failed", "old worker failed", lease_token=claim["lease_token"])
                    else:
                        state.complete_turn_ingestion(db, turn_id, [], lease_token=claim["lease_token"])
                    with db:
                        db.execute("UPDATE turn_ingestion SET source_fingerprint=NULL WHERE id=?", (turn_id,))
                relocated = path.rename(self.root / f"relocated-{chat}.jsonl")
                self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 0)
                replay = pipeline.enqueue_transcript(relocated)
                self.assertEqual((replay["queued_turns"], replay["turn_ids"]), (1, [turn_id]))
                self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 1)
                self.assertEqual(pipeline.enqueue_transcript(relocated)["queued_turns"], 0)
                with closing(thread_tree.connect_db()) as db:
                    turn = self.turn_rows(db, turn_id)
                    self.assertEqual((turn["state"], turn["attempts"]), ("indexed", 2))
                    self.assertEqual(turn["transcript_path"], str(relocated.resolve()))
                    self.assertIsNotNone(turn["source_fingerprint"])

    def test_repeated_old_message_within_new_turn_preserves_original_provenance(self) -> None:
        path = self.root / "duplicates.jsonl"
        chat = "deduplicated-source"
        self.write_rollout(path, chat, "firstdistinct source evidence for replay")
        first = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
        self.write_rollout(path, chat, "seconddistinct source evidence for replay")
        second = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()[1:]]
        second[0]["payload"]["id"] += "-second"
        second[1]["payload"]["id"] += "-second"
        rows = [*first, second[0], first[-1], second[1]]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        queued = pipeline.enqueue_transcript(path)
        self.assertEqual(queued["queued_turns"], 2)
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 2)
        with closing(thread_tree.connect_db()) as db:
            messages = {message for row in db.execute(
                "SELECT source_message_ids FROM turn_chunks WHERE turn_id=?", (queued["turn_ids"][1],),
            ) for message in json.loads(row[0])}
            self.assertEqual(messages, {f"{chat}-user-second", f"{chat}-assistant-second"})

    def test_claude_prompt_replay_crosses_clock_boundary_but_stop_opens_a_new_slot(self) -> None:
        chat = "claude-chat"
        prompt = "identical prompt may be a replay or another request"
        with closing(thread_tree.connect_db()) as db, patch.object(state, "utc_now") as now:
            def stage() -> dict[str, Any]:
                return state.stage_user_prompt(
                    db, codex_turn_id=None, project_id=self.project_id, thread_id=chat, prompt=prompt,
                )

            now.return_value = "2026-11-17T00:00:00+00:00"
            first = stage()
            now.return_value = "2026-11-17T00:00:01+00:00"
            self.assertEqual(stage()["codex_turn_id"], first["codex_turn_id"])
            state.queue_turn(db, project_id=self.project_id, thread_id=chat, turn_id="first-stop", content_hash="first")
            reconciled = state.reconcile_staged_prompt(
                db, codex_turn_id=None, project_id=self.project_id, thread_id=chat, ingestion_turn_id="first-stop",
            )
            self.assertEqual(reconciled["codex_turn_id"], first["codex_turn_id"])
            second = stage()
            self.assertNotEqual(second["codex_turn_id"], first["codex_turn_id"])
            self.assertEqual(stage()["codex_turn_id"], second["codex_turn_id"])
            state.queue_turn(db, project_id=self.project_id, thread_id=chat, turn_id="second-stop", content_hash="second")
            state.reconcile_staged_prompt(
                db, codex_turn_id=None, project_id=self.project_id, thread_id=chat, ingestion_turn_id="second-stop",
            )
            self.assertEqual([tuple(row) for row in db.execute(
                "SELECT codex_turn_id, state, ingestion_turn_id FROM staged_user_prompts ORDER BY rowid",
            )], [
                (first["codex_turn_id"], "reconciled", "first-stop"),
                (second["codex_turn_id"], "reconciled", "second-stop"),
            ])

    def test_explicit_host_turn_ids_keep_identical_prompts_and_reject_scope_collision(self) -> None:
        with closing(thread_tree.connect_db()) as db:
            for identifier in ("host-one", "host-two"):
                state.stage_user_prompt(
                    db, codex_turn_id=identifier, project_id=self.project_id, thread_id="host-chat", prompt="same words",
                )
            with self.assertRaisesRegex(state.StateTransitionError, "another source"):
                state.stage_user_prompt(
                    db, codex_turn_id="host-one", project_id=self.project_id, thread_id="other-chat", prompt="forged",
                )
            self.assertEqual([tuple(row) for row in db.execute(
                "SELECT codex_turn_id, thread_id, prompt FROM staged_user_prompts ORDER BY rowid",
            )], [("host-one", "host-chat", "same words"), ("host-two", "host-chat", "same words")])

    def test_old_staging_database_migrates_reconciled_rows_and_recognizes_pending_replays(self) -> None:
        chat = "legacy-claude"
        with closing(thread_tree.connect_db()) as db, db:
            db.execute("DROP TABLE staged_user_prompts")
            db.execute(
                """CREATE TABLE staged_user_prompts (
                    codex_turn_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    thread_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    ingestion_turn_id TEXT REFERENCES turn_ingestion(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, reconciled_at TEXT,
                    UNIQUE(project_id, thread_id, content_hash)
                )"""
            )
            state.queue_turn(db, project_id=self.project_id, thread_id=chat, turn_id="old-stop", content_hash="old")
            for turn, content, status, ingestion in (
                ("prompt_old_pending", "legacy pending prompt", "staged", None),
                ("prompt_old_finished", "legacy finished prompt", "reconciled", "old-stop"),
            ):
                now = state.utc_now()
                db.execute(
                    "INSERT INTO staged_user_prompts VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (turn, self.project_id, chat, content, pipeline._hash(content), status, ingestion,
                     now, now, now if ingestion else None),
                )
        with closing(thread_tree.connect_db()) as db:
            replay = state.stage_user_prompt(
                db, codex_turn_id=None, project_id=self.project_id, thread_id=chat, prompt="legacy pending prompt",
            )
            self.assertEqual(replay["codex_turn_id"], "prompt_old_pending")
            later = state.stage_user_prompt(
                db, codex_turn_id=None, project_id=self.project_id, thread_id=chat, prompt="legacy finished prompt",
            )
            self.assertNotEqual(later["codex_turn_id"], "prompt_old_finished")
            preserved = db.execute(
                "SELECT state, ingestion_turn_id FROM staged_user_prompts WHERE codex_turn_id='prompt_old_finished'",
            ).fetchone()
            self.assertEqual(tuple(preserved), ("reconciled", "old-stop"))
            self.assert_integrity(db)

    def test_sqlite_busy_does_not_publish_partial_turn_or_lose_owner(self) -> None:
        with closing(thread_tree.connect_db()) as worker, closing(thread_tree.connect_db()) as blocker:
            self.queue_turn(worker, "pending")
            claim = state.claim_next_turn(worker, self.project_id)
            worker.execute("PRAGMA busy_timeout=0")
            blocker.execute("BEGIN IMMEDIATE")
            try:
                with self.assertRaises(sqlite3.OperationalError) as failure:
                    state.complete_turn_ingestion(worker, "pending", TURN_CHUNKS, lease_token=claim["lease_token"])
                self.assertEqual(failure.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
                self.assertEqual(worker.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0], 0)
                self.assertEqual(self.turn_rows(worker, "pending")["lease_token"], claim["lease_token"])
            finally:
                blocker.rollback()
            state.complete_turn_ingestion(worker, "pending", TURN_CHUNKS, lease_token=claim["lease_token"])
            self.assert_pending_turn_complete(worker, attempts=1)
    @staticmethod
    def graph_snapshot(db: sqlite3.Connection) -> dict[str, list[tuple[Any, ...]]]:
        ordered = {
            "cluster_generations": "id", "project_active_tree": "project_id", "semantic_nodes": "id",
            "semantic_node_memberships": "node_id, chunk_id", "semantic_edges": "child_id, parent_id",
            "chunk_layer_states": "chunk_id, layer", "fit_debt_events": "seq",
        }
        return {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}")]
            for table, order in ordered.items()
        }

    def prepare_fit(self) -> tuple[str, str, dict[str, list[tuple[Any, ...]]]]:
        with closing(thread_tree.connect_db()) as db:
            self.seed_turn(db, "prior", "priormarker")
            previous = state.schedule_global_rebuild(db, self.project_id, reason="known good graph")
            pipeline.run_fit(db, previous["id"])
            self.seed_turn(db, "incoming", "incomingmarker")
            replacement = state.schedule_global_rebuild(db, self.project_id, reason="candidate graph")
            before = self.graph_snapshot(db)
            self.assertTrue(before["semantic_nodes"])
            self.assertTrue(before["semantic_edges"])
            return previous["id"], replacement["id"], before

    def assert_fit_crash_preserves_old_graph(self, boundary: str) -> None:
        previous, replacement, before = self.prepare_fit()
        self.crash("fit", boundary, replacement)
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(self.graph_snapshot(db), before)
            self.assert_integrity(db)
            self.assertEqual(db.execute("SELECT generation_token FROM project_active_tree").fetchone()[0], previous)
            self.assertEqual(db.execute("SELECT state FROM fit_runs WHERE id=?", (replacement,)).fetchone()[0], "running")
        hits = pipeline.search_project(self.project_id, "incomingmarker")
        self.assertTrue(hits)
        self.assertEqual({hit["turn_id"] for hit in hits}, {"incoming"})

    def test_crash_during_fit_generation_rolls_back_consumed_debt(self) -> None:
        self.assert_fit_crash_preserves_old_graph("INSERT INTO cluster_generations")

    def test_crash_during_fit_materialization_preserves_previous_memberships(self) -> None:
        self.assert_fit_crash_preserves_old_graph("INSERT INTO semantic_node_memberships")

    def test_crash_during_primary_edge_rebuild_preserves_previous_graph(self) -> None:
        self.assert_fit_crash_preserves_old_graph("INSERT INTO semantic_edges")

    def test_crash_just_before_fit_commit_restores_tree_pointer_and_graph_together(self) -> None:
        self.assert_fit_crash_preserves_old_graph("before_commit")

    def test_crash_after_fit_commit_keeps_published_generation_coherent(self) -> None:
        previous, replacement, _ = self.prepare_fit()
        self.crash("fit", "after_publish", replacement)
        with closing(thread_tree.connect_db()) as db:
            self.assert_integrity(db)
            self.assertEqual(db.execute("SELECT generation_token FROM project_active_tree").fetchone()[0], replacement)
            self.assertEqual(db.execute("SELECT state FROM fit_runs WHERE id=?", (replacement,)).fetchone()[0], "committed")
            generations = db.execute("SELECT fit_run_id, state FROM cluster_generations")
            self.assertCountEqual([tuple(row) for row in generations], [(previous, "superseded")] * 3 + [(replacement, "active")] * 3)
            stale_members = db.execute(
                """SELECT COUNT(*) FROM semantic_nodes n
                   LEFT JOIN cluster_generations g ON g.id=n.generation_id
                   WHERE g.fit_run_id IS NULL OR g.fit_run_id!=?""", (replacement,),
            ).fetchone()[0]
            self.assertEqual(stale_members, 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fit_debt_events WHERE consumed_by IS NULL").fetchone()[0], 0)
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 0)

    def test_competing_fit_workers_publish_one_generation(self) -> None:
        previous, replacement, before = self.prepare_fit()
        owner_entered = threading.Event()
        competitor_started = threading.Event()
        resume_owner = threading.Event()
        original_fit_rows = pipeline._fit_rows_for_layer
        span_loads = 0

        def fit_rows(*args: Any, **kwargs: Any) -> Any:
            nonlocal span_loads
            if args[2] == "span":
                span_loads += 1
                owner_entered.set()
                if not resume_owner.wait(timeout=10):
                    raise RuntimeError("fixture timed out waiting to release fit owner")
            return original_fit_rows(*args, **kwargs)

        def run(competitor: bool) -> dict[str, Any]:
            with closing(thread_tree.connect_db()) as db:
                if competitor:
                    competitor_started.set()
                return pipeline.run_fit(db, replacement)

        with patch.object(pipeline, "_fit_rows_for_layer", fit_rows), ThreadPoolExecutor(max_workers=2) as pool:
            owner = pool.submit(run, False)
            try:
                self.assertTrue(owner_entered.wait(timeout=10))
                opponent = pool.submit(run, True)
                self.assertTrue(competitor_started.wait(timeout=10))
                with closing(thread_tree.connect_db()) as reader:
                    self.assertEqual(self.graph_snapshot(reader), before)
                    self.assertEqual(reader.execute("SELECT generation_token FROM project_active_tree").fetchone()[0], previous)
            finally:
                resume_owner.set()
            self.assertEqual(owner.result(timeout=10)["state"], "committed")
            self.assertEqual(opponent.result(timeout=10)["state"], "committed")
        self.assertEqual(span_loads, 1)
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cluster_generations WHERE fit_run_id=?", (replacement,)).fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT generation_token FROM project_active_tree").fetchone()[0], replacement)
            self.assert_integrity(db)

    def prepare_retention(self) -> None:
        with closing(thread_tree.connect_db()) as db:
            self.seed_turn(db, "removed", "removalmarker")
            self.seed_turn(db, "kept", "survivormarker", protected=True)
            before = state.schedule_global_rebuild(db, self.project_id, reason="pre-retention graph")
            pipeline.run_fit(db, before["id"])
            state.configure_retention(db, self.project_id, high_chunks=5, low_chunks=3)

    def assert_tombstones_and_visibility(self, db: sqlite3.Connection) -> None:
        self.assertEqual(self.turn_rows(db, "removed")["state"], "evicted")
        self.assertEqual((self.turn_rows(db, "kept")["state"], self.turn_rows(db, "kept")["protected"]), ("indexed", 1))
        self.assertEqual([row[0] for row in db.execute("SELECT turn_id FROM evicted_turns")], ["removed"])
        self.assertFalse(pipeline.search_project(self.project_id, "removalmarker"))
        self.assertEqual({row["turn_id"] for row in pipeline.search_project(self.project_id, "survivormarker")}, {"kept"})
        self.assert_integrity(db)

    def test_interrupted_physical_cleanup_cannot_leave_half_a_turn(self) -> None:
        self.prepare_retention()
        self.crash("retention", "between_cleanup_deletes")
        with closing(thread_tree.connect_db()) as db:
            self.assert_tombstones_and_visibility(db)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks WHERE evicted=1").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks_fts WHERE thread_id='chat-removed'").fetchone()[0], 3)

    def test_worker_restart_reclaims_interrupted_fit(self) -> None:
        _, replacement, _ = self.prepare_fit()
        self.crash("fit", "before_commit", replacement)
        pipeline.process_project(self.project_id, max_turns=0)
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT state FROM fit_runs WHERE id=?", (replacement,)).fetchone()[0], "committed")
            self.assertEqual(db.execute("SELECT generation_token FROM project_active_tree").fetchone()[0], replacement)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fit_runs").fetchone()[0], 2)
            self.assert_integrity(db)

    def assert_retention_restart_completes(self, boundary: str) -> None:
        self.prepare_retention()
        self.crash("retention", boundary)
        pipeline.process_project(self.project_id, max_turns=0)
        with closing(thread_tree.connect_db()) as db:
            self.assert_tombstones_and_visibility(db)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks WHERE evicted=1").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks_fts WHERE thread_id='chat-removed'").fetchone()[0], 0)
            self.assertEqual(db.execute(
                """SELECT COUNT(*) FROM project_active_tree a JOIN fit_runs r ON r.id=a.generation_token
                   WHERE r.kind='capacity_rebuild' AND r.state='committed'"""
            ).fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fit_runs WHERE kind='capacity_rebuild'").fetchone()[0], 1)

    def test_worker_restart_resumes_after_retention_tombstone_commit(self) -> None:
        self.assert_retention_restart_completes("after_tombstone")

    def test_worker_restart_retries_cleanup_after_retention_fit_commit(self) -> None:
        self.assert_retention_restart_completes("after_retention_publish")

    def test_worker_restart_retries_cleanup_after_partial_delete_rolls_back(self) -> None:
        self.assert_retention_restart_completes("between_cleanup_deletes")

    def test_interrupted_connection_worker_publishes_failure_and_can_resume(self) -> None:
        _, replacement, _ = self.prepare_fit()
        job_id = "refresh_" + "1" * 32
        thread_tree.write_connection_refresh_job(job_id, "queued", [self.project_id], tracks_worker=True)
        self.crash("connection-job", "after_fit_claim", job_id)
        raw = json.loads((thread_tree.connection_refresh_directory() / f"{job_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["state"], "running")
        failed = thread_tree.connection_refresh_status(job_id)
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(thread_tree.connection_refresh_status(job_id), failed)
        self.assertEqual(thread_tree.connection_refresh_status()["state"], "idle")
        self.assertEqual(rebuild.main([job_id, self.project_id]), 0)
        self.assertEqual(thread_tree.connection_refresh_status(job_id)["state"], "complete")
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT state FROM fit_runs WHERE id=?", (replacement,)).fetchone()[0], "committed")
            total_fits = db.execute("SELECT COUNT(*) FROM fit_runs").fetchone()[0]
            self.assert_integrity(db)
        self.assertEqual(rebuild.main([job_id, self.project_id]), 0)
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fit_runs").fetchone()[0], total_fits)

    def test_refresh_poll_respects_live_worker_and_recovers_abandoned_start(self) -> None:
        active_job = "refresh_" + "2" * 32
        queued_job = "refresh_" + "3" * 32
        with state.exclusive_process_lock(thread_tree.connection_refresh_lock_path(active_job)):
            thread_tree.write_connection_refresh_job(active_job, "running", [self.project_id], tracks_worker=True)
            self.assertEqual(thread_tree.connection_refresh_status(active_job)["state"], "running")
            with patch.object(thread_tree, "utc_now", return_value="2000-01-01T00:00:00+00:00"):
                thread_tree.write_connection_refresh_job(queued_job, "queued", [self.project_id], tracks_worker=True)
            self.assertEqual(thread_tree.connection_refresh_status(queued_job)["state"], "failed")
            self.assertEqual(thread_tree.connection_refresh_status()["id"], active_job)
        self.assertEqual(thread_tree.connection_refresh_status(active_job)["state"], "failed")

    def test_connection_job_replays_without_recomputing_published_fit(self) -> None:
        self.prepare_fit()
        job_id = "refresh_" + "4" * 32
        self.crash("connection-job", "after_fit_commit", job_id)
        self.assertEqual(thread_tree.connection_refresh_status(job_id)["state"], "failed")
        with closing(thread_tree.connect_db()) as db:
            before = self.graph_snapshot(db)
            total_fits = db.execute("SELECT COUNT(*) FROM fit_runs").fetchone()[0]
        self.assertEqual(rebuild.main([job_id, self.project_id]), 0)
        self.assertEqual(thread_tree.connection_refresh_status(job_id)["state"], "complete")
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(self.graph_snapshot(db), before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fit_runs").fetchone()[0], total_fits)
            self.assert_integrity(db)

    def test_retention_removes_old_derived_artifacts_without_an_embedding_provider(self) -> None:
        self.prepare_retention()
        path = vector_index._index_path(thread_tree.data_dir(), self.project_id)
        manifest = vector_index._metadata_path(thread_tree.data_dir(), self.project_id)
        artifacts = (path, manifest, path.with_suffix(path.suffix + ".tmp"), manifest.with_suffix(manifest.suffix + ".tmp"))
        path.parent.mkdir(parents=True)
        for artifact in artifacts:
            artifact.write_text("stale derived fixture", encoding="utf-8")
        pipeline.process_project(self.project_id, max_turns=0)
        self.assertFalse(any(artifact.exists() for artifact in artifacts))
        with closing(thread_tree.connect_db()) as db:
            self.assert_tombstones_and_visibility(db)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks WHERE evicted=1").fetchone()[0], 0)

    def test_vector_write_lock_is_reusable_immediately_after_process_death(self) -> None:
        self.crash("vector-lock", "while-owned")
        self.crash("vector-lock", "after-restart")

    def prepare_vector_publication(self) -> str:
        if not vector_index.available():
            self.skipTest("native USearch dependency is unavailable")
        with closing(thread_tree.connect_db()) as db:
            self.seed_turn(db, "prior", "priormarker")
            with db:
                db.execute("UPDATE turn_chunks SET embedding='[1, 0]', embedding_model='fault-fixture'")
            original = vector_index.rebuild_project_index(
                db, data_directory=thread_tree.data_dir(), project_id=self.project_id, model="fault-fixture", dimension=2,
            )
            self.seed_turn(db, "incoming", "incomingmarker")
            with db:
                db.execute("UPDATE turn_chunks SET embedding='[0, 1]', embedding_model='fault-fixture' WHERE turn_id='incoming'")
            return original["generation_token"]

    def vector_sqlite_generation(self, db: sqlite3.Connection) -> str:
        return db.execute("SELECT generation_token FROM index_shards WHERE name=?", (f"global-chunks:{self.project_id}",)).fetchone()[0]

    def assert_native_index_recovered(self, *, after_generation: str) -> None:
        with closing(thread_tree.connect_db()) as db:
            repaired = vector_index.update_project_index(
                db, data_directory=thread_tree.data_dir(), project_id=self.project_id, model="fault-fixture", dimension=2,
            )
            self.assertEqual(repaired["document_count"], 6)
            self.assertNotEqual(repaired["generation_token"], after_generation)
            self.assertEqual(repaired["generation_token"], self.vector_sqlite_generation(db))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM index_documents").fetchone()[0], 6)
            self.assert_native_index_query(db)

    def assert_native_index_query(self, db: sqlite3.Connection) -> None:
        hits, info = vector_index.search(
            data_directory=thread_tree.data_dir(), project_id=self.project_id, model="fault-fixture", vector=[0, 1], limit=3,
        )
        self.assertTrue(info["available"])
        expected = {row[0] for row in db.execute("SELECT seq FROM turn_chunks WHERE turn_id='incoming'")}
        self.assertEqual({seq for seq, _ in hits}, expected)
        settled = vector_index.update_project_index(
            db, data_directory=thread_tree.data_dir(), project_id=self.project_id, model="fault-fixture", dimension=2,
        )
        self.assertEqual(settled["generation_token"], self.vector_sqlite_generation(db))
        self.assert_integrity(db)

    def test_torn_native_publication_excludes_binary_without_its_manifest(self) -> None:
        original = self.prepare_vector_publication()
        self.crash("vector", "after_binary")
        self.assertIsNone(vector_index.metadata(thread_tree.data_dir(), self.project_id))
        hits, info = vector_index.search(
            data_directory=thread_tree.data_dir(), project_id=self.project_id, model="fault-fixture", vector=[0, 1], limit=3,
        )
        self.assertEqual(hits, [])
        self.assertFalse(info["available"])
        self.assertEqual({hit["turn_id"] for hit in pipeline.search_project(self.project_id, "incomingmarker")}, {"incoming"})
        self.assert_native_index_recovered(after_generation=original)

    def test_native_publication_reconciles_sqlite_after_manifest_commits_first(self) -> None:
        original = self.prepare_vector_publication()
        self.crash("vector", "after_manifest")
        published = vector_index.metadata(thread_tree.data_dir(), self.project_id)
        self.assertNotEqual(published["generation_token"], original)
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(self.vector_sqlite_generation(db), original)
        self.assert_native_index_recovered(after_generation=published["generation_token"])

    def test_enospc_during_native_publication_falls_back_then_recovers(self) -> None:
        original = self.prepare_vector_publication()
        with closing(thread_tree.connect_db()) as db, patch.object(
            vector_index, "_atomic_json", side_effect=OSError(errno.ENOSPC, "injected manifest filesystem full"),
        ):
            with self.assertRaises(OSError) as failure:
                vector_index.rebuild_project_index(
                    db, data_directory=thread_tree.data_dir(), project_id=self.project_id, model="fault-fixture", dimension=2,
                )
            self.assertEqual(failure.exception.errno, errno.ENOSPC)
            self.assertEqual(self.vector_sqlite_generation(db), original)
        self.assertIsNone(vector_index.metadata(thread_tree.data_dir(), self.project_id))
        self.assert_native_index_recovered(after_generation=original)

    def test_malformed_manifest_falls_back_then_rebuilds_from_canonical_chunks(self) -> None:
        original = self.prepare_vector_publication()
        path = vector_index._metadata_path(thread_tree.data_dir(), self.project_id)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["dimension"] = "unrecognized-schema-value"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIsNone(vector_index.metadata(thread_tree.data_dir(), self.project_id))
        self.assert_native_index_recovered(after_generation=original)

    def test_legacy_manifest_rebuilds_once_then_reopens_normally(self) -> None:
        original = self.prepare_vector_publication()
        path = vector_index._metadata_path(thread_tree.data_dir(), self.project_id)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 1
        manifest.pop("generation_token")
        manifest.pop("index_file_identity")
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIsNone(vector_index.metadata(thread_tree.data_dir(), self.project_id))
        self.assert_native_index_recovered(after_generation=original)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--crash-child":
        run_child(*sys.argv[2:])
    else:
        unittest.main()
