#!/usr/bin/env python3

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import thread_tree


class CodexDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.state_db = self.root / "state_5.sqlite"
        db = sqlite3.connect(self.state_db)
        db.executescript("""
            CREATE TABLE projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, position INTEGER NOT NULL
            );
            CREATE TABLE project_roots (
                project_id TEXT NOT NULL, position INTEGER NOT NULL, path TEXT NOT NULL
            );
            CREATE TABLE threads (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, cwd TEXT NOT NULL,
                updated_at_ms INTEGER, updated_at INTEGER NOT NULL, name TEXT
            );
        """)
        db.execute("INSERT INTO projects VALUES ('p1', 'Example project', 0)")
        db.execute("INSERT INTO project_roots VALUES ('p1', 0, ?)", (str(self.project),))
        db.executemany(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("chat-1", "Raw opening prompt one", str(self.project), 2000, 2, "First chat"),
                ("chat-2", "Second chat", str(self.project), 1000, 1, None),
            ],
        )
        db.commit()
        db.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_project_registry_lists_projects_without_rollouts(self) -> None:
        with patch.object(thread_tree, "codex_state_db_path", return_value=self.state_db):
            projects, stats = thread_tree.discover_codex_projects()
        self.assertEqual(stats["source"], "codex-state")
        self.assertEqual(projects, [{
            "path": str(self.project.resolve()),
            "name": "Example project",
            "chatCount": 2,
        }])

    def test_project_chats_are_loaded_only_for_requested_project(self) -> None:
        with patch.object(thread_tree, "codex_state_db_path", return_value=self.state_db):
            chats = thread_tree.discover_codex_project_chats(str(self.project))
            missing = thread_tree.discover_codex_project_chats(str(self.root / "other"))
        self.assertEqual([item["id"] for item in chats], ["chat-1", "chat-2"])
        self.assertEqual([item["title"] for item in chats], ["First chat", "Second chat"])
        self.assertEqual(missing, [])

    def test_rollout_fallback_cache_rereads_only_changed_files(self) -> None:
        sessions = self.root / "sessions"
        sessions.mkdir()
        rollout = sessions / "rollout-example.jsonl"
        rollout.write_text(json.dumps({
            "type": "session_meta",
            "payload": {
                "id": "chat-1",
                "cwd": str(self.project),
                "timestamp": "2026-01-01T00:00:00Z",
            },
        }) + "\n", encoding="utf-8")
        cache_path = self.root / "cache.json"
        with patch.object(thread_tree, "DEFAULT_SESSION_ROOT", sessions), \
             patch.object(thread_tree, "session_discovery_cache_path", return_value=cache_path):
            first, first_stats = thread_tree.discover_session_metadata()
            second, second_stats = thread_tree.discover_session_metadata()
        self.assertEqual([item["id"] for item in first], ["chat-1"])
        self.assertEqual(second, first)
        self.assertEqual(first_stats["refreshed"], 1)
        self.assertEqual(second_stats["cacheHits"], 1)
        self.assertEqual(second_stats["refreshed"], 0)


if __name__ == "__main__":
    unittest.main()
