#!/usr/bin/env python3
"""Fast, fail-open UserPromptSubmit hook for exact prompt staging."""

from __future__ import annotations

import json
import sys
import traceback
from contextlib import closing

from thread_tree import connect_db, data_dir, load_scope_config, scope_mutation_lock, utc_now
from thread_tree_pipeline import _project_config
from thread_tree_scope import scope_decision
from thread_tree_state import ensure_project, observe_session, project_id_for, stage_user_prompt


def main() -> int:
    try:
        event = json.load(sys.stdin)
        prompt = str(event.get("prompt") or "").strip()
        cwd = str(event.get("cwd") or "").strip()
        thread_id = str(event.get("session_id") or "").strip()
        turn_id = str(event.get("turn_id") or "").strip() or None
        if not prompt or not cwd or not thread_id:
            raise RuntimeError("UserPromptSubmit requires prompt, cwd, and session_id")
        project_id = project_id_for(cwd)
        config = _project_config()
        with scope_mutation_lock(), closing(connect_db()) as db:
            activation = load_scope_config()
            row = db.execute("SELECT updated_at FROM projects WHERE id = ?", (project_id,)).fetchone()
            decision = scope_decision(
                activation,
                cwd,
                thread_id,
                last_activity_at=row["updated_at"] if row else None,
            )
            # Session identity is the minimum metadata needed to make an
            # explicit first plugin invocation deterministic. Do not persist
            # prompt text until the user's saved scope permits ingestion. For
            # active chats, let the existing project/staging transaction
            # commit this observation to avoid a second synchronous fsync.
            observe_session(
                db,
                project_root=cwd,
                thread_id=thread_id,
                transcript_path=str(event.get("transcript_path") or "") or None,
                commit=not decision["active"],
            )
            if not decision["active"]:
                print(json.dumps({"continue": True, "suppressOutput": True}))
                return 0
            ensure_project(
                db,
                project_id,
                cwd,
                fit_thresholds=config["fit_thresholds"],
                high_chunks=int(config.get("retention_high_chunks", 10_000)),
                low_chunks=int(config.get("retention_low_chunks", 8_500)),
                byte_ceiling=config.get("retention_byte_ceiling"),
            )
            stage_user_prompt(
                db,
                codex_turn_id=turn_id,
                project_id=project_id,
                thread_id=thread_id,
                prompt=prompt,
            )
        print(json.dumps({"continue": True, "suppressOutput": True}))
    except Exception as error:
        record = {
            "timestamp": utc_now(),
            "hook": "UserPromptSubmit",
            "error": str(error),
            "traceback": traceback.format_exc(limit=8),
        }
        try:
            with (data_dir() / "hook-errors.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass
        print(json.dumps({"continue": True, "suppressOutput": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
