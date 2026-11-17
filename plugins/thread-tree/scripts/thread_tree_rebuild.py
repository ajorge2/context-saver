#!/usr/bin/env python3
"""Rebuild the remaining semantic tree after a connection is removed."""

from __future__ import annotations

import sys
from contextlib import closing

import thread_tree
import thread_tree_pipeline as pipeline
from thread_tree_state import exclusive_process_lock


def main(arguments: list[str]) -> int:
    if len(arguments) < 2:
        return 2
    job_id, *project_ids = arguments
    with exclusive_process_lock(thread_tree.connection_refresh_lock_path(job_id)):
        status = thread_tree.connection_refresh_status(job_id, check_worker=False)
        if status["state"] == "complete":
            return 0
        retryable = bool(status.get("retryable"))
        thread_tree.write_connection_refresh_job(
            job_id, "running", project_ids, tracks_worker=True, retryable=retryable,
        )
        try:
            with closing(thread_tree.connect_db()) as db:
                for project_id in dict.fromkeys(project_ids):
                    if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                        continue
                    pipeline.rebuild_project(db, project_id, reason="connection removed", operation_id=job_id)
        except Exception:
            thread_tree.write_connection_refresh_job(
                job_id, "failed", project_ids, retryable=retryable,
                error="The remaining memory could not be refreshed.",
            )
            return 1
        thread_tree.write_connection_refresh_job(job_id, "complete", project_ids, retryable=retryable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
