#!/usr/bin/env python3
"""Durable orchestration state for the next Thread Tree indexing pipeline.

This module intentionally contains no clustering or vector-store dependency.
It owns the lifecycle invariants that those providers must obey: idempotent turn
ingestion, per-layer fit debt, snapshot watermarks, one active project job,
frontier visibility, atomic generation replacement, and whole-turn eviction.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


LAYERS = ("span", "specific", "broad")
CHUNK_STATES = ("unassigned", "unlocked", "locked")
TURN_STATES = ("queued", "processing", "indexed", "failed", "evicted")
FIT_STATES = ("queued", "running", "committed", "failed", "cancelled")
FIT_KINDS = ("routine", "rebalance", "capacity_rebuild", "backfill")
FIT_RETRY_BASE_SECONDS = 60
FIT_RETRY_MAX_SECONDS = 3600
FIT_RETRY_CIRCUIT_THRESHOLD = 2

TURN_TRANSITIONS = {
    "queued": {"processing", "failed", "evicted"},
    "processing": {"indexed", "failed", "evicted"},
    "indexed": {"evicted"},
    "failed": {"queued", "evicted"},
    "evicted": set(),
}

FIT_TRANSITIONS = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"committed", "failed", "cancelled"},
    "committed": set(),
    "failed": set(),
    "cancelled": set(),
}


class StateTransitionError(RuntimeError):
    """Raised when a persisted state transition violates the state machine."""


class LostTurnLeaseError(StateTransitionError):
    """A newer worker owns the turn or has already finished it."""


@contextmanager
def exclusive_process_lock(path: Path, *, blocking: bool = True) -> Iterator[None]:
    """Hold a kernel lock on a persistent inode until this descriptor closes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unlinking the path would let a competitor lock a different inode while
    # an existing worker still owns the old one.
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            while True:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN):
                        raise
                    if not blocking:
                        raise BlockingIOError(error.errno, str(error)) from error
                    # LK_LOCK gives up after ten retries. Maintenance must
                    # instead wait for its owner just as flock does on Unix.
                    time.sleep(0.05)
        else:
            import fcntl

            mode = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
            fcntl.flock(lock.fileno(), mode)
        yield


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def project_id_for(cwd: str | None, fallback_thread_id: str | None = None) -> str:
    """Return the one tree identity for a canonical project root.

    ``fallback_thread_id`` remains in the signature only for compatibility with
    the first orchestration prototype. A chat identifier must never determine
    tree scope: every chat in one project contributes to the same tree, while
    different project roots remain isolated. Callers without a project root
    must defer indexing until that identity can be recovered.
    """

    del fallback_thread_id
    if not cwd or not cwd.strip():
        raise ValueError("Context Saver indexing requires a project root")
    canonical = str(Path(cwd).expanduser().resolve())
    return stable_id("project", canonical)


STAGED_PROMPTS_DDL = """CREATE TABLE IF NOT EXISTS staged_user_prompts (
    codex_turn_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    synthetic_turn INTEGER NOT NULL DEFAULT 0 CHECK(synthetic_turn IN (0,1)),
    state TEXT NOT NULL CHECK(state IN ('staged','reconciled','failed')),
    ingestion_turn_id TEXT REFERENCES turn_ingestion(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reconciled_at TEXT
)"""


