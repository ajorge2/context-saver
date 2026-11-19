#!/usr/bin/env python3
"""Model-callable Thread Tree tool handlers, independent of MCP transport."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_scope as scope
import thread_tree_state as state


def _activate_scope_for_chat(project_root: str, thread_id: str) -> dict[str, Any]:
    """Treat an explicit plugin invocation as consent for this chat only."""

    with thread_tree.scope_mutation_lock():
        return _activate_scope_for_chat_locked(project_root, thread_id)


def _activate_scope_for_chat_locked(project_root: str, thread_id: str) -> dict[str, Any]:
    canonical = str(Path(project_root).expanduser().resolve())
    config = thread_tree.load_scope_config()
    if config.get("loadError"):
        raise ValueError(str(config["loadError"]))
    projects = [dict(item) for item in config.get("projects", [])]
    selected = next((item for item in projects if item.get("path") == canonical), None)
    now = state.utc_now()
    if selected and (
        selected.get("disconnectPending") or thread_id in selected.get("pendingDisconnectChatIds", [])
    ):
        raise ValueError("Disconnection is pending. Retry Disconnect before reactivating this chat.")
    if selected is None:
        projects.append({
            "path": canonical,
            "includeNewChats": False,
            "includedChatIds": [thread_id],
            "excludedChatIds": [],
            "backfillExisting": True,
            "activatedAt": now,
        })
    else:
        selected["excludedChatIds"] = [
            identifier for identifier in selected.get("excludedChatIds", [])
            if str(identifier) != thread_id
        ]
        if not selected.get("includeNewChats", True):
            selected["includedChatIds"] = list(dict.fromkeys([
                *[str(identifier) for identifier in selected.get("includedChatIds", [])],
                thread_id,
            ]))
        selected["activatedAt"] = now
    return thread_tree.save_scope_config({
        "schemaVersion": 1,
        "configured": True,
        "paused": bool(config.get("paused", False)),
        "projects": projects,
        "pausePolicy": dict(config.get("pausePolicy") or {
            "mode": "manual", "pauseOn": None, "inactivityDays": 30,
        }),
        "setupAt": config.get("setupAt"),
        "updatedAt": config.get("updatedAt"),
    })


def _resolve_current_session(
    *,
    project_root: str | None = None,
    thread_id: str | None = None,
) -> dict[str, str] | None:
    """Resolve the chat observed by the prompt hook without reading its content."""

    requested_root = (
        str(Path(project_root).expanduser().resolve())
        if project_root and project_root.strip()
        else None
    )
    requested_thread = str(
        thread_id
        or os.environ.get("CODEX_THREAD_ID")
        or os.environ.get("CODEX_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or ""
    ).strip() or None
    db = thread_tree.connect_db()
    observed: dict[str, str] | None = None
    try:
        clauses: list[str] = []
        values: list[str] = []
        if requested_root:
            clauses.append("project_root = ?")
            values.append(requested_root)
        if requested_thread:
            clauses.append("thread_id = ?")
            values.append(requested_thread)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        row = db.execute(
            f"""SELECT * FROM session_observations {where}
                ORDER BY observed_at DESC, rowid DESC LIMIT 1""",
            tuple(values),
        ).fetchone()
        if row:
            observed = {
                "project_root": str(row["project_root"]),
                "thread_id": str(row["thread_id"]),
                "transcript_path": str(row["transcript_path"] or ""),
            }
            if observed["transcript_path"]:
                return observed
            requested_root = requested_root or observed["project_root"]
            requested_thread = requested_thread or observed["thread_id"]
    finally:
        db.close()

    # Codex exposes the current thread ID to the local MCP process. Resolve its
    # rollout path from the metadata-only discovery cache when the hook has not
    # yet supplied a transcript path.
    if requested_thread:
        metadata_rows, _diagnostics = thread_tree.discover_session_metadata()
        matches = [
            row for row in metadata_rows
            if str(row.get("id") or "") == requested_thread
            and (not requested_root or str(row.get("cwd") or "") == requested_root)
        ]
        if matches:
            match = max(matches, key=lambda item: str(item.get("timestamp") or ""))
            return {
                "project_root": str(match["cwd"]),
                "thread_id": requested_thread,
                "transcript_path": str(match.get("transcriptPath") or ""),
            }
    return observed


def _control_session(
    *, project_root: str | None = None, thread_id: str | None = None,
) -> dict[str, str] | None:
    """Resolve only an exact host identity; never act on the latest other chat."""
    identifier = str(thread_id or os.environ.get("CODEX_THREAD_ID")
                     or os.environ.get("CODEX_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID") or "").strip()
    if not identifier or len(identifier) > 240 or "${" in identifier:
        return None
    canonical = str(Path(project_root).expanduser().resolve()) if project_root and project_root.strip() else None
    with closing(thread_tree.connect_db()) as db:
        rows = db.execute(
            "SELECT project_root,thread_id,transcript_path FROM session_observations WHERE thread_id=?",
            (identifier,),
        ).fetchall()
    matches = [dict(row) for row in rows if canonical is None or row["project_root"] == canonical]
    if len(matches) == 1:
        return {key: str(value or "") for key, value in matches[0].items()}
    if len(matches) > 1:
        return None
    # Supplying an exact project and chat can disconnect before any transcript
    # is available. Reconnection validates a transcript before enabling it.
    if canonical:
        session = _resolve_current_session(project_root=canonical, thread_id=identifier)
        return session or {"project_root": canonical, "thread_id": identifier, "transcript_path": ""}
    session = _resolve_current_session(thread_id=identifier)
    return session


def _control_reply(session: Mapping[str, Any], status: str, *, ok: bool = True,
                   message: str | None = None, **extra: Any) -> dict[str, Any]:
    messages = {
        "off": "Context Saver is OFF for this chat. New messages won’t be saved and saved history won’t be used here. Existing saved context is kept. Send on to reconnect.",
        "on": "Context Saver is ON for this chat. Saving and history lookup are connected.",
    }
    return {"ok": ok, "status": status, "enabled": status == "on", "scope": "chat",
            "project_root": session.get("project_root"), "thread_id": session.get("thread_id"),
            "message": message or messages.get(status, "Context Saver is not connected for this chat."), **extra}


def _prefix_hash(path: Path, lines: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for _ in range(lines):
            line = handle.readline()
            if not line:
                raise ValueError("The chat transcript was shortened; Context Saver remains off.")
            digest.update(line)
    return digest.hexdigest()


def control_current_chat(
    action: str, *, project_root: str | None = None, thread_id: str | None = None,
) -> dict[str, Any]:
    """Explicit reversible chat switch, separate from destructive disconnection."""
    if action not in {"off", "on", "status"}:
        raise ValueError("action must be off, on, or status")
    session = _control_session(project_root=project_root, thread_id=thread_id)
    if session is None:
        return _control_reply({}, "session_unavailable", ok=False,
            message="Context Saver could not identify this chat safely. Supply the current project and exact chat ID; no connection was changed.")
    canonical, identifier = session["project_root"], session["thread_id"]
    project_id = state.project_id_for(canonical)
    with thread_tree.scope_mutation_lock(), closing(thread_tree.connect_db()) as db:
        control = state.chat_control(db, project_id, identifier)
        config = thread_tree.load_scope_config()
        selected = scope.selected_project(config, canonical)
        project_row = db.execute("SELECT updated_at FROM projects WHERE id=?", (project_id,)).fetchone()
        decision = scope.scope_decision(config, canonical, identifier,
            last_activity_at=str(project_row["updated_at"] or "") if project_row else None)
        if action == "status":
            enabled = not (control and not control["enabled"]) and decision["active"]
            return _control_reply(session, "on" if enabled else "off", reason=decision["reason"])
        if config.get("loadError"):
            return _control_reply(session, "off", ok=False, message="Context Saver could not read its connection settings. No connection was changed.")
        if action == "off":
            state.set_chat_control(db, project_id, identifier, enabled=False,
                capture_after_line=int(control["capture_after_line"]) if control else 0,
                transcript_path=control.get("transcript_path") if control else None,
                prefix_hash=control.get("prefix_hash") if control else None)
            if selected is not None and identifier not in selected.get("excludedChatIds", []):
                selected["excludedChatIds"] = [*selected.get("excludedChatIds", []), identifier]
                thread_tree.save_scope_config(config)
            return _control_reply(session, "off")
        if config.get("paused") or (selected and (
            selected.get("paused") or selected.get("disconnectPending")
            or identifier in selected.get("pendingDisconnectChatIds", [])
        )):
            return _control_reply(session, "paused", ok=False,
                message="Context Saver is still off for this chat. Resume its project or finish the pending disconnection in Connections before reconnecting.")
        resume_data = None
        if control and not control["enabled"]:
            path = Path(session.get("transcript_path") or "").expanduser().resolve()
            if not session.get("transcript_path") or not path.is_file():
                return _control_reply(session, "transcript_unavailable", ok=False,
                    message="Context Saver remains OFF. Its current chat transcript is unavailable; retry on from this chat after the host supplies it.")
            parsed = thread_tree.parse_transcript_lines(path)
            if str(parsed.get("thread_id") or "") != identifier or str(Path(str(parsed.get("cwd") or "")).expanduser().resolve()) != canonical:
                return _control_reply(session, "transcript_unavailable", ok=False,
                    message="Context Saver remains OFF because the transcript does not match this chat and project.")
            old_cutoff = int(control.get("capture_after_line") or 0)
            try:
                if old_cutoff and _prefix_hash(path, old_cutoff) != control.get("prefix_hash"):
                    raise ValueError("The chat transcript was replaced; Context Saver remains off.")
                cutoff = int(parsed.get("last_line") or 0)
                prefix = _prefix_hash(path, cutoff)
            except (OSError, ValueError) as error:
                return _control_reply(session, "transcript_unavailable", ok=False, message=str(error))
            resume_data = {"capture_after_line": cutoff, "transcript_path": str(path), "prefix_hash": prefix}
        _activate_scope_for_chat_locked(canonical, identifier)
        # Keep the durable off guard until the scope file is safely written.
        # A failed on never gives ordinary prepare permission to reconnect.
        if resume_data is not None:
            control = state.set_chat_control(db, project_id, identifier, enabled=True, **resume_data)
        enabled_generation = int(control["generation"]) if control else 0
    try:
        preparation = prepare_current_chat(project_root=canonical, thread_id=identifier)
    except Exception:
        # Do not echo transcript/provider exceptions into the control reply.
        # A failed reconnect must leave the durable switch off.
        preparation = {"status": "failed", "reason": "preparation_failed"}
    if preparation.get("status") != "ready":
        with thread_tree.scope_mutation_lock(), closing(thread_tree.connect_db()) as db:
            current = state.chat_control(db, project_id, identifier)
            if (int(current["generation"]) if current else 0) == enabled_generation:
                state.set_chat_control(db, project_id, identifier, enabled=False,
                    capture_after_line=int(current.get("capture_after_line") or 0) if current else 0,
                    transcript_path=current.get("transcript_path") if current else None,
                    prefix_hash=current.get("prefix_hash") if current else None)
                config = thread_tree.load_scope_config()
                selected = scope.selected_project(config, canonical)
                if selected is not None and identifier not in selected.get("excludedChatIds", []):
                    selected["excludedChatIds"] = [*selected.get("excludedChatIds", []), identifier]
                    thread_tree.save_scope_config(config)
        return _control_reply(session, "off", ok=False, preparation=preparation,
            message="Context Saver remains OFF because it could not finish reconnecting this chat. Retry on.")
    return _control_reply(session, "on", preparation=preparation)


def prepare_current_chat(
    *,
    project_root: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Initialize the current chat once, then return immediately on later calls."""

    invoked_at = state.plugin_invocation_time()
    exact_id = str(thread_id or os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
                   or os.environ.get("CLAUDE_SESSION_ID") or "").strip()
    if not exact_id:
        with closing(thread_tree.connect_db()) as db:
            if db.execute("SELECT 1 FROM chat_plugin_controls WHERE enabled=0 LIMIT 1").fetchone():
                return {**_control_reply({}, "session_unavailable", ok=False,
                    message="Context Saver needs this chat's exact ID before preparing it because a chat is switched off. No connection was changed."),
                    "first_invocation": False, "continue_with_user_request": True}
    session = _resolve_current_session(project_root=project_root, thread_id=exact_id or None)
    if session is None:
        exact = _control_session(project_root=project_root, thread_id=thread_id)
        if exact:
            with thread_tree.scope_mutation_lock(), closing(thread_tree.connect_db()) as db:
                control = state.chat_control(db, state.project_id_for(exact["project_root"]), exact["thread_id"])
                if control and not control["enabled"]:
                    return {**_control_reply(exact, "off"), "first_invocation": False,
                            "continue_with_user_request": True}
        return {
            "status": "session_unavailable",
            "first_invocation": False,
            "continue_with_user_request": True,
            "message": "Context Saver could not identify the current chat; continue with the user's request.",
        }

    canonical = session["project_root"]
    identifier = session["thread_id"]
    project_id = state.project_id_for(canonical)
    with thread_tree.scope_mutation_lock(), closing(thread_tree.connect_db()) as db:
        control = state.chat_control(db, project_id, identifier)
        preparation_generation = int(control["generation"]) if control else 0
        if control and not control["enabled"]:
            return {**_control_reply(session, "off"), "first_invocation": False,
                    "continue_with_user_request": True}
        _activate_scope_for_chat_locked(canonical, identifier)
        config = thread_tree.load_scope_config()
        project_row = db.execute(
            "SELECT updated_at FROM projects WHERE id=?", (project_id,),
        ).fetchone()
        decision = scope.scope_decision(
            config,
            canonical,
            identifier,
            last_activity_at=str(project_row["updated_at"] or "") if project_row else None,
        )
        existing = state.chat_activation(db, project_id, identifier)
        if not decision["active"]:
            return {
                "status": "paused",
                "reason": decision["reason"],
                "first_invocation": existing is None,
                "project_root": canonical,
                "thread_id": identifier,
                "continue_with_user_request": True,
            }
        if existing and existing["state"] == "active":
            activation, _first = state.begin_chat_activation(
                db,
                project_id=project_id,
                thread_id=identifier,
                transcript_path=session.get("transcript_path") or None,
                invoked_at=invoked_at,
            )
            state.record_project_invocation(db, project_id, invoked_at)
            return {
                "status": "ready",
                "first_invocation": False,
                "project_root": canonical,
                "thread_id": identifier,
                "indexed_through_line": int(activation.get("indexed_through_line") or 0),
                "continue_with_user_request": True,
            }

    transcript_path = session.get("transcript_path") or ""
    if not transcript_path:
        db = thread_tree.connect_db()
        try:
            row = db.execute(
                """SELECT transcript_path FROM turn_ingestion
                   WHERE project_id=? AND thread_id=? AND transcript_path IS NOT NULL
                   ORDER BY COALESCE(line_end, 0) DESC LIMIT 1""",
                (project_id, identifier),
            ).fetchone()
            transcript_path = str(row["transcript_path"] or "") if row else ""
        finally:
            db.close()
    path = Path(transcript_path).expanduser().resolve() if transcript_path else None
    if path is None or not path.is_file():
        return {
            "status": "transcript_unavailable",
            "first_invocation": True,
            "project_root": canonical,
            "thread_id": identifier,
            "continue_with_user_request": True,
            "message": "Context Saver could not locate this chat's transcript; continue with the user's request.",
        }

    parsed = thread_tree.parse_transcript_lines(path)
    if parsed.get("thread_id") and str(parsed["thread_id"]) != identifier:
        raise ValueError("resolved transcript does not belong to the current chat")
    if parsed.get("cwd") and str(Path(str(parsed["cwd"])).expanduser().resolve()) != canonical:
        raise ValueError("resolved transcript does not belong to the current project")

    with thread_tree.scope_mutation_lock(), closing(thread_tree.connect_db()) as db:
        current_control = state.chat_control(db, project_id, identifier)
        if (int(current_control["generation"]) if current_control else 0) != preparation_generation:
            return {**_control_reply(session, "off"), "reason": "connection_changed_during_preparation",
                    "first_invocation": False, "continue_with_user_request": True}
        project_row = db.execute("SELECT updated_at FROM projects WHERE id=?", (project_id,)).fetchone()
        decision = scope.scope_decision(
            thread_tree.load_scope_config(), canonical, identifier,
            last_activity_at=str(project_row["updated_at"] or "") if project_row else None,
        )
        if not decision["active"]:
            return {
                "status": "paused",
                "reason": decision["reason"],
                "first_invocation": False,
                "continue_with_user_request": True,
            }
        _activation, first_invocation = state.begin_chat_activation(
            db,
            project_id=project_id,
            thread_id=identifier,
            transcript_path=str(path),
            invoked_at=invoked_at,
        )
        # Another first-invocation worker may already have queued this project.
        # Otherwise its accepted activation stamp is merged after enqueue.
        state.record_project_invocation(db, project_id, invoked_at)
    if not first_invocation:
        return {
            "status": "ready",
            "first_invocation": False,
            "project_root": canonical,
            "thread_id": identifier,
            "continue_with_user_request": True,
        }

    queued = pipeline.enqueue_transcript(
        path,
        supplied_thread_id=identifier,
        supplied_cwd=canonical,
        include_active=False,
        enforce_scope=True,
    )
    if queued.get("scope_blocked"):
        return {
            "status": "paused",
            "reason": queued["reason"],
            "first_invocation": first_invocation,
            "continue_with_user_request": True,
        }
    with thread_tree.scope_mutation_lock(), closing(thread_tree.connect_db()) as db:
        project_row = db.execute("SELECT updated_at FROM projects WHERE id=?", (project_id,)).fetchone()
        decision = scope.scope_decision(
            thread_tree.load_scope_config(), canonical, identifier,
            last_activity_at=str(project_row["updated_at"] or "") if project_row else None,
        )
        if decision["active"]:
            state.record_project_invocation(db, project_id, invoked_at)
    processed = pipeline.process_project(project_id, thread_id=identifier)
    failures = list(processed.get("failures") or [])
    db = thread_tree.connect_db()
    try:
        with thread_tree.scope_mutation_lock():
            control = state.chat_control(db, project_id, identifier)
            if (control and not control["enabled"]) or (int(control["generation"]) if control else 0) != preparation_generation:
                return {**_control_reply(session, "off"), "first_invocation": first_invocation,
                        "continue_with_user_request": True}
            activation = state.finish_chat_activation(
                db,
                project_id=project_id,
                thread_id=identifier,
                indexed_through_line=int(parsed.get("last_line") or 0),
                error="; ".join(failures) if failures else None,
            )
    finally:
        db.close()
    return {
        "status": "failed" if failures else "ready",
        "first_invocation": True,
        "project_root": canonical,
        "thread_id": identifier,
        "queued_turns": int(queued.get("queued_turns") or 0),
        "processed_turns": int(processed.get("processed_turns") or 0),
        "indexed_through_line": int(activation.get("indexed_through_line") or 0),
        "failures": failures,
        "continue_with_user_request": True,
    }


