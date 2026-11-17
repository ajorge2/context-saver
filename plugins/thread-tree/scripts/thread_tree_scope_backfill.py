#!/usr/bin/env python3
"""Queue explicitly selected existing chats after onboarding.

This process is detached from the viewer request.  Queueing is idempotent and
the normal per-project worker performs all chunking and embedding.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_scope as scope
from thread_tree_runtime import worker_command


def launch_worker(project_id: str) -> None:
    worker = Path(__file__).with_name("thread_tree_worker.py")
    subprocess.Popen(
        worker_command(worker, project_id),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main() -> int:
    lock_path = thread_tree.data_dir() / "scope-backfill.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_path.mkdir()
    except FileExistsError:
        try:
            if time.time() - lock_path.stat().st_mtime <= 3_600:
                return 0
            lock_path.rmdir()
            lock_path.mkdir()
        except (FileNotFoundError, OSError):
            return 0

    try:
        config = thread_tree.load_scope_config()
        if not config.get("configured") or config.get("paused"):
            return 0
        selected = {
            project["path"]: project
            for project in config.get("projects", [])
            if project.get("backfillExisting", True)
        }
        if not selected or not thread_tree.DEFAULT_SESSION_ROOT.exists():
            return 0

        touched_projects: set[str] = set()
        for transcript in thread_tree.DEFAULT_SESSION_ROOT.rglob("rollout-*.jsonl"):
            metadata = thread_tree._session_metadata(transcript)
            if not metadata or metadata["cwd"] not in selected:
                continue
            decision = scope.scope_decision(
                config,
                metadata["cwd"],
                metadata["id"],
            )
            if not decision["active"]:
                continue
            try:
                result = pipeline.enqueue_transcript(
                    transcript,
                    supplied_thread_id=metadata["id"],
                    supplied_cwd=metadata["cwd"],
                    include_active=False,
                    enforce_scope=True,
                )
            except Exception:
                # One malformed or concurrently written rollout cannot block
                # the remaining explicitly selected chats.
                continue
            if result.get("queued_turns"):
                touched_projects.add(str(result["project_id"]))

        for project_id in touched_projects:
            launch_worker(project_id)
    finally:
        try:
            os.rmdir(lock_path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

