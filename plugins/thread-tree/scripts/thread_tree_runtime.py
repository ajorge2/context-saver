#!/usr/bin/env python3
"""Pinned runtime commands shared by Thread Tree client adapters."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


FASTEMBED_REQUIREMENT = "fastembed==0.9.1"
USEARCH_REQUIREMENT = "usearch==2.26.6"
PYTHON_VERSION = "3.12"


def detached_process_options() -> dict[str, bool | int]:
    """Keep background workers independent of the host hook process."""

    if os.name == "nt":
        return {
            "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        }
    return {"start_new_session": True}


def worker_command(worker: Path, project_id: str) -> list[str]:
    """Run background embedding with the same pinned runtime as the MCP server."""

    uv = shutil.which("uv")
    if uv:
        return [
            uv,
            "run",
            "--no-project",
            "--python",
            PYTHON_VERSION,
            "--with",
            FASTEMBED_REQUIREMENT,
            "--with",
            USEARCH_REQUIREMENT,
            "python",
            str(worker),
            "--project-id",
            project_id,
        ]
    # FTS ingestion remains fail-open on hosts without uv. Semantic backfill
    # starts automatically once the pinned runtime becomes available.
    return [sys.executable, str(worker), "--project-id", project_id]

