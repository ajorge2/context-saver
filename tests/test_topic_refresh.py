"""Exercise the explicit, project-scoped operator bridge for topic upgrades."""

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state


class TopicRefreshTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary).resolve()
        self.project = self.root / "selected-project"
        self.other = self.root / "other-project"
        self.project.mkdir()
        self.other.mkdir()
        self.enterContext(patch.dict(os.environ, {"THREAD_HISTORY_TREE_DATA": str(self.root / "data")}))
        (self.root / "data").mkdir()
        (self.root / "data" / "config.json").write_text(json.dumps({"embedding_provider": "none"}))
        self.project_id = state.project_id_for(str(self.project))
        self.other_id = state.project_id_for(str(self.other))
        self.configure()
        db = thread_tree.connect_db()
        for project_id, directory in ((self.project_id, self.project), (self.other_id, self.other)):
            state.ensure_project(db, project_id, str(directory), fit_thresholds={layer: 10000 for layer in state.LAYERS})
            turn_id = f"turn-{project_id}"
            state.queue_turn(db, turn_id=turn_id, project_id=project_id, thread_id=f"chat-{project_id}", content_hash=turn_id)
            state.claim_next_turn(db, project_id)
            state.complete_turn_ingestion(db, turn_id, [{
                "id": f"{project_id}-chunk-{index}", "content_hash": f"{project_id}-content-{index}",
                "text": f"PRIVATE_REFRESH_SENTINEL cobalt quartz glacier sapphire tundra evidence {index}",
                "source_message_ids": [f"message-{project_id}-{index}"],
                "embedding": [1.0, 0.0], "embedding_model": "synthetic-stable-model",
            } for index in range(6)])
        db.close()

    def configure(self, *, project_options=None, **options):
        return thread_tree.save_scope_config({
            "schemaVersion": 1, "configured": True, "paused": False,
            "projects": [{"path": str(self.project), "includeNewChats": False,
                          "includedChatIds": [f"chat-{self.project_id}"], "excludedChatIds": [],
                          **(project_options or {})}],
            **options,
        })

    def cli(self, *options, project=None):
        output = io.StringIO()
        with redirect_stdout(output):
            code = thread_tree.main(["refresh-topics", "--project", str(project or self.project), "--json", *options])
        value = output.getvalue()
        self.assertNotIn("PRIVATE_REFRESH_SENTINEL", value)
        return code, json.loads(value)

    def snapshot(self, *, project_id=None):
        db = thread_tree.connect_db()
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        result = {}
        for table in tables:
            if project_id is None:
                rows = db.execute(f'SELECT * FROM "{table}"').fetchall()
            elif "project_id" in {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}:
                rows = db.execute(f'SELECT * FROM "{table}" WHERE project_id=?', (project_id,)).fetchall()
            else:
                continue
            result[table] = sorted((tuple(row) for row in rows), key=repr)
        db.close()
        return result

    def test_public_command_refreshes_only_derived_topics_and_retries_idempotently(self):
        before = self.snapshot()
        other_before = self.snapshot(project_id=self.other_id)
        command = [sys.executable, str(SCRIPTS_ROOT / "thread_tree.py"), "refresh-topics",
                   "--project", str(self.project), "--operation-id", "synthetic-retry", "--json"]
        process = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=90)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn("PRIVATE_REFRESH_SENTINEL", process.stdout)
        result = json.loads(process.stdout)
        self.assertEqual(result["project"], {"id": self.project_id, "path": str(self.project)})
        self.assertEqual(result["fitState"], "committed")
        self.assertEqual(result["counts"]["chunks"], 6)
        self.assertEqual(result["counts"]["messages"], 6)
        self.assertEqual(result["counts"]["chats"], 1)
        after = self.snapshot()
        for table in ("turn_ingestion", "turn_chunks", "turn_chunks_fts", "staged_user_prompts", "index_shards", "index_documents"):
            self.assertEqual(after[table], before[table], table)
        self.assertEqual(self.snapshot(project_id=self.other_id), other_before)
        code, retry = self.cli("--operation-id", "synthetic-retry")
        self.assertEqual(code, 0)
        self.assertEqual(retry["fitRunId"], result["fitRunId"])
        code, fresh = self.cli()
        self.assertEqual(code, 0)
        self.assertNotEqual(fresh["operationId"], result["operationId"])
        self.assertNotEqual(fresh["fitRunId"], result["fitRunId"])
        self.assertEqual(self.snapshot(project_id=self.other_id), other_before)

    def test_paused_unselected_pending_and_out_of_scope_projects_refuse_without_writes(self):
        cases = [
            {"paused": True}, {"project_options": {"paused": True}},
            {"project_options": {"disconnectPending": True}},
            {"project_options": {"pendingDisconnectChatIds": [f"chat-{self.project_id}"]}},
            {"project_options": {"includedChatIds": []}},
            {"project_options": {"excludedChatIds": [f"chat-{self.project_id}"]}},
            {"pausePolicy": {"mode": "date", "pauseOn": "2000-01-01", "inactivityDays": 30}},
        ]
        for options in cases:
            with self.subTest(options=options):
                self.configure(**options)
                before = self.snapshot()
                with patch.object(pipeline, "rebuild_project") as rebuild:
                    code, result = self.cli()
                self.assertEqual(code, 2)
                self.assertFalse(result["ok"])
                self.assertNotIn("counts", result)
                rebuild.assert_not_called()
                self.assertEqual(self.snapshot(), before)
        self.configure()
        missing = self.root / "not-indexed"
        missing.mkdir()
        for directory in (missing, self.other, self.root / "absent"):
            before = self.snapshot()
            with patch.object(pipeline, "rebuild_project") as rebuild:
                code, result = self.cli(project=directory)
            self.assertEqual(code, 2)
            self.assertFalse(result["ok"])
            rebuild.assert_not_called()
            self.assertEqual(self.snapshot(), before)

    def test_consent_lock_is_released_during_rebuild_and_rechecked_before_counts(self):
        held = []

        @contextmanager
        def consent_lock():
            held.append(True)
            try:
                yield
            finally:
                held.pop()

        def revoke_during_fit(db, project_id, **kwargs):
            self.assertEqual(held, [])
            self.assertEqual(project_id, self.project_id)
            self.configure(paused=True)
            return {"id": "synthetic-fit", "state": "committed"}

        before = self.snapshot()
        with patch.object(thread_tree, "scope_mutation_lock", side_effect=consent_lock), \
                patch.object(pipeline, "rebuild_project", side_effect=revoke_during_fit):
            code, result = self.cli()
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertNotIn("counts", result)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_operation_and_fit_errors_do_not_expose_messages_or_touch_other_projects(self):
        before = self.snapshot()
        with patch.object(pipeline, "rebuild_project") as rebuild:
            code, result = self.cli("--operation-id", " ")
        self.assertEqual(code, 2)
        rebuild.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        with patch.object(pipeline, "rebuild_project", side_effect=ValueError("PRIVATE_REFRESH_SENTINEL")):
            code, result = self.cli()
        self.assertEqual(code, 1)
        self.assertEqual(result, {"ok": False, "error": "Context Saver topics could not be refreshed."})
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
