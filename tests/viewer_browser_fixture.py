#!/usr/bin/env python3
"""Launch the real viewer over a disposable, purely synthetic SQLite store."""

from __future__ import annotations

import _support

import hashlib
import json
import signal
import sqlite3
import sys
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import system_validation as fixtures
import thread_tree
import thread_tree_pipeline as pipeline


def snapshot(path: Path) -> str:
    """Hash stored content and provenance, including the full-text projection."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        hasher = hashlib.sha256()
        for table in (
            "turn_ingestion", "turn_chunks", "turn_chunks_fts", "staged_user_prompts",
            "fit_debt_events", "semantic_nodes", "semantic_edges", "semantic_node_memberships",
        ):
            hasher.update(table.encode())
            for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                hasher.update(json.dumps(row, default=str, separators=(",", ":")).encode())
        return hasher.hexdigest()


def serve(*, fail_first_refresh: bool = False) -> None:
    with fixtures.isolated_runtime() as (root, data):
        config_path = data / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["embedding_provider"] = "disabled"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        selected = root / "Selected fixture"
        excluded = root / "Unselected fixture"
        selected.mkdir()
        excluded.mkdir()
        fixtures.activate_projects(selected, excluded)
        seeded = []
        sources = []
        registry_chats = []
        for folder, title, question, reply in (
            (selected, "Nimbus lookup", "Which value does durabilityproof901 resolve to?", "durabilityproof901 is confirmed as Nimbus Blue."),
            (excluded, "Violet lookup", "What is the private result for durabilityproof901?", "durabilityproof901 from the hidden project is Violet Quartz."),
            (selected, "Amber follow-up", "What survived after removal?", "The separate chat keeps evidence in Amber Glass."),
        ):
            transcript = folder / f"fixture-{len(seeded)}.jsonl"
            thread_id = f"fixture-chat-{len(seeded)}"
            fixtures.write_codex_transcript(transcript, folder, thread_id, [(question, reply)])
            project = pipeline.enqueue_transcript(transcript)
            processed = pipeline.process_project(project["project_id"])
            if processed["failures"] or processed["processed_turns"] != 1:
                raise RuntimeError("Could not seed fixture turn")
            seeded.append(project["project_id"])
            sources.append([str(transcript), hashlib.sha256(transcript.read_bytes()).hexdigest()])
            registry_chats.append((thread_id, question, str(folder.resolve()), 0, 0, title))
        with closing(sqlite3.connect(root / "codex-test-state.sqlite")) as registry, registry:
            registry.executescript("""
                CREATE TABLE project_roots (path TEXT);
                CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at_ms INTEGER, updated_at INTEGER, name TEXT);
            """)
            registry.executemany("INSERT INTO project_roots VALUES (?)", [(str(path.resolve()),) for path in (selected, excluded)])
            registry.executemany("INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?)", registry_chats)
        fixtures.activate_projects(selected)
        refresh_attempts = 0

        def rebuild_command(worker, job_id, project_ids):
            nonlocal refresh_attempts
            refresh_attempts += 1
            executable = root / "intentionally-missing-python" if fail_first_refresh and refresh_attempts == 1 else sys.executable
            return [str(executable), str(worker), job_id, *project_ids]

        with patch.object(thread_tree, "_connection_rebuild_command", rebuild_command), ThreadingHTTPServer(
            ("127.0.0.1", 0), thread_tree.ViewerHandler,
        ) as server:
            print(json.dumps({
                "origin": f"http://127.0.0.1:{server.server_port}",
                "db": str(thread_tree.db_path()),
                "digest": snapshot(thread_tree.db_path()),
                "excludedProject": seeded[1],
                "selectedProject": seeded[0],
                "sources": sources,
            }), flush=True)
            server.serve_forever()


def stop(_signum: int, _frame: object) -> None:
    raise SystemExit(0)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--snapshot":
        print(snapshot(Path(sys.argv[2])))
    else:
        signal.signal(signal.SIGTERM, stop)
        serve(fail_first_refresh="--fail-first-refresh" in sys.argv[1:])
