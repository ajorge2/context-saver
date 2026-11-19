"""Scoped HTTP titles use only allowed evidence, with bounded warm caching."""

from __future__ import annotations

import _support

import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import thread_tree
import thread_tree_labels as labels
import thread_tree_pipeline as pipeline
import thread_tree_state as state


class VisibleClusterLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch.dict(os.environ, {"THREAD_HISTORY_TREE_DATA": str(self.root)}))
        (self.root / "config.json").write_text(json.dumps({"embedding_provider": "none"}), encoding="utf-8")
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        self.project = state.project_id_for(str(self.project_root))
        self.nodes = ("synthetic-span", "synthetic-topic", "synthetic-subject")
        self.sentinel = "HIDDEN_GLOBAL_NAME_SENTINEL"
        self.scope(["kept"])
        self.clear_cache()
        self.addCleanup(self.clear_cache)
        db = thread_tree.connect_db()
        with db:
            db.execute("INSERT INTO projects VALUES (?, ?, ?, ?)",
                       (self.project, str(self.project_root), state.utc_now(), state.utc_now()))
            for node, layer in zip(self.nodes, ("span", "specific", "broad")):
                db.execute(
                    """INSERT INTO semantic_nodes
                       (id, project_id, layer, lifecycle, title, summary, created_at, updated_at)
                       VALUES (?, ?, ?, 'locked', ?, ?, ?, ?)""",
                    (node, self.project, layer, self.sentinel, self.sentinel, state.utc_now(), state.utc_now()),
                )
            db.executemany("INSERT INTO semantic_edges (child_id, parent_id, primary_edge, coverage) VALUES (?, ?, 1, 1)",
                           [(self.nodes[0], self.nodes[1]), (self.nodes[1], self.nodes[2])])
        db.close()
        self.add_chunks("kept", 0, 6)
        self.add_chunks("hidden", 0, 1, f"USER: {self.sentinel} private amber telescope.")

    @staticmethod
    def clear_cache() -> None:
        with pipeline._SCOPED_TITLE_LOCK:
            pipeline._SCOPED_TOPIC_TITLES.clear()

    def scope(self, chats: list[str]) -> None:
        thread_tree.save_scope_config({
            "schemaVersion": 1, "configured": True, "paused": False,
            "projects": [{"path": str(self.project_root), "includeNewChats": False, "includedChatIds": chats}],
        })

    def add_chunks(self, chat: str, start: int, stop: int, text: str | None = None) -> None:
        transcript = self.root / f"{chat}.jsonl"
        transcript.write_text("", encoding="utf-8")
        db = thread_tree.connect_db()
        now = state.utc_now()
        with db:
            db.execute(
                """INSERT OR IGNORE INTO turn_ingestion
                   (id, project_id, thread_id, transcript_path, content_hash, state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'indexed', ?, ?)""",
                (f"turn-{chat}", self.project, chat, str(transcript), chat, now, now),
            )
            chunks = []
            for index in range(start, stop):
                body = text or ("USER: All right, carry on." if index == 0 else
                                "USER: Database query optimization. ASSISTANT: Index tuning and execution plans.")
                chunk_id = f"{chat}-{index:05}"
                chunks.append((chunk_id, self.project, chat, f"turn-{chat}", body, chunk_id,
                               len(body), json.dumps([chunk_id]), now))
            db.executemany(
                """INSERT INTO turn_chunks
                   (id, project_id, thread_id, turn_id, text, content_hash, byte_count, source_message_ids, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", chunks,
            )
            db.executemany("INSERT INTO turn_chunks_fts(chunk_id, project_id, thread_id, text) VALUES (?, ?, ?, ?)",
                           [(chunk[0], chunk[1], chunk[2], chunk[4]) for chunk in chunks])
            db.executemany("INSERT INTO semantic_node_memberships VALUES (?, ?, 1)",
                           [(self.nodes[0], chunk[0]) for chunk in chunks])
        db.close()

    def request(self, path: str, **params):
        class WireRequest:
            def __init__(self, wire):
                self.wire = io.BytesIO(wire)
                self.response = bytearray()

            def makefile(self, *_args, **_kwargs):
                return self.wire

            def sendall(self, body):
                self.response.extend(body)

        wire = WireRequest((f"GET {path}?{urlencode({'thread_id': self.project, **params})} HTTP/1.1\r\n"
                            "Host: localhost\r\nConnection: close\r\n\r\n").encode())
        thread_tree.ViewerHandler(wire, ("127.0.0.1", 0), None)
        header, body = bytes(wire.response).split(b"\r\n\r\n", 1)
        self.assertEqual(int(header.split()[1]), 200, body)
        result = json.loads(body)
        self.assertNotIn(self.sentinel, json.dumps(result))
        return result

    @staticmethod
    def semantic_titles(payload):
        return [node["title"] for layer in ("subject", "broad_topic", "specific_topic")
                for node in payload["layers"][layer]]

    def test_actual_scoped_explorer_metadata_and_tree_show_whole_allowed_themes(self) -> None:
        with patch.object(labels, "representation", wraps=labels.representation) as represent, \
                patch.object(labels, "build_background", wraps=labels.build_background) as background:
            browse = self.request("/api/explore", q="")
            titles = self.semantic_titles(browse)
            self.assertEqual(len(titles), 3)
            self.assertEqual(len(set(titles)), 1)
            self.assertIn("Database query optimization", titles[0])
            self.assertNotIn("All right", titles[0])
            self.assertEqual(represent.call_count, 1)  # Three identical ancestry sets.
            for call in (represent.call_args, background.call_args):
                self.assertEqual(len(call.args[0]), 6)
                self.assertTrue(all(row["id"].startswith("kept-") for row in call.args[0]))
                self.assertNotIn(self.sentinel, json.dumps(call.args[0]))
            detail = self.request(f"/api/node/{self.nodes[1]}", view="explorer")
            self.assertEqual(detail["title"], titles[0])
            self.assertTrue(all(relation["title"] == titles[0] for relation in detail["parents"] + detail["children"]))
            message = self.request("/api/node/message:kept-00001", view="explorer")
            self.assertEqual(message["parents"][0]["title"], titles[0])
            tree = self.request("/api/tree")
            self.assertEqual({node["title"] for node in tree["nodes"] if node["id"] in self.nodes}, {titles[0]})
            self.assertEqual(represent.call_count, 1)  # Warm across API request types.
            self.assertEqual(self.semantic_titles(self.request("/api/explore", q="optimization")), titles)
        # Unrestricted local consumers keep their published title contract.
        self.assertEqual(pipeline.project_explorer_payload(self.project, "")["layers"]["subject"][0]["title"], self.sentinel)

    def test_changed_previews_scope_and_memberships_cannot_reuse_stale_titles(self) -> None:
        initial = self.semantic_titles(self.request("/api/explore", q=""))[0]
        self.add_chunks("alternate", 0, 4, "USER: API rate limits and request throttling.")
        self.scope(["alternate"])
        scoped = self.semantic_titles(self.request("/api/explore", q=""))[0]
        self.assertIn("API rate limits", scoped)
        self.assertNotEqual(scoped, initial)
        db = thread_tree.connect_db()
        with db:
            db.execute("UPDATE turn_chunks SET text=? WHERE thread_id='alternate'",
                       ("USER: Vector indexing and query planning.",))
        db.close()
        changed = self.semantic_titles(self.request("/api/explore", q=""))[0]
        self.assertIn("Vector indexing", changed)
        self.assertNotEqual(changed, scoped)
        self.scope(["kept"])
        db = thread_tree.connect_db()
        with db:
            db.execute("DELETE FROM semantic_node_memberships WHERE chunk_id LIKE 'kept-%' AND chunk_id!='kept-00000'")
        db.close()
        self.assertEqual(set(self.semantic_titles(self.request("/api/explore", q=""))), {"Acknowledgments"})

    def test_ten_thousand_allowed_rows_do_not_reextract_titles_on_page_changes(self) -> None:
        self.add_chunks("kept", 6, 10_000)
        times = []
        with patch.object(labels, "_document", wraps=labels._document) as extract, \
                patch.object(labels, "build_background", wraps=labels.build_background) as background, \
                patch.object(labels, "representation", wraps=labels.representation) as represent:
            for offset in (0, 36, 72, 108):
                started = time.perf_counter()
                payload = self.request("/api/explore", q="", message_offset=offset)
                times.append(time.perf_counter() - started)
                self.assertEqual(payload["messagePage"]["total"], 10_000)
                self.assertEqual(len(payload["layers"]["specific_message"]), 36)
            self.assertEqual(background.call_count, 1)
            self.assertEqual(represent.call_count, 1)
            self.assertEqual(extract.call_count, 20_000)
        self.page_timings = times  # Diagnostic measurement; no machine-dependent gate.

    def test_cross_request_cache_is_bounded_and_stores_titles_only(self) -> None:
        chunks = {f"chunk-{index}": {"preview": "USER: Vector indexing and query planning."} for index in range(12)}
        with patch.object(pipeline, "_SCOPED_TITLE_CACHE_LIMIT", 4):
            visible = pipeline._VisibleTopicLabels(chunks)
            for index in range(12):
                visible.title({f"chunk-{index}"})
        self.assertEqual(len(pipeline._SCOPED_TOPIC_TITLES), 4)
        for key, title in pipeline._SCOPED_TOPIC_TITLES.items():
            self.assertTrue(all(len(digest) == 64 for digest in key))
            self.assertLessEqual(len(title), 64)


if __name__ == "__main__":
    unittest.main()