def _initialize_staged_prompts(db: sqlite3.Connection) -> None:
    db.execute(STAGED_PROMPTS_DDL)
    if "synthetic_turn" not in {row[1] for row in db.execute("PRAGMA table_info(staged_user_prompts)")}:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if "synthetic_turn" not in {row[1] for row in db.execute("PRAGMA table_info(staged_user_prompts)")}:
                db.execute("ALTER TABLE staged_user_prompts RENAME TO staged_user_prompts_legacy")
                db.execute(STAGED_PROMPTS_DDL)
                db.execute(
                    """INSERT INTO staged_user_prompts
                       (codex_turn_id, project_id, thread_id, prompt, content_hash, synthetic_turn,
                        state, ingestion_turn_id, created_at, updated_at, reconciled_at)
                       SELECT codex_turn_id, project_id, thread_id, prompt, content_hash,
                              substr(codex_turn_id, 1, 7) = 'prompt_',
                              state, ingestion_turn_id, created_at, updated_at, reconciled_at
                       FROM staged_user_prompts_legacy ORDER BY rowid"""
                )
                db.execute("DROP TABLE staged_user_prompts_legacy")
    db.execute(
        """CREATE INDEX IF NOT EXISTS staged_user_prompts_project_state
           ON staged_user_prompts(project_id, state, created_at)"""
    )
    db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS staged_user_prompts_pending_synthetic_content
           ON staged_user_prompts(project_id, thread_id, content_hash)
           WHERE synthetic_turn=1 AND state='staged'"""
    )


def initialize_state_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            cwd TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS turn_ingestion (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            thread_id TEXT NOT NULL,
            transcript_path TEXT,
            line_start INTEGER,
            line_end INTEGER,
            content_hash TEXT NOT NULL,
            source_fingerprint TEXT,
            state TEXT NOT NULL CHECK(state IN ('queued','processing','indexed','failed','evicted')),
            protected INTEGER NOT NULL DEFAULT 0 CHECK(protected IN (0,1)),
            partial INTEGER NOT NULL DEFAULT 0 CHECK(partial IN (0,1)),
            chunker_version TEXT NOT NULL DEFAULT 'fallback-v1',
            attempts INTEGER NOT NULL DEFAULT 0,
            lease_token TEXT,
            lease_expires_at TEXT,
            error TEXT,
            retryable INTEGER CHECK(retryable IN (0,1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(project_id, thread_id, content_hash)
        );

        CREATE TABLE IF NOT EXISTS turn_chunks (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL UNIQUE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            thread_id TEXT NOT NULL,
            turn_id TEXT NOT NULL REFERENCES turn_ingestion(id) ON DELETE CASCADE,
            text TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            byte_count INTEGER NOT NULL,
            embedding TEXT,
            source_message_ids TEXT NOT NULL DEFAULT '[]',
            line_start INTEGER,
            line_end INTEGER,
            chunker_version TEXT NOT NULL DEFAULT 'fallback-v1',
            embedding_model TEXT,
            evicted INTEGER NOT NULL DEFAULT 0 CHECK(evicted IN (0,1)),
            created_at TEXT NOT NULL,
            UNIQUE(turn_id, content_hash)
        );

        CREATE TABLE IF NOT EXISTS chunk_layer_states (
            chunk_id TEXT NOT NULL REFERENCES turn_chunks(id) ON DELETE CASCADE,
            layer TEXT NOT NULL CHECK(layer IN ('span','specific','broad')),
            state TEXT NOT NULL CHECK(state IN ('unassigned','unlocked','locked')),
            target_id TEXT,
            membership_confidence REAL,
            generation_id TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(chunk_id, layer),
            CHECK((state = 'unassigned' AND target_id IS NULL) OR state != 'unassigned')
        );

        CREATE TABLE IF NOT EXISTS fit_debt_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            layer TEXT NOT NULL CHECK(layer IN ('span','specific','broad')),
            chunk_id TEXT NOT NULL REFERENCES turn_chunks(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            consumed_by TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fit_debt (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            layer TEXT NOT NULL CHECK(layer IN ('span','specific','broad')),
            threshold INTEGER NOT NULL CHECK(threshold > 0),
            debt_count INTEGER NOT NULL DEFAULT 0 CHECK(debt_count >= 0),
            last_completed_chunk_watermark INTEGER NOT NULL DEFAULT 0,
            last_consumed_event_seq INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'idle' CHECK(state IN ('idle','queued','running')),
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, layer)
        );

        CREATE TABLE IF NOT EXISTS fit_runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('routine','rebalance','capacity_rebuild','backfill')),
            state TEXT NOT NULL CHECK(state IN ('queued','running','committed','failed','cancelled')),
            layers TEXT NOT NULL,
            chunk_watermark INTEGER NOT NULL,
            debt_event_watermark INTEGER NOT NULL,
            reason TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS fit_run_phase_metrics (
            run_id TEXT NOT NULL REFERENCES fit_runs(id) ON DELETE CASCADE,
            phase TEXT NOT NULL,
            layer TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
            started_at TEXT NOT NULL,
            completed_at TEXT,
            elapsed_ms REAL,
            input_count INTEGER,
            output_count INTEGER,
            estimated_pair_comparisons INTEGER,
            provider TEXT,
            details TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(run_id, phase, layer)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS one_active_fit_per_project
            ON fit_runs(project_id) WHERE state IN ('queued','running');

        CREATE TABLE IF NOT EXISTS fit_retry_state (
            project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
            next_retry_at TEXT,
            circuit_open INTEGER NOT NULL DEFAULT 0 CHECK(circuit_open IN (0,1)),
            last_failed_run_id TEXT,
            last_failed_chunk_watermark INTEGER,
            last_failed_debt_event_watermark INTEGER,
            last_error TEXT,
            history_initialized INTEGER NOT NULL DEFAULT 0 CHECK(history_initialized IN (0,1)),
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cluster_generations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            layer TEXT NOT NULL CHECK(layer IN ('span','specific','broad')),
            epoch INTEGER NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('building','active','superseded','failed')),
            fit_run_id TEXT NOT NULL REFERENCES fit_runs(id) ON DELETE CASCADE,
            chunk_watermark INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            activated_at TEXT,
            UNIQUE(project_id, layer, epoch)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS one_active_generation_per_layer
            ON cluster_generations(project_id, layer) WHERE state = 'active';

        CREATE TABLE IF NOT EXISTS retention_state (
            project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            high_chunks INTEGER NOT NULL CHECK(high_chunks > 0),
            low_chunks INTEGER NOT NULL CHECK(low_chunks >= 0 AND low_chunks < high_chunks),
            byte_ceiling INTEGER,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evicted_turns (
            turn_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            content_hash TEXT NOT NULL,
            eviction_generation TEXT NOT NULL,
            reason TEXT NOT NULL,
            evicted_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS session_observations (
            project_id TEXT NOT NULL,
            project_root TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            transcript_path TEXT,
            observed_at TEXT NOT NULL,
            PRIMARY KEY(project_id, thread_id)
        );

        CREATE TABLE IF NOT EXISTS chat_plugin_activations (
            project_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('backfilling','active','failed')),
            transcript_path TEXT,
            indexed_through_line INTEGER NOT NULL DEFAULT 0,
            first_invoked_at TEXT NOT NULL,
            last_invoked_at TEXT NOT NULL,
            completed_at TEXT,
            error TEXT,
            PRIMARY KEY(project_id, thread_id)
        );

        CREATE INDEX IF NOT EXISTS turn_ingestion_project_state
            ON turn_ingestion(project_id, state, created_at);
        CREATE INDEX IF NOT EXISTS turn_chunks_project_seq
            ON turn_chunks(project_id, seq);
        CREATE INDEX IF NOT EXISTS turn_chunks_live_embedding_seq
            ON turn_chunks(project_id, embedding_model, seq)
            WHERE evicted=0 AND embedding IS NOT NULL;
        CREATE INDEX IF NOT EXISTS chunk_layer_states_layer_state
            ON chunk_layer_states(layer, state);
        CREATE INDEX IF NOT EXISTS fit_debt_events_unconsumed
            ON fit_debt_events(project_id, layer, consumed_by, seq);
        CREATE INDEX IF NOT EXISTS fit_phase_metrics_status
            ON fit_run_phase_metrics(run_id, status, phase, layer);
        CREATE INDEX IF NOT EXISTS session_observations_recent
            ON session_observations(observed_at DESC);

        CREATE TABLE IF NOT EXISTS semantic_nodes (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            layer TEXT NOT NULL CHECK(layer IN ('span','specific','broad')),
            lifecycle TEXT NOT NULL CHECK(lifecycle IN ('unlocked','locked','retired')),
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            keywords TEXT NOT NULL DEFAULT '[]',
            persistence REAL,
            embedding TEXT,
            generation_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS semantic_node_memberships (
            node_id TEXT NOT NULL REFERENCES semantic_nodes(id) ON DELETE CASCADE,
            chunk_id TEXT NOT NULL REFERENCES turn_chunks(id) ON DELETE CASCADE,
            membership_confidence REAL,
            PRIMARY KEY(node_id, chunk_id)
        );

        CREATE TABLE IF NOT EXISTS semantic_edges (
            child_id TEXT NOT NULL REFERENCES semantic_nodes(id) ON DELETE CASCADE,
            parent_id TEXT NOT NULL REFERENCES semantic_nodes(id) ON DELETE CASCADE,
            primary_edge INTEGER NOT NULL CHECK(primary_edge IN (0,1)),
            coverage REAL NOT NULL CHECK(coverage >= 0 AND coverage <= 1),
            PRIMARY KEY(child_id, parent_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS one_primary_parent_per_semantic_node
            ON semantic_edges(child_id) WHERE primary_edge = 1;

        CREATE TABLE IF NOT EXISTS project_active_tree (
            project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            generation_token TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS index_shards (
            name TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            owner_node_id TEXT,
            document_count INTEGER NOT NULL DEFAULT 0,
            backend TEXT NOT NULL,
            generation_token TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS index_documents (
            shard_name TEXT NOT NULL REFERENCES index_shards(name) ON DELETE CASCADE,
            document_id TEXT NOT NULL,
            node_id TEXT,
            chunk_id TEXT,
            turn_id TEXT,
            PRIMARY KEY(shard_name, document_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS turn_chunks_fts USING fts5(
            chunk_id UNINDEXED,
            project_id UNINDEXED,
            thread_id UNINDEXED,
            text
        );

        CREATE INDEX IF NOT EXISTS semantic_nodes_project_layer
            ON semantic_nodes(project_id, layer, lifecycle);
        CREATE INDEX IF NOT EXISTS semantic_memberships_chunk
            ON semantic_node_memberships(chunk_id);
        """
    )
    _initialize_staged_prompts(db)
    # Existing installations predate the orchestration columns. SQLite has no
    # portable `ADD COLUMN IF NOT EXISTS`, so make migrations explicit.
    existing_turn = {row[1] for row in db.execute("PRAGMA table_info(turn_ingestion)")}
    for name, definition in {
        "partial": "INTEGER NOT NULL DEFAULT 0 CHECK(partial IN (0,1))",
        "chunker_version": "TEXT NOT NULL DEFAULT 'fallback-v1'",
        "lease_token": "TEXT",
        "lease_expires_at": "TEXT",
        "retryable": "INTEGER CHECK(retryable IN (0,1))",
        "source_fingerprint": "TEXT",
    }.items():
        if name not in existing_turn:
            db.execute(f"ALTER TABLE turn_ingestion ADD COLUMN {name} {definition}")
    existing_chunk = {row[1] for row in db.execute("PRAGMA table_info(turn_chunks)")}
    for name, definition in {
        "source_message_ids": "TEXT NOT NULL DEFAULT '[]'",
        "line_start": "INTEGER",
        "line_end": "INTEGER",
        "chunker_version": "TEXT NOT NULL DEFAULT 'fallback-v1'",
        "embedding_model": "TEXT",
    }.items():
        if name not in existing_chunk:
            db.execute(f"ALTER TABLE turn_chunks ADD COLUMN {name} {definition}")
    existing_node = {row[1] for row in db.execute("PRAGMA table_info(semantic_nodes)")}
    if "embedding" not in existing_node:
        db.execute("ALTER TABLE semantic_nodes ADD COLUMN embedding TEXT")
    existing_retry = {row[1] for row in db.execute("PRAGMA table_info(fit_retry_state)")}
    if "history_initialized" not in existing_retry:
        db.execute(
            "ALTER TABLE fit_retry_state ADD COLUMN history_initialized INTEGER NOT NULL DEFAULT 0"
        )
    db.commit()


