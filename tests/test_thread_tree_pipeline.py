#!/usr/bin/env python3

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state
import thread_tree_tools as tools
import stop as stop_hook
import user_prompt_submit as prompt_hook


def message(message_id: str, role: str, text: str) -> dict:
    return {
        "timestamp": "2026-01-01T00:00:00Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "id": message_id,
            "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
        },
    }


class ThreadTreePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["THREAD_HISTORY_TREE_DATA"] = str(self.root / "data")
        (self.root / "data").mkdir()
        (self.root / "data" / "config.json").write_text(
            json.dumps({"fit_thresholds": {"span": 2, "specific": 2, "broad": 2}}),
            encoding="utf-8",
        )
        thread_tree.save_scope_config({
            "schemaVersion": 1,
            "configured": True,
            "paused": False,
            "projects": [{
                "path": str(self.root),
                "includeNewChats": True,
                "includedChatIds": [],
                "excludedChatIds": [],
                "backfillExisting": False,
                "activatedAt": None,
            }],
            "pausePolicy": {"mode": "manual", "pauseOn": None, "inactivityDays": 30},
            "setupAt": None,
            "updatedAt": None,
        })

    def tearDown(self) -> None:
        self.temp.cleanup()

    def transcript(self, name: str, thread_id: str, topic: str) -> Path:
        path = self.root / name
        rows = [
            {"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z", "payload": {"session_id": thread_id, "cwd": str(self.root)}},
            message(f"{thread_id}-u1", "user", f"Plan the {topic} retrieval index."),
            message(f"{thread_id}-a1", "assistant", f"The {topic} retrieval index uses local searchable chunks."),
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return path

    def claude_transcript(self, name: str, thread_id: str, topic: str) -> Path:
        path = self.root / name
        rows = [
            {
                "type": "user",
                "sessionId": thread_id,
                "cwd": str(self.root),
                "uuid": f"{thread_id}-u1",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"role": "user", "content": f"Plan the {topic} retrieval index."},
            },
            {
                "type": "assistant",
                "sessionId": thread_id,
                "cwd": str(self.root),
                "uuid": f"{thread_id}-a1",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {
                    "id": f"msg-{thread_id}",
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"The {topic} index is shared locally."}],
                },
            },
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return path

    def test_two_chats_feed_one_project_tree_and_search(self) -> None:
        first = pipeline.enqueue_transcript(self.transcript("a.jsonl", "chat-a", "semantic"))
        second = pipeline.enqueue_transcript(self.transcript("b.jsonl", "chat-b", "semantic"))
        self.assertEqual(first["project_id"], second["project_id"])

        result = pipeline.process_project(first["project_id"])
        self.assertEqual(result["processed_turns"], 2)
        self.assertFalse(result["failures"])
        hits = pipeline.search_project(first["project_id"], "local retrieval chunks")
        self.assertTrue(hits)
        self.assertEqual({hit["thread_id"] for hit in hits}, {"chat-a", "chat-b"})

        tree = pipeline.project_tree_payload(first["project_id"])
        self.assertEqual(sum(node["kind"] == "root" for node in tree["nodes"]), 1)
        self.assertGreater(tree["stats"]["spans"], 0)
        db = thread_tree.connect_db()
        duplicate_primary = db.execute(
            """SELECT child_id FROM semantic_edges WHERE primary_edge=1
               GROUP BY child_id HAVING COUNT(*) > 1"""
        ).fetchall()
        self.assertEqual(duplicate_primary, [])
        db.close()

    def test_explorer_search_is_read_only_and_closes_hits_over_hierarchy(self) -> None:
        first = pipeline.enqueue_transcript(self.transcript("explore-a.jsonl", "chat-a", "aurora memory"))
        pipeline.enqueue_transcript(self.transcript("explore-b.jsonl", "chat-b", "aurora memory"))
        pipeline.process_project(first["project_id"])
        db = thread_tree.connect_db()
        before = {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("turn_chunks", "semantic_nodes", "semantic_edges", "fit_runs")
        }
        db.close()

        result = pipeline.project_explorer_payload(first["project_id"], "aurora retrieval index")

        self.assertEqual(result["query"], "aurora retrieval index")
        self.assertTrue(result["layers"]["specific_message"])
        self.assertTrue(result["layers"]["specific_topic"])
        all_ids = {
            node["id"]
            for nodes in result["layers"].values()
            for node in nodes
        }
        self.assertTrue(all(edge["child_id"] in all_ids and edge["parent_id"] in all_ids for edge in result["edges"]))
        message_id = result["layers"]["specific_message"][0]["id"]
        detail = pipeline.project_node_detail(message_id)
        self.assertEqual(detail["kind"], "message")
        self.assertTrue(detail["sources"])

        browse = pipeline.project_explorer_payload(first["project_id"], "")
        self.assertEqual(browse["query"], "")
        self.assertTrue(browse["layers"]["specific_topic"])
        self.assertTrue(browse["layers"]["specific_message"])
        browse_ids = {node["id"] for nodes in browse["layers"].values() for node in nodes}
        self.assertTrue(all(edge["child_id"] in browse_ids and edge["parent_id"] in browse_ids for edge in browse["edges"]))
        db = thread_tree.connect_db()
        active_subject_count = db.execute(
            "SELECT COUNT(*) FROM semantic_nodes WHERE project_id=? AND layer='broad' AND lifecycle!='retired'",
            (first["project_id"],),
        ).fetchone()[0]
        db.close()
        self.assertEqual(len(browse["layers"]["subject"]), active_subject_count)

        db = thread_tree.connect_db()
        after = {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in before
        }
        db.close()
        self.assertEqual(after, before)

    def test_recent_explorer_browse_intersects_live_branches_and_keeps_a_scoped_selection(self) -> None:
        first = pipeline.enqueue_transcript(self.transcript("early.jsonl", "early", "original evidence"))
        pipeline.enqueue_transcript(self.transcript("later.jsonl", "later", "recent evidence"))
        project_id = first["project_id"]
        pipeline.process_project(project_id)

        db = thread_tree.connect_db()
        with db:
            db.execute("UPDATE semantic_nodes SET lifecycle='retired' WHERE project_id=?", (project_id,))
            db.executemany(
                """INSERT INTO semantic_nodes (id, project_id, layer, lifecycle, title, created_at, updated_at)
                   VALUES (?, ?, ?, 'locked', ?, ?, ?)""",
                [(node_id, project_id, layer, node_id, state.utc_now(), state.utc_now()) for node_id, layer in
                 (("all-topics", "broad"), ("early-topic", "span"), ("later-topic", "span"))],
            )
            db.executemany(
                "INSERT INTO semantic_edges (child_id, parent_id, primary_edge, coverage) VALUES (?, 'all-topics', 1, 1)",
                [("early-topic",), ("later-topic",)],
            )
            chunks = db.execute("SELECT id, thread_id FROM turn_chunks WHERE project_id=? ORDER BY seq", (project_id,)).fetchall()
            db.executemany("INSERT INTO semantic_node_memberships VALUES (?, ?, 1)",
                           [(f"{chunk['thread_id']}-topic", chunk["id"]) for chunk in chunks])
        db.close()

        early_message = f"message:{next(chunk['id'] for chunk in chunks if chunk['thread_id'] == 'early')}"
        newest_message = f"message:{chunks[-1]['id']}"

        def message_ids(payload):
            return [item["id"] for item in payload["layers"]["specific_message"]]

        self.assertEqual(message_ids(pipeline.project_explorer_payload(project_id, "", limit=1)), [newest_message])
        anchored = pipeline.project_explorer_payload(
            project_id, "", limit=1, browse_nodes=("early-topic", "all-topics"), browse_message=early_message,
        )
        self.assertEqual(message_ids(anchored), [early_message])
        self.assertEqual({node["id"] for node in anchored["layers"]["specific_topic"]}, {"later-topic", "early-topic"})
        self.assertIn({"child_id": early_message, "parent_id": "early-topic"}, anchored["edges"])
        self.assertEqual(message_ids(pipeline.project_explorer_payload(
            project_id, "", browse_nodes=("early-topic", "later-topic"), browse_message=early_message,
        )), [])
        limited_scope = {"includeNewChats": True, "excludedChatIds": ["early"]}
        self.assertNotIn(early_message, message_ids(pipeline.project_explorer_payload(
            project_id, "", project_scope=limited_scope, browse_message=early_message,
        )))
        self.assertEqual(message_ids(pipeline.project_explorer_payload(
            project_id, "", project_scope=limited_scope, browse_nodes=("early-topic",),
        )), [])
        self.assertTrue(message_ids(pipeline.project_explorer_payload(
            project_id, "recent evidence", browse_nodes=("not-in-this-project",),
        )))

    def test_explorer_hides_topics_after_source_removal_and_counts_unique_messages(self) -> None:
        first = pipeline.enqueue_transcript(self.transcript("kept.jsonl", "kept", "aurora"))
        pipeline.enqueue_transcript(self.transcript("removed.jsonl", "removed", "removed sentinel"))
        project_id = first["project_id"]
        pipeline.process_project(project_id)

        db = thread_tree.connect_db()
        with db:
            db.execute("UPDATE semantic_nodes SET lifecycle='retired' WHERE project_id=?", (project_id,))
            for node_id, layer in (("subject", "broad"), ("topic", "specific"), ("kept-span", "span"), ("removed-span", "span")):
                db.execute(
                    """INSERT INTO semantic_nodes (id, project_id, layer, lifecycle, title, summary, created_at, updated_at)
                       VALUES (?, ?, ?, 'locked', ?, 'USER: Stale text; ASSISTANT: Removed text', ?, ?)""",
                    (node_id, project_id, layer, node_id, state.utc_now(), state.utc_now()),
                )
            db.executemany(
                "INSERT INTO semantic_edges (child_id, parent_id, primary_edge, coverage) VALUES (?, ?, 1, 1)",
                [("kept-span", "topic"), ("removed-span", "topic"), ("topic", "subject")],
            )
            for chunk in db.execute("SELECT id, thread_id FROM turn_chunks").fetchall():
                db.execute(
                    "INSERT INTO semantic_node_memberships VALUES (?, ?, 1)",
                    (f"{chunk['thread_id']}-span", chunk["id"]),
                )
            # Model two chunks from the same message plus a short adjacent message
            # kept in one chunk. The topic and subject have only inherited sources.
            first_chunk, second_chunk = db.execute(
                "SELECT id FROM turn_chunks WHERE thread_id='kept' ORDER BY seq",
            ).fetchall()
            db.execute("UPDATE turn_chunks SET source_message_ids=? WHERE id=?", ('["kept-u1","kept-a1"]', first_chunk["id"]))
            db.execute("UPDATE turn_chunks SET source_message_ids=? WHERE id=?", ('["kept-u1"]', second_chunk["id"]))
            # This is the state between deleting a chat and publishing a new tree.
            db.execute("DELETE FROM turn_ingestion WHERE thread_id='removed'")
        db.close()

        browse = pipeline.project_explorer_payload(project_id, "")
        self.assertEqual([node["id"] for node in browse["layers"]["specific_topic"]], ["kept-span"])
        self.assertEqual(browse["layers"]["subject"][0]["messageCount"], 2)
        self.assertNotIn("summary", browse["layers"]["broad_topic"][0])
        no_hits = pipeline.project_explorer_payload(project_id, "nonexistent_identifier_9267")
        self.assertFalse(any(no_hits["layers"].values()))
        self.assertIsNone(pipeline.project_node_detail("removed-span", explorer=True))

        topic = pipeline.project_node_detail("topic", explorer=True)
        self.assertEqual(topic["message_count"], 2)
        self.assertEqual(topic["source_chat_count"], 1)
        self.assertEqual([node["id"] for node in topic["children"]], ["kept-span"])
        self.assertTrue(topic["overview"])
        self.assertNotIn("summary", topic)
        self.assertTrue(all("transcript_path" not in source for source in topic["sources"]))

        message_detail = pipeline.project_node_detail(f"message:{first_chunk['id']}", explorer=True)
        self.assertEqual(message_detail["message_count"], 2)

    def test_explorer_overview_keeps_complete_attributed_sentences(self) -> None:
        overview = pipeline._readable_overview([
            {"text": "USER: Does \x60AGENTS.md\x60 count toward the context window?"},
            {"text": "ASSISTANT: Yes. Prompt caching does **not** remove those tokens from the context window. See [the documentation](https://example.com)."},
        ])
        self.assertEqual(overview, [
            {"label": "Example question", "text": "Does AGENTS.md count toward the context window?"},
            {"label": "Excerpt from a reply", "text": "Prompt caching does not remove those tokens from the context window."},
        ])
        self.assertIsNone(pipeline._evidence_counts([{"thread_id": "chat-a", "source_message_ids": "[]"}])[0])

    def test_claude_code_transcript_uses_same_project_pipeline(self) -> None:
        queued = pipeline.enqueue_transcript(
            self.claude_transcript("claude.jsonl", "claude-session", "cross client")
        )
        self.assertEqual(queued["thread_id"], "claude-session")
        result = pipeline.process_project(queued["project_id"])
        self.assertEqual(result["processed_turns"], 1)
        hits = pipeline.search_project(queued["project_id"], "shared locally")
        self.assertTrue(hits)
        self.assertEqual({hit["thread_id"] for hit in hits}, {"claude-session"})

    def test_codex_and_claude_sessions_share_one_project_tree(self) -> None:
        codex = pipeline.enqueue_transcript(
            self.transcript("codex.jsonl", "codex-chat", "shared project")
        )
        claude = pipeline.enqueue_transcript(
            self.claude_transcript("claude.jsonl", "claude-session", "shared project")
        )
        self.assertEqual(codex["project_id"], claude["project_id"])
        result = pipeline.process_project(codex["project_id"])
        self.assertEqual(result["processed_turns"], 2)
        hits = pipeline.search_project(codex["project_id"], "shared project")
        self.assertEqual(
            {hit["thread_id"] for hit in hits},
            {"codex-chat", "claude-session"},
        )
        tree = pipeline.project_tree_payload(codex["project_id"])
        self.assertEqual(sum(node["kind"] == "root" for node in tree["nodes"]), 1)

    def test_chunk_provenance_and_fts_are_written_atomically(self) -> None:
        queued = pipeline.enqueue_transcript(self.transcript("one.jsonl", "chat-a", "frontier"))
        pipeline.process_project(queued["project_id"], max_turns=1)
        db = thread_tree.connect_db()
        chunk = db.execute("SELECT * FROM turn_chunks LIMIT 1").fetchone()
        self.assertEqual(chunk["chunker_version"], pipeline.CHUNKER_VERSION)
        self.assertTrue(json.loads(chunk["source_message_ids"]))
        self.assertIsNotNone(chunk["line_start"])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks_fts").fetchone()[0], db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0])
        db.close()

    def test_expired_worker_lease_is_recovered(self) -> None:
        queued = pipeline.enqueue_transcript(self.transcript("lease.jsonl", "chat-a", "lease"))
        db = thread_tree.connect_db()
        claimed = state.claim_next_turn(db, queued["project_id"], lease_seconds=-1)
        self.assertIsNotNone(claimed)
        recovered = state.claim_next_turn(db, queued["project_id"])
        self.assertEqual(recovered["id"], claimed["id"])
        self.assertEqual(recovered["attempts"], 2)
        db.close()

    def test_duplicate_hook_delivery_queues_one_turn(self) -> None:
        transcript = self.transcript("duplicate.jsonl", "chat-a", "deduplication")
        first = pipeline.enqueue_transcript(transcript)
        second = pipeline.enqueue_transcript(transcript)
        self.assertEqual(first["queued_turns"], 1)
        self.assertEqual(second["queued_turns"], 0)
        result = pipeline.process_project(first["project_id"])
        self.assertEqual(result["processed_turns"], 1)

    def test_partial_precompact_boundary_is_deferred_and_superseded(self) -> None:
        transcript = self.root / "partial.jsonl"
        rows = [
            {"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z", "payload": {"session_id": "chat-a", "cwd": str(self.root)}},
            message("chat-a-u1", "user", "Design a stable partial boundary."),
        ]
        transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        partial = pipeline.enqueue_transcript(transcript, mark_incomplete_partial=True)
        self.assertEqual(partial["queued_turns"], 1)
        self.assertEqual(pipeline.process_project(partial["project_id"])["processed_turns"], 0)

        with transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message("chat-a-a1", "assistant", "The completed turn supersedes its user-only prefix.")) + "\n")
        complete = pipeline.enqueue_transcript(transcript)
        self.assertEqual(complete["queued_turns"], 1)
        self.assertEqual(pipeline.process_project(complete["project_id"])["processed_turns"], 1)
        db = thread_tree.connect_db()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_ingestion WHERE partial=1 AND state='evicted'").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_ingestion WHERE partial=0 AND state='indexed'").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0], 2)
        db.close()

    def test_global_rebuild_preserves_node_id_by_chunk_overlap(self) -> None:
        first = pipeline.enqueue_transcript(self.transcript("stable-a.jsonl", "chat-a", "semantic memory"))
        pipeline.enqueue_transcript(self.transcript("stable-b.jsonl", "chat-b", "semantic memory"))
        pipeline.process_project(first["project_id"])
        db = thread_tree.connect_db()
        before = {row[0] for row in db.execute("SELECT id FROM semantic_nodes WHERE project_id=?", (first["project_id"],))}
        self.assertTrue(before)
        run = state.schedule_global_rebuild(db, first["project_id"], reason="test stable mapping")
        pipeline.run_fit(db, run["id"])
        after = {row[0] for row in db.execute("SELECT id FROM semantic_nodes WHERE project_id=?", (first["project_id"],))}
        self.assertTrue(before & after)
        phases = db.execute(
            "SELECT phase, layer, status, elapsed_ms FROM fit_run_phase_metrics WHERE run_id=?",
            (run["id"],),
        ).fetchall()
        self.assertTrue(phases)
        self.assertTrue(all(row["status"] == "completed" for row in phases))
        self.assertTrue(all(row["elapsed_ms"] is not None for row in phases))
        self.assertTrue(
            {"cluster", "commit_state", "materialize", "publish_tree"}.issubset(
                {row["phase"] for row in phases}
            )
        )
        input_units = {
            row["layer"]: json.loads(row["details"] or "{}").get("input_unit")
            for row in db.execute(
                "SELECT layer, details FROM fit_run_phase_metrics WHERE run_id=? AND phase='load_input'",
                (run["id"],),
            )
        }
        self.assertEqual(input_units, {"span": "chunk", "specific": "span", "broad": "specific"})
        independent_upper = db.execute(
            """SELECT COUNT(*) FROM chunk_layer_states
               WHERE layer IN ('specific','broad') AND target_id IS NOT NULL"""
        ).fetchone()[0]
        self.assertEqual(independent_upper, 0)
        orphan_children = db.execute(
            """SELECT COUNT(*) FROM semantic_nodes child
               WHERE child.project_id=? AND child.layer IN ('span','specific')
                 AND child.lifecycle!='retired'
                 AND NOT EXISTS (
                   SELECT 1 FROM semantic_edges edge
                   WHERE edge.child_id=child.id AND edge.primary_edge=1
                 )""",
            (first["project_id"],),
        ).fetchone()[0]
        self.assertEqual(orphan_children, 0)
        db.close()

    def test_failed_tree_publication_rolls_back_every_graph_change(self) -> None:
        project_id = state.project_id_for(str(self.root))
        db = thread_tree.connect_db()
        state.ensure_project(db, project_id, str(self.root), fit_thresholds={layer: 99 for layer in state.LAYERS})
        state.queue_turn(
            db,
            turn_id="atomic-publish-turn",
            project_id=project_id,
            thread_id="atomic-publish-thread",
            content_hash="atomic-publish-hash",
        )
        state.claim_next_turn(db, project_id)
        state.complete_turn_ingestion(
            db,
            "atomic-publish-turn",
            [
                {"id": f"atomic-publish-{index}", "text": f"atomic publication evidence {index}"}
                for index in range(4)
            ],
        )
        before_states = [tuple(row) for row in db.execute(
            "SELECT chunk_id, layer, state, target_id, generation_id FROM chunk_layer_states ORDER BY chunk_id, layer"
        )]
        run = state.schedule_global_rebuild(db, project_id, reason="atomic rollback test")
        with patch.object(pipeline, "_materialize_layer", side_effect=RuntimeError("injected materialization failure")):
            with self.assertRaisesRegex(RuntimeError, "injected materialization failure"):
                pipeline.run_fit(db, run["id"])
        after_states = [tuple(row) for row in db.execute(
            "SELECT chunk_id, layer, state, target_id, generation_id FROM chunk_layer_states ORDER BY chunk_id, layer"
        )]
        self.assertEqual(after_states, before_states)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM semantic_nodes").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM semantic_edges").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM cluster_generations").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM project_active_tree").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT state FROM fit_runs WHERE id=?", (run["id"],)).fetchone()[0], "failed")
        db.close()

    def test_project_tree_and_search_include_legacy_nodes_without_second_root(self) -> None:
        legacy_path = self.transcript("legacy.jsonl", "legacy-chat", "legacy migration")
        legacy = thread_tree.index_range(legacy_path, 1, None, "backfill", "legacy-chat")
        self.assertEqual(legacy["status"], "indexed")
        db = thread_tree.connect_db()
        legacy_node_ids = {
            row["id"] for row in db.execute(
                "SELECT id FROM nodes WHERE thread_id='legacy-chat' AND kind != 'root'"
            )
        }
        db.close()
        self.assertTrue(legacy_node_ids)

        queued = pipeline.enqueue_transcript(self.transcript("current.jsonl", "current-chat", "current pipeline"))
        pipeline.process_project(queued["project_id"])
        payload = pipeline.project_tree_payload(queued["project_id"])
        self.assertEqual(sum(node["kind"] == "root" for node in payload["nodes"]), 1)
        self.assertTrue(legacy_node_ids.issubset({node["id"] for node in payload["nodes"]}))
        hits = pipeline.search_project_nodes(queued["project_id"], "legacy migration")
        self.assertTrue(legacy_node_ids & {hit["id"] for hit in hits})

    def test_capacity_eviction_rebuilds_and_physically_removes_tree_copy(self) -> None:
        (self.root / "data" / "config.json").write_text(
            json.dumps({
                "fit_thresholds": {"span": 2, "specific": 2, "broad": 2},
                "retention_high_chunks": 2,
                "retention_low_chunks": 1,
            }),
            encoding="utf-8",
        )
        first = pipeline.enqueue_transcript(self.transcript("capacity-a.jsonl", "chat-a", "old context"))
        pipeline.enqueue_transcript(self.transcript("capacity-b.jsonl", "chat-b", "new context"))
        result = pipeline.process_project(first["project_id"])
        self.assertTrue(result["evicted_turns"])
        db = thread_tree.connect_db()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks WHERE evicted=1").fetchone()[0], 0)
        # Whole-turn eviction cannot retain half of a two-chunk turn merely to
        # hit a one-chunk target, so both complete turns are removed.
        self.assertEqual(db.execute("SELECT COUNT(*) FROM evicted_turns").fetchone()[0], 2)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks_fts").fetchone()[0], db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0])
        db.close()

    def test_stop_hook_only_queues_and_detaches_worker(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        output = io.StringIO()
        event = {"session_id": "chat-a", "transcript_path": str(self.transcript("stop.jsonl", "chat-a", "stop hook"))}
        with patch.object(stop_hook.sys, "stdin", io.StringIO(json.dumps(event))), \
             patch.object(stop_hook.subprocess, "Popen") as popen, \
             redirect_stdout(output):
            self.assertEqual(stop_hook.main(), 0)
        self.assertTrue(json.loads(output.getvalue())["continue"])
        popen.assert_called_once()
        db = thread_tree.connect_db()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_ingestion WHERE state='queued'").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0], 0)
        db.close()

    def test_user_prompt_hook_stages_exact_text_without_searchable_chunks(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        output = io.StringIO()
        event = {
            "session_id": "chat-a",
            "turn_id": "codex-turn-a",
            "cwd": str(self.root),
            "prompt": "Recover the exact earlier indexing decision.",
        }
        with patch.object(prompt_hook.sys, "stdin", io.StringIO(json.dumps(event))), redirect_stdout(output):
            self.assertEqual(prompt_hook.main(), 0)
        self.assertTrue(json.loads(output.getvalue())["continue"])
        db = thread_tree.connect_db()
        staged = db.execute("SELECT * FROM staged_user_prompts").fetchone()
        self.assertEqual(staged["prompt"], event["prompt"])
        self.assertEqual(staged["state"], "staged")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0], 0)
        db.close()

    def test_user_prompt_hook_supports_claude_without_turn_id(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        event = {
            "session_id": "claude-session",
            "cwd": str(self.root),
            "prompt": "Recover a Claude Code project decision.",
        }
        with patch.object(prompt_hook.sys, "stdin", io.StringIO(json.dumps(event))), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(prompt_hook.main(), 0)
        db = thread_tree.connect_db()
        staged = db.execute("SELECT * FROM staged_user_prompts").fetchone()
        self.assertEqual(staged["thread_id"], "claude-session")
        self.assertEqual(staged["state"], "staged")
        db.close()

    def test_unconfigured_prompt_observes_session_without_storing_prompt(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        thread_tree.save_scope_config({
            "schemaVersion": 1,
            "configured": False,
            "paused": False,
            "projects": [],
            "pausePolicy": {"mode": "manual", "pauseOn": None, "inactivityDays": 30},
            "setupAt": None,
            "updatedAt": None,
        })
        transcript = self.transcript("observed.jsonl", "observed-chat", "first invocation")
        event = {
            "session_id": "observed-chat",
            "cwd": str(self.root),
            "transcript_path": str(transcript),
            "prompt": "This content must not be staged before activation.",
        }
        with patch.object(prompt_hook.sys, "stdin", io.StringIO(json.dumps(event))), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(prompt_hook.main(), 0)
        db = thread_tree.connect_db()
        observation = db.execute("SELECT * FROM session_observations").fetchone()
        self.assertEqual(observation["thread_id"], "observed-chat")
        self.assertEqual(observation["transcript_path"], str(transcript.resolve()))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM staged_user_prompts").fetchone()[0], 0)
        db.close()

    def test_prepare_current_chat_backfills_once_and_tracks_attachment(self) -> None:
        transcript = self.transcript("attached.jsonl", "attached-chat", "activation")
        db = thread_tree.connect_db()
        state.observe_session(
            db,
            project_root=str(self.root),
            thread_id="attached-chat",
            transcript_path=str(transcript),
        )
        db.close()

        first = tools.prepare_current_chat(
            project_root=str(self.root),
            thread_id="attached-chat",
        )
        self.assertEqual(first["status"], "ready")
        self.assertTrue(first["first_invocation"])
        self.assertEqual(first["processed_turns"], 1)
        self.assertTrue(first["continue_with_user_request"])

        second = tools.prepare_current_chat(
            project_root=str(self.root),
            thread_id="attached-chat",
        )
        self.assertEqual(second["status"], "ready")
        self.assertFalse(second["first_invocation"])

        db = thread_tree.connect_db()
        activation = db.execute("SELECT * FROM chat_plugin_activations").fetchone()
        self.assertEqual(activation["thread_id"], "attached-chat")
        self.assertEqual(activation["state"], "active")
        self.assertEqual(
            db.execute(
                "SELECT COUNT(*) FROM turn_ingestion WHERE thread_id='attached-chat'"
            ).fetchone()[0],
            1,
        )
        db.close()
        attached = thread_tree.scope_payload()["attachedChats"]
        self.assertEqual([item["threadId"] for item in attached], ["attached-chat"])

    def test_prepare_current_chat_activates_only_unconfigured_current_chat(self) -> None:
        thread_tree.save_scope_config({
            "schemaVersion": 1,
            "configured": False,
            "paused": False,
            "projects": [],
            "pausePolicy": {"mode": "manual", "pauseOn": None, "inactivityDays": 30},
            "setupAt": None,
            "updatedAt": None,
        })
        transcript = self.transcript("first-call.jsonl", "first-call-chat", "history")
        db = thread_tree.connect_db()
        state.observe_session(
            db,
            project_root=str(self.root),
            thread_id="first-call-chat",
            transcript_path=str(transcript),
        )
        db.close()

        result = tools.prepare_current_chat(
            project_root=str(self.root),
            thread_id="first-call-chat",
        )
        self.assertEqual(result["status"], "ready")
        saved = thread_tree.load_scope_config()
        self.assertTrue(saved["configured"])
        self.assertEqual(len(saved["projects"]), 1)
        self.assertFalse(saved["projects"][0]["includeNewChats"])
        self.assertEqual(saved["projects"][0]["includedChatIds"], ["first-call-chat"])

    def test_attached_chat_registry_claim_is_idempotent(self) -> None:
        project_id = state.project_id_for(str(self.root))
        db = thread_tree.connect_db()
        first, first_claimed = state.begin_chat_activation(
            db,
            project_id=project_id,
            thread_id="claim-chat",
            transcript_path=None,
        )
        second, second_claimed = state.begin_chat_activation(
            db,
            project_id=project_id,
            thread_id="claim-chat",
            transcript_path=None,
        )
        self.assertTrue(first_claimed)
        self.assertFalse(second_claimed)
        self.assertEqual(first["state"], "backfilling")
        self.assertEqual(second["state"], "backfilling")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_plugin_activations").fetchone()[0], 1)
        db.close()

    def test_stop_reconciles_staged_prompt_with_completed_turn(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        transcript = self.transcript("reconcile.jsonl", "chat-a", "reconciliation")
        db = thread_tree.connect_db()
        project_id = state.project_id_for(str(self.root))
        state.ensure_project(db, project_id, str(self.root))
        state.stage_user_prompt(
            db,
            codex_turn_id="codex-turn-a",
            project_id=project_id,
            thread_id="chat-a",
            prompt="Plan the reconciliation retrieval index.",
        )
        db.close()

        event = {
            "session_id": "chat-a",
            "turn_id": "codex-turn-a",
            "cwd": str(self.root),
            "transcript_path": str(transcript),
        }
        with patch.object(stop_hook.sys, "stdin", io.StringIO(json.dumps(event))), \
             patch.object(stop_hook.subprocess, "Popen"), redirect_stdout(io.StringIO()):
            self.assertEqual(stop_hook.main(), 0)
        db = thread_tree.connect_db()
        staged = db.execute("SELECT * FROM staged_user_prompts WHERE codex_turn_id='codex-turn-a'").fetchone()
        self.assertEqual(staged["state"], "reconciled")
        self.assertIsNotNone(staged["ingestion_turn_id"])
        db.close()

    def test_claude_stop_reconciles_latest_stage_without_turn_id(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        transcript = self.claude_transcript(
            "claude-reconcile.jsonl", "claude-session", "stage reconciliation"
        )
        prompt_event = {
            "session_id": "claude-session",
            "cwd": str(self.root),
            "prompt": "Plan the stage reconciliation retrieval index.",
        }
        with patch.object(prompt_hook.sys, "stdin", io.StringIO(json.dumps(prompt_event))), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(prompt_hook.main(), 0)

        stop_event = {
            "session_id": "claude-session",
            "cwd": str(self.root),
            "transcript_path": str(transcript),
        }
        with patch.object(stop_hook.sys, "stdin", io.StringIO(json.dumps(stop_event))), \
             patch.object(stop_hook.subprocess, "Popen"), redirect_stdout(io.StringIO()):
            self.assertEqual(stop_hook.main(), 0)

        db = thread_tree.connect_db()
        staged = db.execute("SELECT * FROM staged_user_prompts").fetchone()
        self.assertEqual(staged["state"], "reconciled")
        self.assertIsNotNone(staged["ingestion_turn_id"])
        db.close()

    def test_project_history_tool_uses_one_global_lookup_and_returns_grounded_trace(self) -> None:
        first = pipeline.enqueue_transcript(self.transcript("tool-a.jsonl", "chat-a", "semantic memory"))
        pipeline.enqueue_transcript(self.transcript("tool-b.jsonl", "chat-b", "retrieval trace"))
        pipeline.process_project(first["project_id"])

        result = tools.search_project_history(
            "How does the local searchable chunk retrieval index work?",
            evidence_needed="The earlier implementation decision.",
            project_root=str(self.root),
            max_results=6,
        )
        self.assertEqual(result["trace"]["global_lookup_count"], 1)
        self.assertEqual(result["status"], "supported")
        self.assertTrue(result["evidence"])
        self.assertEqual(
            len({item["chunk_id"] for item in result["evidence"]}),
            len(result["evidence"]),
        )
        self.assertTrue(all(item["source"]["verified"] for item in result["evidence"]))
        self.assertTrue(all(item["source"]["chat_title"] for item in result["evidence"]))
        self.assertTrue(all(item["source"]["timestamp"] for item in result["evidence"]))
        self.assertTrue(all(item["source"]["citation_label"] for item in result["evidence"]))
        self.assertTrue(all("url" not in item["source"] for item in result["evidence"]))

        source = result["evidence"][0]["source"]
        detail = thread_tree.chunk_source_detail(result["evidence"][0]["chunk_id"])
        self.assertIsNotNone(detail)
        self.assertEqual(detail["chat_title"], source["chat_title"])
        self.assertEqual(detail["timestamp"], source["timestamp"])
        self.assertEqual(detail["citation_label"], source["citation_label"])
        self.assertTrue(source["citation_label"].startswith("["))
        self.assertTrue(source["citation_label"].endswith("]"))
        self.assertIn("2026-01-01 00:00Z", source["citation_label"])
        self.assertLessEqual(len(source["citation_label"]), 58)

        excluded = result["evidence"][0]["chunk_id"]
        follow_up = tools.search_project_history(
            "local searchable chunks",
            project_root=str(self.root),
            exclude_chunk_ids=[excluded],
        )
        self.assertNotIn(excluded, {item["chunk_id"] for item in follow_up["evidence"]})

    def test_project_history_tool_enforces_selected_chat_scope(self) -> None:
        first = pipeline.enqueue_transcript(self.transcript("scope-a.jsonl", "chat-a", "shared scope evidence"))
        pipeline.enqueue_transcript(self.transcript("scope-b.jsonl", "chat-b", "shared scope evidence"))
        pipeline.process_project(first["project_id"])
        configured = thread_tree.load_scope_config()
        configured["projects"][0].update({
            "includeNewChats": False,
            "includedChatIds": ["chat-a"],
            "excludedChatIds": [],
        })
        thread_tree.save_scope_config(configured)

        result = tools.search_project_history(
            "How does the shared scope evidence retrieval index work?",
            project_root=str(self.root),
            max_results=8,
        )
        self.assertTrue(result["evidence"])
        self.assertEqual({item["thread_id"] for item in result["evidence"]}, {"chat-a"})

    def test_project_history_tool_refuses_manually_paused_scope(self) -> None:
        queued = pipeline.enqueue_transcript(self.transcript("paused.jsonl", "chat-a", "paused scope"))
        pipeline.process_project(queued["project_id"])
        configured = thread_tree.load_scope_config()
        configured["paused"] = True
        thread_tree.save_scope_config(configured)
        with self.assertRaisesRegex(ValueError, "not active"):
            tools.search_project_history("Find paused scope evidence", project_root=str(self.root))

    def test_bm25_orders_exact_historical_term_ahead_of_generic_distractors(self) -> None:
        project_id = state.project_id_for(str(self.root))
        db = thread_tree.connect_db()
        state.ensure_project(
            db,
            project_id,
            str(self.root),
            fit_thresholds={layer: 10_000 for layer in state.LAYERS},
        )
        for index in range(64):
            turn_id = f"distractor-turn-{index}"
            state.queue_turn(
                db,
                turn_id=turn_id,
                project_id=project_id,
                thread_id="distractor-thread",
                content_hash=f"distractor-hash-{index}",
            )
            state.claim_next_turn(db, project_id)
            state.complete_turn_ingestion(
                db,
                turn_id,
                [{"id": f"distractor-{index}", "text": "topic candidates lookup chunks broad topic search workflow"}],
            )
        state.queue_turn(
            db,
            turn_id="gold-turn",
            project_id=project_id,
            thread_id="gold-thread",
            content_hash="gold-hash",
        )
        state.claim_next_turn(db, project_id)
        state.complete_turn_ingestion(
            db,
            "gold-turn",
            [
                {
                    "id": "gold-exact-term",
                    "text": "USER: Let's stick with the term searchable representation candidate.",
                },
            ],
        )
        db.close()

        hits = pipeline.search_project(
            project_id,
            "What exact term replaced topic candidates?",
            limit=5,
        )
        self.assertIn("gold-exact-term", {hit["id"] for hit in hits[:2]})
        gold = next(hit for hit in hits if hit["id"] == "gold-exact-term")
        self.assertEqual(gold["retrieval_diagnostics"]["decision_declaration"], 1)

        tool_result = tools.search_project_history(
            "Find the earlier conversation where the user chose an exact replacement term for topic candidates specifically to avoid confusion with the topic-node layers. Return the exact chosen term and supporting chunk ID.",
            evidence_needed="A direct user statement selecting the replacement term.",
            project_root=str(self.root),
            max_results=2,
        )
        self.assertIn("gold-exact-term", {item["chunk_id"] for item in tool_result["evidence"]})
        self.assertIn("route_counts", tool_result["trace"])
        self.assertIn("stop_reason", tool_result["trace"])

    def test_plugin_manifest_exposes_local_mcp_and_hooks(self) -> None:
        root = PACKAGE_ROOT
        codex_plugin = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        claude_plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
        hooks = json.loads((root / codex_plugin["hooks"]).read_text(encoding="utf-8"))
        self.assertEqual(codex_plugin["name"], "thread-tree")
        self.assertEqual(codex_plugin["skills"], "./skills/")
        self.assertEqual(claude_plugin["name"], "thread-tree")
        self.assertEqual(mcp["mcpServers"]["thread-tree"]["cwd"], ".")
        self.assertEqual(mcp["mcpServers"]["thread-tree"]["command"], "uv")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", mcp["mcpServers"]["thread-tree"]["args"])
        self.assertIn("UserPromptSubmit", hooks["hooks"])
        self.assertIn("Stop", hooks["hooks"])
        self.assertIn("PreCompact", hooks["hooks"])
        self.assertTrue((root / "skills" / "context-saver" / "SKILL.md").is_file())

    def test_large_embedded_fit_uses_bounded_usearch_fallback(self) -> None:
        try:
            import usearch  # noqa: F401
        except ImportError:
            self.skipTest("USearch runtime is not installed")
        rows = []
        for index in range(1_200):
            topic = index % 24
            vector = [0.0] * 32
            vector[topic] = 1.0
            vector[(topic + 1) % 32] = (index % 7) * 0.002
            rows.append(
                {
                    "id": f"large-{index}",
                    "text": f"topic {topic} evidence {index}",
                    "embedding": pipeline._normalize(vector),
                }
            )
        groups = pipeline._cluster_groups(rows, "span")
        self.assertTrue(groups)
        self.assertEqual(sum(len(group["rows"]) for group in groups), len(rows))
        self.assertEqual({group["provider"] for group in groups}, {"usearch-centroid-fallback"})
        self.assertLessEqual(len(groups), 512)

    def test_deterministic_fallback_computes_group_persistence_once(self) -> None:
        rows = [
            {"id": f"row-{index}", "text": f"evidence {index}", "embedding": None}
            for index in range(8)
        ]
        with patch.object(pipeline, "_components", return_value=[rows]), \
             patch.object(pipeline, "_cluster_persistence", return_value=0.625) as persistence:
            groups = pipeline._deterministic_cluster_groups(rows, "span")
        persistence.assert_called_once_with(rows)
        self.assertEqual(groups[0]["persistence"], 0.625)
        self.assertEqual(set(groups[0]["confidences"].values()), {0.625})

    def test_large_deterministic_fallback_fails_fast(self) -> None:
        pipeline._guard_deterministic_fallback_size(
            pipeline.DETERMINISTIC_FALLBACK_MAX_ROWS
        )
        with self.assertRaisesRegex(RuntimeError, "Scalable clustering runtime"):
            pipeline._guard_deterministic_fallback_size(
                pipeline.DETERMINISTIC_FALLBACK_MAX_ROWS + 1
            )


if __name__ == "__main__":
    unittest.main()