def _resolve_project(project_root: str | None) -> tuple[str, str, dict[str, Any]]:
    db = thread_tree.connect_db()
    try:
        config = thread_tree.load_scope_config()
        if not config.get("configured"):
            raise ValueError("Context Saver is not configured. Open the local viewer to choose project folders and chats.")

        def active_project(row: Mapping[str, Any]) -> tuple[bool, dict[str, Any] | None, str]:
            canonical = str(Path(str(row["cwd"] or "")).expanduser().resolve())
            selected = scope.selected_project(config, canonical)
            if selected is None:
                return False, None, "project_not_selected"
            probe_thread = next(
                (identifier for identifier in selected.get("includedChatIds", []) if scope.chat_is_selected(selected, identifier)),
                None,
            ) if not selected.get("includeNewChats", True) else None
            decision = scope.scope_decision(
                config,
                canonical,
                probe_thread,
                last_activity_at=str(row["updated_at"] or ""),
            )
            return bool(decision["active"]), selected, str(decision["reason"])

        if project_root and project_root.strip():
            canonical = str(Path(project_root).expanduser().resolve())
            project_id = state.project_id_for(canonical)
            row = db.execute("SELECT cwd, updated_at FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise ValueError(f"No Context Saver index exists for project root: {canonical}")
            active, selected, reason = active_project(row)
            if not active or selected is None:
                raise ValueError(f"Context Saver is not active for this project ({reason}).")
            return project_id, str(row["cwd"] or canonical), selected
        rows = db.execute("SELECT id, cwd, updated_at FROM projects ORDER BY updated_at DESC").fetchall()
        active_rows: list[tuple[Any, dict[str, Any]]] = []
        for row in rows:
            active, selected, _reason = active_project(row)
            if active and selected is not None:
                active_rows.append((row, selected))
        if len(active_rows) == 1:
            row, selected = active_rows[0]
            return str(row["id"]), str(row["cwd"] or ""), selected
        if not active_rows:
            raise ValueError("No active Context Saver project is available")
        raise ValueError("project_root is required when more than one active Context Saver project exists")
    finally:
        db.close()


def _primary_parent(db: Any, node_id: str) -> dict[str, Any] | None:
    row = db.execute(
        """SELECT n.id, n.layer, n.title, e.coverage, e.primary_edge
           FROM semantic_edges e JOIN semantic_nodes n ON n.id = e.parent_id
           WHERE e.child_id = ? AND n.lifecycle != 'retired'
           ORDER BY e.primary_edge DESC, e.coverage DESC, n.id LIMIT 1""",
        (node_id,),
    ).fetchone()
    return dict(row) if row else None


def _path_from_span(db: Any, span_id: str) -> list[dict[str, Any]]:
    row = db.execute(
        "SELECT id, layer, title FROM semantic_nodes WHERE id = ? AND lifecycle != 'retired'",
        (span_id,),
    ).fetchone()
    if row is None:
        return []
    path = [dict(row)]
    while path[-1]["layer"] != "broad":
        parent = _primary_parent(db, path[-1]["id"])
        if parent is None or parent["id"] in {item["id"] for item in path}:
            break
        path.append(parent)
    return path


def _evidence_record(
    row: Mapping[str, Any],
    *,
    score: float,
    path: list[dict[str, Any]],
    route: str,
    source_detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_ids = row.get("source_message_ids")
    if isinstance(source_ids, str):
        try:
            source_ids = json.loads(source_ids)
        except json.JSONDecodeError:
            source_ids = []
    detail = dict(source_detail or {})
    transcript_path = str(detail.get("transcript_path") or row.get("transcript_path") or "")
    return {
        "chunk_id": str(row["id"]),
        "turn_id": str(row["turn_id"]),
        "thread_id": str(row["thread_id"]),
        "text": str(row["text"]),
        "score": round(float(score), 4),
        "route": route,
        "retrieval_diagnostics": dict(row.get("retrieval_diagnostics") or {}),
        "semantic_path": [
            {"node_id": item["id"], "layer": item["layer"], "title": item["title"]}
            for item in path
        ],
        "source": {
            "chat_title": detail.get("chat_title"),
            "timestamp": detail.get("timestamp"),
            "citation_label": detail.get("citation_label"),
            "message_ids": list(detail.get("message_ids") or source_ids or []),
            "line_start": detail.get("line_start", row.get("line_start")),
            "line_end": detail.get("line_end", row.get("line_end")),
            "transcript_path": transcript_path,
            "verified": bool(
                detail.get("verified")
                if source_detail is not None
                else transcript_path and pipeline._source_ids_verified(transcript_path, list(source_ids or []))
            ),
        },
    }


def search_project_history(
    query: str,
    *,
    evidence_needed: str | None = None,
    project_root: str | None = None,
    exclude_chunk_ids: Iterable[str] = (),
    max_results: int = 8,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Search one project's history through a single global lookup and bounded widening."""

    invoked_at = state.plugin_invocation_time()
    query = query.strip()
    if not query:
        raise ValueError("query is required")
    if not 1 <= int(max_results) <= 20:
        raise ValueError("max_results must be between 1 and 20")
    excluded = {str(chunk_id) for chunk_id in exclude_chunk_ids}
    # Host chat identity, not the queried project, gates recall. An exact chat
    # can have an off marker before its first session observation exists.
    caller_id = str(thread_id or os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
                    or os.environ.get("CLAUDE_SESSION_ID") or "").strip()
    caller = {"thread_id": caller_id}
    def control_snapshot(connection: Any) -> list[tuple[Any, ...]]:
        query = "SELECT project_id,generation,enabled FROM chat_plugin_controls"
        if caller_id:
            return [tuple(row) for row in connection.execute(query + " WHERE thread_id=? ORDER BY project_id", (caller_id,))]
        return [tuple(row) for row in connection.execute(query + " ORDER BY project_id,thread_id")]
    with thread_tree.scope_mutation_lock(), closing(thread_tree.connect_db()) as db:
        if not caller_id and db.execute("SELECT 1 FROM chat_plugin_controls WHERE enabled=0 LIMIT 1").fetchone():
            return {**_control_reply({}, "session_unavailable", ok=False,
                message="Context Saver needs the exact current chat ID before history lookup because a chat is switched off. No saved history was returned."),
                "evidence": [], "trace": {"global_lookup_count": 0}}
        caller_generation = control_snapshot(db)
        if any(not item[2] for item in caller_generation):
            return {**_control_reply(caller, "off"), "evidence": [], "trace": {"global_lookup_count": 0}}
        project_id, canonical_root, project_scope = _resolve_project(project_root)
        state.record_project_invocation(db, project_id, invoked_at)
        watermark = int(db.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM turn_chunks WHERE project_id = ? AND evicted = 0",
            (project_id,),
        ).fetchone()[0])
    # `evidence_needed` describes answer-bearing evidence for the calling model;
    # it is not query expansion and the tool does not decide whether returned
    # text answers the model's information need. Mixing it into candidate
    # generation can make generic words such as "statement" or "term" outrank
    # the historical fact the model is actually seeking.
    search_text = query
    global_hits = pipeline.search_project(
        project_id,
        search_text,
        limit=max(max_results * 3, 18),
        exclude_chunk_ids=excluded,
        chunk_watermark=watermark,
        allowed_thread_ids=(
            None if project_scope.get("includeNewChats", True)
            else project_scope.get("includedChatIds", [])
        ),
        excluded_thread_ids=[*project_scope.get("excludedChatIds", []), *project_scope.get("pendingDisconnectChatIds", [])],
    )

    def thread_allowed(thread_id: Any) -> bool:
        return scope.chat_is_selected(project_scope, str(thread_id))

    db = thread_tree.connect_db()
    try:
        transcript_cache: dict[str, dict[str, dict[str, Any]]] = {}
        source_detail_cache: dict[str, dict[str, Any] | None] = {}

        def evidence_record(
            row: Mapping[str, Any],
            *,
            score: float,
            path: list[dict[str, Any]],
            route: str,
        ) -> dict[str, Any]:
            chunk_id = str(row["id"])
            if chunk_id not in source_detail_cache:
                source_detail_cache[chunk_id] = thread_tree.chunk_source_detail(
                    chunk_id,
                    db=db,
                    transcript_cache=transcript_cache,
                )
            return _evidence_record(
                row,
                score=score,
                path=path,
                route=route,
                source_detail=source_detail_cache[chunk_id],
            )

        candidate_span_ids: list[str] = []
        for hit in global_hits:
            for node in hit.get("nodes", []):
                if node.get("layer") == "span" and node["id"] not in candidate_span_ids:
                    candidate_span_ids.append(str(node["id"]))

        paths = {span_id: _path_from_span(db, span_id) for span_id in candidate_span_ids[:4]}
        if scope.restricts_chats(project_scope):
            # Stored titles may have been generated while more chats were in scope.
            visible_labels = {"span": "Specific topic", "specific": "Broad topic", "broad": "Subject"}
            for path in paths.values():
                for item in path:
                    item["title"] = visible_labels.get(item["layer"], "Conversation topic")
        evidence: list[dict[str, Any]] = []
        visited = set(excluded)
        searched_nodes: list[dict[str, Any]] = []

        # The global lookup is a router, not the first evidence layer. Use it
        # to nominate spans, then inspect one best exact chunk from each span
        # before returning global frontier/fallback chunks. Wider parents stay
        # below the span in the existing path order.
        global_by_id = {str(hit["id"]): hit for hit in global_hits}
        for span_id in candidate_span_ids[:4]:
            if len(evidence) >= max_results:
                break
            path = paths.get(span_id, [])
            if not path:
                continue
            span = path[0]
            searched_nodes.append({
                "node_id": span["id"],
                "layer": span["layer"],
                "title": span["title"],
            })
            rows = db.execute(
                """SELECT c.*, t.transcript_path
                   FROM semantic_node_memberships m
                   JOIN turn_chunks c ON c.id = m.chunk_id
                   JOIN turn_ingestion t ON t.id = c.turn_id
                   WHERE m.node_id = ? AND c.project_id = ? AND c.evicted = 0
                     AND c.seq <= ? ORDER BY c.seq DESC""",
                (span_id, project_id, watermark),
            ).fetchall()
            scored = sorted(
                (
                    (
                        float(global_by_id[str(row["id"])]["score"])
                        if str(row["id"]) in global_by_id
                        else pipeline._lexical_similarity(search_text, str(row["text"])),
                        row,
                    )
                    for row in rows
                    if str(row["id"]) not in visited and thread_allowed(row["thread_id"])
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            if scored and scored[0][0] > 0:
                score, row = scored[0]
                evidence.append(
                    evidence_record(dict(row), score=score, path=path, route="span")
                )
                visited.add(str(row["id"]))

        for hit in global_hits:
            if len(evidence) >= max_results:
                break
            if str(hit["id"]) in visited:
                continue
            bundle = [hit]
            companion = next(
                (
                    candidate
                    for candidate in global_hits
                    if candidate["turn_id"] == hit["turn_id"]
                    and candidate["id"] != hit["id"]
                    and str(candidate["id"]) not in visited
                ),
                None,
            )
            if companion is not None:
                bundle.append(companion)
            for index, candidate in enumerate(bundle):
                if len(evidence) >= max_results:
                    break
                span = next((node for node in candidate.get("nodes", []) if node.get("layer") == "span"), None)
                path = paths.get(str(span["id"]), []) if span else []
                evidence.append(
                    evidence_record(
                        candidate,
                        score=float(candidate["score"]),
                        path=path,
                        route="global" if index == 0 else "global_turn_context",
                    )
                )
                visited.add(str(candidate["id"]))

        # The global lookup nominates spans. Widening only searches chunks
        # attached to those spans and their unique parent chains; it never
        # performs another project-wide nearest-neighbor lookup.
        for span_id in candidate_span_ids[:4]:
            path = paths.get(span_id, [])
            for node in path[1:]:
                if len(evidence) >= max_results:
                    break
                searched_nodes.append({
                    "node_id": node["id"],
                    "layer": node["layer"],
                    "title": node["title"],
                })
                rows = db.execute(
                    """SELECT c.*, t.transcript_path
                       FROM semantic_node_memberships m
                       JOIN turn_chunks c ON c.id = m.chunk_id
                       JOIN turn_ingestion t ON t.id = c.turn_id
                       WHERE m.node_id = ? AND c.project_id = ? AND c.evicted = 0
                         AND c.seq <= ? ORDER BY c.seq DESC""",
                    (node["id"], project_id, watermark),
                ).fetchall()
                scored = sorted(
                    (
                        (pipeline._lexical_similarity(search_text, str(row["text"])), row)
                        for row in rows
                        if str(row["id"]) not in visited and thread_allowed(row["thread_id"])
                    ),
                    key=lambda item: item[0],
                    reverse=True,
                )
                for score, row in scored:
                    if len(evidence) >= max_results or score <= 0:
                        break
                    evidence.append(
                        evidence_record(
                            dict(row),
                            score=score,
                            path=path,
                            route=f"{node['layer']}_widening",
                        )
                    )
                    visited.add(str(row["id"]))
    finally:
        db.close()

    lookup_id = state.stable_id(
        "lookup",
        project_id,
        watermark,
        query,
        evidence_needed or "",
        *sorted(excluded),
    )
    route_counts: dict[str, int] = {}
    for item in evidence:
        route = str(item.get("route") or "unknown")
        route_counts[route] = route_counts.get(route, 0) + 1
    if not global_hits:
        stop_reason = "no_global_candidates"
    elif len(evidence) >= max_results:
        stop_reason = "max_results"
    else:
        stop_reason = "candidates_exhausted"
    if caller_id:
        with thread_tree.scope_mutation_lock(), closing(thread_tree.connect_db()) as current_db:
            current_generation = control_snapshot(current_db)
            if current_generation != caller_generation or any(not item[2] for item in current_generation):
                return {**_control_reply(caller, "off"), "evidence": [], "trace": {"global_lookup_count": 1},
                        "reason": "connection_changed_during_lookup"}
    else:
        with thread_tree.scope_mutation_lock(), closing(thread_tree.connect_db()) as current_db:
            current_generation = control_snapshot(current_db)
            if current_generation != caller_generation or any(not item[2] for item in current_generation):
                return {**_control_reply({}, "session_unavailable", ok=False,
                    message="Context Saver needs this chat's exact ID because a connection changed during lookup. No saved history was returned."),
                    "evidence": [], "trace": {"global_lookup_count": 1}}
    return {
        "lookup_id": lookup_id,
        "project_id": project_id,
        "project_root": canonical_root,
        "query": query,
        "evidence_needed": evidence_needed,
        "chunk_watermark": watermark,
        "status": "supported" if evidence else "uncovered",
        "evidence": evidence,
        "trace": {
            "global_lookup_count": 1,
            "global_candidate_count": len(global_hits),
            "query_echo_candidate_count": sum(
                int(hit.get("retrieval_diagnostics", {}).get("query_echo_candidate", 0))
                for hit in global_hits
            ),
            "candidate_span_ids": candidate_span_ids[:4],
            "searched_nodes": searched_nodes,
            "route_counts": route_counts,
            "stop_reason": stop_reason,
            "visited_chunk_ids": [item["chunk_id"] for item in evidence],
            "verified_evidence_count": sum(int(item["source"]["verified"]) for item in evidence),
            "evidence_with_chunk_id_count": sum(int(bool(item["chunk_id"])) for item in evidence),
        },
    }
