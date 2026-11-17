#!/usr/bin/env python3
"""Local activation scope and pause policy for Thread Tree.

The scope file is deliberately separate from viewer appearance and semantic
state.  It is the consent boundary used by hooks, the MCP tool, and the public
viewer.  Pausing never deletes already indexed data.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
DEFAULT_SCOPE_CONFIG: dict[str, Any] = {
    "schemaVersion": SCHEMA_VERSION,
    "configured": False,
    "paused": False,
    "projects": [],
    "pausePolicy": {
        "mode": "manual",
        "pauseOn": None,
        "inactivityDays": 30,
    },
    "setupAt": None,
    "updatedAt": None,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def scope_config_path(data_directory: Path) -> Path:
    return data_directory / "scope-config.json"


def _canonical_path(value: str) -> str:
    if not value.strip():
        raise ValueError("project path cannot be blank")
    return str(Path(value).expanduser().resolve())


def _string_ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result: list[str] = []
    for item in value:
        identifier = str(item).strip()
        if not identifier or len(identifier) > 240:
            raise ValueError(f"{field} contains an invalid chat ID")
        if identifier not in result:
            result.append(identifier)
    if len(result) > 2_000:
        raise ValueError(f"{field} contains too many chat IDs")
    return result


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def validate_scope_config(value: Any, *, require_existing_paths: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("scope config must be an object")
    unknown = set(value) - set(DEFAULT_SCOPE_CONFIG)
    if unknown:
        raise ValueError(f"unknown scope config keys: {', '.join(sorted(unknown))}")

    configured = value.get("configured", False)
    paused = value.get("paused", False)
    if not isinstance(configured, bool) or not isinstance(paused, bool):
        raise ValueError("configured and paused must be true or false")

    raw_projects = value.get("projects", [])
    if not isinstance(raw_projects, list) or len(raw_projects) > 128:
        raise ValueError("projects must be a list containing at most 128 folders")
    projects: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw in raw_projects:
        if not isinstance(raw, Mapping):
            raise ValueError("each project selection must be an object")
        allowed = {
            "path", "includeNewChats", "includedChatIds", "excludedChatIds",
            "backfillExisting", "activatedAt", "paused", "disconnectPending", "pendingDisconnectChatIds",
            "disconnectRefreshJobs",
        }
        unexpected = set(raw) - allowed
        if unexpected:
            raise ValueError(f"unknown project selection keys: {', '.join(sorted(unexpected))}")
        path = _canonical_path(str(raw.get("path") or ""))
        if path in seen_paths:
            raise ValueError(f"project folder is selected more than once: {path}")
        if require_existing_paths and not Path(path).is_dir():
            raise ValueError(f"project folder does not exist: {path}")
        seen_paths.add(path)
        include_new = raw.get("includeNewChats", True)
        backfill = raw.get("backfillExisting", True)
        project_paused = raw.get("paused", False)
        disconnect_pending = raw.get("disconnectPending", False)
        if not isinstance(include_new, bool) or not isinstance(backfill, bool) or not isinstance(project_paused, bool):
            raise ValueError("includeNewChats, backfillExisting, and paused must be true or false")
        if not isinstance(disconnect_pending, bool):
            raise ValueError("disconnectPending must be true or false")
        included = _string_ids(raw.get("includedChatIds", []), "includedChatIds")
        excluded = _string_ids(raw.get("excludedChatIds", []), "excludedChatIds")
        pending_chats = _string_ids(raw.get("pendingDisconnectChatIds", []), "pendingDisconnectChatIds")
        refresh_jobs = raw.get("disconnectRefreshJobs", {})
        targets = {f"chat:{thread_id}" for thread_id in pending_chats}
        if disconnect_pending:
            targets.add("project")
        if not isinstance(refresh_jobs, dict) or any(
            target not in targets or not isinstance(job_id, str) or not re.fullmatch(r"refresh_[0-9a-f]{32}", job_id)
            for target, job_id in refresh_jobs.items()
        ):
            raise ValueError("invalid pending disconnection refresh jobs")
        activated_at = str(raw.get("activatedAt") or "").strip() or None
        if activated_at and _parse_timestamp(activated_at) is None:
            raise ValueError("activatedAt must be an ISO timestamp")
        projects.append({
            "path": path,
            "includeNewChats": include_new,
            "includedChatIds": included,
            "excludedChatIds": excluded,
            "backfillExisting": backfill,
            "paused": project_paused,
            "activatedAt": activated_at,
            **({"disconnectPending": True} if disconnect_pending else {}),
            **({"pendingDisconnectChatIds": pending_chats} if pending_chats else {}),
            **({"disconnectRefreshJobs": refresh_jobs} if refresh_jobs else {}),
        })

    if configured and not projects:
        raise ValueError("choose at least one project folder")

    raw_policy = value.get("pausePolicy", {})
    if not isinstance(raw_policy, Mapping):
        raise ValueError("pausePolicy must be an object")
    policy_unknown = set(raw_policy) - {"mode", "pauseOn", "inactivityDays"}
    if policy_unknown:
        raise ValueError(f"unknown pause policy keys: {', '.join(sorted(policy_unknown))}")
    mode = str(raw_policy.get("mode") or "manual")
    if mode not in {"manual", "date", "inactivity"}:
        raise ValueError("pause policy must be manual, date, or inactivity")
    pause_on = str(raw_policy.get("pauseOn") or "").strip() or None
    if pause_on:
        try:
            date.fromisoformat(pause_on)
        except ValueError as error:
            raise ValueError("pauseOn must be a YYYY-MM-DD date") from error
    if mode == "date" and not pause_on:
        raise ValueError("choose a date for the date pause policy")
    inactivity_days = raw_policy.get("inactivityDays", 30)
    if isinstance(inactivity_days, bool) or not isinstance(inactivity_days, int) or not 1 <= inactivity_days <= 3_650:
        raise ValueError("inactivityDays must be between 1 and 3650")

    setup_at = str(value.get("setupAt") or "").strip() or None
    updated_at = str(value.get("updatedAt") or "").strip() or None
    for name, timestamp in (("setupAt", setup_at), ("updatedAt", updated_at)):
        if timestamp and _parse_timestamp(timestamp) is None:
            raise ValueError(f"{name} must be an ISO timestamp")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "configured": configured,
        "paused": paused,
        "projects": projects,
        "pausePolicy": {
            "mode": mode,
            "pauseOn": pause_on,
            "inactivityDays": inactivity_days,
        },
        "setupAt": setup_at,
        "updatedAt": updated_at,
    }


def load_scope_config(data_directory: Path) -> dict[str, Any]:
    path = scope_config_path(data_directory)
    if not path.exists():
        return deepcopy(DEFAULT_SCOPE_CONFIG)
    try:
        return validate_scope_config(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError):
        # Invalid consent state must fail closed.  The file remains available
        # for manual recovery and no history is silently read or indexed.
        result = deepcopy(DEFAULT_SCOPE_CONFIG)
        result["loadError"] = "Context Saver scope settings are invalid"
        return result


def save_scope_config(data_directory: Path, value: Any) -> dict[str, Any]:
    previous = load_scope_config(data_directory)
    normalized = validate_scope_config(value)
    now = utc_now()
    previous_projects = {
        item["path"]: item for item in previous.get("projects", []) if isinstance(item, dict) and item.get("path")
    }
    for project in normalized["projects"]:
        if (
            project["path"] not in previous_projects and not Path(project["path"]).is_dir()
            and not (project.get("disconnectPending") or project.get("pendingDisconnectChatIds"))
        ):
            raise ValueError(f"project folder does not exist: {project['path']}")
        project["activatedAt"] = (
            project.get("activatedAt")
            or previous_projects.get(project["path"], {}).get("activatedAt")
            or now
        )
    normalized["setupAt"] = previous.get("setupAt") or normalized.get("setupAt") or now
    normalized["updatedAt"] = now
    path = scope_config_path(data_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".json.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            parent_file = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_file)
            finally:
                os.close(parent_file)
    finally:
        temporary.unlink(missing_ok=True)
    return normalized


def selected_project(config: Mapping[str, Any], project_root: str | None) -> dict[str, Any] | None:
    if not project_root:
        return None
    try:
        canonical = _canonical_path(project_root)
    except ValueError:
        return None
    for item in config.get("projects", []):
        try:
            if _canonical_path(str(item.get("path") or "")) == canonical:
                return item
        except ValueError:
            continue
    return None


def project_is_selected(config: Mapping[str, Any], project_root: str | None) -> bool:
    project = selected_project(config, project_root)
    return bool(config.get("configured") and project and not project.get("disconnectPending"))


def chat_is_selected(project: Mapping[str, Any], thread_id: str) -> bool:
    """Check a chat's consent independently of a project-wide pause."""

    return (
        not project.get("disconnectPending")
        and thread_id not in project.get("pendingDisconnectChatIds", [])
        and thread_id not in project.get("excludedChatIds", [])
        and (project.get("includeNewChats", True) or thread_id in project.get("includedChatIds", []))
    )


