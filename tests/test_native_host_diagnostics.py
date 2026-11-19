"""Failed native probes retain evidence before disposable fixture cleanup."""

from __future__ import annotations

import _support

import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from contextlib import closing
from unittest.mock import patch

import native_hosts


class NativeHostDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.reports = self.root / "reports"
        self.fixture = self.root / "fixture"
        self.env = native_hosts.isolated_environment(self.fixture)
        self.project = self.fixture / "project"
        self.project.mkdir()

    def test_failed_host_command_preserves_stdout_and_stderr_before_raising(self):
        output = self.reports / "claude-output.jsonl"
        result = subprocess.CompletedProcess(["synthetic"], 7, '{"partial":"stream"}\n', "synthetic stderr")
        with patch.object(native_hosts, "host_command", return_value=["synthetic"]), patch.object(native_hosts.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(AssertionError, "failed"):
                native_hosts.run_host("claude", project=self.project, env=self.env, output_path=output)
        self.assertEqual(output.read_text(), result.stdout)
        self.assertEqual(output.with_suffix(".stderr.txt").read_text(), result.stderr)

    def test_host_timeout_preserves_partial_byte_output(self):
        output = self.reports / "claude-output.jsonl"
        error = subprocess.TimeoutExpired("synthetic", 1, output=b"partial stream", stderr=b"partial stderr")
        with patch.object(native_hosts, "host_command", return_value=["synthetic"]), patch.object(native_hosts.subprocess, "run", side_effect=error):
            with self.assertRaises(subprocess.TimeoutExpired):
                native_hosts.run_host("claude", project=self.project, env=self.env, output_path=output)
        self.assertEqual(output.read_text(), "partial stream")
        self.assertEqual(output.with_suffix(".stderr.txt").read_text(), "partial stderr")

    def test_cancelled_hook_still_fails_after_worker_settles_and_diagnostics_are_saved(self):
        store = Path(self.env["THREAD_HISTORY_TREE_DATA"])
        transcript = Path(self.env["CLAUDE_CONFIG_DIR"]) / "synthetic.jsonl"
        with closing(sqlite3.connect(store / "index.sqlite3")) as db:
            db.executescript("CREATE TABLE turn_ingestion(state TEXT, transcript_path TEXT);"
                             "CREATE TABLE staged_user_prompts(state TEXT);"
                             "CREATE TABLE turn_chunks(text TEXT);")
            db.execute("INSERT INTO turn_ingestion VALUES ('processing', ?)", (str(transcript),))
            db.execute("INSERT INTO staged_user_prompts VALUES ('reconciled')")
            db.execute("INSERT INTO turn_chunks VALUES (?)", (native_hosts.CLAUDE_FIXTURE_ANSWER,))
            db.commit()
        (store / "hook-errors.jsonl").write_text("synthetic hook diagnostic\n")
        output = "\n".join(json.dumps(event) for event in [
            {"subtype": "hook_response", "hook_event": "UserPromptSubmit", "outcome": "cancelled"},
            {"subtype": "hook_response", "hook_event": "Stop", "outcome": "success"},
            {"result": native_hosts.CLAUDE_FIXTURE_ANSWER},
        ])
        poll_started = threading.Event()
        finished = threading.Event()

        def worker():
            if poll_started.wait(timeout=3):
                with closing(sqlite3.connect(store / "index.sqlite3")) as db, db:
                    db.execute("UPDATE turn_ingestion SET state='indexed'")
                finished.set()

        read_snapshot = native_hosts._claude_index_snapshot

        def poll(*args):
            poll_started.set()
            return read_snapshot(*args)

        class FixtureServer:
            server_port = 1

            def __init__(self, *_args):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def serve_forever(self, **_kwargs):
                pass

            def shutdown(self):
                pass

        background = threading.Thread(target=worker)
        background.start()
        try:
            with patch.object(native_hosts, "ThreadingHTTPServer", FixtureServer), patch.object(native_hosts, "run_host", return_value=output), patch.object(native_hosts, "_claude_index_snapshot", side_effect=poll):
                with self.assertRaisesRegex(AssertionError, "cancelled"):
                    native_hosts.verify_claude_turn(self.project, self.fixture, self.env, self.reports)
            self.assertTrue(finished.is_set(), "strict assertion must wait for the existing fixture worker")
            self.assertEqual((self.reports / "claude-output.jsonl").read_text(), output)
            hooks = json.loads((self.reports / "claude-hooks.json").read_text())
            self.assertEqual(hooks, [["UserPromptSubmit", "cancelled"], ["Stop", "success"]])
            index = json.loads((self.reports / "claude-index.json").read_text())
            self.assertTrue(index["settled"])
            self.assertEqual(index["turns"], [["indexed", str(transcript)]])
            self.assertEqual((self.reports / "claude-hook-errors.jsonl").read_text(), "synthetic hook diagnostic\n")
        finally:
            poll_started.set()
            background.join(timeout=3)
        self.assertFalse(background.is_alive())


if __name__ == "__main__":
    unittest.main()
