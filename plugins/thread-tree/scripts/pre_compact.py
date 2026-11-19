#!/usr/bin/env python3
"""Fail-open PreCompact recovery hook entrypoint."""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
from pathlib import Path

from thread_tree import connect_db, data_dir, load_scope_config, parse_transcript_lines, utc_now
from thread_tree_pipeline import enqueue_transcript
from thread_tree_runtime import detached_process_options, worker_command
from thread_tree_scope import scope_decision
from thread_tree_state import project_id_for


def main() -> int:
    try:
        event = json.load(sys.stdin)
        transcript = event.get("transcript_path")
        if not transcript:
            raise RuntimeError("PreCompact event did not include transcript_path")
        transcript_path = Path(str(transcript))
        parsed = parse_transcript_lines(transcript_path, 1, 1)
        resolved_cwd = str(event.get("cwd") or parsed.get("cwd") or "").strip()
        resolved_thread_id = str(event.get("session_id") or parsed.get("thread_id") or "").strip()
        activation = load_scope_config()
        db = connect_db()
        try:
            project_id = project_id_for(resolved_cwd) if resolved_cwd else None
            row = db.execute("SELECT updated_at FROM projects WHERE id = ?", (project_id,)).fetchone() if project_id else None
            decision = scope_decision(
                activation,
                resolved_cwd,
                resolved_thread_id,
                last_activity_at=row["updated_at"] if row else None,
            )
        finally:
            db.close()
        if not decision["active"]:
            print(json.dumps({"continue": True, "suppressOutput": True}))
            return 0
        result = enqueue_transcript(
            transcript_path,
            supplied_thread_id=resolved_thread_id or None,
            supplied_cwd=resolved_cwd or None,
            include_active=True,
            mark_incomplete_partial=True,
            enforce_scope=True,
        )
        if result.get("scope_blocked"):
            print(json.dumps({"continue": True, "suppressOutput": True}))
            return 0
        worker = Path(__file__).with_name("thread_tree_worker.py")
        subprocess.Popen(
            worker_command(worker, result["project_id"]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **detached_process_options(),
        )
        print(
            json.dumps(
                {
                    "continue": True,
                    "systemMessage": (
                        "Context Saver auto-indexing is active for this project. "
                        f"Preserving about {result.get('approx_tokens', 0):,} conversation tokens "
                        "from turns queued before compaction. "
                        "Send Context Saver off to pause it for this chat."
                    ),
                }
            )
        )
    except Exception as error:
        error_record = {
            "timestamp": utc_now(),
            "error": str(error),
            "traceback": traceback.format_exc(limit=8),
        }
        try:
            with (data_dir() / "hook-errors.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(error_record, ensure_ascii=False) + "\n")
        except Exception:
            pass
        print(
            json.dumps(
                {
                    "continue": True,
                    "systemMessage": (
                        "Context Saver auto-indexing is active for this project, but this indexing run failed open. "
                        "A later backfill can recover this window. Send Context Saver off to pause it for this chat."
                    ),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
