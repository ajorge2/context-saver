#!/usr/bin/env python3
"""Finite reference models for retention and fit snapshot boundaries."""

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import itertools
import importlib.util
import sqlite3
import unittest
from contextlib import closing
from dataclasses import dataclass
from unittest.mock import Mock, patch

import system_validation as fixtures
import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state


@dataclass(frozen=True)
class Turn:
    name: str
    age_order: int
    protected: bool
    texts: tuple[str, ...]

    @property
    def bytes(self) -> int:
        return sum(len(text.encode("utf-8")) for text in self.texts)


def store() -> sqlite3.Connection:
    """Use the shipped schema while keeping the model entirely off disk."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    thread_tree.initialize_schema(db)
    for project in ("project-a", "project-b"):
        state.ensure_project(db, project, f"/fixture/{project}", fit_thresholds={layer: 1 for layer in state.LAYERS})
    return db


def ingest(db: sqlite3.Connection, project: str, turn: Turn) -> list[str]:
    state.queue_turn(
        db,
        turn_id=turn.name,
        project_id=project,
        thread_id=f"chat-{turn.name}",
        content_hash=f"hash-{turn.name}",
        protected=turn.protected,
    )
    claimed = state.claim_next_turn(db, project)
    if not claimed or claimed["id"] != turn.name:
        raise AssertionError(f"fixture claimed the wrong turn: {claimed}")
    chunks = state.complete_turn_ingestion(db, turn.name, [
        {"text": text, "source_message_ids": [f"msg-{turn.name}-{index}"]}
        for index, text in enumerate(turn.texts)
    ])
    with db:
        db.execute(
            "UPDATE turn_ingestion SET created_at=? WHERE id=?",
            (f"2026-01-01T00:00:{turn.age_order:02d}+00:00", turn.name),
        )
    return [chunk["id"] for chunk in chunks]


def expected_evictions(turns: tuple[Turn, ...], high: int, low: int, ceiling: int | None) -> list[str] | None:
    """Find the minimum oldest-first removable prefix, or report no valid plan."""
    total_chunks = sum(len(turn.texts) for turn in turns)
    total_bytes = sum(turn.bytes for turn in turns)
    if total_chunks <= high and (ceiling is None or total_bytes <= ceiling):
        return []
    removable = sorted(
        (turn for turn in turns if not turn.protected),
        key=lambda turn: (turn.age_order, turn.name),
    )
    for count in range(1, len(removable) + 1):
        rows_removed = removable[:count]
        if total_chunks - sum(len(turn.texts) for turn in rows_removed) > low:
            continue
        if ceiling is not None and total_bytes - sum(turn.bytes for turn in rows_removed) > ceiling:
            continue
        return [turn.name for turn in rows_removed]
    return None


class StateMatrixTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("numpy") is not None, "native persistence requires NumPy")
    def test_linear_cluster_persistence_matches_the_pairwise_definition(self):
        samples = [
            {"embedding": [1, 0], "text": "aurora query evidence"},
            {"embedding": [3, 0], "text": "aurora evidence"},
            {"embedding": [-1, 1], "text": "query diff"},
            {"embedding": [0, 0], "text": "aurora"},
            {"embedding": [0, -4], "text": "!?"},
        ]
        for size in range(2, len(samples) + 1):
            rows = samples[:size]
            for ordering in (rows, list(reversed(rows))):
                with self.subTest(size=size, reversed=ordering != rows):
                    pairs = [
                        0.78 * pipeline._cosine(left["embedding"], right["embedding"])
                        + 0.22 * pipeline._lexical_similarity(left["text"], right["text"])
                        for left, right in itertools.combinations(ordering, 2)
                    ]
                    self.assertAlmostEqual(pipeline._cluster_persistence(ordering), sum(pairs) / len(pairs), places=12)

    def test_semantic_runtime_uses_lexical_path_when_its_only_vector_is_disallowed(self):
        with fixtures.isolated_runtime():
            with closing(thread_tree.connect_db()) as db:
                state.ensure_project(db, "project-a", "/fixture/project-a")
                expected = ingest(db, "project-a", Turn("allowed", 0, False, ("Bamboo pioneer",)))[0]
                excluded = ingest(db, "project-a", Turn("excluded", 1, False, ("Bamboo warehouse",)))[0]
                with db:
                    db.execute(
                        "UPDATE turn_chunks SET embedding='[1,0]', embedding_model='fixture' WHERE id=?",
                        (excluded,),
                    )
            provider = Mock(can_embed=True, embedding_model="fixture")
            with patch.object(thread_tree, "SemanticProvider", return_value=provider):
                result = pipeline.search_project("project-a", "bamboo", excluded_thread_ids=["chat-excluded"])
            self.assertEqual([hit["id"] for hit in result], [expected])
            self.assertEqual(result[0]["retrieval_diagnostics"]["fusion_mode"], "lexical_fallback")
            provider.embed.assert_not_called()

    def test_embedding_delta_lookup_stays_bounded_with_fifty_thousand_lexical_rows(self):
        with closing(store()) as db:
            state.queue_turn(db, turn_id="fixture", project_id="project-a", thread_id="chat", content_hash="fixture")
            with db:
                db.execute("""
                    WITH RECURSIVE numbers(n) AS (
                        VALUES(1) UNION ALL SELECT n+1 FROM numbers WHERE n<50000
                    )
                    INSERT INTO turn_chunks(id, project_id, thread_id, turn_id, text, content_hash, byte_count, created_at)
                    SELECT 'chunk-'||n, 'project-a', 'chat', 'fixture', 'test', n, 4, '2026-01-01' FROM numbers
                """)
                db.execute("UPDATE turn_chunks SET embedding='[1,0]', embedding_model='fixture' WHERE id='chunk-1'")
            instructions = []

            def count_steps():
                instructions.append(100)
                return 0

            db.set_progress_handler(count_steps, 100)
            try:
                rows = db.execute(
                    """SELECT id FROM turn_chunks
                       WHERE project_id=? AND evicted=0 AND seq>? AND seq<=?
                         AND embedding IS NOT NULL AND embedding_model=?
                       ORDER BY seq DESC LIMIT ?""",
                    ("project-a", 0, 50_000, "fixture", 1_001),
                ).fetchall()
            finally:
                db.set_progress_handler(None, 0)
            self.assertEqual([row[0] for row in rows], ["chunk-1"])
            self.assertLess(sum(instructions), 5_000)

    def test_new_chunks_and_duplicate_delivery_do_not_scan_fts_for_deletion(self):
        with closing(store()) as db:
            statements = []
            db.set_trace_callback(statements.append)
            ids = ingest(db, "project-a", Turn("first", 0, False, ("fox alpha", "fox beta", "fox alpha")))
            state.queue_turn(
                db,
                turn_id="duplicate",
                project_id="project-a",
                thread_id="chat-first",
                content_hash="hash-first",
            )
            self.assertIsNone(state.claim_next_turn(db, "project-a"))
            self.assertFalse(any(sql.lstrip().upper().startswith("DELETE FROM TURN_CHUNKS_FTS") for sql in statements))
            self.assertEqual(len(set(ids)), 2)
            self.assertEqual(
                [row[0] for row in db.execute("SELECT DISTINCT chunk_id FROM turn_chunks_fts WHERE turn_chunks_fts MATCH 'fox' ORDER BY chunk_id")],
                sorted(set(ids)),
            )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks_fts").fetchone()[0], 2)

    def test_retention_matches_reference_for_1728_policies_and_corpora(self):
        policies = (
            (1, 0, None), (3, 2, None), (5, 0, None), (9, 8, None),
            (9, 4, 25), (5, 3, 31), (4, 1, 17), (9, 8, 10_000),
        )
        for sizes, protected in itertools.product(
            itertools.product(range(1, 4), repeat=3),
            itertools.product((False, True), repeat=3),
        ):
            # Tied timestamps require an ID tiebreak. Ingestion delivers newest first.
            turns = tuple(
                Turn(name, ordinal, guarded, tuple(f"{name} {index} {suffix}" for index in range(size)))
                for name, ordinal, guarded, size, suffix in zip(
                    ("turn-z", "turn-a", "turn-b"), (1, 1, 2), protected, sizes, ("雪", "abc", "🙂"),
                )
            )
            with closing(store()) as db:
                ingest(db, "project-b", Turn("foreign", 0, False, ("another project with different constraints",)))
                for turn in reversed(turns):
                    ingest(db, "project-a", turn)
                for high, low, ceiling in policies:
                    with self.subTest(sizes=sizes, protected=protected, high=high, low=low, byte_ceiling=ceiling):
                        state.configure_retention(db, "project-a", high_chunks=high, low_chunks=low, byte_ceiling=ceiling)
                        expected = expected_evictions(turns, high, low, ceiling)
                        if expected is None:
                            with self.assertRaises(state.StateTransitionError):
                                state.plan_capacity_eviction(db, "project-a")
                        else:
                            self.assertEqual(state.plan_capacity_eviction(db, "project-a"), expected)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM evicted_turns").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks WHERE evicted=1").fetchone()[0], 0)

    def test_bad_eviction_batches_roll_back_before_removing_anything(self):
        for bad_id, error in (
            ("protected", state.StateTransitionError),
            ("foreign", KeyError),
            ("missing", KeyError),
        ):
            for bad_first in (False, True):
                with self.subTest(bad_id=bad_id, bad_first=bad_first), closing(store()) as db:
                    ingest(db, "project-a", Turn("good", 0, False, ("one", "two")))
                    ingest(db, "project-a", Turn("protected", 1, True, ("three",)))
                    ingest(db, "project-b", Turn("foreign", 2, False, ("four",)))
                    batch = [bad_id, "good"] if bad_first else ["good", bad_id]
                    with self.assertRaises(error):
                        state.mark_turns_evicted(db, "project-a", batch, eviction_generation="invalid")
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM evicted_turns").fetchone()[0], 0)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM turn_chunks WHERE evicted=0").fetchone()[0], 4)
                    self.assertEqual(
                        state.mark_turns_evicted(db, "project-a", ["good", "good"], eviction_generation="valid"),
                        ["good"],
                    )
                    self.assertEqual(
                        [tuple(row) for row in db.execute("SELECT turn_id, SUM(evicted) FROM turn_chunks GROUP BY turn_id")],
                        [("foreign", 0), ("good", 2), ("protected", 0)],
                    )
                    with self.assertRaises(state.StateTransitionError):
                        state.mark_turns_evicted(db, "project-a", ["good"], eviction_generation="duplicate")
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM evicted_turns").fetchone()[0], 1)
                    self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")

    def test_fit_rejects_foreign_and_late_assignments_without_advancing_snapshot(self):
        for kind, late_size, forbidden_owner in itertools.product(
            ("routine", "rebalance"), (1, 3), ("late", "foreign"),
        ):
            with self.subTest(kind=kind, late_size=late_size, forbidden_owner=forbidden_owner), closing(store()) as db:
                first = ingest(db, "project-a", Turn("first", 0, False, ("first evidence",)))[0]
                run = (
                    state.schedule_routine_fit(db, "project-a")
                    if kind == "routine"
                    else state.schedule_global_rebuild(db, "project-a", reason="boundary")
                )
                state.claim_fit_run(db, run["id"])
                foreign = ingest(db, "project-b", Turn("foreign", 1, False, ("private foreign evidence",)))[0]
                late = ingest(db, "project-a", Turn("late", 2, False, tuple(f"late evidence {i}" for i in range(late_size))))
                forbidden = foreign if forbidden_owner == "foreign" else late[0]
                with self.assertRaisesRegex(state.StateTransitionError, "ineligible chunks"):
                    state.commit_fit_run(db, run["id"], {"broad": {forbidden: "unassigned"}})
                self.assertEqual(db.execute("SELECT state FROM fit_runs WHERE id=?", (run["id"],)).fetchone()[0], "running")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM cluster_generations").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM fit_debt_events WHERE consumed_by IS NOT NULL").fetchone()[0], 0)
                self.assertTrue(all(state.fit_input_chunk_ids(db, run["id"], layer) == [first] for layer in state.LAYERS))

                state.commit_fit_run(db, run["id"], {})
                actual = {
                    tuple(row) for row in db.execute(
                        "SELECT DISTINCT project_id, chunk_id, consumed_by FROM fit_debt_events",
                    )
                }
                self.assertEqual(actual, {
                    ("project-a", first, run["id"]),
                    ("project-b", foreign, None),
                    *(("project-a", chunk_id, None) for chunk_id in late),
                })


if __name__ == "__main__":
    unittest.main()
