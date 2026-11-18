#!/usr/bin/env python3

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import sqlite3
import unittest

import thread_tree_state as state


class ThreadTreeStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        state.initialize_state_schema(self.db)
        self.project_id = "project-test"
        state.ensure_project(
            self.db,
            self.project_id,
            "/tmp/thread-tree-project",
            fit_thresholds={"span": 1, "specific": 1, "broad": 1},
            high_chunks=10,
            low_chunks=8,
        )

    def tearDown(self) -> None:
        self.db.close()

    def ingest(
        self,
        turn_id: str,
        chunks: list[dict],
        *,
        content_hash: str | None = None,
        protected: bool = False,
        thread_id: str = "thread-test",
    ) -> list[dict]:
        state.queue_turn(
            self.db,
            turn_id=turn_id,
            project_id=self.project_id,
            thread_id=thread_id,
            content_hash=content_hash or f"hash-{turn_id}",
            protected=protected,
        )
        claimed = state.claim_next_turn(self.db, self.project_id)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], turn_id)
        return state.complete_turn_ingestion(self.db, turn_id, chunks)

    def test_one_tree_per_canonical_project_root(self) -> None:
        left = state.project_id_for("/tmp/example/../example", "thread-a")
        right = state.project_id_for("/tmp/example", "thread-b")
        self.assertEqual(left, right)
        self.assertNotEqual(left, state.project_id_for("/tmp/other-project", "thread-a"))
        with self.assertRaises(ValueError):
            state.project_id_for(None, "thread-a")

    def test_chats_in_one_project_share_tree_state(self) -> None:
        self.ingest("turn-a", [{"id": "chunk-a", "text": "From chat A."}], thread_id="thread-a")
        self.ingest("turn-b", [{"id": "chunk-b", "text": "From chat B."}], thread_id="thread-b")

        threads = {
            row["thread_id"]
            for row in self.db.execute(
                "SELECT DISTINCT thread_id FROM turn_chunks WHERE project_id = ?",
                (self.project_id,),
            )
        }
        self.assertEqual(threads, {"thread-a", "thread-b"})
        debt = {row["layer"]: row["debt_count"] for row in state.debt_status(self.db, self.project_id)}
        self.assertEqual(debt, {"broad": 2, "span": 2, "specific": 2})

    def test_raw_prompt_stage_is_idempotent_and_reconciles_to_authoritative_turn(self) -> None:
        first = state.stage_user_prompt(
            self.db,
            codex_turn_id="codex-turn-1",
            project_id=self.project_id,
            thread_id="thread-test",
            prompt="Find the earlier retrieval decision.",
        )
        duplicate = state.stage_user_prompt(
            self.db,
            codex_turn_id="codex-turn-1",
            project_id=self.project_id,
            thread_id="thread-test",
            prompt="Find the earlier retrieval decision.",
        )
        self.assertEqual(first["content_hash"], duplicate["content_hash"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0], 0)

        state.queue_turn(
            self.db,
            turn_id="ingestion-turn-1",
            project_id=self.project_id,
            thread_id="thread-test",
            content_hash="completed-turn",
        )
        reconciled = state.reconcile_staged_prompt(
            self.db,
            codex_turn_id="codex-turn-1",
            project_id=self.project_id,
            thread_id="thread-test",
            ingestion_turn_id="ingestion-turn-1",
        )
        self.assertEqual(reconciled["state"], "reconciled")
        self.assertEqual(reconciled["ingestion_turn_id"], "ingestion-turn-1")

    def test_latest_raw_stage_reconciles_for_client_without_turn_ids(self) -> None:
        state.stage_user_prompt(
            self.db,
            codex_turn_id="generated-stage-id",
            project_id=self.project_id,
            thread_id="claude-session",
            prompt="Find the earlier Claude Code decision.",
        )
        state.queue_turn(
            self.db,
            turn_id="claude-ingestion-turn",
            project_id=self.project_id,
            thread_id="claude-session",
            content_hash="claude-completed-turn",
        )
        reconciled = state.reconcile_staged_prompt(
            self.db,
            codex_turn_id=None,
            project_id=self.project_id,
            thread_id="claude-session",
            ingestion_turn_id="claude-ingestion-turn",
        )
        self.assertEqual(reconciled["state"], "reconciled")
        self.assertEqual(reconciled["ingestion_turn_id"], "claude-ingestion-turn")

    def test_turn_queue_is_idempotent_and_rejects_invalid_transition(self) -> None:
        first = state.queue_turn(
            self.db,
            turn_id="turn-1",
            project_id=self.project_id,
            thread_id="thread-test",
            content_hash="same-content",
        )
        duplicate = state.queue_turn(
            self.db,
            turn_id="turn-other-id",
            project_id=self.project_id,
            thread_id="thread-test",
            content_hash="same-content",
        )
        self.assertEqual(first["id"], duplicate["id"])
        claimed = state.claim_next_turn(self.db, self.project_id)
        self.assertEqual(claimed["state"], "processing")
        self.assertEqual(claimed["attempts"], 1)
        with self.assertRaises(state.StateTransitionError):
            state.transition_turn(self.db, "turn-1", "queued")

    def test_ingestion_tracks_debt_per_layer_and_frontier_visibility(self) -> None:
        chunks = self.ingest(
            "turn-1",
            [
                {
                    "id": "chunk-1",
                    "text": "A chunk with a locked broad assignment.",
                    "layer_states": {
                        "span": "unassigned",
                        "specific": {"state": "unlocked", "target_id": "specific-temp"},
                        "broad": {"state": "locked", "target_id": "broad-stable"},
                    },
                }
            ],
        )
        self.assertEqual(len(chunks), 1)
        debt = {row["layer"]: row["debt_count"] for row in state.debt_status(self.db, self.project_id)}
        self.assertEqual(debt, {"broad": 0, "span": 1, "specific": 1})
        frontier = state.frontier_chunks(self.db, self.project_id)
        self.assertEqual([row["id"] for row in frontier], ["chunk-1"])
        self.assertEqual(frontier[0]["unassigned_layers"], "span")

    def test_fit_debt_schedules_once_and_fit_input_excludes_locked_chunks(self) -> None:
        self.ingest(
            "turn-1",
            [
                {"id": "open", "text": "Needs clustering."},
                {
                    "id": "locked",
                    "text": "Already belongs everywhere.",
                    "layer_states": {
                        layer: {"state": "locked", "target_id": f"{layer}-stable"}
                        for layer in state.LAYERS
                    },
                },
            ],
        )
        run = state.schedule_routine_fit(self.db, self.project_id)
        self.assertIsNotNone(run)
        self.assertEqual(state.schedule_routine_fit(self.db, self.project_id)["id"], run["id"])
        state.claim_fit_run(self.db, run["id"])
        for layer in state.LAYERS:
            self.assertEqual(state.fit_input_chunk_ids(self.db, run["id"], layer), ["open"])

    def test_post_watermark_debt_survives_commit_and_old_unlocked_members_do_not_retrigger(self) -> None:
        self.ingest("turn-1", [{"id": "before", "text": "Before fit."}])
        run = state.schedule_routine_fit(self.db, self.project_id)
        state.claim_fit_run(self.db, run["id"])
        self.ingest("turn-2", [{"id": "after", "text": "Arrived while fit was running."}])
        self.assertEqual(state.fit_input_chunk_ids(self.db, run["id"], "span"), ["before"])

        assignments = {
            layer: {
                "before": {
                    "state": "unlocked",
                    "target_id": f"{layer}-provisional",
                    "membership_confidence": 0.8,
                }
            }
            for layer in state.LAYERS
        }
        state.commit_fit_run(self.db, run["id"], assignments)
        debt = {row["layer"]: row["debt_count"] for row in state.debt_status(self.db, self.project_id)}
        self.assertEqual(debt, {"broad": 1, "span": 1, "specific": 1})

        next_run = state.schedule_routine_fit(self.db, self.project_id)
        self.assertIsNotNone(next_run)
        state.claim_fit_run(self.db, next_run["id"])
        for layer in state.LAYERS:
            self.assertEqual(state.fit_input_chunk_ids(self.db, next_run["id"], layer), ["before", "after"])
        state.commit_fit_run(
            self.db,
            next_run["id"],
            {
                layer: {
                    chunk_id: {"state": "unlocked", "target_id": f"{layer}-next"}
                    for chunk_id in ("before", "after")
                }
                for layer in state.LAYERS
            },
        )
        self.assertIsNone(state.schedule_routine_fit(self.db, self.project_id))

    def test_failed_fit_preserves_unconsumed_debt(self) -> None:
        self.ingest("turn-1", [{"id": "chunk-1", "text": "Needs clustering."}])
        run = state.schedule_routine_fit(self.db, self.project_id)
        state.claim_fit_run(self.db, run["id"])
        state.fail_fit_run(self.db, run["id"], "provider unavailable")
        debt = {row["layer"]: row for row in state.debt_status(self.db, self.project_id)}
        self.assertTrue(all(row["debt_count"] == 1 and row["state"] == "idle" for row in debt.values()))
        retry_state = state.fit_retry_status(self.db, self.project_id)
        self.assertEqual(retry_state["consecutive_failures"], 1)
        self.assertFalse(retry_state["circuit_open"])
        self.assertIsNotNone(retry_state["next_retry_at"])
        self.assertIsNone(state.schedule_routine_fit(self.db, self.project_id))
        state.reset_fit_retry_state(self.db, self.project_id)
        retry = state.schedule_routine_fit(self.db, self.project_id)
        self.assertNotEqual(retry["id"], run["id"])

    def test_repeated_fit_failures_open_persisted_circuit(self) -> None:
        self.ingest("turn-1", [{"id": "chunk-1", "text": "Needs clustering."}])
        for attempt in range(state.FIT_RETRY_CIRCUIT_THRESHOLD):
            run = state.schedule_routine_fit(self.db, self.project_id)
            self.assertIsNotNone(run)
            state.claim_fit_run(self.db, run["id"])
            state.fail_fit_run(self.db, run["id"], f"provider failure {attempt}")
            if attempt + 1 < state.FIT_RETRY_CIRCUIT_THRESHOLD:
                self.db.execute(
                    "UPDATE fit_retry_state SET next_retry_at='1970-01-01T00:00:00+00:00' WHERE project_id=?",
                    (self.project_id,),
                )
        retry_state = state.fit_retry_status(self.db, self.project_id)
        self.assertEqual(retry_state["consecutive_failures"], state.FIT_RETRY_CIRCUIT_THRESHOLD)
        self.assertTrue(retry_state["circuit_open"])
        self.assertIsNone(state.schedule_routine_fit(self.db, self.project_id))
        state.reset_fit_retry_state(self.db, self.project_id)
        self.assertIsNotNone(state.schedule_routine_fit(self.db, self.project_id))

    def test_existing_failed_runs_backfill_retry_circuit_once(self) -> None:
        self.ingest("turn-1", [{"id": "chunk-1", "text": "Needs clustering."}])
        failed_ids = []
        for attempt in range(state.FIT_RETRY_CIRCUIT_THRESHOLD):
            run = state.schedule_routine_fit(self.db, self.project_id)
            self.assertIsNotNone(run)
            failed_ids.append(run["id"])
            state.claim_fit_run(self.db, run["id"])
            state.fail_fit_run(self.db, run["id"], f"historical provider failure {attempt}")
            self.db.execute(
                "UPDATE fit_retry_state SET next_retry_at='1970-01-01T00:00:00+00:00', circuit_open=0 WHERE project_id=?",
                (self.project_id,),
            )

        # Recreate the state of an installation upgraded after those failures.
        self.db.execute(
            """UPDATE fit_retry_state
               SET consecutive_failures=0, next_retry_at=NULL, circuit_open=0,
                   last_failed_run_id=NULL, last_failed_chunk_watermark=NULL,
                   last_failed_debt_event_watermark=NULL, last_error=NULL,
                   history_initialized=0
               WHERE project_id=?""",
            (self.project_id,),
        )
        state.ensure_project(self.db, self.project_id, "/tmp/thread-tree-project")

        retry_state = state.fit_retry_status(self.db, self.project_id)
        self.assertEqual(retry_state["consecutive_failures"], len(failed_ids))
        self.assertTrue(retry_state["circuit_open"])
        self.assertEqual(retry_state["last_failed_run_id"], failed_ids[-1])
        self.assertTrue(retry_state["history_initialized"])

        # Explicit remediation must remain authoritative on later startups.
        state.reset_fit_retry_state(self.db, self.project_id)
        state.ensure_project(self.db, self.project_id, "/tmp/thread-tree-project")
        reset = state.fit_retry_status(self.db, self.project_id)
        self.assertEqual(reset["consecutive_failures"], 0)
        self.assertFalse(reset["circuit_open"])

    def test_frontier_disappears_after_span_is_assigned(self) -> None:
        self.ingest("turn-1", [{"id": "chunk-1", "text": "Initially unclustered."}])
        state.update_chunk_layer_state(
            self.db,
            "chunk-1",
            "span",
            "locked",
            target_id="span-stable",
            accrue_debt=False,
        )
        self.assertEqual(state.frontier_chunks(self.db, self.project_id), [])

    def test_global_rebuild_includes_locked_chunks(self) -> None:
        self.ingest(
            "turn-1",
            [
                {
                    "id": "locked",
                    "text": "Locked evidence must reenter global rebuilds.",
                    "layer_states": {
                        layer: {"state": "locked", "target_id": f"{layer}-stable"}
                        for layer in state.LAYERS
                    },
                }
            ],
        )
        run = state.schedule_global_rebuild(
            self.db,
            self.project_id,
            kind="rebalance",
            reason="retrieval_sla",
        )
        state.claim_fit_run(self.db, run["id"])
        for layer in state.LAYERS:
            self.assertEqual(state.fit_input_chunk_ids(self.db, run["id"], layer), ["locked"])

    def test_empty_global_corpus_commits_without_fabricating_generation(self) -> None:
        run = state.schedule_global_rebuild(self.db, self.project_id, reason="empty rebuild")
        state.claim_fit_run(self.db, run["id"])
        state.commit_fit_run(self.db, run["id"], {})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM cluster_generations").fetchone()[0], 0)

    def test_fit_cannot_assign_post_watermark_chunk(self) -> None:
        self.ingest("turn-1", [{"id": "before", "text": "Before."}])
        run = state.schedule_routine_fit(self.db, self.project_id)
        state.claim_fit_run(self.db, run["id"])
        self.ingest("turn-2", [{"id": "after", "text": "After."}])
        with self.assertRaises(state.StateTransitionError):
            state.commit_fit_run(
                self.db,
                run["id"],
                {"span": {"after": {"state": "unlocked", "target_id": "invalid"}}},
            )
        self.assertEqual(
            self.db.execute("SELECT state FROM fit_runs WHERE id = ?", (run["id"],)).fetchone()[0],
            "running",
        )

    def test_generation_swap_supersedes_previous_generation(self) -> None:
        self.ingest("turn-1", [{"id": "one", "text": "One."}])
        first = state.schedule_routine_fit(self.db, self.project_id)
        state.claim_fit_run(self.db, first["id"])
        state.commit_fit_run(self.db, first["id"], {})
        self.ingest("turn-2", [{"id": "two", "text": "Two."}])
        second = state.schedule_routine_fit(self.db, self.project_id)
        state.claim_fit_run(self.db, second["id"])
        state.commit_fit_run(self.db, second["id"], {})
        for layer in state.LAYERS:
            generations = self.db.execute(
                "SELECT state FROM cluster_generations WHERE project_id = ? AND layer = ? ORDER BY epoch",
                (self.project_id, layer),
            ).fetchall()
            self.assertEqual([row["state"] for row in generations], ["superseded", "active"])

    def test_capacity_eviction_selects_complete_oldest_unprotected_turns(self) -> None:
        state.configure_retention(self.db, self.project_id, high_chunks=4, low_chunks=2)
        self.ingest("turn-1", [{"text": "1a"}, {"text": "1b"}])
        self.ingest("turn-2", [{"text": "protected"}], protected=True)
        self.ingest("turn-3", [{"text": "3a"}, {"text": "3b"}])
        planned = state.plan_capacity_eviction(self.db, self.project_id)
        self.assertEqual(planned, ["turn-1", "turn-3"])
        state.mark_turns_evicted(
            self.db,
            self.project_id,
            planned,
            eviction_generation="eviction-1",
        )
        snapshot = state.state_snapshot(self.db, self.project_id)
        self.assertEqual(snapshot["live_chunks"], 1)
        self.assertEqual(snapshot["turns"]["evicted"], 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM evicted_turns").fetchone()[0], 2)

    def test_capacity_eviction_fails_when_protected_turns_prevent_target(self) -> None:
        state.configure_retention(self.db, self.project_id, high_chunks=1, low_chunks=0)
        self.ingest("turn-1", [{"text": "protected a"}, {"text": "protected b"}], protected=True)
        with self.assertRaises(state.StateTransitionError):
            state.plan_capacity_eviction(self.db, self.project_id)

    def test_evicted_content_is_not_requeued(self) -> None:
        self.ingest("turn-1", [{"text": "old"}], content_hash="old-hash")
        state.mark_turns_evicted(
            self.db,
            self.project_id,
            ["turn-1"],
            eviction_generation="eviction-1",
        )
        duplicate = state.queue_turn(
            self.db,
            turn_id="new-id",
            project_id=self.project_id,
            thread_id="thread-test",
            content_hash="old-hash",
        )
        self.assertEqual(duplicate["id"], "turn-1")
        self.assertEqual(duplicate["state"], "evicted")


if __name__ == "__main__":
    unittest.main()
