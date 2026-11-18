#!/usr/bin/env python3
"""Whole-system Thread Tree validation with product-level metrics.

This runner deliberately separates implemented-system scenarios from completion
probes. A stable migration baseline can pass its regression tests while still
failing normative requirements that are not implemented yet.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import platform
import re
import shlex
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
from unittest.mock import patch

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

SCRIPT_ROOT = SCRIPTS_ROOT
SKILL_ROOT = PACKAGE_ROOT
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import stop as stop_hook
import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state
import thread_tree_tools as tools
import thread_tree_vector_index as vector_index
import user_prompt_submit as prompt_hook


@dataclass
class Metric:
    metric_id: str
    label: str
    observed: float | int | str | None
    comparator: str
    target: float | int | str
    unit: str = ""
    gate: str = "hard"
    details: str = ""
    passed: bool = field(init=False)

    def __post_init__(self) -> None:
        if self.observed is None:
            self.passed = False
        elif self.comparator == "==":
            self.passed = self.observed == self.target
        elif self.comparator == "<=":
            self.passed = float(self.observed) <= float(self.target)
        elif self.comparator == ">=":
            self.passed = float(self.observed) >= float(self.target)
        else:
            raise ValueError(f"unknown comparator: {self.comparator}")


@dataclass
class Scenario:
    name: str
    category: str
    areas: list[str]
    metrics: list[Metric] = field(default_factory=list)
    error: str | None = None
    elapsed_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.error is None and all(
            metric.passed or metric.gate == "diagnostic" for metric in self.metrics
        )


def metric(
    metric_id: str,
    label: str,
    observed: float | int | str | None,
    comparator: str,
    target: float | int | str,
    unit: str = "",
    gate: str = "hard",
    details: str = "",
) -> Metric:
    return Metric(metric_id, label, observed, comparator, target, unit, gate, details)


def percentile(values: Iterable[float], fraction: float = 0.95) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_config(
    data_dir: Path,
    *,
    fit_thresholds: dict[str, int] | None = None,
    high_chunks: int = 100_000,
    low_chunks: int = 90_000,
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    value = {
        "ollama_url": "http://127.0.0.1:1",
        "fit_thresholds": fit_thresholds or {"span": 100_000, "specific": 100_000, "broad": 100_000},
        "retention_high_chunks": high_chunks,
        "retention_low_chunks": low_chunks,
    }
    (data_dir / "config.json").write_text(json.dumps(value), encoding="utf-8")


@contextlib.contextmanager
def isolated_runtime(
    *,
    fit_thresholds: dict[str, int] | None = None,
    high_chunks: int = 100_000,
    low_chunks: int = 90_000,
):
    with tempfile.TemporaryDirectory(prefix="thread-tree-validation-") as temporary:
        root = Path(temporary)
        data = root / "data"
        write_config(
            data,
            fit_thresholds=fit_thresholds,
            high_chunks=high_chunks,
            low_chunks=low_chunks,
        )
        fixture_env = {
            "THREAD_HISTORY_TREE_DATA": str(data),
            "CODEX_STATE_DB": str(root / "codex-test-state.sqlite"),
        }
        with patch.dict(os.environ, fixture_env), patch.object(thread_tree, "DEFAULT_SESSION_ROOT", root / "sessions"):
            yield root, data


def activate_projects(*project_roots: Path) -> None:
    """Explicitly opt validation fixtures into the production scope boundary."""

    thread_tree.save_scope_config({
        "schemaVersion": 1,
        "configured": True,
        "paused": False,
        "projects": [
            {
                "path": str(project_root),
                "includeNewChats": True,
                "includedChatIds": [],
                "excludedChatIds": [],
                "backfillExisting": False,
                "activatedAt": None,
            }
            for project_root in project_roots
        ],
        "pausePolicy": {"mode": "manual", "pauseOn": None, "inactivityDays": 30},
        "setupAt": None,
        "updatedAt": None,
    })


def codex_message(message_id: str, role: str, text: str) -> dict[str, Any]:
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


def write_codex_transcript(
    path: Path,
    project_root: Path,
    session_id: str,
    turns: list[tuple[str, str]],
    extra_rows: list[dict[str, Any]] | None = None,
) -> Path:
    rows: list[dict[str, Any]] = [
        {
            "type": "session_meta",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"session_id": session_id, "cwd": str(project_root)},
        }
    ]
    rows.extend(extra_rows or [])
    for index, (user_text, assistant_text) in enumerate(turns):
        rows.append(codex_message(f"{session_id}-u{index}", "user", user_text))
        rows.append(codex_message(f"{session_id}-a{index}", "assistant", assistant_text))
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def write_claude_transcript(
    path: Path,
    project_root: Path,
    session_id: str,
    turns: list[tuple[str, str]],
) -> Path:
    rows: list[dict[str, Any]] = []
    for index, (user_text, assistant_text) in enumerate(turns):
        rows.extend(
            [
                {
                    "type": "user",
                    "sessionId": session_id,
                    "cwd": str(project_root),
                    "uuid": f"{session_id}-u{index}",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {"role": "user", "content": user_text},
                },
                {
                    "type": "assistant",
                    "sessionId": session_id,
                    "cwd": str(project_root),
                    "uuid": f"{session_id}-a{index}",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {"role": "assistant", "content": assistant_text},
                },
            ]
        )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def direct_ingest(
    db: sqlite3.Connection,
    project_id: str,
    turn_id: str,
    chunks: list[dict[str, Any]],
    *,
    thread_id: str = "thread",
    protected: bool = False,
    transcript_path: str | None = None,
) -> list[dict[str, Any]]:
    state.queue_turn(
        db,
        turn_id=turn_id,
        project_id=project_id,
        thread_id=thread_id,
        content_hash=f"hash-{turn_id}",
        protected=protected,
        transcript_path=transcript_path,
    )
    claimed = state.claim_next_turn(db, project_id)
    if claimed is None or claimed["id"] != turn_id:
        raise RuntimeError(f"failed to claim {turn_id}: {claimed}")
    return state.complete_turn_ingestion(db, turn_id, chunks)


def db_snapshot(db: sqlite3.Connection, project_id: str) -> dict[str, int]:
    return {
        "chunks": db.execute("SELECT COUNT(*) FROM turn_chunks WHERE project_id=?", (project_id,)).fetchone()[0],
        "fts": db.execute("SELECT COUNT(*) FROM turn_chunks_fts WHERE project_id=?", (project_id,)).fetchone()[0],
        "nodes": db.execute("SELECT COUNT(*) FROM semantic_nodes WHERE project_id=?", (project_id,)).fetchone()[0],
        "edges": db.execute(
            "SELECT COUNT(*) FROM semantic_edges WHERE child_id IN (SELECT id FROM semantic_nodes WHERE project_id=?)",
            (project_id,),
        ).fetchone()[0],
        "debt_events": db.execute("SELECT COUNT(*) FROM fit_debt_events WHERE project_id=?", (project_id,)).fetchone()[0],
        "staged": db.execute("SELECT COUNT(*) FROM staged_user_prompts WHERE project_id=?", (project_id,)).fetchone()[0],
    }


def run_scenario(name: str, category: str, areas: list[str], fn: Callable[[], list[Metric]]) -> Scenario:
    result = Scenario(name=name, category=category, areas=areas)
    started = time.perf_counter()
    try:
        result.metrics = fn()
    except Exception as error:  # keep the remainder of the system report running
        result.error = f"{type(error).__name__}: {error}"
    result.elapsed_ms = (time.perf_counter() - started) * 1000
    return result


def regression_scenario() -> list[Metric]:
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        str(SCRIPT_ROOT),
        "-p",
        "test_*.py",
    ]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    match = re.search(r"Ran (\d+) tests?", completed.stdout)
    count = int(match.group(1)) if match else 0
    return [
        metric(
            "REG-01", "Existing regression suite exits successfully", completed.returncode, "==", 0,
            details=completed.stdout[-12_000:] if completed.returncode else "",
        ),
        metric("REG-02", "Regression tests discovered", count, ">=", 42, "tests",
               details="\n".join(completed.stdout.splitlines()[-3:])),
    ]


def cross_client_scope_scenario() -> list[Metric]:
    with isolated_runtime() as (root, _):
        project_a, project_b = root / "project-a", root / "project-b"
        project_a.mkdir()
        project_b.mkdir()
        project_a_ids: set[str] = set()
        for index in range(12):
            transcript = write_codex_transcript(
                root / f"codex-{index}.jsonl",
                project_a,
                f"codex-{index}",
                [(f"Plan alphaartifact{index} project memory.", f"Alphaartifact{index} remains local and grounded.")],
            )
            project_a_ids.add(pipeline.enqueue_transcript(transcript)["project_id"])
        for index in range(12):
            transcript = write_claude_transcript(
                root / f"claude-{index}.jsonl",
                project_a,
                f"claude-{index}",
                [(f"Plan betaartifact{index} project memory.", f"Betaartifact{index} remains local and grounded.")],
            )
            project_a_ids.add(pipeline.enqueue_transcript(transcript)["project_id"])
        other = write_codex_transcript(
            root / "other.jsonl",
            project_b,
            "other-chat",
            [("Store isolatedartifact only in project B.", "Isolatedartifact belongs only to project B.")],
        )
        project_b_id = pipeline.enqueue_transcript(other)["project_id"]
        project_a_id = next(iter(project_a_ids))
        result = pipeline.process_project(project_a_id)
        pipeline.process_project(project_b_id)
        payload = pipeline.project_tree_payload(project_a_id)
        leak_hits = pipeline.search_project(project_a_id, "isolatedartifact", limit=20)
        db = thread_tree.connect_db()
        thread_count = db.execute(
            "SELECT COUNT(DISTINCT thread_id) FROM turn_ingestion WHERE project_id=?",
            (project_a_id,),
        ).fetchone()[0]
        verified = []
        for hit in pipeline.search_project(project_a_id, "alphaartifact5 betaartifact5", limit=20):
            source_ids = json.loads(hit["source_message_ids"])
            verified.append(pipeline._source_ids_verified(hit["transcript_path"], source_ids))
        db.close()
        return [
            metric("SYS-06", "Codex and Claude resolve to one project", len(project_a_ids), "==", 1),
            metric("SYS-07", "Different roots remain isolated", int(project_a_id != project_b_id), "==", 1),
            metric("XC-THREADS", "All cross-client sessions were ingested", thread_count, "==", 24, "threads"),
            metric("XC-TURNS", "All cross-client turns were processed", result["processed_turns"], "==", 24, "turns"),
            metric("RET-05", "Cross-project retrieval leakage", len(leak_hits), "==", 0, "hits"),
            metric("RET-04", "Cross-client source grounding", sum(verified), "==", len(verified), "verified hits"),
            metric("SYS-08", "Viewer project roots", sum(node["kind"] == "root" for node in payload["nodes"]), "==", 1),
        ]


def atomicity_scenario() -> list[Metric]:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    state.initialize_state_schema(db)
    project_id = "atomic-project"
    state.ensure_project(db, project_id, "/tmp/atomic-project", fit_thresholds={layer: 100 for layer in state.LAYERS})
    state.queue_turn(db, turn_id="atomic-turn", project_id=project_id, thread_id="atomic-thread", content_hash="atomic")
    state.claim_next_turn(db, project_id)
    failed = 0
    try:
        state.complete_turn_ingestion(
            db,
            "atomic-turn",
            [{"id": "valid-first", "text": "valid first atomic chunk"}, {"id": "invalid-second", "text": ""}],
        )
    except ValueError:
        failed = 1
    residue = {
        "chunks": db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0],
        "fts": db.execute("SELECT COUNT(*) FROM turn_chunks_fts").fetchone()[0],
        "debt": db.execute("SELECT COUNT(*) FROM fit_debt_events").fetchone()[0],
    }
    state.complete_turn_ingestion(
        db,
        "atomic-turn",
        [{"id": "retry-one", "text": "retry first atomic chunk"}, {"id": "retry-two", "text": "retry second atomic chunk"}],
    )
    indexed = db.execute("SELECT state FROM turn_ingestion WHERE id='atomic-turn'").fetchone()[0]
    final_chunks = db.execute("SELECT COUNT(*) FROM turn_chunks").fetchone()[0]
    before_publish_states = [tuple(row) for row in db.execute(
        "SELECT chunk_id, layer, state, target_id, generation_id FROM chunk_layer_states ORDER BY chunk_id, layer"
    )]
    fit_run = state.schedule_global_rebuild(db, project_id, reason="atomic publication injection")
    publish_failure_observed = 0
    try:
        with patch.object(pipeline, "_materialize_layer", side_effect=RuntimeError("injected publication failure")):
            pipeline.run_fit(db, fit_run["id"])
    except RuntimeError:
        publish_failure_observed = 1
    after_publish_states = [tuple(row) for row in db.execute(
        "SELECT chunk_id, layer, state, target_id, generation_id FROM chunk_layer_states ORDER BY chunk_id, layer"
    )]
    publication_residue = sum(
        db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("semantic_nodes", "semantic_edges", "cluster_generations", "project_active_tree")
    )
    atomic_publication_rollback = int(
        publish_failure_observed
        and before_publish_states == after_publish_states
        and publication_residue == 0
        and db.execute("SELECT state FROM fit_runs WHERE id=?", (fit_run["id"],)).fetchone()[0] == "failed"
    )
    db.close()
    return [
        metric("COR-03A", "Injected failure was observed", failed, "==", 1),
        metric("COR-03B", "Atomic failure chunk residue", residue["chunks"], "==", 0, "chunks"),
        metric("COR-03C", "Atomic failure FTS residue", residue["fts"], "==", 0, "rows"),
        metric("COR-03D", "Atomic failure debt residue", residue["debt"], "==", 0, "events"),
        metric("COR-RECOVERY", "Same processing turn can complete after retry", int(indexed == "indexed" and final_chunks == 2), "==", 1),
        metric("COR-04", "Failed tree publication leaves prior graph and chunk states intact", atomic_publication_rollback, "==", 1),
    ]


def concurrency_scenario() -> list[Metric]:
    with isolated_runtime() as (root, _):
        project_root = root / "project"
        project_root.mkdir()
        project_id = state.project_id_for(str(project_root))
        db = thread_tree.connect_db()
        state.ensure_project(db, project_id, str(project_root), fit_thresholds={layer: 100_000 for layer in state.LAYERS})
        for index in range(200):
            state.queue_turn(
                db,
                turn_id=f"turn-{index:04d}",
                project_id=project_id,
                thread_id=f"thread-{index % 7}",
                content_hash=f"content-{index:04d}",
            )
        db.close()

        claimed: list[str] = []
        errors: list[str] = []
        guard = threading.Lock()

        def worker() -> None:
            connection = thread_tree.connect_db()
            try:
                while True:
                    row = state.claim_next_turn(connection, project_id)
                    if row is None:
                        break
                    with guard:
                        claimed.append(str(row["id"]))
            except Exception as error:
                with guard:
                    errors.append(str(error))
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(worker) for _ in range(12)]
            for future in futures:
                future.result()

        def duplicate_delivery(index: int) -> None:
            connection = thread_tree.connect_db()
            try:
                state.queue_turn(
                    connection,
                    turn_id=f"duplicate-{index}",
                    project_id=project_id,
                    thread_id="duplicate-thread",
                    content_hash="same-duplicate-content",
                )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(duplicate_delivery, range(50)))
        db = thread_tree.connect_db()
        duplicate_rows = db.execute(
            "SELECT COUNT(*) FROM turn_ingestion WHERE project_id=? AND thread_id='duplicate-thread'",
            (project_id,),
        ).fetchone()[0]
        db.close()
        return [
            metric("COR-04A", "Concurrent worker claims", len(claimed), "==", 200, "claims"),
            metric("COR-04B", "Unique concurrent worker claims", len(set(claimed)), "==", 200, "turns"),
            metric("COR-04C", "Worker concurrency errors", len(errors), "==", 0, "errors", details="; ".join(errors[:3])),
            metric("COR-02", "Concurrent duplicate deliveries create one row", duplicate_rows, "==", 1, "rows"),
        ]


def watermark_and_failure_scenario() -> list[Metric]:
    with isolated_runtime(fit_thresholds={layer: 3 for layer in state.LAYERS}) as (root, _):
        project_root = root / "project"
        project_root.mkdir()
        project_id = state.project_id_for(str(project_root))
        db = thread_tree.connect_db()
        state.ensure_project(db, project_id, str(project_root), fit_thresholds={layer: 3 for layer in state.LAYERS})
        direct_ingest(
            db,
            project_id,
            "before-turn",
            [{"id": f"before-{index}", "text": f"before watermark evidence {index}"} for index in range(3)],
        )
        run = state.schedule_routine_fit(db, project_id)
        if run is None:
            raise RuntimeError("fit was not scheduled")
        direct_ingest(
            db,
            project_id,
            "after-turn",
            [
                {"id": "after-watermark", "text": "postwatermark sentinel evidence"},
                {"id": "after-watermark-2", "text": "second postwatermark debt item"},
                {"id": "after-watermark-3", "text": "third postwatermark debt item"},
            ],
        )
        late_seq = db.execute("SELECT seq FROM turn_chunks WHERE id='after-watermark'").fetchone()[0]
        state.claim_fit_run(db, run["id"])
        state.commit_fit_run(db, run["id"], assignments={})
        unconsumed_late = db.execute(
            "SELECT COUNT(*) FROM fit_debt_events WHERE chunk_id='after-watermark' AND consumed_by IS NULL"
        ).fetchone()[0]
        late_state = db.execute(
            "SELECT state FROM chunk_layer_states WHERE chunk_id='after-watermark' AND layer='span'"
        ).fetchone()[0]
        generation_count = db.execute("SELECT COUNT(*) FROM cluster_generations WHERE state='active'").fetchone()[0]
        next_run = state.schedule_routine_fit(db, project_id)
        state.claim_fit_run(db, next_run["id"])
        debt_before_failure = sum(row["debt_count"] for row in state.debt_status(db, project_id))
        state.fail_fit_run(db, next_run["id"], "injected provider failure")
        debt_after_failure = sum(row["debt_count"] for row in state.debt_status(db, project_id))
        generations_after_failure = db.execute("SELECT COUNT(*) FROM cluster_generations WHERE state='active'").fetchone()[0]
        db.close()
        hits = pipeline.search_project(project_id, "postwatermark sentinel", limit=5)
        return [
            metric("COR-05A", "Fit watermark precedes late chunk", int(run["chunk_watermark"] < late_seq), "==", 1),
            metric("COR-05B", "Post-watermark debt remains unconsumed", unconsumed_late, "==", 3, "events"),
            metric("COR-05C", "Post-watermark span remains unresolved", late_state, "==", "unassigned"),
            metric("SR-01", "Post-watermark frontier remains searchable", int(any(hit["id"] == "after-watermark" for hit in hits)), "==", 1),
            metric("COR-06A", "Failed fit consumes no debt", debt_after_failure, "==", debt_before_failure, "events"),
            metric("COR-06B", "Failed fit activates no generation", generations_after_failure, "==", generation_count, "generations"),
        ]


def hierarchy_and_viewer_scenario() -> list[Metric]:
    with isolated_runtime(fit_thresholds={layer: 1 for layer in state.LAYERS}) as (root, _):
        project_root = root / "project"
        project_root.mkdir()
        project_id = state.project_id_for(str(project_root))
        db = thread_tree.connect_db()
        state.ensure_project(db, project_id, str(project_root), fit_thresholds={layer: 1 for layer in state.LAYERS})
        topics = {
            "alpha": "authn sessioncookie oauthguard alphamarker",
            "beta": "postgres queryplanner btreeindex betamarker",
            "gamma": "canvas viewport treelayout gammamarker",
        }
        labeled_chunks: dict[str, str] = {}
        for topic, words in topics.items():
            chunks = []
            for index in range(24):
                chunk_id = f"{topic}-{index:02d}"
                labeled_chunks[chunk_id] = topic
                chunks.append({"id": chunk_id, "text": f"{words} {topic}detail{index}"})
            direct_ingest(db, project_id, f"turn-{topic}", chunks, thread_id=f"thread-{topic}")
        run = state.schedule_global_rebuild(db, project_id, reason="system hierarchy validation")
        pipeline.run_fit(db, run["id"])

        duplicate_parents = db.execute(
            "SELECT COUNT(*) FROM (SELECT child_id FROM semantic_edges WHERE primary_edge=1 GROUP BY child_id HAVING COUNT(*)>1)"
        ).fetchone()[0]
        orphan_spans = db.execute(
            """SELECT COUNT(*) FROM semantic_nodes n WHERE n.project_id=? AND n.layer='span'
               AND NOT EXISTS (SELECT 1 FROM semantic_edges e WHERE e.child_id=n.id AND e.primary_edge=1)""",
            (project_id,),
        ).fetchone()[0]
        orphan_specific = db.execute(
            """SELECT COUNT(*) FROM semantic_nodes n WHERE n.project_id=? AND n.layer='specific'
               AND NOT EXISTS (SELECT 1 FROM semantic_edges e WHERE e.child_id=n.id AND e.primary_edge=1)""",
            (project_id,),
        ).fetchone()[0]
        multi_span = db.execute(
            """SELECT COUNT(*) FROM (
                   SELECT m.chunk_id FROM semantic_node_memberships m JOIN semantic_nodes n ON n.id=m.node_id
                   WHERE n.project_id=? AND n.layer='span' AND n.lifecycle!='retired'
                   GROUP BY m.chunk_id HAVING COUNT(*)>1)""",
            (project_id,),
        ).fetchone()[0]
        span_rows = db.execute(
            """SELECT n.id, m.chunk_id FROM semantic_nodes n JOIN semantic_node_memberships m ON m.node_id=n.id
               WHERE n.project_id=? AND n.layer='span' AND n.lifecycle!='retired'""",
            (project_id,),
        ).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in span_rows:
            grouped.setdefault(row["id"], []).append(labeled_chunks[row["chunk_id"]])
        purities = []
        for values in grouped.values():
            purities.append(max(values.count(value) for value in set(values)) / len(values))
        macro_purity = statistics.mean(purities) if purities else 0.0
        frontier_count = len(state.frontier_chunks(db, project_id))
        total_chunks = db.execute("SELECT COUNT(*) FROM turn_chunks WHERE project_id=?", (project_id,)).fetchone()[0]
        db.close()

        payload = pipeline.project_tree_payload(project_id)
        node_ids = {node["id"] for node in payload["nodes"]}
        dangling = sum(
            edge["child_id"] not in node_ids or edge["parent_id"] not in node_ids
            for edge in payload["edges"]
        )
        primary_counts: dict[str, int] = {}
        for edge in payload["edges"]:
            if edge["relation"] == "primary":
                primary_counts[edge["child_id"]] = primary_counts.get(edge["child_id"], 0) + 1
        viewer_multi_parent = sum(value > 1 for value in primary_counts.values())
        return [
            metric("HIE-01A", "Duplicate structural parents", duplicate_parents, "==", 0),
            metric("HIE-01B", "Orphan spans", orphan_spans, "==", 0),
            metric("HIE-01C", "Orphan specific topics", orphan_specific, "==", 0),
            metric("HIE-03", "Chunks with multiple span memberships", multi_span, "==", 0),
            metric("HIE-09", "Synthetic span macro purity", round(macro_purity, 4), ">=", 0.85, "ratio", "quality"),
            metric("HIE-10", "Post-fit frontier rate", round(frontier_count / total_chunks, 4), "<=", 0.20, "ratio", "quality"),
            metric("SYS-08", "Viewer roots", sum(node["kind"] == "root" for node in payload["nodes"]), "==", 1),
            metric("SYS-09", "Viewer dangling edges", dangling, "==", 0),
            metric("SYS-10", "Viewer primary-parent violations", viewer_multi_parent, "==", 0),
            metric("SYS-11", "Viewer default bind is local-only", thread_tree.build_parser().parse_args(["serve"]).host, "==", "127.0.0.1"),
            metric("UI-READ-01", "Viewer exposes no semantic-node mutation API", int(not hasattr(thread_tree, "apply_correction")), "==", 1),
        ]


def retrieval_scenario() -> list[Metric]:
    with isolated_runtime() as (root, _):
        project_root = root / "project"
        other_root = root / "other-project"
        project_root.mkdir()
        other_root.mkdir()
        activate_projects(project_root)
        expected_turns: dict[str, str] = {}
        for index in range(30):
            marker = f"retrievalartifact{index:02d}"
            transcript = write_codex_transcript(
                root / f"retrieval-{index}.jsonl",
                project_root,
                f"retrieval-thread-{index}",
                [
                    (
                        f"Decide how {marker} should preserve exact source context across the project.",
                        f"The decision for {marker} is to retain verified source identifiers and bounded evidence.",
                    )
                ],
            )
            queued = pipeline.enqueue_transcript(transcript)
            expected_turns[marker] = queued["turn_ids"][0]
        other = write_codex_transcript(
            root / "retrieval-other.jsonl",
            other_root,
            "other-thread",
            [("Store foreignartifact in the other project.", "Foreignartifact must never leak across projects.")],
        )
        other_project = pipeline.enqueue_transcript(other)["project_id"]
        project_id = state.project_id_for(str(project_root))
        pipeline.process_project(project_id)
        pipeline.process_project(other_project)

        reciprocal_ranks: list[float] = []
        recalls: list[int] = []
        grounding: list[int] = []
        latencies: list[float] = []
        for marker, expected_turn in expected_turns.items():
            started = time.perf_counter()
            hits = pipeline.search_project(project_id, marker, limit=5)
            latencies.append((time.perf_counter() - started) * 1000)
            ranks = [index + 1 for index, hit in enumerate(hits) if hit["turn_id"] == expected_turn]
            recalls.append(int(bool(ranks)))
            reciprocal_ranks.append(1.0 / ranks[0] if ranks else 0.0)
            for hit in hits:
                source_ids = json.loads(hit["source_message_ids"])
                grounding.append(int(pipeline._source_ids_verified(hit["transcript_path"], source_ids)))

        db = thread_tree.connect_db()
        before = db_snapshot(db, project_id)
        db.close()
        tool_result = tools.search_project_history(
            "retrievalartifact07 exact source context",
            evidence_needed="The prior decision and verified source.",
            project_root=str(project_root),
            max_results=5,
        )
        excluded = tool_result["evidence"][0]["chunk_id"] if tool_result["evidence"] else "missing"
        excluded_result = tools.search_project_history(
            "retrievalartifact07",
            project_root=str(project_root),
            exclude_chunk_ids=[excluded],
            max_results=5,
        )
        unknown = tools.search_project_history("zzzxqvnohistoricalevidence", project_root=str(project_root), max_results=5)
        query_only = "transientquerysentinel"
        tools.search_project_history(query_only, project_root=str(project_root), max_results=5)
        db = thread_tree.connect_db()
        after = db_snapshot(db, project_id)
        persisted_query = db.execute(
            """SELECT
               (SELECT COUNT(*) FROM turn_chunks WHERE project_id=? AND text LIKE ?) +
               (SELECT COUNT(*) FROM semantic_nodes WHERE project_id=? AND (title LIKE ? OR summary LIKE ?))""",
            (project_id, f"%{query_only}%", project_id, f"%{query_only}%", f"%{query_only}%"),
        ).fetchone()[0]
        db.close()
        foreign_hits = pipeline.search_project(project_id, "foreignartifact", limit=10)
        evidence_ids = [item["chunk_id"] for item in tool_result["evidence"]]
        citation_metadata_complete = all(
            item["source"].get("chat_title")
            and item["source"].get("timestamp")
            and item["source"].get("citation_label")
            and "url" not in item["source"]
            for item in tool_result["evidence"]
        )
        citation_sources_resolve = all(
            (detail := thread_tree.chunk_source_detail(item["chunk_id"])) is not None
            and detail["chunk_id"] == item["chunk_id"]
            and detail["thread_id"] == item["thread_id"]
            and detail["turn_id"] == item["turn_id"]
            and detail["verified"]
            for item in tool_result["evidence"]
        )
        return [
            metric("RET-01", "Exact-term Recall@5", round(statistics.mean(recalls), 4), ">=", 0.99, "ratio", "quality"),
            metric("RET-03", "Mean reciprocal rank", round(statistics.mean(reciprocal_ranks), 4), ">=", 0.90, "ratio", "quality"),
            metric("RET-04", "Source-grounding accuracy", round(statistics.mean(grounding), 4), "==", 1.0, "ratio"),
            metric("RET-05", "Project leakage", len(foreign_hits), "==", 0, "hits"),
            metric("RET-06", "Transient query persistence", persisted_query, "==", 0, "records"),
            metric("RET-07", "Duplicate evidence chunks", len(evidence_ids) - len(set(evidence_ids)), "==", 0, "duplicates"),
            metric("RET-08", "Excluded chunk returned", int(excluded in {item["chunk_id"] for item in excluded_result["evidence"]}), "==", 0),
            metric("RET-09", "Global lookups per tool call", tool_result["trace"]["global_lookup_count"], "==", 1),
            metric("RET-10", "Negative query reports uncovered", int(unknown["status"] == "uncovered"), "==", 1),
            metric("RET-14", "Retrieval is read-only", int(before == after), "==", 1),
            metric("RET-17", "Citation metadata coverage", int(citation_metadata_complete), "==", 1),
            metric("RET-18", "Citation source resolution", int(citation_sources_resolve), "==", 1),
            metric("UX-03", "Warm lexical retrieval p95", round(percentile(latencies), 3), "<=", 100.0, "ms", "performance"),
            metric("UX-08", "Tool result respects max_results", len(tool_result["evidence"]), "<=", 5, "chunks"),
        ]


def hook_latency_and_privacy_scenario() -> list[Metric]:
    with isolated_runtime() as (root, _):
        project_root = root / "project"
        project_root.mkdir()
        activate_projects(project_root)
        prompt_latencies: list[float] = []
        for index in range(40):
            event = {
                "session_id": "hook-thread",
                "turn_id": f"hook-turn-{index}",
                "cwd": str(project_root),
                "prompt": f"Stage exact prompt {index} without indexing it.",
            }
            started = time.perf_counter()
            with patch.object(prompt_hook.sys, "stdin", io.StringIO(json.dumps(event))), contextlib.redirect_stdout(io.StringIO()):
                prompt_hook.main()
            prompt_latencies.append((time.perf_counter() - started) * 1000)

        secret = "SUPERSECRET-CREDENTIAL-MUST-NOT-INDEX"
        extra_rows = [
            {"type": "reasoning", "encrypted_content": secret},
            {"type": "tool_result", "payload": {"token": secret}},
            codex_message("ignored-env", "user", "<environment_context>" + secret + "</environment_context>"),
        ]
        transcript = write_codex_transcript(
            root / "private.jsonl",
            project_root,
            "private-thread",
            [("Index only this ordinary privacy decision.", "The privacy decision excludes unsupported payloads.")],
            extra_rows=extra_rows,
        )
        original_hash = sha256_file(transcript)
        stop_latencies: list[float] = []
        stop_event = {"session_id": "private-thread", "cwd": str(project_root), "transcript_path": str(transcript)}
        for _ in range(20):
            started = time.perf_counter()
            with patch.object(stop_hook.sys, "stdin", io.StringIO(json.dumps(stop_event))), \
                 patch.object(stop_hook.subprocess, "Popen"), contextlib.redirect_stdout(io.StringIO()):
                stop_hook.main()
            stop_latencies.append((time.perf_counter() - started) * 1000)
        project_id = state.project_id_for(str(project_root))
        pipeline.process_project(project_id)
        db = thread_tree.connect_db()
        sensitive_rows = db.execute(
            "SELECT COUNT(*) FROM turn_chunks WHERE project_id=? AND text LIKE ?",
            (project_id, f"%{secret}%"),
        ).fetchone()[0]
        private_turns = db.execute(
            "SELECT COUNT(*) FROM turn_ingestion WHERE project_id=? AND thread_id='private-thread'",
            (project_id,),
        ).fetchone()[0]
        raw_stage_chunks = db.execute(
            "SELECT COUNT(*) FROM turn_chunks WHERE project_id=? AND text LIKE '%Stage exact prompt%'",
            (project_id,),
        ).fetchone()[0]
        db.close()
        return [
            metric("UX-01", "UserPromptSubmit p95", round(percentile(prompt_latencies), 3), "<=", 25.0, "ms", "performance"),
            metric("UX-02", "Stop enqueue p95", round(percentile(stop_latencies), 3), "<=", 75.0, "ms", "performance"),
            metric("UX-07", "Duplicate Stop delivery creates one canonical turn", private_turns, "==", 1, "turns"),
            metric("QP-RAW", "Raw stages are not searchable chunks", raw_stage_chunks, "==", 0, "chunks"),
            metric("SYS-05", "Unsupported sensitive payloads indexed", sensitive_rows, "==", 0, "chunks"),
            metric("COR-07", "Transcript remains byte-identical", sha256_file(transcript), "==", original_hash),
        ]


def retention_scenario() -> list[Metric]:
    with isolated_runtime(high_chunks=20, low_chunks=10) as (root, _):
        project_root = root / "project"
        project_root.mkdir()
        activate_projects(project_root)
        project_id = state.project_id_for(str(project_root))
        db = thread_tree.connect_db()
        state.ensure_project(
            db,
            project_id,
            str(project_root),
            fit_thresholds={layer: 100_000 for layer in state.LAYERS},
            high_chunks=20,
            low_chunks=10,
        )
        transcript_hashes: dict[Path, str] = {}
        for index in range(14):
            transcript = root / f"retention-{index}.jsonl"
            transcript.write_text(json.dumps({"turn": index, "evidence": f"retentionartifact{index}"}), encoding="utf-8")
            transcript_hashes[transcript] = sha256_file(transcript)
            direct_ingest(
                db,
                project_id,
                f"retention-turn-{index:02d}",
                [
                    {"id": f"retention-{index}-a", "text": f"retentionartifact{index} first evidence"},
                    {"id": f"retention-{index}-b", "text": f"retentionartifact{index} second evidence"},
                ],
                thread_id="retention-thread",
                protected=index < 2,
                transcript_path=str(transcript),
            )
        plan = state.plan_capacity_eviction(db, project_id)
        protected_selected = sum(turn_id in {"retention-turn-00", "retention-turn-01"} for turn_id in plan)
        state.mark_turns_evicted(db, project_id, plan, eviction_generation="retention-validation")
        visible_evicted = 0
        for index in range(14):
            if f"retention-turn-{index:02d}" in plan:
                visible_evicted += len(pipeline.search_project(project_id, f"retentionartifact{index}", limit=10))
        run = state.schedule_global_rebuild(db, project_id, kind="capacity_rebuild", reason="system retention validation")
        pipeline.run_fit(db, run["id"])
        with db:
            db.executemany(
                "DELETE FROM turn_chunks_fts WHERE chunk_id IN (SELECT id FROM turn_chunks WHERE turn_id=?)",
                [(turn_id,) for turn_id in plan],
            )
            db.executemany("DELETE FROM turn_chunks WHERE turn_id=? AND evicted=1", [(turn_id,) for turn_id in plan])
        live_chunks = db.execute(
            "SELECT COUNT(*) FROM turn_chunks WHERE project_id=? AND evicted=0", (project_id,)
        ).fetchone()[0]
        partial_evictions = db.execute(
            """SELECT COUNT(*) FROM turn_ingestion t WHERE t.project_id=? AND t.state='evicted'
               AND EXISTS (SELECT 1 FROM turn_chunks c WHERE c.turn_id=t.id)""",
            (project_id,),
        ).fetchone()[0]
        tombstone_columns = {row[1] for row in db.execute("PRAGMA table_info(evicted_turns)")}
        content_columns = tombstone_columns & {"text", "content", "prompt", "summary", "embedding"}
        db.close()
        mutated_sources = sum(sha256_file(path) != digest for path, digest in transcript_hashes.items())
        return [
            metric("SYS-01", "Retention reaches low watermark", live_chunks, "<=", 10, "chunks"),
            metric("SYS-02", "Partially retained evicted turns", partial_evictions, "==", 0, "turns"),
            metric("SYS-03", "Protected turns selected", protected_selected, "==", 0, "turns"),
            metric("SYS-04", "Content-bearing tombstone columns", len(content_columns), "==", 0, "columns"),
            metric("COR-08", "Evicted chunks visible before physical cleanup", visible_evicted, "==", 0, "hits"),
            metric("COR-07", "Source transcripts mutated by retention", mutated_sources, "==", 0, "files"),
        ]


def scale_scenario(chunk_count: int) -> list[Metric]:
    with isolated_runtime() as (root, data_dir):
        project_root = root / "project"
        project_root.mkdir()
        activate_projects(project_root)
        project_id = state.project_id_for(str(project_root))
        db = thread_tree.connect_db()
        state.ensure_project(db, project_id, str(project_root), fit_thresholds={layer: chunk_count * 10 for layer in state.LAYERS})
        chunks = []
        for index in range(chunk_count):
            chunks.append(
                {
                    "id": f"scale-{index:05d}",
                    "text": f"scalemark{index:05d} fallback retrieval performance evidence",
                    "layer_states": {
                        layer: {"state": "locked", "target_id": f"locked-{layer}-{index % 10}", "membership_confidence": 1.0}
                        for layer in state.LAYERS
                    },
                }
            )
        tracemalloc.start()
        started = time.perf_counter()
        direct_ingest(db, project_id, "scale-turn", chunks, thread_id="scale-thread")
        ingestion_seconds = time.perf_counter() - started
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        db.close()

        sample_indexes = [round(index * (chunk_count - 1) / 99) for index in range(100)]
        latencies: list[float] = []
        recall: list[int] = []
        for index in sample_indexes:
            started = time.perf_counter()
            hits = pipeline.search_project(project_id, f"scalemark{index:05d}", limit=5)
            latencies.append((time.perf_counter() - started) * 1000)
            recall.append(int(any(hit["id"] == f"scale-{index:05d}" for hit in hits)))
        database_bytes = sum(
            path.stat().st_size
            for path in data_dir.glob("index.sqlite3*")
            if path.is_file()
        )
        return [
            metric("SCALE-N", "Retained fallback chunks exercised", chunk_count, ">=", 10_000, "chunks", "performance"),
            metric("UX-06", "Fallback ingestion throughput", round(chunk_count / ingestion_seconds, 2), ">=", 100.0, "chunks/s", "performance"),
            metric("RET-01-SCALE", "Scale exact-term Recall@5", round(statistics.mean(recall), 4), ">=", 0.99, "ratio", "quality"),
            metric("UX-03-SCALE", f"{chunk_count:,}-chunk warm lexical retrieval p95",
                   round(percentile(latencies), 3), "<=", 100.0, "ms", "performance"),
            metric("SYS-12", "Database bytes per retained chunk", round(database_bytes / chunk_count, 2), "<=", 16 * 1024, "bytes/chunk", "performance"),
            metric("SYS-13", "Peak Python allocation", round(peak_bytes / (1024 * 1024), 2), "<=", 512.0, "MiB", "performance"),
        ]


def plugin_mcp_scenario() -> list[Metric]:
    mcp = json.loads((SKILL_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    launcher = mcp["mcpServers"]["thread-tree"]
    args = shlex.split(launcher["args"][1].split("exec ", 1)[1])
    shared_native_launcher = (
        (SKILL_ROOT / ".codex-plugin/plugin.json").is_file()
        and (SKILL_ROOT / ".claude-plugin/plugin.json").is_file()
        and not (SKILL_ROOT / "plugin.json").exists()
        and not (SKILL_ROOT / "mcp.json").exists()
        and launcher["cwd"] == "."
        and launcher["args"][-1] == "${CLAUDE_PLUGIN_ROOT}"
        and args[-2:] == ["server/thread_tree_mcp.py", "stdio"]
    )
    started = time.perf_counter()
    completed = subprocess.run(
        [*args[:2], "--offline", *args[2:-2], str(SKILL_ROOT / "server" / "smoke_mcp.py")],
        cwd=SKILL_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    cold_ms = (time.perf_counter() - started) * 1000
    return [
        metric("XC-001", "Codex and Claude use the shared native MCP launcher", int(shared_native_launcher), "==", 1),
        metric("MCP-LIST", "MCP initialize and tools/list succeeds", completed.returncode, "==", 0, details=completed.stdout[-500:]),
        metric("UX-05", "Cold MCP tool-list availability", round(cold_ms, 3), "<=", 2000.0, "ms", "performance"),
    ]


def diagnostic_shape_scenario() -> list[Metric]:
    sizes = [64, 128, 256, 512]
    timings: dict[int, float] = {}
    for size in sizes:
        rows = [
            {"id": f"diag-{index}", "text": f"diagnostic fallback cluster token{index} shared"}
            for index in range(size)
        ]
        samples: list[float] = []
        for _ in range(3):
            started = time.perf_counter()
            pipeline._components(rows, 2.0)
            samples.append((time.perf_counter() - started) * 1000)
        timings[size] = statistics.median(samples)
    scaling_exponent = math.log(timings[512] / timings[256], 2) if timings[256] > 0 else 0.0
    live_chunks = 2383
    legacy_pair_comparisons = 3 * live_chunks * (live_chunks - 1) // 2

    with isolated_runtime(fit_thresholds={layer: 10_000 for layer in state.LAYERS}) as (root, _):
        project_root = root / "project"
        project_root.mkdir()
        activate_projects(project_root)
        project_id = state.project_id_for(str(project_root))
        db = thread_tree.connect_db()
        state.ensure_project(
            db,
            project_id,
            str(project_root),
            fit_thresholds={layer: 10_000 for layer in state.LAYERS},
        )
        for index in range(64):
            direct_ingest(
                db,
                project_id,
                f"diag-distractor-turn-{index}",
                [{"id": f"diag-distractor-{index}", "text": "topic candidates lookup chunks broad topic search workflow"}],
            )
        direct_ingest(
            db,
            project_id,
            "diag-gold-turn",
            [
                {
                    "id": "diag-gold",
                    "text": "USER: Let's stick with the term searchable representation candidate so it is not confused with topic node layers.",
                }
            ],
        )
        direct_ingest(
            db,
            project_id,
            "diag-query-echo-turn",
            [
                {
                    "id": "diag-query-echo",
                    "text": "USER: What exact term replaced topic candidates in the earlier project conversation?",
                }
            ],
        )
        fit_run = state.schedule_global_rebuild(db, project_id, reason="diagnostic phase and lineage probe")
        pipeline.run_fit(db, fit_run["id"])
        phase_rows = db.execute(
            "SELECT rowid AS phase_seq, * FROM fit_run_phase_metrics WHERE run_id=?",
            (fit_run["id"],),
        ).fetchall()
        upper_input_units = [
            json.loads(row["details"] or "{}").get("input_unit")
            for row in phase_rows
            if row["phase"] == "load_input" and row["layer"] in {"specific", "broad"}
        ]
        raw_upper_input_fraction = (
            sum(unit == "chunk" for unit in upper_input_units) / len(upper_input_units)
            if upper_input_units else 1.0
        )
        completed_phases = sum(row["status"] == "completed" for row in phase_rows)
        unfinished_phases = sum(row["status"] != "completed" for row in phase_rows)
        recorded_pairs = sum(int(row["estimated_pair_comparisons"] or 0) for row in phase_rows)
        fixture_chunks = db.execute(
            "SELECT COUNT(*) FROM turn_chunks WHERE project_id=? AND evicted=0",
            (project_id,),
        ).fetchone()[0]
        legacy_fixture_pairs = 3 * fixture_chunks * (fixture_chunks - 1) // 2
        pair_reduction = 1.0 - (recorded_pairs / legacy_fixture_pairs) if legacy_fixture_pairs else 0.0
        publication_rows = [
            row for row in phase_rows
            if row["phase"] in {"commit_state", "materialize", "rebuild_edges", "publish_tree"}
        ]
        atomic_publication_marked = int(
            bool(publication_rows)
            and all(json.loads(row["details"] or "{}").get("atomic_publication") for row in publication_rows)
        )
        independent_upper_assignments = db.execute(
            """SELECT COUNT(*) FROM chunk_layer_states s
               JOIN turn_chunks c ON c.id=s.chunk_id
               WHERE c.project_id=? AND s.layer IN ('specific','broad') AND s.target_id IS NOT NULL""",
            (project_id,),
        ).fetchone()[0]
        primary_parent_violations = db.execute(
            """SELECT COUNT(*) FROM (
                 SELECT child_id, SUM(primary_edge) AS primary_count
                 FROM semantic_edges GROUP BY child_id HAVING primary_count > 1
               )"""
        ).fetchone()[0]
        db.close()
        hits = pipeline.search_project(
            project_id,
            "What exact term replaced topic candidates in the earlier project conversation?",
            limit=100,
        )
        gold_rank = next((index + 1 for index, hit in enumerate(hits) if hit["id"] == "diag-gold"), 0)
        gold = next((hit for hit in hits if hit["id"] == "diag-gold"), None)
        score_margin = (float(hits[0]["score"]) - float(hits[1]["score"])) if len(hits) > 1 else 0.0
        coverage = float(gold["retrieval_diagnostics"].get("query_token_coverage", 0.0)) if gold else 0.0
        candidate_recall = int(gold_rank > 0)
        final_recall = int(0 < gold_rank <= 8)
        tool_result = tools.search_project_history(
            "What exact term replaced topic candidates in the earlier project conversation?",
            evidence_needed="The direct user statement selecting the replacement term.",
            project_root=str(project_root),
            max_results=8,
        )
        trace = tool_result["trace"]
        route_counts = trace.get("route_counts", {})
        provider = thread_tree.SemanticProvider(pipeline._project_config())

    return [
        metric("DIAG-FIT-01", "Legacy three-raw-layer pair-comparison estimate at 2,383 chunks", legacy_pair_comparisons, ">=", 0, "comparisons", "diagnostic"),
        metric("DIAG-FIT-02", "Observed fallback scaling exponent from 256 to 512 chunks", round(scaling_exponent, 3), ">=", 0.0, "exponent", "diagnostic"),
        metric("DIAG-FIT-03", "Median 512-chunk fallback component time", round(timings[512], 3), ">=", 0.0, "ms", "diagnostic"),
        metric("DIAG-FIT-04", "Completed per-phase fit checkpoints", completed_phases, ">=", 0, "phases", "diagnostic"),
        metric("DIAG-FIT-05", "Unfinished per-phase fit checkpoints", unfinished_phases, ">=", 0, "phases", "diagnostic"),
        metric("DIAG-FIT-06", "Pair comparisons recorded by fit checkpoints", recorded_pairs, ">=", 0, "comparisons", "diagnostic"),
        metric("DIAG-FIT-07", "All publication phases share one atomic transaction", atomic_publication_marked, "==", 1, "boolean", "diagnostic"),
        metric("DIAG-FIT-08", "Pair-comparison reduction from evidence-first upper layers", round(pair_reduction, 4), ">=", 0.50, "ratio", "diagnostic"),
        metric("DIAG-RET-01", "Exact historical phrase fixture rank", gold_rank, "<=", 5, "rank", "quality"),
        metric("DIAG-RET-02", "Top-result score margin over second result", round(score_margin, 4), ">=", 0.0, "score", "diagnostic"),
        metric("DIAG-RET-03", "Gold query-token coverage", round(coverage, 4), ">=", 0.0, "ratio", "diagnostic"),
        metric("DIAG-RET-04", "Semantic provider available in fallback fixture", int(provider.can_embed), ">=", 0, "boolean", "diagnostic"),
        metric("DIAG-RET-05", "Query-echo candidates in routed lookup", int(trace.get("query_echo_candidate_count", 0)), ">=", 0, "chunks", "diagnostic"),
        metric("DIAG-RET-06", "Gold evidence present in top-100 candidate set", candidate_recall, ">=", 0, "boolean", "diagnostic"),
        metric("DIAG-RET-07", "Gold evidence survives final top-8 bound", final_recall, ">=", 0, "boolean", "diagnostic"),
        metric("DIAG-HIE-01", "Raw chunks used directly as upper-layer fit inputs", round(raw_upper_input_fraction, 4), "==", 0.0, "ratio", "diagnostic"),
        metric("DIAG-HIE-02", "Independent upper-layer chunk assignments", independent_upper_assignments, ">=", 0, "rows", "diagnostic"),
        metric("DIAG-HIE-03", "Primary-parent uniqueness violations", primary_parent_violations, ">=", 0, "rows", "diagnostic"),
        metric("DIAG-ROUTE-01", "Candidate spans nominated by global lookup", len(trace.get("candidate_span_ids", [])), ">=", 0, "spans", "diagnostic"),
        metric("DIAG-ROUTE-02", "Semantic nodes actually searched during widening", len(trace.get("searched_nodes", [])), ">=", 0, "nodes", "diagnostic"),
        metric("DIAG-ROUTE-03", "Distinct evidence routes returned", len(route_counts), ">=", 0, "routes", "diagnostic"),
        metric("DIAG-ROUTE-04", "Explicit retrieval stop reason present", int(bool(trace.get("stop_reason"))), ">=", 0, "boolean", "diagnostic"),
    ]


def _load_model_evaluation(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    evaluation = value.get("evaluation") if isinstance(value, dict) else None
    return evaluation if isinstance(evaluation, dict) else {}


def semantic_retrieval_benchmark() -> dict[str, Any]:
    """Measure query-class failure shapes with the currently configured provider."""

    from embedding_provider_benchmark import CASES, NEGATIVE_QUERIES

    with isolated_runtime(fit_thresholds={layer: 10_000 for layer in state.LAYERS}) as (root, data_dir):
        project_root = root / "project"
        project_root.mkdir()
        activate_projects(project_root)
        project_id = state.project_id_for(str(project_root))
        db = thread_tree.connect_db()
        state.ensure_project(db, project_id, str(project_root), fit_thresholds={layer: 10_000 for layer in state.LAYERS})
        for index, case in enumerate(CASES):
            direct_ingest(
                db,
                project_id,
                f"semantic-turn-{index}",
                [
                    {"id": f"semantic-{case.key}", "text": f"USER: {case.current}"},
                    {"id": f"obsolete-{case.key}", "text": f"USER: {case.obsolete}"},
                ],
            )
        direct_ingest(
            db,
            project_id,
            "revision-old",
            [{"id": "revision-old-chunk", "text": "USER: The websocket lease duration is sixty seconds."}],
        )
        direct_ingest(
            db,
            project_id,
            "revision-new",
            [{"id": "revision-new-chunk", "text": "USER: Final decision: the websocket lease duration is fifteen seconds; this supersedes sixty seconds."}],
        )
        provider_started = time.perf_counter()
        provider = thread_tree.SemanticProvider(pipeline._project_config())
        provider_probe_ms = (time.perf_counter() - provider_started) * 1000
        index_info: dict[str, Any] = {}
        if provider.can_embed:
            pipeline._backfill_project_embeddings(db, project_id, provider)
            index_info = vector_index.update_project_index(
                db,
                data_directory=data_dir,
                project_id=project_id,
                model=provider.embedding_model,
                dimension=provider.embedding_dimension,
            )
        stored_embeddings = db.execute(
            "SELECT COUNT(*) FROM turn_chunks WHERE project_id=? AND embedding IS NOT NULL",
            (project_id,),
        ).fetchone()[0]
        db.close()

        exact_ranks: list[int] = []
        paraphrase_ranks: list[int] = []
        latencies: list[float] = []
        bounded_vector_work: list[int] = []
        for case in CASES:
            gold = f"semantic-{case.key}"
            query_groups = (
                *((query, exact_ranks) for query in case.exact_queries),
                *((query, paraphrase_ranks) for query in case.paraphrases),
            )
            for query, ranks in query_groups:
                started = time.perf_counter()
                hits = pipeline.search_project(project_id, query, limit=5)
                latencies.append((time.perf_counter() - started) * 1000)
                ranks.append(next((position + 1 for position, hit in enumerate(hits) if hit["id"] == gold), 0))
                if hits:
                    diagnostics = hits[0].get("retrieval_diagnostics", {})
                    bounded_vector_work.append(
                        int(diagnostics.get("ann_candidates_visited", 0))
                        + int(diagnostics.get("delta_vectors_scanned", 0))
                    )
        negative_uncovered = 0
        for query in NEGATIVE_QUERIES:
            started = time.perf_counter()
            hits = pipeline.search_project(project_id, query, limit=5)
            latencies.append((time.perf_counter() - started) * 1000)
            negative_uncovered += int(not hits)
            if hits:
                diagnostics = hits[0].get("retrieval_diagnostics", {})
                bounded_vector_work.append(
                    int(diagnostics.get("ann_candidates_visited", 0))
                    + int(diagnostics.get("delta_vectors_scanned", 0))
                )
        revision_hits = pipeline.search_project(project_id, "final websocket lease duration", limit=5)
        revision_rank = next((position + 1 for position, hit in enumerate(revision_hits) if hit["id"] == "revision-new-chunk"), 0)
        database_bytes = sum(path.stat().st_size for path in data_dir.glob("index.sqlite3*") if path.is_file())
        chunk_count = len(CASES) * 2 + 2

        model_bytes = sum(
            path.stat().st_size
            for path in thread_tree.DEFAULT_FASTEMBED_MODEL_PATH.rglob("*")
            if path.is_file()
        )
        model_manifest = json.loads(
            (thread_tree.DEFAULT_FASTEMBED_MODEL_PATH / "MODEL.json").read_text(encoding="utf-8")
        )
        recorded_validation = model_manifest.get("validation", {})
    exact_recall = statistics.mean(rank > 0 for rank in exact_ranks)
    paraphrase_recall = statistics.mean(rank > 0 for rank in paraphrase_ranks)
    exact_mrr = statistics.mean((1 / rank) if rank else 0 for rank in exact_ranks)
    paraphrase_mrr = statistics.mean((1 / rank) if rank else 0 for rank in paraphrase_ranks)
    return {
        "provider_available": int(provider.can_embed),
        "provider_label": provider.label,
        "provider_probe_ms": round(provider_probe_ms, 3),
        "exact_recall_at_5": round(exact_recall, 4),
        "paraphrase_recall_at_5": round(paraphrase_recall, 4),
        "exact_mrr": round(exact_mrr, 4),
        "paraphrase_mrr": round(paraphrase_mrr, 4),
        "negative_uncovered_precision": round(negative_uncovered / len(NEGATIVE_QUERIES), 4),
        "revision_accuracy": int(revision_rank == 1),
        "revision_top_ids": [hit["id"] for hit in revision_hits],
        "warm_query_p95_ms": round(percentile(latencies), 3),
        "model_size_mib": round(model_bytes / (1024 * 1024), 2),
        "peak_rss_mib": recorded_validation.get("peak_rss_mib") if provider.can_embed else None,
        "cold_start_seconds": recorded_validation.get("cold_start_seconds") if provider.can_embed else None,
        "stored_embedding_rows": stored_embeddings,
        "ann_backend": index_info.get("backend"),
        "embedding_rows_scanned_per_semantic_query": max(bounded_vector_work, default=0),
        "database_bytes_per_chunk": round(database_bytes / chunk_count, 2),
    }


def completion_probe_scenario(model_eval_path: Path | None = None) -> list[Metric]:
    model_eval = _load_model_evaluation(model_eval_path)
    model_metrics = model_eval.get("metrics", {}) if isinstance(model_eval.get("metrics"), dict) else {}
    model_fixture_minimum = int(bool(model_eval.get("minimum_fixtures_met")))
    semantic = semantic_retrieval_benchmark()
    with isolated_runtime(fit_thresholds={layer: 1 for layer in state.LAYERS}) as (root, _):
        project_root = root / "project"
        project_root.mkdir()
        activate_projects(project_root)
        project_id = state.project_id_for(str(project_root))
        db = thread_tree.connect_db()
        state.ensure_project(db, project_id, str(project_root), fit_thresholds={layer: 1 for layer in state.LAYERS})
        chunks = [
            {"id": f"probe-{index}", "text": f"bottomup semantic representation probevalue{index}"}
            for index in range(12)
        ]
        direct_ingest(db, project_id, "probe-turn", chunks)
        run = state.schedule_global_rebuild(db, project_id, reason="completion probe")
        pipeline.run_fit(db, run["id"])
        input_units = {
            row["layer"]: json.loads(row["details"] or "{}").get("input_unit")
            for row in db.execute(
                "SELECT layer, details FROM fit_run_phase_metrics WHERE run_id=? AND phase='load_input'",
                (run["id"],),
            )
        }
        child_representation_fraction = (
            sum(input_units.get(layer) == expected for layer, expected in (("specific", "span"), ("broad", "specific"))) / 2
        )
        independent_upper_rows = db.execute(
            """SELECT COUNT(*) FROM chunk_layer_states
               WHERE layer IN ('specific','broad') AND target_id IS NOT NULL"""
        ).fetchone()[0]
        orphan_children = db.execute(
            """SELECT COUNT(*) FROM semantic_nodes child
               WHERE child.project_id=? AND child.layer IN ('span','specific')
                 AND child.lifecycle!='retired'
                 AND NOT EXISTS (
                   SELECT 1 FROM semantic_edges edge
                   WHERE edge.child_id=child.id AND edge.primary_edge=1
                 )""",
            (project_id,),
        ).fetchone()[0]
        direct_ingest(
            db,
            project_id,
            "retry-probe-turn",
            [{"id": "retry-probe-chunk", "text": "provider retry circuit breaker probe"}],
        )
        retry_run = state.schedule_routine_fit(db, project_id)
        state.claim_fit_run(db, retry_run["id"])
        state.fail_fit_run(db, retry_run["id"], "injected repeated provider timeout")
        immediate_retry = state.schedule_routine_fit(db, project_id)
        retry_backoff_enforced = int(immediate_retry is None)
        db.close()
        result = tools.search_project_history(
            "bottomup semantic representation",
            evidence_needed="The exact probe evidence should already be sufficient at the span.",
            project_root=str(project_root),
            max_results=8,
        )
        first_route_is_span = int(bool(result["evidence"]) and result["evidence"][0]["route"].startswith("span"))
        continuation_pass = int(
            model_fixture_minimum
            and float(model_metrics.get("answer_bearing_first_batch_stop_rate", 0.0)) >= 0.95
            and float(model_metrics.get("insufficient_first_batch_follow_up_rate", 0.0)) >= 0.90
            and float(model_metrics.get("follow_up_exclusion_completeness", 0.0)) == 1.0
            and float(model_metrics.get("duplicate_reinspection_rate", 1.0)) <= 0.01
        )
        adjacent_context = 0
        if result["evidence"]:
            first_turn = result["evidence"][0]["turn_id"]
            adjacent_context = sum(item["turn_id"] == first_turn for item in result["evidence"])
        return [
            metric("HIE-04", "Upper fits consume child-node representations", round(child_representation_fraction, 4), "==", 1.0, "ratio"),
            metric("HIE-05", "Independent upper-layer chunk assignments", independent_upper_rows, "==", 0, "rows"),
            metric("HIE-06", "Active semantic children without one parent", orphan_children, "==", 0, "nodes"),
            metric("RET-12", "First returned routed evidence is span-level", first_route_is_span, "==", 1),
            metric(
                "RET-13",
                "Model stops or continues from returned chunks correctly",
                continuation_pass,
                "==",
                1,
                gate="quality",
                details=(
                    "Requires paired real-model fixtures: one where the first returned chunks answer the "
                    "information need and one where the model must follow up with inspected chunk IDs excluded."
                ),
            ),
            metric(
                "FP-011",
                "Failed fit snapshot cannot immediately reschedule",
                retry_backoff_enforced,
                "==",
                1,
                gate="hard",
                details="Requires persisted retry count, next-retry time, and a circuit breaker for repeated failures.",
            ),
            metric("RET-11", "Precise hit includes adjacent same-turn context", adjacent_context, ">=", 2, "chunks", "quality"),
            metric(
                "RET-02",
                "Bundled semantic paraphrase Recall@5",
                semantic["paraphrase_recall_at_5"] if semantic["provider_available"] else 0.0,
                ">=",
                0.90,
                "ratio",
                "quality",
                f"Provider={semantic['provider_label']}; exact Recall@5={semantic['exact_recall_at_5']}.",
            ),
            metric(
                "RET-15",
                "Active-context tool-suppression benchmark executed",
                model_metrics.get("active_context_suppression_rate"),
                ">=",
                0.95,
                "ratio",
                gate="quality",
                details="Requires a real-model fixture set whose answers are fully present in the invocation context.",
            ),
            metric(
                "RET-16",
                "Missing-history tool-trigger benchmark executed",
                model_metrics.get("missing_history_trigger_recall"),
                ">=",
                0.90,
                "ratio",
                gate="quality",
                details="Requires paired real-model fixtures where project-specific gold evidence is absent from active context but indexed locally.",
            ),
            metric("DIAG-CONT-01", "Answer-bearing first-result stop rate", model_metrics.get("answer_bearing_first_batch_stop_rate"), ">=", 0.95, "ratio", "diagnostic"),
            metric("DIAG-CONT-02", "Insufficient-result follow-up rate", model_metrics.get("insufficient_first_batch_follow_up_rate"), ">=", 0.90, "ratio", "diagnostic"),
            metric("DIAG-CONT-03", "Follow-up exclusion completeness", model_metrics.get("follow_up_exclusion_completeness"), "==", 1.0, "ratio", "diagnostic"),
            metric("DIAG-CONT-04", "Duplicate chunk reinspection rate", model_metrics.get("duplicate_reinspection_rate"), "<=", 0.01, "ratio", "diagnostic"),
            metric("DIAG-CONT-05", "Controlled continuation gold recovery", model_metrics.get("controlled_gold_recovery_rate"), ">=", 0.90, "ratio", "diagnostic"),
            metric("DIAG-CONT-06", "Retrieved citation preservation", model_metrics.get("citation_preservation_rate"), ">=", 0.95, "ratio", "diagnostic"),
            metric("DIAG-CONT-07", "Natural supported-query mean tool calls", model_metrics.get("natural_mean_tool_calls"), "<=", 1.20, "calls", "diagnostic"),
            metric("DIAG-CONT-08", "Controlled continuation stays within three calls", model_metrics.get("controlled_bounded_call_rate"), "==", 1.0, "ratio", "diagnostic"),
            metric("DIAG-TRIGGER-01", "Unnecessary tool-call rate with explicit active evidence", None if model_metrics.get("active_context_suppression_rate") is None else round(1.0 - float(model_metrics["active_context_suppression_rate"]), 4), "<=", 0.05, "ratio", "diagnostic"),
            metric("DIAG-TRIGGER-02", "Missing-history tool-call recall", model_metrics.get("missing_history_trigger_recall"), ">=", 0.90, "ratio", "diagnostic"),
            metric("DIAG-TRIGGER-03", "Unsupported direct-answer rate", model_metrics.get("unsupported_direct_answer_rate"), "==", 0.0, "ratio", "diagnostic"),
            metric("DIAG-TRIGGER-04", "Forbidden auxiliary action rate", model_metrics.get("forbidden_auxiliary_action_rate"), "==", 0.0, "ratio", "diagnostic"),
            metric("DIAG-TRIGGER-05", "Real-model fixture minimum met", model_fixture_minimum, "==", 1, "boolean", "diagnostic"),
            metric("DIAG-TRIGGER-06", "Unsupported-query bounded search rate", model_metrics.get("unsupported_bounded_search_rate"), "==", 1.0, "ratio", "diagnostic"),
            metric("DIAG-SEM-00", "Local embedding provider available", semantic["provider_available"], "==", 1, "boolean", "diagnostic", f"Provider={semantic['provider_label']}"),
            metric("DIAG-SEM-01", "Bundled model download size", semantic["model_size_mib"], "<=", 250.0, "MiB", "diagnostic"),
            metric("DIAG-SEM-02", "Bundled provider peak resident memory", semantic["peak_rss_mib"], "<=", 500.0, "MiB", "diagnostic", "Fresh-process benchmark; pinned bundled artifact."),
            metric("DIAG-SEM-03", "Bundled provider cold start", semantic["cold_start_seconds"], "<=", 2.0, "seconds", "diagnostic", "Fresh-process benchmark; pinned bundled artifact."),
            metric("DIAG-SEM-04", "Warm semantic-provider query p95", semantic["warm_query_p95_ms"] if semantic["provider_available"] else None, "<=", 100.0, "ms", "diagnostic"),
            metric("DIAG-SEM-FB-01", "Warm lexical-fallback query p95", semantic["warm_query_p95_ms"], "<=", 100.0, "ms", "diagnostic"),
            metric("DIAG-SEM-05", "Held-out semantic paraphrase Recall@5", semantic["paraphrase_recall_at_5"], ">=", 0.90, "ratio", "diagnostic"),
            metric("DIAG-SEM-06", "Exact identifier Recall@5", semantic["exact_recall_at_5"], ">=", 0.99, "ratio", "diagnostic"),
            metric("DIAG-SEM-07", "Semantic paraphrase MRR", semantic["paraphrase_mrr"], ">=", 0.90, "ratio", "diagnostic"),
            metric("DIAG-SEM-08", "Hard-negative uncovered precision", semantic["negative_uncovered_precision"], ">=", 0.95, "ratio", "diagnostic"),
            metric("DIAG-SEM-09", "Superseded-decision top-rank accuracy", semantic["revision_accuracy"], "==", 1, "boolean", "diagnostic"),
            metric("DIAG-SEM-10", "Provider availability probe latency", semantic["provider_probe_ms"], "<=", 100.0, "ms", "diagnostic"),
            metric("DIAG-SEM-11", "Stored embedding rows", semantic["stored_embedding_rows"], ">=", 0, "rows", "diagnostic"),
            metric("DIAG-SEM-12", "Bounded vectors visited per semantic query", semantic["embedding_rows_scanned_per_semantic_query"], "<=", 1000, "vectors", "diagnostic", f"Backend={semantic['ann_backend']}; includes ANN candidates plus the bounded post-index delta."),
            metric("DIAG-SEM-13", "Small-fixture database bytes per chunk", semantic["database_bytes_per_chunk"], ">=", 0, "bytes/chunk", "diagnostic", "Includes fixed SQLite page overhead; SYS-12 is the release-scale storage gate."),
        ]


def render_report(run: dict[str, Any]) -> str:
    lines = [
        "# Thread Tree whole-system validation report",
        "",
        f"- Generated: {run['generated_at']}",
        f"- Python: {run['environment']['python']}",
        f"- Platform: {run['environment']['platform']}",
        f"- Overall readiness: **{run['overall_status']}**",
        f"- Scenarios: {run['summary']['passed']} passed, {run['summary']['failed']} failed",
        f"- Metrics: {run['summary']['metrics_passed']} passed, {run['summary']['metrics_failed']} failed",
        "",
        "## Scenario results",
        "",
        "| Scenario | Category | Status | Elapsed |",
        "|---|---|---:|---:|",
    ]
    for scenario in run["scenarios"]:
        lines.append(
            f"| {scenario['name']} | {scenario['category']} | {'PASS' if scenario['passed'] else 'FAIL'} | {scenario['elapsed_ms']:.1f} ms |"
        )
    lines.extend(["", "## Metric results", ""])
    for scenario in run["scenarios"]:
        lines.extend([f"### {scenario['name']}", ""])
        if scenario.get("error"):
            lines.append(f"Scenario error: `{scenario['error']}`")
            lines.append("")
        lines.extend([
            "| ID | Metric | Observed | Target | Gate | Result |",
            "|---|---|---:|---:|---|---:|",
        ])
        for item in scenario["metrics"]:
            observed = f"{item['observed']} {item['unit']}".strip()
            target = f"{item['comparator']} {item['target']} {item['unit']}".strip()
            result = "INFO" if item["gate"] == "diagnostic" else ("PASS" if item["passed"] else "FAIL")
            lines.append(
                f"| {item['metric_id']} | {item['label']} | {observed} | {target} | {item['gate']} | {result} |"
            )
        details = [item for item in scenario["metrics"] if item.get("details")]
        if details:
            lines.append("")
            for item in details:
                lines.append(f"- **{item['metric_id']} detail:** {item['details']}")
        lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            "A failure in a completion probe means the migration baseline may be stable, but the documented final product contract is not implemented yet. Performance results apply only to the recorded local fixture and do not substitute for the bundled embedding-provider benchmark.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=int, default=10_000, help="Retained chunks in the scale scenario")
    parser.add_argument("--output-prefix", type=Path, default=Path("/tmp/thread-tree-system-validation"))
    parser.add_argument(
        "--model-eval",
        type=Path,
        help="JSON output from real_model_validation.py; required to satisfy model-facing completion gates",
    )
    args = parser.parse_args()

    definitions: list[tuple[str, str, list[str], Callable[[], list[Metric]]]] = [
        ("Regression suite", "implemented", ["migration", "unit", "integration"], regression_scenario),
        ("Cross-client scope and isolation", "implemented", ["scope", "portability", "grounding"], cross_client_scope_scenario),
        ("Atomic turn completion and retry", "implemented", ["transactions", "ingestion", "FTS", "debt"], atomicity_scenario),
        ("Concurrent workers and duplicate delivery", "implemented", ["concurrency", "leases", "idempotency"], concurrency_scenario),
        ("Fit watermark and failure recovery", "implemented", ["fit debt", "watermark", "failure"], watermark_and_failure_scenario),
        ("Hierarchy and viewer integrity", "implemented", ["clustering", "hierarchy", "viewer"], hierarchy_and_viewer_scenario),
        ("Retrieval quality and read-only behavior", "implemented", ["recall", "MRR", "grounding", "latency"], retrieval_scenario),
        ("Hook latency, privacy, and source safety", "implemented", ["hooks", "latency", "privacy", "provenance"], hook_latency_and_privacy_scenario),
        ("Retention and rebuild safety", "implemented", ["retention", "tombstones", "rebuild"], retention_scenario),
        ("Reference-scale fallback performance", "implemented", ["scale", "search", "memory", "disk"], lambda: scale_scenario(args.chunks)),
        ("Plugin and MCP packaging", "implemented", ["plugin", "MCP", "startup"], plugin_mcp_scenario),
        ("Diagnostic failure-shape probes", "diagnostic", ["fit complexity", "retrieval ranking", "provider availability"], diagnostic_shape_scenario),
        (
            "Normative completion probes",
            "completion-probe",
            ["bottom-up fit", "model continuation", "context expansion", "semantic retrieval"],
            lambda: completion_probe_scenario(args.model_eval),
        ),
    ]

    scenarios = []
    for name, category, areas, fn in definitions:
        print(f"Running {name}", file=sys.stderr, flush=True)
        scenario = run_scenario(name, category, areas, fn)
        scenarios.append(scenario)
        outcome = "PASS" if scenario.passed else "FAIL"
        print(f"{outcome} {name} ({scenario.elapsed_ms / 1_000:.2f}s)", file=sys.stderr, flush=True)
    serialized = []
    for scenario in scenarios:
        value = asdict(scenario)
        value["passed"] = scenario.passed
        serialized.append(value)
    metrics = [item for scenario in scenarios for item in scenario.metrics if item.gate != "diagnostic"]
    failed = [scenario for scenario in scenarios if not scenario.passed]
    run = {
        "generated_at": state.utc_now(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "scale_chunks": args.chunks,
        },
        "overall_status": "PASS" if not failed else "NOT READY",
        "summary": {
            "passed": len(scenarios) - len(failed),
            "failed": len(failed),
            "metrics_passed": sum(item.passed for item in metrics),
            "metrics_failed": sum(not item.passed for item in metrics),
        },
        "scenarios": serialized,
    }
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.output_prefix.with_suffix(".json")
    md_path = args.output_prefix.with_suffix(".md")
    json_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_report(run), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), **run["summary"], "status": run["overall_status"]}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
