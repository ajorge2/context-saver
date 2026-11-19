"""Exercise browse pagination against a large, isolated SQLite archive."""

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import io
import json
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state


class ExplorerPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary).resolve()
        self.enterContext(patch.dict(os.environ, {"THREAD_HISTORY_TREE_DATA": str(self.root)}))
        (self.root / "config.json").write_text(json.dumps({"embedding_provider": "none"}), encoding="utf-8")
        self.enterContext(patch.object(thread_tree.SemanticProvider, "_check"))
        self.project_id = state.project_id_for(str(self.root / "project"))
        self.other_project_id = state.project_id_for(str(self.root / "other"))
        self.project_scope = {
            "path": str(self.root / "project"), "includeNewChats": False,
            "includedChatIds": ["chat-a", "chat-b", "excluded", "pending", "evicted", "disconnected"],
            "excludedChatIds": ["excluded"], "pendingDisconnectChatIds": ["pending"],
        }
        thread_tree.save_scope_config({
            "schemaVersion": 1, "configured": True, "paused": False,
            "projects": [self.project_scope],
        })
        self.live_ids = [f"live-{index:03}" for index in range(145)]
        db = thread_tree.connect_db()
        with db:
            for project_id, directory in ((self.project_id, "project"), (self.other_project_id, "other")):
                db.execute("INSERT INTO projects (id, cwd, created_at, updated_at) VALUES (?, ?, ?, ?)",
                           (project_id, str(self.root / directory), state.utc_now(), state.utc_now()))
            for node_id, layer in (("all", "broad"), ("topic", "specific"), ("early", "span"), ("later", "span")):
                db.execute(
                    """INSERT INTO semantic_nodes (id, project_id, layer, title, lifecycle, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'locked', ?, ?)""",
                    (node_id, self.project_id, layer, node_id, state.utc_now(), state.utc_now()),
                )
            db.executemany(
                "INSERT INTO semantic_edges (child_id, parent_id, primary_edge, coverage) VALUES (?, ?, 1, 1)",
                [("topic", "all"), ("early", "topic"), ("later", "topic")],
            )
            for index, chunk_id in enumerate(self.live_ids):
                self.add_chunk(db, chunk_id, "chat-a" if index % 2 else "chat-b", span="early" if index < 70 else "later")
            for chat, count in (("excluded", 4), ("pending", 3), ("unselected", 2), ("evicted", 2), ("disconnected", 2)):
                for index in range(count):
                    self.add_chunk(db, f"{chat}-{index}", chat, evicted=chat == "evicted")
            db.execute("DELETE FROM turn_ingestion WHERE thread_id='disconnected'")
            for index in range(3):
                self.add_chunk(db, f"foreign-{index}", "foreign", project_id=self.other_project_id, span=None)
            db.execute(
                """INSERT INTO staged_user_prompts
                   (codex_turn_id, project_id, thread_id, prompt, content_hash, state, created_at, updated_at)
                   VALUES ('staged-only', ?, 'chat-a', 'uniquematcholder staged private prompt', 'staged', 'staged', ?, ?)""",
                (self.project_id, state.utc_now(), state.utc_now()),
            )
        db.close()

    def add_chunk(self, db, chunk_id, chat, *, project_id=None, span="later", evicted=False):
        project_id = project_id or self.project_id
        turn_id = f"turn-{chat}"
        db.execute(
            """INSERT OR IGNORE INTO turn_ingestion
               (id, project_id, thread_id, content_hash, state, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'indexed', ?, ?)""",
            (turn_id, project_id, chat, turn_id, state.utc_now(), state.utc_now()),
        )
        text = f"USER: pagedarchive evidence {chunk_id}" + (" uniquematcholder" if chunk_id == "live-000" else "")
        db.execute(
            """INSERT INTO turn_chunks
               (id, project_id, thread_id, turn_id, text, content_hash, byte_count, source_message_ids, evicted, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (chunk_id, project_id, chat, turn_id, text, chunk_id, len(text), json.dumps([chunk_id]), int(evicted), state.utc_now()),
        )
        db.execute("INSERT INTO turn_chunks_fts(chunk_id, project_id, thread_id, text) VALUES (?, ?, ?, ?)",
                   (chunk_id, project_id, chat, text))
        if span:
            db.execute("INSERT INTO semantic_node_memberships VALUES (?, ?, 1)", (span, chunk_id))

    def browse(self, **kwargs):
        return pipeline.project_explorer_payload(self.project_id, "", project_scope=self.project_scope, **kwargs)

    @staticmethod
    def ids(payload):
        return [item["id"].removeprefix("message:") for item in payload["layers"]["specific_message"]]

    def test_pages_reach_every_scoped_live_message_in_stable_order(self) -> None:
        union = []
        for offset in range(0, 145, 36):
            payload = self.browse(message_offset=offset)
            page = payload["messagePage"]
            self.assertEqual(page, {
                "offset": offset, "limit": 36, "total": 145,
                "hasNext": offset + 36 < 145, "hasPrevious": offset > 0,
            })
            page_ids = self.ids(payload)
            self.assertLessEqual(len(page_ids), 36)
            self.assertEqual(payload["counts"]["specific_message"], len(page_ids))
            self.assertEqual({item["id"] for item in payload["layers"]["specific_topic"]}, {"early", "later"})
            self.assertEqual({edge["child_id"].removeprefix("message:") for edge in payload["edges"]
                              if edge["child_id"].startswith("message:")}, set(page_ids))
            union.extend(page_ids)
        self.assertEqual(union, self.live_ids[::-1])
        self.assertEqual(len(set(union)), 145)
        # An explicit page size overrides the old generic retrieval limit.
        self.assertEqual(len(self.ids(self.browse(limit=1, message_limit=100))), 100)
        self.assertEqual(len(self.ids(self.browse(limit=1))), 1)
        self.assertEqual(self.browse(message_limit=1000)["messagePage"]["limit"], 100)

    def test_search_stays_bounded_and_older_matches_are_reachable_in_browse(self) -> None:
        search = pipeline.project_explorer_payload(self.project_id, "pagedarchive", project_scope=self.project_scope)
        self.assertEqual(len(self.ids(search)), 80)
        self.assertIsNone(search["messagePage"])
        match = pipeline.project_explorer_payload(self.project_id, "uniquematcholder", project_scope=self.project_scope,
                                                 message_offset=100, message_limit=1)
        self.assertEqual(self.ids(match), ["live-000"])
        self.assertNotIn("live-000", self.ids(self.browse()))
        browse_union = set().union(*(self.ids(self.browse(message_offset=offset)) for offset in range(0, 145, 36)))
        self.assertLessEqual(set(self.ids(search) + self.ids(match)), browse_union)
        self.assertNotIn("staged-only", json.dumps(match))

    def test_intersected_branches_preserve_only_a_scoped_anchor_and_full_topics(self) -> None:
        result = self.browse(browse_nodes=("all", "early"), browse_message="message:live-000", message_limit=10)
        self.assertEqual(result["messagePage"]["total"], 70)
        self.assertEqual(len(self.ids(result)), 10)
        self.assertEqual(self.ids(result), [*self.live_ids[61:70][::-1], "live-000"])
        self.assertEqual({item["id"] for item in result["layers"]["specific_topic"]}, {"early", "later"})
        for anchor in ("message:excluded-0", "message:pending-0", "message:unselected-0", "message:evicted-0",
                       "message:disconnected-0", "message:foreign-0", "message:live-100"):
            with self.subTest(anchor=anchor):
                result = self.browse(browse_nodes=("early",), browse_message=anchor, message_limit=1)
                self.assertEqual(self.ids(result), ["live-069"])
        included = pipeline.project_explorer_payload(
            self.project_id, "", project_scope={"includeNewChats": False, "includedChatIds": ["chat-a"]}, message_limit=100,
        )
        self.assertEqual(self.ids(included), [chunk_id for index, chunk_id in reversed(list(enumerate(self.live_ids))) if index % 2])

    def test_empty_branches_and_stale_offsets_have_consistent_metadata(self) -> None:
        empty_page = {"offset": 0, "limit": 36, "total": 0, "hasNext": False, "hasPrevious": False}
        for nodes in (("early", "later"), ("missing",), ("all", "topic", "early", "later")):
            with self.subTest(nodes=nodes):
                result = self.browse(browse_nodes=nodes, message_offset=1000)
                self.assertEqual(self.ids(result), [])
                self.assertEqual(result["messagePage"], empty_page)
        tail = self.browse(message_offset=1000)
        self.assertEqual(tail["messagePage"], {"offset": 109, "limit": 36, "total": 145, "hasNext": False, "hasPrevious": True})
        self.assertEqual(self.ids(tail), self.live_ids[:36][::-1])
        self.assertEqual(self.browse(message_offset=144)["messagePage"]["offset"], 144)
        self.assertEqual(self.ids(self.browse(message_offset=144)), ["live-000"])
        with patch.object(pipeline, "_explorer_evidence", return_value=({}, {}, {}, {})):
            self.assertEqual(self.browse(message_offset=1000)["messagePage"], empty_page)
        for options in ({"message_offset": -1}, {"message_offset": "1"}, {"message_limit": 0}, {"message_limit": 1.5}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.browse(**options)

    def test_pages_read_one_snapshot_and_only_fetch_bounded_bodies(self) -> None:
        statements = []

        def read_connection():
            db = sqlite3.connect(thread_tree.db_path())
            db.row_factory = sqlite3.Row
            db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 101)
            db.set_trace_callback(statements.append)
            return db

        db = thread_tree.connect_db()
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        before = {name: db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}
        db.close()
        with patch.object(thread_tree, "connect_db", side_effect=read_connection):
            for offset in range(0, 145, 36):
                self.browse(message_offset=offset, message_limit=100)
            pipeline.project_explorer_payload(self.project_id, "pagedarchive", project_scope=self.project_scope)
        self.assertFalse([sql for sql in statements if re.match(r"\s*(INSERT|UPDATE|DELETE|REPLACE)\b", sql, re.I)])
        bodies = [sql for sql in statements if "substr(text, 1, 1200)" in sql]
        self.assertTrue(bodies)
        self.assertTrue(all(len(re.findall(r"'live-\d+'", sql)) <= 100 for sql in bodies))
        db = thread_tree.connect_db()
        after = {name: db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}
        db.close()
        self.assertEqual(after, before)

        original_evidence = pipeline._explorer_evidence

        def evict_after_metadata(db, project_id, project_scope):
            result = original_evidence(db, project_id, project_scope)
            other = sqlite3.connect(thread_tree.db_path())
            with other:
                other.execute("UPDATE turn_chunks SET evicted=1 WHERE id='live-144'")
            other.close()
            return result

        with patch.object(pipeline, "_explorer_evidence", side_effect=evict_after_metadata):
            result = self.browse(message_limit=1)
        self.assertEqual(self.ids(result), ["live-144"])
        self.assertEqual(result["messagePage"]["total"], 145)
        self.assertEqual(self.ids(self.browse(message_limit=1)), ["live-143"])
        self.assertEqual(self.browse()["messagePage"]["total"], 144)

    def request(self, **params):
        class Request:
            def __init__(self, wire):
                self.wire = io.BytesIO(wire)
                self.response = bytearray()

            def makefile(self, *_args, **_kwargs):
                return self.wire

            def sendall(self, body):
                self.response.extend(body)

        request = Request(f"GET /api/explore?{urlencode({'thread_id': self.project_id, **params})} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
        thread_tree.ViewerHandler(request, ("127.0.0.1", 0), None)
        header, body = bytes(request.response).split(b"\r\n\r\n", 1)
        return int(header.split()[1]), json.loads(body)

    def test_http_wrapper_forwards_pagination_and_rejects_invalid_integers(self) -> None:
        status, payload = self.request(message_offset=100, message_limit=25)
        self.assertEqual(status, 200)
        self.assertEqual(payload["messagePage"], {"offset": 100, "limit": 25, "total": 145, "hasNext": True, "hasPrevious": True})
        self.assertEqual(self.ids(payload), self.live_ids[20:45][::-1])
        self.assertEqual(self.request(message_limit=1000)[1]["messagePage"]["limit"], 100)
        for name, values in (("message_offset", ("", "-1", "1.5", "abc", "1_0")),
                             ("message_limit", ("", "0", "-1", "1.5", "abc"))):
            for value in values:
                with self.subTest(name=name, value=value):
                    status, payload = self.request(**{name: value})
                    self.assertEqual(status, 400)
                    self.assertIn(name, payload["error"])


if __name__ == "__main__":
    unittest.main()
