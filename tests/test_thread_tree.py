#!/usr/bin/env python3

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pre_compact


MODULE_PATH = SCRIPTS_ROOT / "thread_tree.py"
SPEC = importlib.util.spec_from_file_location("thread_tree", MODULE_PATH)
assert SPEC and SPEC.loader
thread_tree = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(thread_tree)


def message(line_id: str, role: str, text: str) -> dict:
    return {
        "timestamp": "2026-01-01T00:00:00Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "id": line_id,
            "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
        },
    }


class ThreadTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        os.environ["THREAD_HISTORY_TREE_DATA"] = str(Path(self.temp.name) / "data")
        self.transcript = Path(self.temp.name) / "rollout.jsonl"
        rows = [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "session_meta",
                "payload": {"session_id": "thread-test", "id": "thread-test", "cwd": self.temp.name},
            },
            message("m1", "user", "How does Codex compaction preserve thread context?"),
            message("m2", "assistant", "Compaction carries forward an opaque compacted context item."),
            message("m3", "user", "Can a pre-compaction hook index the window first?"),
            message("m4", "assistant", "Yes. PreCompact runs before manual and automatic compaction."),
        ]
        self.transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_index_search_and_verified_sources(self) -> None:
        result = thread_tree.index_range(self.transcript, 1, None, "test")
        self.assertEqual(result["status"], "indexed")
        self.assertEqual(result["messages"], 4)
        self.assertGreaterEqual(result["spans"], 2)

        results = thread_tree.search_nodes("pre compact hook", "thread-test")
        self.assertTrue(results)
        span = next(item for item in results if item["kind"] == "span")
        detail = thread_tree.node_detail(span["id"], include_sources=True)
        self.assertIsNotNone(detail)
        self.assertIn("PreCompact", detail["sources"][0]["text"])
        self.assertTrue(detail["sources"][0]["verified"])

    def test_hook_cursor_is_incremental(self) -> None:
        event = {"session_id": "thread-test", "transcript_path": str(self.transcript), "trigger": "auto"}
        first = thread_tree.index_hook_event(event)
        self.assertEqual(first["status"], "indexed")
        self.assertGreater(first["approx_tokens"], 0)
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message("m5", "user", "Show the semantic tree viewer.")) + "\n")
            handle.write(json.dumps(message("m6", "assistant", "The viewer shows nodes and connections read-only.")) + "\n")
        second = thread_tree.index_hook_event(event)
        self.assertEqual(second["messages"], 2)
        self.assertGreater(second["line_start"], first["line_end"])

    def test_connection_rebuild_uses_pinned_uv_runtime_when_scalable_modules_are_missing(self) -> None:
        worker = Path(self.temp.name) / "worker.py"
        with patch.object(thread_tree.importlib.util, "find_spec", return_value=None), \
             patch.object(thread_tree.shutil, "which", return_value="/opt/homebrew/bin/uv"):
            command = thread_tree._connection_rebuild_command(
                worker,
                "refresh_" + ("a" * 32),
                ["project-one"],
            )
        self.assertEqual(command[:5], [
            "/opt/homebrew/bin/uv",
            "run",
            "--no-project",
            "--python",
            "3.12",
        ])
        for requirement in thread_tree.SEMANTIC_REQUIREMENTS:
            self.assertIn(requirement, command)
        self.assertEqual(command[-3:], [str(worker), "refresh_" + ("a" * 32), "project-one"])

    def test_precompact_notice_names_active_automation_and_disable_path(self) -> None:
        output = io.StringIO()
        with patch.object(pre_compact, "enqueue_transcript", return_value={"approx_tokens": 12_345, "project_id": "project-test"}), \
             patch.object(pre_compact.subprocess, "Popen"), \
             patch.object(pre_compact, "parse_transcript_lines", return_value={"cwd": self.temp.name, "thread_id": "thread-test"}), \
             patch.object(pre_compact, "scope_decision", return_value={"active": True, "reason": "active"}), \
             patch.object(pre_compact.sys, "stdin", io.StringIO("{}")), \
             redirect_stdout(output):
            with patch.object(pre_compact.Path, "exists", return_value=True):
                # The queue adapter is mocked, so the transcript value only
                # needs to exercise the visible recovery notice.
                pre_compact.sys.stdin = io.StringIO('{"transcript_path":"/tmp/rollout.jsonl"}')
                self.assertEqual(pre_compact.main(), 0)

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["continue"])
        self.assertIn("Context Saver auto-indexing is active for this project", payload["systemMessage"])
        self.assertIn("Preserving about 12,345 conversation tokens", payload["systemMessage"])
        self.assertIn("queued before compaction", payload["systemMessage"])
        self.assertIn("Context Saver off", payload["systemMessage"])
        self.assertIn("this chat", payload["systemMessage"])

    def test_token_estimate_is_local_and_message_based(self) -> None:
        messages = [
            {"text": "abcd"},
            {"text": "eight888"},
        ]
        self.assertEqual(thread_tree.estimate_message_tokens(messages), 3)

    def test_environment_messages_are_ignored(self) -> None:
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message("m-env", "user", "<environment_context>secret plumbing</environment_context>")) + "\n")
            handle.write(json.dumps(message("m-review", "user", "The following is the Codex agent history whose request action you are assessing")) + "\n")
        parsed = thread_tree.parse_transcript_lines(self.transcript)
        self.assertNotIn("m-env", {item["id"] for item in parsed["messages"]})
        self.assertNotIn("m-review", {item["id"] for item in parsed["messages"]})

    def test_assistant_only_fragment_is_not_a_span(self) -> None:
        assistant_only = [
            {"id": "a-only", "role": "assistant", "text": "I am still inspecting the implementation.", "line": 1}
        ]
        self.assertEqual(thread_tree.extract_fallback(assistant_only), [])

    def test_lexical_scores_preserve_ranking(self) -> None:
        thread_tree.index_range(self.transcript, 1, None, "test")
        results = thread_tree.search_nodes("compaction context hook", "thread-test")
        scores = [item["score"] for item in results]
        self.assertGreater(len(set(scores)), 1)
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_viewer_config_persists_validated_values(self) -> None:
        defaults = thread_tree.load_viewer_config()
        self.assertEqual(defaults["title"], "Context Saver")
        saved = thread_tree.save_viewer_config({**defaults, "title": "History Map", "layerGap": 180})
        self.assertEqual(saved["title"], "History Map")
        self.assertEqual(thread_tree.load_viewer_config()["layerGap"], 180)
        with self.assertRaises(ValueError):
            thread_tree.save_viewer_config({**defaults, "accentColor": "red"})
        with self.assertRaises(ValueError):
            thread_tree.save_viewer_config({**defaults, "leafGap": 500})

if __name__ == "__main__":
    unittest.main()