def restricts_chats(project: Mapping[str, Any] | None) -> bool:
    return bool(project is not None and (
        project.get("disconnectPending") or project.get("pendingDisconnectChatIds")
        or not project.get("includeNewChats", True) or project.get("excludedChatIds")
    ))


def scope_decision(
    config: Mapping[str, Any],
    project_root: str | None,
    thread_id: str | None,
    *,
    last_activity_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return whether ingestion/retrieval is active for this project and chat."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not config.get("configured"):
        return {"active": False, "reason": "not_configured", "project": None}
    project = selected_project(config, project_root)
    if project is None:
        return {"active": False, "reason": "project_not_selected", "project": None}
    if project.get("disconnectPending") or thread_id in project.get("pendingDisconnectChatIds", []):
        return {"active": False, "reason": "disconnect_pending", "project": project}
    if config.get("paused"):
        return {"active": False, "reason": "paused_manually", "project": project}
    if project.get("paused"):
        return {"active": False, "reason": "project_paused", "project": project}

    policy = config.get("pausePolicy", {})
    mode = policy.get("mode", "manual")
    if mode == "date":
        pause_on = policy.get("pauseOn")
        if pause_on and current.astimezone().date() >= date.fromisoformat(str(pause_on)):
            return {"active": False, "reason": "pause_date_reached", "project": project}
    elif mode == "inactivity":
        candidates = [
            parsed for parsed in (
                _parse_timestamp(last_activity_at),
                _parse_timestamp(project.get("activatedAt")),
                _parse_timestamp(config.get("setupAt")),
            ) if parsed is not None
        ]
        last_activity = max(candidates) if candidates else current
        elapsed_days = (current - last_activity).total_seconds() / 86_400
        if elapsed_days >= int(policy.get("inactivityDays", 30)):
            return {"active": False, "reason": "inactive_too_long", "project": project}

    identifier = str(thread_id or "").strip()
    if identifier and identifier in set(project.get("excludedChatIds", [])):
        return {"active": False, "reason": "chat_excluded", "project": project}
    if not project.get("includeNewChats", True):
        if not identifier or identifier not in set(project.get("includedChatIds", [])):
            return {"active": False, "reason": "chat_not_selected", "project": project}
    return {"active": True, "reason": "active", "project": project}

