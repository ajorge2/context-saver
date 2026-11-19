"""Durable reversible chat controls and stale-work publication boundaries."""

from __future__ import annotations

import _support
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from contextlib import closing
from unittest.mock import PropertyMock, patch

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state
import thread_tree_tools as tools


class ChatControlTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.data = self.root / "data"
        self.data.mkdir()
        self.enterContext(patch.dict(os.environ, {
            "THREAD_HISTORY_TREE_DATA": str(self.data), "CODEX_HOME": str(self.root / "codex"),
            "CLAUDE_CONFIG_DIR": str(self.root / "claude"),
            "CODEX_THREAD_ID": "", "CODEX_SESSION_ID": "", "CLAUDE_SESSION_ID": "",
        }))
        (self.data / "config.json").write_text(json.dumps({
            "embedding_provider": "none", "ollama_url": "fixture-no-network:",
            "fit_thresholds": {"span": 100000, "specific": 100000, "broad": 100000},
        }))
        self.enterContext(patch.object(thread_tree.SemanticProvider, "_check"))
        self.project_id = state.project_id_for(str(self.project))
        self.transcript = self.project / "chat.jsonl"
        self.chat = "chat-a"
        self.rows = [{"type": "session_meta", "payload": {
            "session_id": self.chat, "cwd": str(self.project),
        }}]
        self.append_turn("before", "Searchable original ARCHIVE-801")
        with closing(thread_tree.connect_db()) as db:
            state.observe_session(db, project_root=str(self.project), thread_id=self.chat,
                                  transcript_path=str(self.transcript))
        self.configure()

    def configure(self, **extra):
        return thread_tree.save_scope_config({"schemaVersion": 1, "configured": True,
            "paused": False, "projects": [{"path": str(self.project), "includeNewChats": True}], **extra})

    def append_turn(self, name, text):
        for role, content in (("user", text), ("assistant", f"Recorded {name}")):
            self.rows.append({"type": "response_item", "payload": {"type": "message",
                "id": f"{name}-{role}", "role": role,
                "content": [{"type": "input_text" if role == "user" else "output_text", "text": content}]}})
        self.transcript.write_text("\n".join(json.dumps(row) for row in self.rows) + "\n")

    def control(self, action):
        return tools.control_current_chat(action, project_root=str(self.project), thread_id=self.chat)

    def activate(self):
        result = tools.prepare_current_chat(project_root=str(self.project), thread_id=self.chat)
        self.assertEqual(result["status"], "ready", result)

    def saved_text(self):
        with closing(thread_tree.connect_db()) as db:
            return "\n".join(row[0] for row in db.execute("SELECT text FROM turn_chunks ORDER BY seq"))

    def test_off_before_activation_persists_without_creating_an_index(self):
        result = self.control("off")
        self.assertEqual(result["status"], "off")
        self.assertTrue(result["ok"])
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 0)
            first = state.chat_control(db, self.project_id, self.chat)
        self.assertEqual(self.control("off")["status"], "off")
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(first, state.chat_control(db, self.project_id, self.chat))

    def test_off_without_observation_is_still_reported_by_prepare(self):
        tools.control_current_chat("off", project_root=str(self.project), thread_id="never-observed")
        result = tools.prepare_current_chat(project_root=str(self.project), thread_id="never-observed")
        self.assertEqual(result["status"], "off")

    def test_missing_identity_never_acts_on_latest_observed_chat(self):
        before = thread_tree.load_scope_config()
        result = tools.control_current_chat("off", project_root=str(self.project))
        self.assertEqual(result["status"], "session_unavailable")
        self.assertFalse(result["ok"])
        self.assertEqual(before, thread_tree.load_scope_config())
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_plugin_controls").fetchone()[0], 0)

    def test_claude_identity_never_prepares_newer_sibling(self):
        self.activate()
        self.control("off")
        with closing(thread_tree.connect_db()) as db:
            state.observe_session(db, project_root=str(self.project), thread_id="newer-sibling", transcript_path=None)
        with patch.dict(os.environ, {"CLAUDE_SESSION_ID": self.chat}):
            self.assertEqual(tools.prepare_current_chat()["status"], "off")

    def test_status_and_off_do_not_promote_recency_or_delete_saved_messages(self):
        self.activate()
        original = self.saved_text()
        with closing(thread_tree.connect_db()) as db:
            timestamp = db.execute("SELECT last_plugin_invoked_at FROM projects").fetchone()[0]
        self.assertEqual(self.control("status")["status"], "on")
        self.control("off")
        self.assertEqual(self.control("status")["status"], "off")
        self.assertEqual(original, self.saved_text())
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(timestamp, db.execute("SELECT last_plugin_invoked_at FROM projects").fetchone()[0])

    def test_ordinary_invocation_cannot_turn_off_chat_back_on(self):
        self.activate()
        self.control("off")
        with patch.object(pipeline, "process_project", side_effect=AssertionError("must not index")):
            self.assertEqual(tools.prepare_current_chat(project_root=str(self.project), thread_id=self.chat)["status"], "off")
        with closing(thread_tree.connect_db()) as db:
            result = state.stage_user_prompt(db, codex_turn_id="off-prompt", project_id=self.project_id,
                                            thread_id=self.chat, prompt="PRIVATE OFF INPUT")
            self.assertTrue(result["scope_blocked"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM staged_user_prompts").fetchone()[0], 0)

    def test_manual_enqueue_also_honors_off(self):
        self.control("off")
        for enforce_scope in (False, True):
            result = pipeline.enqueue_transcript(self.transcript, enforce_scope=enforce_scope)
            self.assertTrue(result["scope_blocked"])
        self.assertEqual(self.saved_text(), "")

    def test_on_resumes_after_off_interval_and_preserves_old_messages(self):
        self.activate()
        self.control("off")
        self.append_turn("private", "PRIVATE-GAP-9934")
        self.assertEqual(self.control("on")["status"], "on")
        self.append_turn("after", "PUBLIC-AFTER-1438")
        pipeline.enqueue_transcript(self.transcript, enforce_scope=True)
        pipeline.process_project(self.project_id)
        text = self.saved_text()
        self.assertIn("ARCHIVE-801", text)
        self.assertIn("PUBLIC-AFTER-1438", text)
        self.assertNotIn("PRIVATE-GAP-9934", text)

    def test_repeated_on_does_not_advance_capture_watermark(self):
        self.activate()
        self.control("off")
        self.control("on")
        with closing(thread_tree.connect_db()) as db:
            before = state.chat_control(db, self.project_id, self.chat)
        self.append_turn("pending", "PUBLIC-PENDING-710")
        self.control("on")
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(before, state.chat_control(db, self.project_id, self.chat))
        pipeline.enqueue_transcript(self.transcript)
        pipeline.process_project(self.project_id)
        self.assertIn("PUBLIC-PENDING-710", self.saved_text())

    def test_replaced_or_truncated_resume_transcript_fails_closed(self):
        self.activate()
        self.control("off")
        self.control("on")
        self.control("off")
        original = self.transcript.read_text()
        for replacement in (original.replace("ARCHIVE-801", "REPLACEMENT"), original.splitlines()[0] + "\n"):
            self.transcript.write_text(replacement)
            result = self.control("on")
            self.assertEqual(result["status"], "transcript_unavailable")
            self.assertFalse(result["ok"])
            self.assertEqual(self.control("status")["status"], "off")
        self.transcript.write_text(original)

    def test_on_scope_write_failure_leaves_durable_off_guard(self):
        self.activate()
        self.control("off")
        with patch.object(thread_tree, "save_scope_config", side_effect=OSError("fixture write failed")):
            with self.assertRaises(OSError):
                self.control("on")
        self.assertEqual(self.control("status")["status"], "off")
        self.assertEqual(tools.prepare_current_chat(project_root=str(self.project), thread_id=self.chat)["status"], "off")

    def test_on_preparation_failure_rolls_back_to_off(self):
        self.activate()
        self.control("off")
        with patch.object(tools, "prepare_current_chat", return_value={"status": "failed"}):
            result = self.control("on")
        self.assertFalse(result["ok"])
        self.assertEqual(self.control("status")["status"], "off")

    def test_on_preparation_exception_rolls_back_without_disclosing_source_text(self):
        self.activate()
        self.control("off")
        with patch.object(tools, "prepare_current_chat", side_effect=RuntimeError("PRIVATE-SOURCE-EXCEPTION")):
            result = self.control("on")
        self.assertFalse(result["ok"])
        self.assertEqual(self.control("status")["status"], "off")
        self.assertNotIn("PRIVATE-SOURCE-EXCEPTION", json.dumps(result))

    def test_inflight_embedding_cannot_publish_after_off_or_off_on(self):
        for reconnect in (False, True):
            with self.subTest(reconnect=reconnect):
                if reconnect:
                    self.control("on")
                else:
                    self.activate()
                self.append_turn(f"race-{reconnect}", f"STALE-EMBEDDING-{reconnect}")
                pipeline.enqueue_transcript(self.transcript)
                triggered = False
                def embed(provider, texts, **kwargs):
                    nonlocal triggered
                    if not triggered:
                        triggered = True
                        self.control("off")
                        if reconnect:
                            self.control("on")
                    return [[1.0, 0.0] for _ in texts]
                with patch.object(thread_tree.SemanticProvider, "can_embed", new_callable=PropertyMock, return_value=True), patch.object(thread_tree.SemanticProvider, "embed", embed):
                    result = pipeline.process_project(self.project_id)
                self.assertTrue(triggered)
                self.assertNotIn(f"STALE-EMBEDDING-{reconnect}", self.saved_text())
                self.assertEqual(result["processed_turns"], 0)

    def test_inflight_search_discards_results_after_off_on(self):
        self.activate()
        def lookup(*args, **kwargs):
            self.control("off")
            self.control("on")
            return []
        with patch.object(pipeline, "search_project", side_effect=lookup):
            result = tools.search_project_history("original", project_root=str(self.project), thread_id=self.chat)
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["reason"], "connection_changed_during_lookup")

    def test_off_caller_blocks_cross_project_and_identityless_retrieval(self):
        self.activate()
        self.control("off")
        with patch.object(pipeline, "search_project", side_effect=AssertionError("no retrieval while off")):
            for root in (self.project, self.root / "other-project"):
                result = tools.search_project_history("secret", project_root=str(root), thread_id=self.chat)
                self.assertEqual(result["status"], "off")
                self.assertEqual(result["evidence"], [])
            result = tools.search_project_history("secret", project_root=str(self.project))
            self.assertEqual(result["status"], "session_unavailable")

    def test_enabled_sibling_keeps_retrieval_and_its_scope(self):
        self.activate()
        self.control("off")
        result = tools.search_project_history("original", project_root=str(self.project), thread_id="chat-b")
        self.assertEqual(result["status"], "uncovered")
        self.assertEqual(result["trace"]["global_lookup_count"], 1)
        selected = thread_tree.load_scope_config()["projects"][0]
        self.assertEqual(selected["excludedChatIds"], [self.chat])

    def test_project_pause_cannot_be_overridden_by_chat_on(self):
        self.activate()
        self.control("off")
        self.configure(paused=True)
        result = self.control("on")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "paused")
        self.assertEqual(self.control("status")["status"], "off")

    def test_sqlite_blocks_pre_upgrade_worker_writing_off_period(self):
        self.activate()
        self.control("off")
        self.append_turn("legacy", "PRIVATE-LEGACY-157")
        self.control("on")
        with closing(thread_tree.connect_db()) as db:
            # Simulate a 0.1.22 worker that has no awareness of the new guard.
            state.queue_turn(db, turn_id="legacy-worker", project_id=self.project_id, thread_id=self.chat,
                transcript_path=str(self.transcript), line_start=4, line_end=5, content_hash="legacy-distinct")
            turn = state.claim_next_turn(db, self.project_id, thread_id=self.chat)
            self.assertIsNotNone(turn)
            with self.assertRaises(sqlite3.IntegrityError):
                state.complete_turn_ingestion(db, turn["id"], [{"text": "PRIVATE-LEGACY-157", "line_start": 4}],
                    lease_token=turn["lease_token"])
            # An old chunker may retain just the post-resume assistant suffix
            # of a user turn that started while disconnected. Its entire turn
            # remains outside the capture window.
            with self.assertRaises(sqlite3.IntegrityError):
                state.complete_turn_ingestion(db, turn["id"], [{"text": "PRIVATE-SUFFIX-157", "line_start": 999}],
                    lease_token=turn["lease_token"])
        self.assertNotIn("PRIVATE-LEGACY-157", self.saved_text())


if __name__ == "__main__":
    unittest.main()
