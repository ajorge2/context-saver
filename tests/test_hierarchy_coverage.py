"""Keep every published span's live evidence covered through both ancestors."""

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import thread_tree_pipeline as pipeline
import thread_tree_state as state
import thread_tree


class HierarchyCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        state.initialize_state_schema(self.db)
        self.addCleanup(self.db.close)
        self.project_id = "synthetic-hierarchy-project"
        state.ensure_project(self.db, self.project_id, "/synthetic/hierarchy", fit_thresholds={
            "span": 6, "specific": 12, "broad": 24,
        })

    def ingest(self, marker, count=6):
        words = {
            "old": "cobalt zephyr quartz glacier sapphire tundra",
            "new": "tulip orchard meadow blossom petal garden",
            "third": "voltage resistor diode capacitor circuit transistor",
        }[marker]
        turn_id = f"turn-{marker}"
        state.queue_turn(self.db, turn_id=turn_id, project_id=self.project_id,
                         thread_id=f"chat-{marker}", content_hash=turn_id)
        state.claim_next_turn(self.db, self.project_id)
        return state.complete_turn_ingestion(self.db, turn_id, [{
            "id": f"{marker}-{index}", "content_hash": f"{marker}-{index}",
            "text": words, "source_message_ids": [f"{marker}-message-{index}"],
        } for index in range(count)])

    def run_due(self):
        run = state.schedule_routine_fit(self.db, self.project_id)
        self.assertIsNotNone(run)
        return pipeline.run_fit(self.db, run["id"])

    def force_layers(self, layers):
        with self.db:
            self.db.execute("UPDATE fit_debt SET threshold=10000 WHERE project_id=?", (self.project_id,))
            self.db.executemany("UPDATE fit_debt SET threshold=1 WHERE project_id=? AND layer=?",
                                [(self.project_id, layer) for layer in layers])
        return self.run_due()

    def live_members(self, node_id):
        return {row[0] for row in self.db.execute(
            """SELECT m.chunk_id FROM semantic_node_memberships m
               JOIN turn_chunks c ON c.id=m.chunk_id
               WHERE m.node_id=? AND c.evicted=0""", (node_id,),
        )}

    def assert_complete_ancestry(self, expected_ids):
        covered = set()
        for span in self.db.execute("SELECT id FROM semantic_nodes WHERE layer='span' AND lifecycle!='retired'"):
            members = self.live_members(span["id"])
            if not members:
                continue
            covered.update(members)
            current = span["id"]
            for layer in ("specific", "broad"):
                edges = self.db.execute(
                    """SELECT e.parent_id, e.coverage, n.layer FROM semantic_edges e
                       JOIN semantic_nodes n ON n.id=e.parent_id
                       WHERE e.child_id=? AND e.primary_edge=1 AND n.lifecycle!='retired'""", (current,),
                ).fetchall()
                self.assertEqual(len(edges), 1, f"missing {layer} ancestor for {current}")
                self.assertEqual(edges[0]["layer"], layer)
                self.assertEqual(edges[0]["coverage"], 1)
                parent_id = edges[0]["parent_id"]
                self.assertLessEqual(self.live_members(current), self.live_members(parent_id))
                current = parent_id
        self.assertEqual(covered, set(expected_ids))

    def test_initial_run_orders_all_layers_and_builds_complete_hierarchy(self):
        self.ingest("old", 24)
        queued = state.schedule_routine_fit(self.db, self.project_id)
        self.assertEqual(json.loads(queued["layers"]), ["span", "specific", "broad"])
        run = pipeline.run_fit(self.db, queued["id"])
        loads = self.db.execute(
            "SELECT layer, output_count FROM fit_run_phase_metrics WHERE run_id=? AND phase='load_input' ORDER BY rowid",
            (run["id"],),
        ).fetchall()
        self.assertEqual([row["layer"] for row in loads], ["span", "specific", "broad"])
        self.assertTrue(all(row["output_count"] for row in loads))
        self.assert_complete_ancestry(f"old-{index}" for index in range(24))

    def test_upper_only_fit_loads_historical_locked_children(self):
        self.ingest("old")
        self.run_due()
        locked = self.db.execute("SELECT id FROM semantic_nodes WHERE layer='span' AND lifecycle='locked'").fetchone()[0]
        self.ingest("new", 1)
        run = self.force_layers(("specific", "broad"))
        inputs = {row["layer"]: row["output_count"] for row in self.db.execute(
            "SELECT layer, output_count FROM fit_run_phase_metrics WHERE run_id=? AND phase='load_input'", (run["id"],),
        )}
        self.assertEqual(inputs["specific"], 1)
        self.assertGreater(inputs["broad"], 0)
        self.assertEqual(self.db.execute("SELECT lifecycle FROM semantic_nodes WHERE id=?", (locked,)).fetchone()[0], "locked")
        self.assert_complete_ancestry(f"old-{index}" for index in range(6))

    def test_span_only_publication_keeps_old_and_new_coverage_without_consuming_upper_debt(self):
        self.ingest("old")
        first = self.run_due()
        self.assertEqual(json.loads(first["layers"]), ["span"])
        self.assert_complete_ancestry(f"old-{index}" for index in range(6))
        self.ingest("new")
        with self.db:
            self.db.execute("UPDATE fit_debt SET threshold=1000 WHERE layer!='span'")
        second = self.run_due()
        self.assertEqual(json.loads(second["layers"]), ["span"])
        self.assert_complete_ancestry(f"{marker}-{index}" for marker in ("old", "new") for index in range(6))
        debt = {row["layer"]: row["debt_count"] for row in state.debt_status(self.db, self.project_id)}
        self.assertEqual(debt, {"span": 0, "specific": 12, "broad": 12})
        self.ingest("third")
        self.force_layers(("specific", "broad"))
        self.assert_complete_ancestry(f"{marker}-{index}" for marker in ("old", "new") for index in range(6))

    def test_later_full_fit_combines_old_locked_span_and_new_replacements(self):
        self.ingest("old")
        self.run_due()
        self.ingest("new")
        with self.db:
            self.db.execute("UPDATE fit_debt SET threshold=1")
        run = self.run_due()
        specific_count = self.db.execute(
            "SELECT output_count FROM fit_run_phase_metrics WHERE run_id=? AND phase='load_input' AND layer='specific'",
            (run["id"],),
        ).fetchone()[0]
        self.assertEqual(specific_count, 2)
        self.assert_complete_ancestry(f"{marker}-{index}" for marker in ("old", "new") for index in range(6))

    def test_empty_upper_input_does_not_erase_published_parents(self):
        self.ingest("old")
        self.run_due()
        parents = {row[0] for row in self.db.execute("SELECT id FROM semantic_nodes WHERE layer!='span'")}
        self.ingest("new", 1)
        original = pipeline._fit_rows_for_layer

        def empty_upper(db, run, layer, materialized):
            return ([], "span" if layer == "specific" else "specific") if layer != "span" else original(db, run, layer, materialized)

        with patch.object(pipeline, "_fit_rows_for_layer", side_effect=empty_upper):
            self.force_layers(("specific", "broad"))
        self.assertLessEqual(parents, {row[0] for row in self.db.execute("SELECT id FROM semantic_nodes")})
        self.assert_complete_ancestry(f"old-{index}" for index in range(6))

    def test_authoritative_empty_span_replacement_does_not_resurrect_old_parents(self):
        self.ingest("old")
        self.run_due()
        run = state.schedule_global_rebuild(self.db, self.project_id, reason="synthetic changed density")
        original = pipeline._cluster_groups

        def singleton_spans(rows, layer):
            if layer != "span":
                return original(rows, layer)
            return [{"rows": [row], "persistence": 0, "confidences": {row["id"]: 0}, "provider": "synthetic-outlier"}
                    for row in rows]

        with patch.object(pipeline, "_cluster_groups", side_effect=singleton_spans):
            pipeline.run_fit(self.db, run["id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM turn_chunks WHERE evicted=0").fetchone()[0], 6)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM semantic_nodes").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM semantic_edges").fetchone()[0], 0)
        broad_load = self.db.execute(
            "SELECT output_count FROM fit_run_phase_metrics WHERE run_id=? AND phase='load_input' AND layer='broad'",
            (run["id"],),
        ).fetchone()[0]
        self.assertEqual(broad_load, 0)

    def test_global_empty_upper_clustering_replaces_old_parents_with_new_wrappers(self):
        self.ingest("old")
        self.run_due()
        previous = {row[0] for row in self.db.execute("SELECT id FROM semantic_nodes WHERE layer!='span'")}
        run = state.schedule_global_rebuild(self.db, self.project_id, reason="synthetic upper density outliers")
        original = pipeline._cluster_groups
        with patch.object(pipeline, "_cluster_groups", side_effect=lambda rows, layer: original(rows, layer) if layer == "span" else []):
            pipeline.run_fit(self.db, run["id"])
        current = {row[0] for row in self.db.execute("SELECT id FROM semantic_nodes WHERE layer!='span'")}
        self.assertTrue(current)
        self.assertTrue(previous.isdisjoint(current))
        self.assert_complete_ancestry(f"old-{index}" for index in range(6))

    def test_legacy_queued_and_running_layer_order_is_normalized(self):
        for already_running in (False, True):
            with self.subTest(already_running=already_running):
                self.setUp_legacy_run(already_running)

    def setUp_legacy_run(self, already_running):
        if self.db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0] == 0:
            self.ingest("old", 24)
        run = state.schedule_global_rebuild(self.db, self.project_id, reason="synthetic legacy order")
        with self.db:
            self.db.execute("UPDATE fit_runs SET layers=?, state=? WHERE id=?",
                            (json.dumps(["broad", "span", "specific"]), "running" if already_running else "queued", run["id"]))
        committed = pipeline.run_fit(self.db, run["id"])
        self.assertEqual(json.loads(committed["layers"]), ["span", "specific", "broad"])
        self.assert_complete_ancestry(f"old-{index}" for index in range(24))

    def test_effective_snapshot_excludes_evicted_retired_and_replaced_children(self):
        self.ingest("old")
        self.run_due()
        self.ingest("new")
        self.run_due()
        old_span = self.db.execute("""SELECT n.id FROM semantic_nodes n JOIN semantic_node_memberships m ON m.node_id=n.id
                                      WHERE n.layer='span' AND m.chunk_id='old-0'""").fetchone()[0]
        new_span = self.db.execute("""SELECT n.id FROM semantic_nodes n JOIN semantic_node_memberships m ON m.node_id=n.id
                                      WHERE n.layer='span' AND m.chunk_id='new-0'""").fetchone()[0]
        with self.db:
            self.db.execute("UPDATE turn_chunks SET evicted=1 WHERE thread_id='chat-old'")
            self.db.execute("UPDATE semantic_nodes SET lifecycle='retired' WHERE id=?", (new_span,))
        run = {"id": "snapshot", "project_id": self.project_id, "kind": "routine", "chunk_watermark": 1000}
        rows, _ = pipeline._fit_rows_for_layer(self.db, run, "specific", {})
        self.assertEqual(rows, [])
        with self.db:
            self.db.execute("UPDATE semantic_nodes SET lifecycle='unlocked' WHERE id=?", (new_span,))
        rows, _ = pipeline._fit_rows_for_layer(self.db, run, "specific", {})
        self.assertEqual([row["id"] for row in rows], [new_span])
        broad_rows, _ = pipeline._fit_rows_for_layer(self.db, run, "broad", {})
        retained_rows, _ = pipeline._fit_rows_for_layer(self.db, run, "broad", {"specific": []})
        self.assertEqual(retained_rows, broad_rows)
        rows, _ = pipeline._fit_rows_for_layer(self.db, run, "specific", {"span": []})
        self.assertEqual(rows, [])
        run["kind"] = "rebalance"
        rows, _ = pipeline._fit_rows_for_layer(self.db, run, "specific", {"span": []})
        self.assertEqual(rows, [])
        with self.db:
            self.db.execute("DELETE FROM turn_ingestion WHERE thread_id='chat-new'")
        rows, _ = pipeline._fit_rows_for_layer(self.db, run, "specific", {})
        self.assertEqual(rows, [])
        self.assertIsNotNone(self.db.execute("SELECT id FROM semantic_nodes WHERE id=?", (old_span,)).fetchone())
        cleanup = state.schedule_global_rebuild(self.db, self.project_id, reason="synthetic eviction cleanup")
        pipeline.run_fit(self.db, cleanup["id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM semantic_nodes").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM semantic_edges").fetchone()[0], 0)


class OnlineHierarchyAssignmentTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary).resolve()
        self.enterContext(patch.dict(os.environ, {"THREAD_HISTORY_TREE_DATA": str(self.root / "data")}))
        (self.root / "data").mkdir()
        (self.root / "data" / "config.json").write_text(json.dumps({
            "embedding_provider": "none", "fit_thresholds": {"span": 6, "specific": 10000, "broad": 10000},
        }))
        self.enterContext(patch.object(thread_tree.SemanticProvider, "_check"))
        self.transcript = self.root / "synthetic.jsonl"
        self.transcript.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": "synthetic-online-chat", "cwd": str(self.root),
        }}) + "\n")
        self.append_messages(0, 6)
        queued = pipeline.enqueue_transcript(self.transcript)
        self.project_id = queued["project_id"]
        result = pipeline.process_project(self.project_id)
        self.assertEqual(result["failures"], [])
        self.assertEqual(len(pipeline.search_project(self.project_id, "cobalt", limit=100)), 6)

    def append_messages(self, start, stop):
        with self.transcript.open("a") as handle:
            for index in range(start, stop):
                handle.write(json.dumps({"type": "response_item", "payload": {
                    "type": "message", "id": f"synthetic-message-{index}", "role": "user",
                    "content": [{"type": "input_text", "text": f"Cobalt zephyr quartz glacier sapphire tundra archive evidence item {index}."}],
                }}) + "\n")

    def assert_covered(self, db, count):
        chunks = {row[0] for row in db.execute("SELECT id FROM turn_chunks WHERE evicted=0")}
        self.assertEqual(len(chunks), count)
        span = db.execute("SELECT id FROM semantic_nodes WHERE layer='span' AND lifecycle='locked'").fetchone()[0]
        current = span
        for layer in ("span", "specific", "broad"):
            members = {row[0] for row in db.execute("SELECT chunk_id FROM semantic_node_memberships WHERE node_id=?", (current,))}
            self.assertEqual(members, chunks, layer)
            if layer != "broad":
                edge = db.execute("SELECT parent_id, coverage FROM semantic_edges WHERE child_id=? AND primary_edge=1", (current,)).fetchone()
                self.assertIsNotNone(edge)
                self.assertEqual(edge["coverage"], 1)
                current = edge["parent_id"]

    def test_production_enqueue_process_accepts_seventh_chunk_without_fit_or_replay_debt(self):
        db = thread_tree.connect_db()
        before_fits = db.execute("SELECT COUNT(*) FROM fit_runs").fetchone()[0]
        before_debt = {row["layer"]: row["debt_count"] for row in state.debt_status(db, self.project_id)}
        before_vectors = [tuple(row) for row in db.execute("SELECT embedding, embedding_model FROM turn_chunks ORDER BY seq")]
        db.close()
        self.append_messages(6, 7)
        self.assertEqual(pipeline.enqueue_transcript(self.transcript)["queued_turns"], 1)
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 1)
        self.assertEqual(len(pipeline.search_project(self.project_id, "cobalt", limit=100)), 7)
        db = thread_tree.connect_db()
        self.assert_covered(db, 7)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM fit_runs").fetchone()[0], before_fits)
        debt = {row["layer"]: row["debt_count"] for row in state.debt_status(db, self.project_id)}
        self.assertEqual(debt, {"span": 0, "specific": before_debt["specific"] + 1, "broad": before_debt["broad"] + 1})
        self.assertEqual([tuple(row) for row in db.execute("SELECT embedding, embedding_model FROM turn_chunks ORDER BY seq LIMIT 6")], before_vectors)
        snapshot = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("turn_chunks", "semantic_node_memberships", "fit_debt_events", "fit_runs")}
        db.close()
        self.assertEqual(pipeline.enqueue_transcript(self.transcript)["queued_turns"], 0)
        self.assertEqual(pipeline.process_project(self.project_id)["processed_turns"], 0)
        db = thread_tree.connect_db()
        self.assert_covered(db, 7)
        self.assertEqual({table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in snapshot}, snapshot)
        db.close()

    def test_accepted_assignment_after_fit_watermark_survives_upper_and_global_publication(self):
        db = thread_tree.connect_db()
        for index, global_rebuild in enumerate((False, True), start=6):
            if global_rebuild:
                run = state.schedule_global_rebuild(db, self.project_id, reason="synthetic concurrent assignment")
            else:
                with db:
                    db.execute("UPDATE fit_debt SET threshold=1 WHERE layer!='span'")
                run = state.schedule_routine_fit(db, self.project_id)
            self.assertEqual(run["chunk_watermark"], index)
            self.append_messages(index, index + 1)
            pipeline.enqueue_transcript(self.transcript)
            # Ingest while holding back the already queued older fit.
            with patch.object(state, "schedule_routine_fit", return_value=None):
                pipeline.process_project(self.project_id)
            self.assert_covered(db, index + 1)
            pipeline.run_fit(db, run["id"])
            self.assert_covered(db, index + 1)
            self.assertEqual(db.execute("SELECT chunk_watermark FROM fit_runs WHERE id=?", (run["id"],)).fetchone()[0], index)
        db.close()

    def test_stale_foreign_and_retired_prototypes_fall_back_without_membership(self):
        db = thread_tree.connect_db()
        state.ensure_project(db, "foreign-project", "/synthetic/foreign")
        first_chunk = db.execute("SELECT id FROM turn_chunks ORDER BY seq LIMIT 1").fetchone()[0]
        with db:
            db.execute("UPDATE fit_debt SET threshold=10000 WHERE layer='span'")
            db.execute("""INSERT INTO turn_ingestion(id,project_id,thread_id,content_hash,state,created_at,updated_at)
                          VALUES ('evicted-turn',?,'evicted-chat','evicted-hash','evicted',?,?)""",
                       (self.project_id, state.utc_now(), state.utc_now()))
            db.execute("""INSERT INTO turn_chunks(id,project_id,thread_id,turn_id,text,content_hash,byte_count,evicted,created_at)
                          VALUES ('evicted-chunk',?,'evicted-chat','evicted-turn','Synthetic evicted evidence','evicted-chunk',26,1,?)""",
                       (self.project_id, state.utc_now()))
            for node_id, project_id, lifecycle, layer in (("retired", self.project_id, "retired", "span"),
                                                        ("foreign", "foreign-project", "locked", "span"),
                                                        ("evicted", self.project_id, "locked", "span"),
                                                        ("wrong-layer", self.project_id, "locked", "specific")):
                db.execute("""INSERT INTO semantic_nodes(id,project_id,layer,lifecycle,title,created_at,updated_at)
                              VALUES (?,?,?,?, 'Synthetic invalid prototype',?,?)""",
                           (node_id, project_id, layer, lifecycle, state.utc_now(), state.utc_now()))
                db.execute("INSERT INTO semantic_node_memberships VALUES (?, ?, 1)",
                           (node_id, "evicted-chunk" if node_id == "evicted" else first_chunk))
        original = pipeline._initial_states
        for index, target in enumerate(("missing", "retired", "foreign", "evicted", "wrong-layer"), start=6):
            self.append_messages(index, index + 1)
            pipeline.enqueue_transcript(self.transcript)

            def stale_assignment(connection, project_id, chunks):
                original(connection, project_id, chunks)
                for chunk in chunks:
                    chunk["layer_states"]["span"] = {"state": "locked", "target_id": target, "membership_confidence": 1}

            with patch.object(pipeline, "_initial_states", side_effect=stale_assignment):
                self.assertEqual(pipeline.process_project(self.project_id)["failures"], [])
            latest = db.execute("SELECT id FROM turn_chunks ORDER BY seq DESC LIMIT 1").fetchone()[0]
            assignment = db.execute("SELECT state,target_id FROM chunk_layer_states WHERE chunk_id=? AND layer='span'", (latest,)).fetchone()
            self.assertEqual(tuple(assignment), ("unassigned", None))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM semantic_node_memberships WHERE chunk_id=?", (latest,)).fetchone()[0], 0)
        db.close()

    def test_newer_assignment_returns_to_frontier_when_authoritative_rebuild_removes_prototype(self):
        db = thread_tree.connect_db()
        run = state.schedule_global_rebuild(db, self.project_id, reason="synthetic removed prototype")
        self.append_messages(6, 7)
        pipeline.enqueue_transcript(self.transcript)
        with patch.object(state, "schedule_routine_fit", return_value=None):
            pipeline.process_project(self.project_id)
        self.assert_covered(db, 7)
        with patch.object(pipeline, "_cluster_groups", return_value=[]):
            pipeline.run_fit(db, run["id"])
        latest = db.execute("SELECT id FROM turn_chunks ORDER BY seq DESC LIMIT 1").fetchone()[0]
        self.assertEqual(tuple(db.execute(
            "SELECT state,target_id FROM chunk_layer_states WHERE chunk_id=? AND layer='span'", (latest,),
        ).fetchone()), ("unassigned", None))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM semantic_nodes").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM fit_debt_events WHERE chunk_id=? AND layer='span' AND consumed_by IS NULL", (latest,)).fetchone()[0], 1)
        self.assertEqual(len(pipeline.search_project(self.project_id, "cobalt", limit=100)), 7)
        db.close()

    def test_newer_assignment_tracks_reused_prototype_that_becomes_unlocked(self):
        db = thread_tree.connect_db()
        run = state.schedule_global_rebuild(db, self.project_id, reason="synthetic prototype confidence change")
        self.append_messages(6, 7)
        pipeline.enqueue_transcript(self.transcript)
        with patch.object(state, "schedule_routine_fit", return_value=None):
            pipeline.process_project(self.project_id)
        original = pipeline._cluster_groups

        def low_persistence(rows, layer):
            groups = original(rows, layer)
            if layer == "span":
                for group in groups:
                    group["persistence"] = 0
            return groups

        with patch.object(pipeline, "_cluster_groups", side_effect=low_persistence):
            pipeline.run_fit(db, run["id"])
        latest = db.execute("SELECT id FROM turn_chunks ORDER BY seq DESC LIMIT 1").fetchone()[0]
        assignment = db.execute("SELECT state,target_id FROM chunk_layer_states WHERE chunk_id=? AND layer='span'", (latest,)).fetchone()
        self.assertEqual(assignment["state"], "unlocked")
        self.assertEqual(db.execute("SELECT lifecycle FROM semantic_nodes WHERE id=?", (assignment["target_id"],)).fetchone()[0], "unlocked")
        self.assertEqual(db.execute("SELECT COUNT(*) FROM semantic_node_memberships WHERE node_id=?", (assignment["target_id"],)).fetchone()[0], 7)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM fit_debt_events WHERE chunk_id=? AND layer='span' AND consumed_by IS NULL", (latest,)).fetchone()[0], 1)
        db.close()

    def test_newer_assignment_follows_only_reused_child_when_old_prototype_splits(self):
        db = thread_tree.connect_db()
        run = state.schedule_global_rebuild(db, self.project_id, reason="synthetic prototype split")
        self.append_messages(6, 7)
        pipeline.enqueue_transcript(self.transcript)
        with patch.object(state, "schedule_routine_fit", return_value=None):
            pipeline.process_project(self.project_id)
        accepted = db.execute("SELECT id FROM turn_chunks ORDER BY seq DESC LIMIT 1").fetchone()[0]
        old_target = db.execute("SELECT target_id FROM chunk_layer_states WHERE chunk_id=? AND layer='span'", (accepted,)).fetchone()[0]

        def split_groups(rows, layer):
            groups = [rows[:4], rows[4:]] if layer == "span" else [[row] for row in rows]
            return [{"rows": group, "persistence": 1,
                     "confidences": {row["id"]: 1 for row in group}, "provider": "synthetic-split"}
                    for group in groups if group]

        with patch.object(pipeline, "_cluster_groups", side_effect=split_groups):
            pipeline.run_fit(db, run["id"])
        current = db.execute("SELECT target_id FROM chunk_layer_states WHERE chunk_id=? AND layer='span'", (accepted,)).fetchone()[0]
        self.assertEqual(current, old_target)
        for layer in state.LAYERS:
            owners = [row[0] for row in db.execute(
                """SELECT n.id FROM semantic_nodes n JOIN semantic_node_memberships m ON m.node_id=n.id
                   WHERE n.layer=? AND m.chunk_id=?""", (layer, accepted),
            )]
            self.assertEqual(owners, [current], layer)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM semantic_node_memberships WHERE node_id=?", (current,)).fetchone()[0], 5)
            if layer != "broad":
                current = db.execute("SELECT parent_id FROM semantic_edges WHERE child_id=? AND primary_edge=1", (current,)).fetchone()[0]
        db.close()

    def test_publication_holds_writer_lock_before_online_assignment_snapshot(self):
        db = thread_tree.connect_db()
        run = state.schedule_global_rebuild(db, self.project_id, reason="synthetic concurrent publication")
        self.append_messages(6, 7)
        pipeline.enqueue_transcript(self.transcript)
        other = thread_tree.connect_db()
        other.execute("PRAGMA busy_timeout=0")
        turn = state.claim_next_turn(other, self.project_id)
        chunks = pipeline.semantic_chunks(pipeline._read_turn_messages(turn))
        chunks[0]["id"] = "synthetic-concurrent-chunk"
        pipeline._initial_states(other, self.project_id, chunks)
        self.assertEqual(chunks[0]["layer_states"]["span"]["state"], "locked")
        original = state.commit_fit_run
        attempts = []

        def concurrent_ingestion(connection, run_id, assignments, **kwargs):
            self.assertTrue(connection.in_transaction)
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                state.complete_turn_ingestion(other, turn["id"], chunks, lease_token=turn["lease_token"])
            attempts.append(True)
            return original(connection, run_id, assignments, **kwargs)

        with patch.object(state, "commit_fit_run", side_effect=concurrent_ingestion):
            pipeline.run_fit(db, run["id"])
        self.assertEqual(attempts, [True])
        state.complete_turn_ingestion(other, turn["id"], chunks, lease_token=turn["lease_token"])
        self.assert_covered(db, 7)
        self.assertEqual(len(pipeline.search_project(self.project_id, "cobalt", limit=100)), 7)
        other.close()
        db.close()

    def test_accepted_membership_failure_rolls_back_chunk_fts_states_and_ancestors(self):
        db = thread_tree.connect_db()
        broad = db.execute("SELECT id FROM semantic_nodes WHERE layer='broad'").fetchone()[0]
        with db:
            db.execute(f"""CREATE TRIGGER reject_synthetic_ancestor BEFORE INSERT ON semantic_node_memberships
                           WHEN NEW.node_id='{broad}' BEGIN SELECT RAISE(ABORT, 'synthetic membership failure'); END""")
        before = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("turn_chunks", "turn_chunks_fts", "chunk_layer_states", "semantic_node_memberships", "fit_debt_events")}
        self.append_messages(6, 7)
        pipeline.enqueue_transcript(self.transcript)
        result = pipeline.process_project(self.project_id)
        self.assertEqual(result["processed_turns"], 0)
        self.assertTrue(any("synthetic membership failure" in failure for failure in result["failures"]))
        self.assertEqual({table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}, before)
        self.assert_covered(db, 6)
        db.close()


if __name__ == "__main__":
    unittest.main()