def observe_session(
    db: sqlite3.Connection,
    *,
    project_root: str,
    thread_id: str,
    transcript_path: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Record session identity without retaining prompt or transcript content."""

    canonical = str(Path(project_root).expanduser().resolve())
    identifier = str(thread_id).strip()
    if not canonical or not identifier:
        raise ValueError("project_root and thread_id are required")
    project_id = project_id_for(canonical)
    now = utc_now()
    resolved_transcript = (
        str(Path(transcript_path).expanduser().resolve())
        if transcript_path and str(transcript_path).strip()
        else None
    )
    def write() -> None:
        db.execute(
            """INSERT INTO session_observations
               (project_id, project_root, thread_id, transcript_path, observed_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(project_id, thread_id) DO UPDATE SET
                 project_root=excluded.project_root,
                 transcript_path=COALESCE(excluded.transcript_path, session_observations.transcript_path),
                 observed_at=excluded.observed_at""",
            (project_id, canonical, identifier, resolved_transcript, now),
        )
    if commit:
        with db:
            write()
    else:
        write()
    row = db.execute(
        "SELECT * FROM session_observations WHERE project_id=? AND thread_id=?",
        (project_id, identifier),
    ).fetchone()
    return dict(row) if row else {}


def chat_activation(
    db: sqlite3.Connection,
    project_id: str,
    thread_id: str,
) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT * FROM chat_plugin_activations WHERE project_id=? AND thread_id=?",
        (project_id, thread_id),
    ).fetchone()
    return dict(row) if row else None


def begin_chat_activation(
    db: sqlite3.Connection,
    *,
    project_id: str,
    thread_id: str,
    transcript_path: str | None,
) -> tuple[dict[str, Any], bool]:
    """Begin an idempotent first-invocation backfill for one chat."""

    now = utc_now()
    with db:
        inserted = db.execute(
            """INSERT OR IGNORE INTO chat_plugin_activations
               (project_id, thread_id, state, transcript_path,
                first_invoked_at, last_invoked_at)
               VALUES (?, ?, 'backfilling', ?, ?, ?)""",
            (project_id, thread_id, transcript_path, now, now),
        )
        if inserted.rowcount == 1:
            return chat_activation(db, project_id, thread_id) or {}, True
        existing = chat_activation(db, project_id, thread_id)
        if existing and existing["state"] == "failed":
            db.execute(
                """UPDATE chat_plugin_activations
                   SET state='backfilling',
                       transcript_path=COALESCE(?, transcript_path),
                       last_invoked_at=?, error=NULL
                   WHERE project_id=? AND thread_id=?""",
                (transcript_path, now, project_id, thread_id),
            )
            return chat_activation(db, project_id, thread_id) or existing, True
        db.execute(
            """UPDATE chat_plugin_activations SET last_invoked_at=?
               WHERE project_id=? AND thread_id=?""",
            (now, project_id, thread_id),
        )
    return chat_activation(db, project_id, thread_id) or existing or {}, False


def finish_chat_activation(
    db: sqlite3.Connection,
    *,
    project_id: str,
    thread_id: str,
    indexed_through_line: int,
    error: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    new_state = "failed" if error else "active"
    with db:
        db.execute(
            """UPDATE chat_plugin_activations
               SET state=?, indexed_through_line=?, completed_at=?, error=?, last_invoked_at=?
               WHERE project_id=? AND thread_id=?""",
            (new_state, max(0, int(indexed_through_line)), now, error, now, project_id, thread_id),
        )
    return chat_activation(db, project_id, thread_id) or {}


def stage_user_prompt(
    db: sqlite3.Connection,
    *,
    codex_turn_id: str | None,
    project_id: str,
    thread_id: str,
    prompt: str,
) -> dict[str, Any]:
    """Durably stage the exact prompt without making it searchable yet.

    `UserPromptSubmit` runs before the completed transcript boundary exists.
    Staging therefore records source material only; chunking, embedding, and
    insertion into the searchable index still happen from the authoritative
    transcript after `Stop`.
    """

    prompt = prompt.strip()
    if not thread_id:
        raise ValueError("thread_id is required")
    if not prompt:
        raise ValueError("prompt is required")
    now = utc_now()
    content_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    with db:
        if codex_turn_id:
            db.execute(
                """INSERT INTO staged_user_prompts
                   (codex_turn_id, project_id, thread_id, prompt, content_hash, state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'staged', ?, ?)
                   ON CONFLICT(codex_turn_id) DO UPDATE SET
                     prompt=excluded.prompt, content_hash=excluded.content_hash, updated_at=excluded.updated_at
                   WHERE staged_user_prompts.state != 'reconciled' AND staged_user_prompts.synthetic_turn=0
                     AND staged_user_prompts.project_id=excluded.project_id
                     AND staged_user_prompts.thread_id=excluded.thread_id""",
                (codex_turn_id, project_id, thread_id, prompt, content_hash, now, now),
            )
            row = db.execute(
                """SELECT * FROM staged_user_prompts
                   WHERE codex_turn_id=? AND project_id=? AND thread_id=? AND synthetic_turn=0""",
                (codex_turn_id, project_id, thread_id),
            ).fetchone()
            if row is None:
                raise StateTransitionError("prompt turn ID belongs to another source")
        else:
            # Claude does not provide a per-turn ID. The existing pending
            # prompt wins a replay; reconciliation opens a new slot.
            db.execute(
                """INSERT INTO staged_user_prompts
                   (codex_turn_id, project_id, thread_id, prompt, content_hash, synthetic_turn,
                    state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, 'staged', ?, ?)
                   ON CONFLICT(project_id, thread_id, content_hash)
                   WHERE synthetic_turn=1 AND state='staged' DO NOTHING""",
                (f"prompt_{uuid.uuid4().hex}", project_id, thread_id, prompt, content_hash, now, now),
            )
            row = db.execute(
                """SELECT * FROM staged_user_prompts
                   WHERE project_id=? AND thread_id=? AND content_hash=? AND synthetic_turn=1 AND state='staged'""",
                (project_id, thread_id, content_hash),
            ).fetchone()
    if row is None:
        raise RuntimeError("prompt staging failed")
    return dict(row)


def reconcile_staged_prompt(
    db: sqlite3.Connection,
    *,
    codex_turn_id: str | None,
    project_id: str,
    thread_id: str,
    ingestion_turn_id: str | None = None,
) -> dict[str, Any] | None:
    """Link a staged prompt to the authoritative completed-turn record."""

    if codex_turn_id:
        staged = db.execute(
            """SELECT * FROM staged_user_prompts
               WHERE codex_turn_id = ? AND project_id = ? AND thread_id = ?""",
            (codex_turn_id, project_id, thread_id),
        ).fetchone()
    else:
        staged = db.execute(
            """SELECT * FROM staged_user_prompts
               WHERE project_id = ? AND thread_id = ? AND state = 'staged'
               ORDER BY rowid DESC LIMIT 1""",
            (project_id, thread_id),
        ).fetchone()
    if staged is None:
        return None
    if ingestion_turn_id is None:
        candidate = db.execute(
            """SELECT id FROM turn_ingestion
               WHERE project_id = ? AND thread_id = ? AND partial = 0
               ORDER BY COALESCE(line_end, 0) DESC, created_at DESC LIMIT 1""",
            (project_id, thread_id),
        ).fetchone()
        ingestion_turn_id = candidate["id"] if candidate else None
    if ingestion_turn_id is None:
        return dict(staged)
    target = db.execute(
        """SELECT id FROM turn_ingestion
           WHERE id = ? AND project_id = ? AND thread_id = ?""",
        (ingestion_turn_id, project_id, thread_id),
    ).fetchone()
    if target is None:
        raise StateTransitionError("staged prompt cannot reconcile across project or thread scope")
    now = utc_now()
    with db:
        db.execute(
            """UPDATE staged_user_prompts
               SET state='reconciled', ingestion_turn_id=?, updated_at=?, reconciled_at=?
               WHERE codex_turn_id=? AND state='staged'""",
            (ingestion_turn_id, now, now, staged["codex_turn_id"]),
        )
    row = db.execute(
        "SELECT * FROM staged_user_prompts WHERE codex_turn_id = ?",
        (staged["codex_turn_id"],),
    ).fetchone()
    return dict(row) if row else None


def ensure_project(
    db: sqlite3.Connection,
    project_id: str,
    cwd: str | None = None,
    *,
    fit_thresholds: Mapping[str, int] | None = None,
    high_chunks: int = 10_000,
    low_chunks: int = 8_500,
    byte_ceiling: int | None = None,
) -> None:
    if low_chunks >= high_chunks:
        raise ValueError("low_chunks must be smaller than high_chunks")
    thresholds = {layer: 100 for layer in LAYERS}
    if fit_thresholds:
        thresholds.update({layer: int(value) for layer, value in fit_thresholds.items()})
    if any(layer not in LAYERS for layer in thresholds) or any(value <= 0 for value in thresholds.values()):
        raise ValueError("fit thresholds must be positive values for known layers")
    now = utc_now()
    with db:
        db.execute(
            """INSERT INTO projects(id, cwd, created_at, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 cwd = COALESCE(excluded.cwd, projects.cwd),
                 updated_at = excluded.updated_at""",
            (project_id, cwd, now, now),
        )
        for layer in LAYERS:
            db.execute(
                """INSERT INTO fit_debt(project_id, layer, threshold, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(project_id, layer) DO NOTHING""",
                (project_id, layer, thresholds[layer], now),
            )
        db.execute(
            """INSERT INTO retention_state(project_id, high_chunks, low_chunks, byte_ceiling, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(project_id) DO NOTHING""",
            (project_id, high_chunks, low_chunks, byte_ceiling, now),
        )
        db.execute(
            """INSERT INTO fit_retry_state(project_id, updated_at)
               VALUES (?, ?) ON CONFLICT(project_id) DO NOTHING""",
            (project_id, now),
        )
        retry = db.execute(
            "SELECT history_initialized FROM fit_retry_state WHERE project_id=?",
            (project_id,),
        ).fetchone()
        if retry is not None and not retry["history_initialized"]:
            # `utc_now()` is intentionally second-resolution for readable state.
            # Use SQLite insertion order here so a commit and a later failure in
            # the same second cannot be mistaken for simultaneous events.
            last_commit_rowid = db.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM fit_runs WHERE project_id=? AND state='committed'",
                (project_id,),
            ).fetchone()[0]
            failed_runs = db.execute(
                """SELECT * FROM fit_runs
                   WHERE project_id=? AND state='failed' AND rowid > ?
                   ORDER BY rowid DESC""",
                (project_id, last_commit_rowid),
            ).fetchall()
            failures = len(failed_runs)
            if failed_runs:
                latest = failed_runs[0]
                completed = datetime.fromisoformat(str(latest["completed_at"] or latest["created_at"]))
                delay_seconds = min(
                    FIT_RETRY_MAX_SECONDS,
                    FIT_RETRY_BASE_SECONDS * (2 ** (failures - 1)),
                )
                next_retry_at = (completed + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
                db.execute(
                    """UPDATE fit_retry_state
                       SET consecutive_failures=?, next_retry_at=?, circuit_open=?,
                           last_failed_run_id=?, last_failed_chunk_watermark=?,
                           last_failed_debt_event_watermark=?, last_error=?,
                           history_initialized=1, updated_at=? WHERE project_id=?""",
                    (
                        failures,
                        next_retry_at,
                        int(failures >= FIT_RETRY_CIRCUIT_THRESHOLD),
                        latest["id"],
                        latest["chunk_watermark"],
                        latest["debt_event_watermark"],
                        latest["error"],
                        now,
                        project_id,
                    ),
                )
            else:
                db.execute(
                    "UPDATE fit_retry_state SET history_initialized=1, updated_at=? WHERE project_id=?",
                    (now, project_id),
                )


def fit_retry_status(db: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM fit_retry_state WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        raise KeyError(project_id)
    return dict(row)


def reset_fit_retry_state(db: sqlite3.Connection, project_id: str) -> None:
    """Explicitly close the fit circuit after remediation or user retry."""

    now = utc_now()
    with db:
        db.execute(
            """UPDATE fit_retry_state
               SET consecutive_failures=0, next_retry_at=NULL, circuit_open=0,
                   last_failed_run_id=NULL, last_failed_chunk_watermark=NULL,
                   last_failed_debt_event_watermark=NULL, last_error=NULL, updated_at=?
               WHERE project_id=?""",
            (now, project_id),
        )


def _routine_fit_retry_allowed(db: sqlite3.Connection, project_id: str) -> bool:
    retry = fit_retry_status(db, project_id)
    if retry["circuit_open"]:
        return False
    if not retry["next_retry_at"]:
        return True
    return datetime.fromisoformat(str(retry["next_retry_at"])) <= datetime.now(timezone.utc)


def queue_turn(
    db: sqlite3.Connection,
    *,
    turn_id: str,
    project_id: str,
    thread_id: str,
    content_hash: str,
    transcript_path: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
    source_fingerprint: str | None = None,
    protected: bool = False,
    partial: bool = False,
    chunker_version: str = "fallback-v1",
    revalidate_replay: bool = False,
) -> dict[str, Any]:
    now = utc_now()
    with db:
        inserted = db.execute(
            """INSERT INTO turn_ingestion
               (id, project_id, thread_id, transcript_path, line_start, line_end,
                content_hash, source_fingerprint, state, protected, partial, chunker_version, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, thread_id, content_hash) DO NOTHING""",
            (
                turn_id,
                project_id,
                thread_id,
                transcript_path,
                line_start,
                line_end,
                content_hash,
                source_fingerprint,
                int(protected),
                int(partial),
                chunker_version,
                now,
                now,
            ),
        )
        if inserted.rowcount == 0 and revalidate_replay and not partial:
            # A fresh read of the same source can recover failed legacy
            # entries and turns once marked indexed without any evidence.
            db.execute(
                """UPDATE turn_ingestion
                   SET state='queued', transcript_path=?, line_start=?, line_end=?, source_fingerprint=?,
                       error=NULL, retryable=NULL, updated_at=?, completed_at=NULL
                   WHERE project_id=? AND thread_id=? AND content_hash=? AND partial=0
                     AND ((state='failed' AND retryable IS NOT 0)
                          OR (state='indexed' AND transcript_path IS NOT NULL AND NOT EXISTS (
                              SELECT 1 FROM turn_chunks c WHERE c.turn_id=turn_ingestion.id
                          )))""",
                (transcript_path, line_start, line_end, source_fingerprint, now, project_id, thread_id, content_hash),
            )
    row = db.execute(
        "SELECT * FROM turn_ingestion WHERE project_id = ? AND thread_id = ? AND content_hash = ?",
        (project_id, thread_id, content_hash),
    ).fetchone()
    if row is None:
        raise RuntimeError("turn queue insert failed")
    return dict(row)


def _validate_transition(current: str, new: str, transitions: Mapping[str, set[str]], entity: str) -> None:
    if new not in transitions.get(current, set()):
        raise StateTransitionError(f"invalid {entity} transition: {current} -> {new}")


def transition_turn(
    db: sqlite3.Connection,
    turn_id: str,
    new_state: str,
    error: str | None = None,
    *,
    lease_token: str | None = None,
    retryable: bool | None = None,
) -> None:
    if new_state not in TURN_STATES:
        raise ValueError(f"unknown turn state: {new_state}")
    row = db.execute("SELECT state, lease_token FROM turn_ingestion WHERE id = ?", (turn_id,)).fetchone()
    if row is None:
        if lease_token is not None:
            raise LostTurnLeaseError(turn_id)
        raise KeyError(turn_id)
    if lease_token is not None and row["lease_token"] != lease_token:
        raise LostTurnLeaseError(turn_id)
    _validate_transition(row["state"], new_state, TURN_TRANSITIONS, "turn")
    completed_at = utc_now() if new_state in {"indexed", "failed", "evicted"} else None
    with db:
        changed = db.execute(
            """UPDATE turn_ingestion
               SET state = ?, error = ?, retryable = ?, updated_at = ?, completed_at = COALESCE(?, completed_at),
                   attempts = attempts + CASE WHEN ? = 'processing' THEN 1 ELSE 0 END,
                   lease_token = CASE WHEN ? IN ('indexed','failed','evicted') THEN NULL ELSE lease_token END,
                   lease_expires_at = CASE WHEN ? IN ('indexed','failed','evicted') THEN NULL ELSE lease_expires_at END
               WHERE id = ? AND state = ? AND lease_token IS ?""",
            (new_state, error, retryable, utc_now(), completed_at, new_state, new_state, new_state, turn_id,
             row["state"], row["lease_token"]),
        )
        if changed.rowcount != 1:
            raise LostTurnLeaseError(turn_id)


def requeue_retryable_turns(db: sqlite3.Connection, project_id: str, thread_id: str | None) -> None:
    """Make transient failures eligible once at the start of a worker pass."""
    with db:
        db.execute(
            """UPDATE turn_ingestion
               SET state='queued', updated_at=?, completed_at=NULL
               WHERE project_id=? AND (? IS NULL OR thread_id=?)
                 AND state='failed' AND retryable=1 AND partial=0""",
            (utc_now(), project_id, thread_id, thread_id),
        )


def claim_next_turn(
    db: sqlite3.Connection,
    project_id: str,
    *,
    thread_id: str | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any] | None:
    """Atomically claim the oldest queued turn and recover expired leases."""

    now = utc_now()
    lease_token = uuid.uuid4().hex
    lease_expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
    with db:
        if thread_id:
            db.execute(
                """UPDATE turn_ingestion
                   SET state = 'queued', lease_token = NULL, lease_expires_at = NULL,
                       error = 'worker lease expired', updated_at = ?
                   WHERE project_id = ? AND thread_id = ? AND state = 'processing'
                     AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?""",
                (now, project_id, thread_id, now),
            )
            row = db.execute(
                """SELECT id FROM turn_ingestion
                   WHERE project_id = ? AND thread_id = ?
                     AND state = 'queued' AND partial = 0
                   ORDER BY created_at, id LIMIT 1""",
                (project_id, thread_id),
            ).fetchone()
        else:
            db.execute(
                """UPDATE turn_ingestion
                   SET state = 'queued', lease_token = NULL, lease_expires_at = NULL,
                       error = 'worker lease expired', updated_at = ?
                   WHERE project_id = ? AND state = 'processing'
                     AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?""",
                (now, project_id, now),
            )
            row = db.execute(
                """SELECT id FROM turn_ingestion
                   WHERE project_id = ? AND state = 'queued' AND partial = 0
                   ORDER BY created_at, id LIMIT 1""",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        cursor = db.execute(
            """UPDATE turn_ingestion
               SET state = 'processing', attempts = attempts + 1,
                   lease_token = ?, lease_expires_at = ?, error = NULL, retryable = NULL, updated_at = ?
               WHERE id = ? AND state = 'queued'""",
            (lease_token, lease_expires, now, row["id"]),
        )
        if cursor.rowcount != 1:
            return None
    claimed = db.execute(
        "SELECT * FROM turn_ingestion WHERE id = ? AND lease_token = ?",
        (row["id"], lease_token),
    ).fetchone()
    return dict(claimed) if claimed else None


def _normalize_layer_state(value: Any) -> tuple[str, str | None, float | None]:
    if isinstance(value, str):
        state, target_id, confidence = value, None, None
    elif isinstance(value, Mapping):
        state = str(value.get("state", "unassigned"))
        target_id = str(value["target_id"]) if value.get("target_id") is not None else None
        confidence = float(value["membership_confidence"]) if value.get("membership_confidence") is not None else None
    else:
        state, target_id, confidence = "unassigned", None, None
    if state not in CHUNK_STATES:
        raise ValueError(f"unknown chunk layer state: {state}")
    if state == "unassigned":
        target_id = None
    elif not target_id:
        raise ValueError(f"{state} state requires target_id")
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        raise ValueError("membership_confidence must be between 0 and 1")
    return state, target_id, confidence


def _record_debt_event(
    db: sqlite3.Connection,
    project_id: str,
    layer: str,
    chunk_id: str,
    reason: str,
) -> None:
    db.execute(
        """INSERT INTO fit_debt_events(project_id, layer, chunk_id, reason, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (project_id, layer, chunk_id, reason, utc_now()),
    )
    debt_count = db.execute(
        """SELECT COUNT(*) FROM fit_debt_events
           WHERE project_id = ? AND layer = ? AND consumed_by IS NULL""",
        (project_id, layer),
    ).fetchone()[0]
    db.execute(
        "UPDATE fit_debt SET debt_count = ?, updated_at = ? WHERE project_id = ? AND layer = ?",
        (debt_count, utc_now(), project_id, layer),
    )


def complete_turn_ingestion(
    db: sqlite3.Connection,
    turn_id: str,
    chunks: Sequence[Mapping[str, Any]],
    *,
    lease_token: str | None = None,
) -> list[dict[str, Any]]:
    now = utc_now()
    inserted: list[dict[str, Any]] = []
    with db:
        if lease_token is not None:
            # Obtain the writer transaction before the check so a reclaimer
            # cannot change ownership between validation and the first insert.
            owned = db.execute(
                """UPDATE turn_ingestion SET lease_token=lease_token
                   WHERE id=? AND state='processing' AND lease_token=?""",
                (turn_id, lease_token),
            )
            if owned.rowcount != 1:
                raise LostTurnLeaseError(turn_id)
        turn = db.execute("SELECT * FROM turn_ingestion WHERE id = ?", (turn_id,)).fetchone()
        if turn is None:
            raise KeyError(turn_id)
        if turn["state"] != "processing":
            raise StateTransitionError(f"turn must be processing before completion, got {turn['state']}")
        for ordinal, raw_chunk in enumerate(chunks):
            text = str(raw_chunk.get("text", "")).strip()
            if not text:
                raise ValueError("chunk text cannot be empty")
            content_hash = str(raw_chunk.get("content_hash") or hashlib.sha256(text.encode("utf-8")).hexdigest())
            chunk_id = str(raw_chunk.get("id") or stable_id("chunk", turn_id, ordinal, content_hash))
            embedding = raw_chunk.get("embedding")
            cursor = db.execute(
                """INSERT OR IGNORE INTO turn_chunks
                   (id, project_id, thread_id, turn_id, text, content_hash, byte_count, embedding,
                    source_message_ids, line_start, line_end, chunker_version, embedding_model, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk_id,
                    turn["project_id"],
                    turn["thread_id"],
                    turn_id,
                    text,
                    content_hash,
                    len(text.encode("utf-8")),
                    json.dumps(embedding) if embedding is not None else None,
                    json.dumps(list(raw_chunk.get("source_message_ids") or [])),
                    raw_chunk.get("line_start"),
                    raw_chunk.get("line_end"),
                    str(raw_chunk.get("chunker_version") or turn["chunker_version"]),
                    raw_chunk.get("embedding_model"),
                    now,
                ),
            )
            if cursor.rowcount == 0:
                existing = db.execute(
                    "SELECT * FROM turn_chunks WHERE turn_id = ? AND content_hash = ?",
                    (turn_id, content_hash),
                ).fetchone()
                if existing:
                    inserted.append(dict(existing))
                continue
            layer_states = raw_chunk.get("layer_states") if isinstance(raw_chunk.get("layer_states"), Mapping) else {}
            for layer in LAYERS:
                state, target_id, confidence = _normalize_layer_state(layer_states.get(layer))
                db.execute(
                    """INSERT INTO chunk_layer_states
                       (chunk_id, layer, state, target_id, membership_confidence, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (chunk_id, layer, state, target_id, confidence, now),
                )
                if state != "locked":
                    _record_debt_event(db, turn["project_id"], layer, chunk_id, "ingested_non_locked")
            row = db.execute("SELECT * FROM turn_chunks WHERE id = ?", (chunk_id,)).fetchone()
            if row:
                inserted.append(dict(row))
                # Only newly inserted chunks reach this branch. FTS mirrors the
                # canonical insert in this transaction, so there is no old row
                # to remove. Searching the UNINDEXED chunk_id would scan the
                # whole FTS table for every chunk in a backfill.
                db.execute(
                    "INSERT INTO turn_chunks_fts(chunk_id, project_id, thread_id, text) VALUES (?, ?, ?, ?)",
                    (chunk_id, turn["project_id"], turn["thread_id"], text),
                )
        db.execute(
            """UPDATE turn_ingestion
               SET state = 'indexed', error = NULL, lease_token = NULL,
                   lease_expires_at = NULL, updated_at = ?, completed_at = ?
               WHERE id = ?""",
            (now, now, turn_id),
        )
        db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, turn["project_id"]))
    return inserted


def update_chunk_layer_state(
    db: sqlite3.Connection,
    chunk_id: str,
    layer: str,
    state: str,
    *,
    target_id: str | None = None,
    membership_confidence: float | None = None,
    generation_id: str | None = None,
    accrue_debt: bool = True,
    reason: str = "meaningful_reassignment",
) -> None:
    if layer not in LAYERS:
        raise ValueError(f"unknown layer: {layer}")
    state, target_id, membership_confidence = _normalize_layer_state(
        {"state": state, "target_id": target_id, "membership_confidence": membership_confidence}
    )
    chunk = db.execute("SELECT project_id, evicted FROM turn_chunks WHERE id = ?", (chunk_id,)).fetchone()
    if chunk is None:
        raise KeyError(chunk_id)
    if chunk["evicted"]:
        raise StateTransitionError("cannot reassign an evicted chunk")
    previous = db.execute(
        "SELECT state, target_id, membership_confidence FROM chunk_layer_states WHERE chunk_id = ? AND layer = ?",
        (chunk_id, layer),
    ).fetchone()
    changed = previous is None or (
        previous["state"], previous["target_id"], previous["membership_confidence"]
    ) != (state, target_id, membership_confidence)
    with db:
        db.execute(
            """INSERT INTO chunk_layer_states
               (chunk_id, layer, state, target_id, membership_confidence, generation_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chunk_id, layer) DO UPDATE SET
                 state = excluded.state,
                 target_id = excluded.target_id,
                 membership_confidence = excluded.membership_confidence,
                 generation_id = excluded.generation_id,
                 updated_at = excluded.updated_at""",
            (chunk_id, layer, state, target_id, membership_confidence, generation_id, utc_now()),
        )
        if changed and accrue_debt and state != "locked":
            _record_debt_event(db, chunk["project_id"], layer, chunk_id, reason)


def debt_status(db: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            "SELECT * FROM fit_debt WHERE project_id = ? ORDER BY layer",
            (project_id,),
        )
    ]


def _active_fit(db: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM fit_runs WHERE project_id = ? AND state IN ('queued','running') ORDER BY created_at LIMIT 1",
        (project_id,),
    ).fetchone()


def schedule_routine_fit(db: sqlite3.Connection, project_id: str) -> dict[str, Any] | None:
    existing = _active_fit(db, project_id)
    if existing:
        return dict(existing)
    if not _routine_fit_retry_allowed(db, project_id):
        return None
    layers = [
        row["layer"]
        for row in db.execute(
            """SELECT layer FROM fit_debt
               WHERE project_id = ? AND debt_count >= threshold AND state = 'idle'
               ORDER BY layer""",
            (project_id,),
        )
    ]
    if not layers:
        return None
    chunk_watermark = db.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM turn_chunks WHERE project_id = ? AND evicted = 0",
        (project_id,),
    ).fetchone()[0]
    debt_watermark = db.execute(
        """SELECT COALESCE(MAX(seq), 0) FROM fit_debt_events
           WHERE project_id = ? AND consumed_by IS NULL""",
        (project_id,),
    ).fetchone()[0]
    run_id = f"fit_{uuid.uuid4().hex}"
    now = utc_now()
    with db:
        db.execute(
            """INSERT INTO fit_runs
               (id, project_id, kind, state, layers, chunk_watermark,
                debt_event_watermark, reason, created_at)
               VALUES (?, ?, 'routine', 'queued', ?, ?, ?, 'fit_debt_threshold', ?)""",
            (run_id, project_id, json.dumps(layers), chunk_watermark, debt_watermark, now),
        )
        db.executemany(
            "UPDATE fit_debt SET state = 'queued', updated_at = ? WHERE project_id = ? AND layer = ?",
            [(now, project_id, layer) for layer in layers],
        )
    return dict(db.execute("SELECT * FROM fit_runs WHERE id = ?", (run_id,)).fetchone())


def schedule_global_rebuild(
    db: sqlite3.Connection,
    project_id: str,
    *,
    kind: str = "rebalance",
    reason: str,
    manage_transaction: bool = True,
) -> dict[str, Any]:
    if kind not in {"rebalance", "capacity_rebuild", "backfill"}:
        raise ValueError(f"invalid global rebuild kind: {kind}")
    existing = _active_fit(db, project_id)
    if existing:
        return dict(existing)
    chunk_watermark = db.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM turn_chunks WHERE project_id = ? AND evicted = 0",
        (project_id,),
    ).fetchone()[0]
    debt_watermark = db.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM fit_debt_events WHERE project_id = ? AND consumed_by IS NULL",
        (project_id,),
    ).fetchone()[0]
    run_id = f"fit_{uuid.uuid4().hex}"
    now = utc_now()
    with db if manage_transaction else nullcontext():
        db.execute(
            """INSERT INTO fit_runs
               (id, project_id, kind, state, layers, chunk_watermark,
                debt_event_watermark, reason, created_at)
               VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)""",
            (run_id, project_id, kind, json.dumps(LAYERS), chunk_watermark, debt_watermark, reason, now),
        )
        db.execute(
            "UPDATE fit_debt SET state = 'queued', updated_at = ? WHERE project_id = ?",
            (now, project_id),
        )
    return dict(db.execute("SELECT * FROM fit_runs WHERE id = ?", (run_id,)).fetchone())


