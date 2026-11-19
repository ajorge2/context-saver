"""Viewer ordering follows scoped plugin calls, not indexing activity."""

from __future__ import annotations

import _support

import io
import json
import multiprocessing
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state
import thread_tree_tools as tools


T1 = "2026-01-01T12:00:00.100000+00:00"
T2 = "2026-01-01T12:00:00.200000+00:00"
T3 = "2026-01-01T12:00:00.300000+00:00"


def _concurrent_project_migration(path, barrier, results):
    """Force two old-schema reads before either worker can add the column."""

    class PausingConnection(sqlite3.Connection):
        synchronized = False

        def execute(self, sql, *args, **kwargs):
            cursor = super().execute(sql, *args, **kwargs)
            if sql == "PRAGMA table_info(projects)":
                rows = cursor.fetchall()
                if not self.synchronized and "last_plugin_invoked_at" not in {row[1] for row in rows}:
                    self.synchronized = True
                    barrier.wait(timeout=15)
                return rows
            return cursor

    try:
        with closing(sqlite3.connect(path, timeout=20, factory=PausingConnection)) as db:
            state.initialize_state_schema(db)
        results.put("ok")
    except Exception as error:
        results.put(f"{type(error).__name__}: {error}")


class ProjectRecencyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.data = self.root / "data"
        self.data.mkdir()
        self.enterContext(patch.dict(os.environ, {"THREAD_HISTORY_TREE_DATA": str(self.data)}))
        (self.data / "config.json").write_text(json.dumps({"embedding_provider": "none"}))
        self.enterContext(patch.object(thread_tree.SemanticProvider, "_check"))
        self.paths = {name: self.root / name for name in ("alpha", "beta", "gamma")}
        self.ids = {name: state.project_id_for(str(path)) for name, path in self.paths.items()}
        with closing(thread_tree.connect_db()) as db:
            for name, path in self.paths.items():
                path.mkdir()
                state.ensure_project(db, self.ids[name], str(path))
        self.configure()

    def configure(self, names=("alpha", "beta", "gamma"), **overrides):
        projects = overrides.pop("projects", [{"path": str(self.paths[name]), "includeNewChats": True} for name in names])
        return thread_tree.save_scope_config({
            "schemaVersion": 1, "configured": bool(projects), "paused": False,
            "projects": projects,
            **overrides,
        })

    def stamp(self, name):
        with closing(thread_tree.connect_db()) as db:
            row = db.execute("SELECT last_plugin_invoked_at FROM projects WHERE id=?", (self.ids[name],)).fetchone()
            return row[0] if row else None

    def invoke(self, name, when):
        with closing(thread_tree.connect_db()) as db:
            state.record_project_invocation(db, self.ids[name], when)

    def snapshot(self, *, exclude=()):
        with closing(thread_tree.connect_db()) as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {table: sorted((tuple(r) for r in db.execute(f'SELECT * FROM "{table}"')), key=repr)
                    for table in tables if table not in exclude}

    def request_projects(self):
        class Request:
            def __init__(self):
                self.wire = io.BytesIO(b"GET /api/threads?include_all=1 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                self.response = bytearray()

            def makefile(self, *_args, **_kwargs):
                return self.wire

            def sendall(self, body):
                self.response.extend(body)

        request = Request()
        thread_tree.ViewerHandler(request, ("127.0.0.1", 0), None)
        header, body = bytes(request.response).split(b"\r\n\r\n", 1)
        self.assertEqual(header.split()[1], b"200")
        return json.loads(body)

    def transcript(self, name="alpha", chat="attached"):
        path = self.paths[name] / "synthetic.jsonl"
        messages = [{"type": "session_meta", "payload": {"session_id": chat, "cwd": str(self.paths[name])}}]
        for role, text in (("user", "Plan the synthetic retrieval index."), ("assistant", "The index retains source evidence.")):
            messages.append({"type": "response_item", "payload": {
                "type": "message", "id": f"{chat}-{role}", "role": role,
                "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
            }})
        path.write_text("\n".join(json.dumps(row) for row in messages) + "\n")
        with closing(thread_tree.connect_db()) as db:
            state.observe_session(db, project_root=str(self.paths[name]), thread_id=chat, transcript_path=str(path))
        return path

    def test_legacy_schema_migration_is_idempotent_and_preserves_project_data(self):
        with closing(sqlite3.connect(self.root / "legacy.sqlite3")) as db:
            db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, cwd TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            db.execute("INSERT INTO projects VALUES ('legacy', '/synthetic/legacy', 'created', 'updated')")
            db.commit()
            for _ in range(2):
                state.initialize_state_schema(db)
            self.assertEqual(db.execute("SELECT * FROM projects").fetchone(), ("legacy", "/synthetic/legacy", "created", "updated", None))

    def test_two_process_upgrade_rechecks_the_old_schema_after_acquiring_write_ownership(self):
        path = self.root / "concurrent-legacy.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, cwd TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            db.execute("INSERT INTO projects VALUES ('legacy', '/synthetic/legacy', 'created', 'updated')")
            db.commit()
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        results = context.Queue()
        processes = [context.Process(target=_concurrent_project_migration, args=(str(path), barrier, results)) for _ in range(2)]
        started = []
        try:
            for process in processes:
                process.start()
                started.append(process)
            deadline = time.monotonic() + 25
            for process in started:
                process.join(timeout=max(0, deadline - time.monotonic()))
            self.assertFalse(any(process.is_alive() for process in processes), "concurrent migrations timed out")
            self.assertEqual([process.exitcode for process in processes], [0, 0])
            self.assertEqual([results.get(timeout=3) for _ in processes], ["ok", "ok"])
        finally:
            for process in started:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
            results.close()
            results.join_thread()
        with closing(sqlite3.connect(path)) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(projects)")]
            self.assertEqual(columns.count("last_plugin_invoked_at"), 1)
            self.assertEqual(db.execute("SELECT * FROM projects").fetchone(), ("legacy", "/synthetic/legacy", "created", "updated", None))
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            statements = []
            db.set_trace_callback(statements.append)
            state.initialize_state_schema(db)
            self.assertNotIn("BEGIN IMMEDIATE", statements, "already-migrated fast path must avoid taking the upgrade lock")

    def test_order_uses_invocation_history_and_accepts_newer_legacy_client_calls(self):
        with closing(thread_tree.connect_db()) as db:
            state.begin_chat_activation(db, project_id=self.ids["alpha"], thread_id="a", transcript_path=None, invoked_at=T1)
            state.begin_chat_activation(db, project_id=self.ids["beta"], thread_id="b", transcript_path=None, invoked_at=T2)
            # Maintenance can advance activity without representing plugin use.
            with db:
                db.execute("UPDATE projects SET updated_at='2099-01-01T00:00:00+00:00' WHERE id=?", (self.ids["gamma"],))
        self.assertEqual([r["id"] for r in pipeline.list_projects()][:2], [self.ids["beta"], self.ids["alpha"]])
        self.assertIsNone(pipeline.list_projects()[-1]["last_plugin_invoked_at"])
        self.invoke("alpha", T3)
        self.assertEqual(self.request_projects()[0]["id"], self.ids["alpha"])
        # Existing MCP processes may still update only the old activation field.
        with closing(thread_tree.connect_db()) as db, db:
            db.execute("UPDATE chat_plugin_activations SET last_invoked_at='2026-01-01T12:00:00.400000+00:00' WHERE project_id=?", (self.ids["beta"],))
        self.assertEqual(self.request_projects()[0]["id"], self.ids["beta"])

    def test_unknown_usage_ties_are_stable_and_deleted_or_disconnected_projects_fall_back(self):
        unknown = [r["id"] for r in self.request_projects()]
        self.assertEqual(unknown, sorted(self.ids.values()))
        for name, stamp in (("alpha", T1), ("beta", T2), ("gamma", T3)):
            self.invoke(name, stamp)
        self.assertEqual(self.request_projects()[0]["id"], self.ids["gamma"])
        self.configure(("alpha", "beta"))
        self.assertEqual(self.request_projects()[0]["id"], self.ids["beta"])
        with closing(thread_tree.connect_db()) as db, db:
            db.execute("DELETE FROM projects WHERE id=?", (self.ids["beta"],))
        self.assertEqual(self.request_projects()[0]["id"], self.ids["alpha"])
        self.configure(())
        self.assertEqual(self.request_projects(), [])

    def test_later_completion_cannot_replace_a_newer_call_or_turn_finish_into_usage(self):
        self.invoke("alpha", T3)
        with closing(thread_tree.connect_db()) as db:
            state.begin_chat_activation(db, project_id=self.ids["alpha"], thread_id="a", transcript_path=None, invoked_at=T3)
            state.begin_chat_activation(db, project_id=self.ids["alpha"], thread_id="a", transcript_path=None, invoked_at=T1)
            state.record_project_invocation(db, self.ids["alpha"], T1)
            state.finish_chat_activation(db, project_id=self.ids["alpha"], thread_id="a", indexed_through_line=4)
            activation = state.chat_activation(db, self.ids["alpha"], "a")
        self.assertEqual(self.stamp("alpha"), T3)
        self.assertEqual(activation["last_invoked_at"], T3)
        self.assertNotEqual(activation["completed_at"], T3)

    def test_first_prepare_records_before_slow_backfill_and_fast_prepare_records_again(self):
        self.transcript()
        with closing(thread_tree.connect_db()) as db, db:
            db.execute("DELETE FROM projects WHERE id=?", (self.ids["alpha"],))

        def process(*_args, **_kwargs):
            self.assertEqual(self.stamp("alpha"), T1)
            return {"processed_turns": 0, "failures": []}

        with patch.object(state, "plugin_invocation_time", return_value=T1), patch.object(pipeline, "process_project", side_effect=process):
            first = tools.prepare_current_chat(project_root=str(self.paths["alpha"]), thread_id="attached")
        self.assertTrue(first["first_invocation"])
        self.assertEqual(first["status"], "ready")
        with patch.object(state, "plugin_invocation_time", return_value=T2), patch.object(pipeline, "process_project") as process_again:
            second = tools.prepare_current_chat(project_root=str(self.paths["alpha"]), thread_id="attached")
        self.assertFalse(second["first_invocation"])
        process_again.assert_not_called()
        self.assertEqual(self.stamp("alpha"), T2)

    def test_concurrent_first_prepare_preserves_newer_call_before_project_exists(self):
        self.transcript()
        with closing(thread_tree.connect_db()) as db, db:
            db.execute("DELETE FROM projects WHERE id=?", (self.ids["alpha"],))
        enqueue = pipeline.enqueue_transcript

        def interleave(*args, **kwargs):
            other = tools.prepare_current_chat(project_root=str(self.paths["alpha"]), thread_id="attached")
            self.assertFalse(other["first_invocation"])
            self.assertIsNone(self.stamp("alpha"))
            return enqueue(*args, **kwargs)

        with patch.object(state, "plugin_invocation_time", side_effect=[T1, T2]), patch.object(pipeline, "enqueue_transcript", side_effect=interleave), patch.object(pipeline, "process_project", return_value={"processed_turns": 0, "failures": []}):
            tools.prepare_current_chat(project_root=str(self.paths["alpha"]), thread_id="attached")
        self.assertEqual(self.stamp("alpha"), T2)

    def test_zero_hit_mcp_search_updates_only_project_usage_and_not_query_storage(self):
        before = self.snapshot()
        with closing(thread_tree.connect_db()) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(projects)")]
        stamp_index = columns.index("last_plugin_invoked_at")
        id_index = columns.index("id")
        with patch.object(state, "plugin_invocation_time", return_value=T2):
            result = tools.search_project_history("unretained-query-sentinel", project_root=str(self.paths["beta"]))
        self.assertEqual(result["evidence"], [])
        self.assertEqual(self.stamp("beta"), T2)
        expected = {**before, "projects": [
            tuple(T2 if row[id_index] == self.ids["beta"] and index == stamp_index else value
                  for index, value in enumerate(row))
            for row in before["projects"]
        ]}
        self.assertEqual(self.snapshot(), expected)
        self.assertEqual(self.request_projects()[0]["id"], self.ids["beta"])

    def test_rejected_search_and_paused_prepare_never_record_usage(self):
        for options in ({"configured": False}, {"paused": True},
                        {"projects": [{"path": str(self.paths["beta"]), "includeNewChats": True}]},
                        {"projects": [{"path": str(self.paths["alpha"]), "includeNewChats": False, "includedChatIds": []}]}):
            self.configure(**options)
            before = self.snapshot()
            with self.subTest(options=options), self.assertRaises(ValueError):
                tools.search_project_history("unused query", project_root=str(self.paths["alpha"]))
            self.assertEqual(self.snapshot(), before)
        self.configure(paused=True)
        with patch.object(tools, "_resolve_current_session", return_value={"project_root": str(self.paths["alpha"]), "thread_id": "paused", "transcript_path": ""}):
            self.assertEqual(tools.prepare_current_chat()["status"], "paused")
        self.assertIsNone(self.stamp("alpha"))

    def test_browsing_ingestion_and_topic_maintenance_do_not_promote_project(self):
        self.invoke("alpha", T1)
        self.invoke("beta", T2)
        pipeline.project_explorer_payload(self.ids["alpha"], "")
        pipeline.project_explorer_payload(self.ids["alpha"], "no results")
        with closing(thread_tree.connect_db()) as db:
            state.ensure_project(db, self.ids["alpha"], str(self.paths["alpha"]))
            pipeline.rebuild_project(db, self.ids["alpha"], reason="synthetic empty maintenance")
        self.assertEqual(self.stamp("alpha"), T1)
        self.assertEqual(self.request_projects()[0]["id"], self.ids["beta"])


if __name__ == "__main__":
    unittest.main()