def claim_fit_run(db: sqlite3.Connection, run_id: str, *, resume: bool = False) -> dict[str, Any]:
    row = db.execute("SELECT * FROM fit_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    # Only the project maintenance lock holder may resume a running fit.
    if resume and row["state"] == "running":
        return dict(row)
    _validate_transition(row["state"], "running", FIT_TRANSITIONS, "fit")
    layers = json.loads(row["layers"])
    now = utc_now()
    with db:
        db.execute("UPDATE fit_runs SET state = 'running', started_at = ? WHERE id = ?", (now, run_id))
        db.executemany(
            "UPDATE fit_debt SET state = 'running', updated_at = ? WHERE project_id = ? AND layer = ?",
            [(now, row["project_id"], layer) for layer in layers],
        )
    claimed = db.execute("SELECT * FROM fit_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(claimed) if claimed else {}


def fit_input_chunk_ids(db: sqlite3.Connection, run_id: str, layer: str) -> list[str]:
    if layer not in LAYERS:
        raise ValueError(f"unknown layer: {layer}")
    run = db.execute("SELECT * FROM fit_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise KeyError(run_id)
    state_filter = "AND s.state IN ('unassigned','unlocked')" if run["kind"] == "routine" else ""
    return [
        row["id"]
        for row in db.execute(
            f"""SELECT c.id FROM turn_chunks c
               JOIN chunk_layer_states s ON s.chunk_id = c.id
               WHERE c.project_id = ? AND c.evicted = 0 AND c.seq <= ?
                 AND s.layer = ? {state_filter}
               ORDER BY c.seq""",
            (run["project_id"], run["chunk_watermark"], layer),
        )
    ]


def commit_fit_run(
    db: sqlite3.Connection,
    run_id: str,
    assignments: Mapping[str, Mapping[str, Mapping[str, Any] | str]],
    *,
    manage_transaction: bool = True,
) -> dict[str, Any]:
    run = db.execute("SELECT * FROM fit_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise KeyError(run_id)
    _validate_transition(run["state"], "committed", FIT_TRANSITIONS, "fit")
    layers = json.loads(run["layers"])
    now = utc_now()
    with db if manage_transaction else nullcontext():
        for layer in layers:
            eligible = set(fit_input_chunk_ids(db, run_id, layer))
            if not eligible:
                db.execute(
                    """UPDATE fit_debt_events SET consumed_by = ?
                       WHERE project_id = ? AND layer = ? AND consumed_by IS NULL AND seq <= ?""",
                    (run_id, run["project_id"], layer, run["debt_event_watermark"]),
                )
                remaining = db.execute(
                    "SELECT COUNT(*) FROM fit_debt_events WHERE project_id=? AND layer=? AND consumed_by IS NULL",
                    (run["project_id"], layer),
                ).fetchone()[0]
                db.execute(
                    """UPDATE fit_debt SET debt_count=?, last_completed_chunk_watermark=?,
                       state='idle', updated_at=? WHERE project_id=? AND layer=?""",
                    (remaining, run["chunk_watermark"], now, run["project_id"], layer),
                )
                continue
            epoch = db.execute(
                "SELECT COALESCE(MAX(epoch), 0) + 1 FROM cluster_generations WHERE project_id = ? AND layer = ?",
                (run["project_id"], layer),
            ).fetchone()[0]
            generation_id = stable_id("generation", run["project_id"], layer, epoch, run_id)
            db.execute(
                "UPDATE cluster_generations SET state = 'superseded' WHERE project_id = ? AND layer = ? AND state = 'active'",
                (run["project_id"], layer),
            )
            db.execute(
                """INSERT INTO cluster_generations
                   (id, project_id, layer, epoch, state, fit_run_id, chunk_watermark, created_at, activated_at)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
                (generation_id, run["project_id"], layer, epoch, run_id, run["chunk_watermark"], now, now),
            )
            layer_assignments = assignments.get(layer, {})
            unknown = set(layer_assignments) - eligible
            if unknown:
                raise StateTransitionError(f"fit assigned ineligible chunks at {layer}: {sorted(unknown)}")
            for chunk_id in eligible:
                raw_state = layer_assignments.get(chunk_id, "unassigned")
                state, target_id, confidence = _normalize_layer_state(raw_state)
                db.execute(
                    """UPDATE chunk_layer_states
                       SET state = ?, target_id = ?, membership_confidence = ?, generation_id = ?, updated_at = ?
                       WHERE chunk_id = ? AND layer = ?""",
                    (state, target_id, confidence, generation_id, now, chunk_id, layer),
                )
            db.execute(
                """UPDATE fit_debt_events SET consumed_by = ?
                   WHERE project_id = ? AND layer = ? AND consumed_by IS NULL AND seq <= ?""",
                (run_id, run["project_id"], layer, run["debt_event_watermark"]),
            )
            remaining = db.execute(
                """SELECT COUNT(*) FROM fit_debt_events
                   WHERE project_id = ? AND layer = ? AND consumed_by IS NULL""",
                (run["project_id"], layer),
            ).fetchone()[0]
            last_event = db.execute(
                """SELECT COALESCE(MAX(seq), 0) FROM fit_debt_events
                   WHERE project_id = ? AND layer = ? AND consumed_by = ?""",
                (run["project_id"], layer, run_id),
            ).fetchone()[0]
            db.execute(
                """UPDATE fit_debt
                   SET debt_count = ?, last_completed_chunk_watermark = ?,
                       last_consumed_event_seq = MAX(last_consumed_event_seq, ?),
                       state = 'idle', updated_at = ?
                   WHERE project_id = ? AND layer = ?""",
                (remaining, run["chunk_watermark"], last_event, now, run["project_id"], layer),
            )
        db.execute(
            "UPDATE fit_runs SET state = 'committed', completed_at = ? WHERE id = ?",
            (now, run_id),
        )
        db.execute(
            """UPDATE fit_retry_state
               SET consecutive_failures=0, next_retry_at=NULL, circuit_open=0,
                   last_failed_run_id=NULL, last_failed_chunk_watermark=NULL,
                   last_failed_debt_event_watermark=NULL, last_error=NULL, updated_at=?
               WHERE project_id=?""",
            (now, run["project_id"]),
        )
    committed = db.execute("SELECT * FROM fit_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(committed) if committed else {}


def fail_fit_run(db: sqlite3.Connection, run_id: str, error: str) -> None:
    run = db.execute("SELECT * FROM fit_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise KeyError(run_id)
    _validate_transition(run["state"], "failed", FIT_TRANSITIONS, "fit")
    layers = json.loads(run["layers"])
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds")
    retry = fit_retry_status(db, run["project_id"])
    failures = int(retry["consecutive_failures"]) + 1
    delay_seconds = min(FIT_RETRY_MAX_SECONDS, FIT_RETRY_BASE_SECONDS * (2 ** (failures - 1)))
    next_retry_at = (now_dt + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
    circuit_open = int(failures >= FIT_RETRY_CIRCUIT_THRESHOLD)
    with db:
        db.execute(
            "UPDATE fit_runs SET state = 'failed', error = ?, completed_at = ? WHERE id = ?",
            (error, now, run_id),
        )
        db.executemany(
            "UPDATE fit_debt SET state = 'idle', updated_at = ? WHERE project_id = ? AND layer = ?",
            [(now, run["project_id"], layer) for layer in layers],
        )
        db.execute(
            """UPDATE fit_retry_state
               SET consecutive_failures=?, next_retry_at=?, circuit_open=?,
                   last_failed_run_id=?, last_failed_chunk_watermark=?,
                   last_failed_debt_event_watermark=?, last_error=?, updated_at=?
               WHERE project_id=?""",
            (
                failures,
                next_retry_at,
                circuit_open,
                run_id,
                run["chunk_watermark"],
                run["debt_event_watermark"],
                error,
                now,
                run["project_id"],
            ),
        )


def frontier_chunks(db: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            """SELECT c.*, 'span' AS unassigned_layers
               FROM turn_chunks c
               JOIN chunk_layer_states s ON s.chunk_id = c.id
                 AND s.layer = 'span' AND s.state = 'unassigned'
               WHERE c.project_id = ? AND c.evicted = 0
               GROUP BY c.id ORDER BY c.seq""",
            (project_id,),
        )
    ]


def configure_retention(
    db: sqlite3.Connection,
    project_id: str,
    *,
    high_chunks: int,
    low_chunks: int,
    byte_ceiling: int | None = None,
) -> None:
    if high_chunks <= 0 or low_chunks < 0 or low_chunks >= high_chunks:
        raise ValueError("retention requires 0 <= low_chunks < high_chunks")
    with db:
        db.execute(
            """UPDATE retention_state
               SET high_chunks = ?, low_chunks = ?, byte_ceiling = ?, updated_at = ?
               WHERE project_id = ?""",
            (high_chunks, low_chunks, byte_ceiling, utc_now(), project_id),
        )


def plan_capacity_eviction(db: sqlite3.Connection, project_id: str) -> list[str]:
    retention = db.execute("SELECT * FROM retention_state WHERE project_id = ?", (project_id,)).fetchone()
    if retention is None:
        raise KeyError(project_id)
    totals = db.execute(
        """SELECT COUNT(*) AS chunks, COALESCE(SUM(byte_count), 0) AS bytes
           FROM turn_chunks WHERE project_id = ? AND evicted = 0""",
        (project_id,),
    ).fetchone()
    over_chunks = totals["chunks"] > retention["high_chunks"]
    over_bytes = retention["byte_ceiling"] is not None and totals["bytes"] > retention["byte_ceiling"]
    if not over_chunks and not over_bytes:
        return []
    remaining_chunks = totals["chunks"]
    remaining_bytes = totals["bytes"]
    selected: list[str] = []
    rows = db.execute(
        """SELECT t.id, t.created_at, COUNT(c.id) AS chunks, COALESCE(SUM(c.byte_count), 0) AS bytes
           FROM turn_ingestion t
           JOIN turn_chunks c ON c.turn_id = t.id AND c.evicted = 0
           WHERE t.project_id = ? AND t.state = 'indexed' AND t.protected = 0
           GROUP BY t.id ORDER BY t.created_at, t.id""",
        (project_id,),
    ).fetchall()
    for row in rows:
        chunks_ok = remaining_chunks <= retention["low_chunks"]
        bytes_ok = retention["byte_ceiling"] is None or remaining_bytes <= retention["byte_ceiling"]
        if chunks_ok and bytes_ok:
            break
        selected.append(row["id"])
        remaining_chunks -= row["chunks"]
        remaining_bytes -= row["bytes"]
    chunks_ok = remaining_chunks <= retention["low_chunks"]
    bytes_ok = retention["byte_ceiling"] is None or remaining_bytes <= retention["byte_ceiling"]
    if not selected or not chunks_ok or not bytes_ok:
        raise StateTransitionError("capacity exceeded but evictable complete turns cannot reach the retention target")
    return selected


def mark_turns_evicted(
    db: sqlite3.Connection,
    project_id: str,
    turn_ids: Iterable[str],
    *,
    eviction_generation: str,
    reason: str = "capacity",
) -> list[str]:
    selected = list(dict.fromkeys(turn_ids))
    now = utc_now()
    with db:
        for turn_id in selected:
            turn = db.execute(
                "SELECT * FROM turn_ingestion WHERE id = ? AND project_id = ?",
                (turn_id, project_id),
            ).fetchone()
            if turn is None:
                raise KeyError(turn_id)
            if turn["state"] != "indexed" or turn["protected"]:
                raise StateTransitionError(f"turn is not evictable: {turn_id}")
            db.execute(
                """INSERT INTO evicted_turns
                   (turn_id, project_id, content_hash, eviction_generation, reason, evicted_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (turn_id, project_id, turn["content_hash"], eviction_generation, reason, now),
            )
            db.execute("UPDATE turn_chunks SET evicted = 1 WHERE turn_id = ?", (turn_id,))
            db.execute(
                "UPDATE turn_ingestion SET state = 'evicted', updated_at = ?, completed_at = ? WHERE id = ?",
                (now, now, turn_id),
            )
    return selected


def state_snapshot(db: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    active_fit = _active_fit(db, project_id)
    return {
        "project_id": project_id,
        "turns": {
            row["state"]: row["count"]
            for row in db.execute(
                "SELECT state, COUNT(*) AS count FROM turn_ingestion WHERE project_id = ? GROUP BY state",
                (project_id,),
            )
        },
        "live_chunks": db.execute(
            "SELECT COUNT(*) FROM turn_chunks WHERE project_id = ? AND evicted = 0",
            (project_id,),
        ).fetchone()[0],
        "frontier_chunks": len(frontier_chunks(db, project_id)),
        "fit_debt": debt_status(db, project_id),
        "active_fit": dict(active_fit) if active_fit else None,
    }
