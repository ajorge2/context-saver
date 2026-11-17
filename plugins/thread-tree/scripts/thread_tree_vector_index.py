#!/usr/bin/env python3
"""Persistent project-wide ANN index derived from Thread Tree's SQLite state.

SQLite remains authoritative.  This module stores only a rebuildable USearch
index whose integer keys are ``turn_chunks.seq`` values, plus a small JSON
manifest.  Search never deserializes the full embedding table into Python.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Sequence

from thread_tree_state import exclusive_process_lock, stable_id


INDEX_SCHEMA_VERSION = 2
INDEX_BACKEND = "usearch-hnsw-f32-v1"
INDEX_FILENAME = "chunks.usearch"
METADATA_FILENAME = "chunks.json"

_CACHE_LOCK = RLock()
_INDEX_CACHE: dict[str, tuple[list[int], Any]] = {}


def _imports() -> tuple[Any, Any]:
    try:
        import numpy as np
        from usearch.index import Index
    except ImportError as error:  # pragma: no cover - exercised by fallback installs
        raise RuntimeError("USearch and NumPy are unavailable") from error
    return np, Index


def available() -> bool:
    try:
        _imports()
        return True
    except RuntimeError:
        return False


def _root(data_directory: Path, project_id: str) -> Path:
    return data_directory / "vector-indexes" / project_id


def _index_path(data_directory: Path, project_id: str) -> Path:
    return _root(data_directory, project_id) / INDEX_FILENAME


def _metadata_path(data_directory: Path, project_id: str) -> Path:
    return _root(data_directory, project_id) / METADATA_FILENAME


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _file_identity(path: Path) -> list[int] | None:
    try:
        stat = path.stat()
        return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
    except FileNotFoundError:
        return None


def metadata(data_directory: Path, project_id: str) -> dict[str, Any] | None:
    path = _metadata_path(data_directory, project_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != INDEX_SCHEMA_VERSION:
        return None
    if (
        value.get("project_id") != project_id
        or not isinstance(value.get("generation_token"), str)
        or not value["generation_token"]
        or not isinstance(value.get("embedding_model"), str)
        or type(value.get("dimension")) is not int
        or value["dimension"] <= 0
        or type(value.get("document_count")) is not int
        or value["document_count"] < 0
        or type(value.get("indexed_through_seq")) is not int
        or value["indexed_through_seq"] < 0
    ):
        return None
    file_identity = _file_identity(_index_path(data_directory, project_id))
    if file_identity is None or file_identity != value.get("index_file_identity"):
        return None
    return value


@contextmanager
def _write_lock(data_directory: Path, project_id: str) -> Iterator[None]:
    name = stable_id("vector", project_id)
    with exclusive_process_lock(data_directory / "maintenance-locks" / name):
        yield


def _new_index(dimension: int) -> Any:
    _, Index = _imports()
    return Index(
        ndim=dimension,
        metric="cos",
        dtype="f32",
        connectivity=16,
        expansion_add=128,
        expansion_search=96,
    )


def _publish(
    index: Any,
    *,
    data_directory: Path,
    project_id: str,
    model: str,
    dimension: int,
    indexed_through_seq: int,
    count: int,
) -> dict[str, Any]:
    directory = _root(data_directory, project_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = _index_path(data_directory, project_id)
    temporary = path.with_suffix(path.suffix + ".tmp")
    index.save(str(temporary))
    file_identity = _file_identity(temporary)
    os.replace(temporary, path)
    result = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "backend": INDEX_BACKEND,
        "project_id": project_id,
        "embedding_model": model,
        "dimension": dimension,
        "document_count": count,
        "indexed_through_seq": indexed_through_seq,
        "generation_token": uuid.uuid4().hex,
        "index_file_identity": file_identity,
        "updated_at_unix": round(time.time(), 3),
    }
    _atomic_json(_metadata_path(data_directory, project_id), result)
    with _CACHE_LOCK:
        _INDEX_CACHE.pop(str(path), None)
    return result


def rebuild_project_index(
    db: Any,
    *,
    data_directory: Path,
    project_id: str,
    model: str,
    dimension: int,
) -> dict[str, Any]:
    """Rebuild one project's derived index from matching live SQLite rows."""

    with _write_lock(data_directory, project_id):
        return _rebuild_locked(
            db,
            data_directory=data_directory,
            project_id=project_id,
            model=model,
            dimension=dimension,
        )


def _rebuild_locked(
    db: Any, *, data_directory: Path, project_id: str, model: str, dimension: int,
) -> dict[str, Any]:
    np, _ = _imports()
    rows = db.execute(
        """SELECT seq, id, turn_id, embedding FROM turn_chunks
           WHERE project_id=? AND evicted=0 AND embedding IS NOT NULL
             AND embedding_model=? ORDER BY seq""",
        (project_id, model),
    ).fetchall()
    index = _new_index(dimension)
    accepted: list[Any] = []
    vectors: list[list[float]] = []
    for row in rows:
        try:
            vector = json.loads(row["embedding"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(vector, list) or len(vector) != dimension:
            continue
        accepted.append(row)
        vectors.append([float(value) for value in vector])
    if accepted:
        index.add(
            np.asarray([int(row["seq"]) for row in accepted], dtype=np.uint64),
            np.asarray(vectors, dtype=np.float32),
        )
    indexed_through = max((int(row["seq"]) for row in accepted), default=0)
    result = _publish(
        index,
        data_directory=data_directory,
        project_id=project_id,
        model=model,
        dimension=dimension,
        indexed_through_seq=indexed_through,
        count=len(accepted),
    )
    shard_name = f"global-chunks:{project_id}"
    with db:
        db.execute(
            """INSERT INTO index_shards
               (name, project_id, kind, owner_node_id, document_count, backend,
                generation_token, updated_at)
               VALUES (?, ?, 'global_chunks', NULL, ?, ?, ?, datetime('now'))
               ON CONFLICT(name) DO UPDATE SET
                 document_count=excluded.document_count,
                 backend=excluded.backend,
                 generation_token=excluded.generation_token,
                 updated_at=excluded.updated_at""",
            (shard_name, project_id, len(accepted), INDEX_BACKEND, result["generation_token"]),
        )
        db.execute("DELETE FROM index_documents WHERE shard_name=?", (shard_name,))
        db.executemany(
            """INSERT INTO index_documents
               (shard_name, document_id, chunk_id, turn_id)
               VALUES (?, ?, ?, ?)""",
            [(shard_name, str(row["seq"]), str(row["id"]), str(row["turn_id"])) for row in accepted],
        )
    return result


def invalidate_project_index(db: Any, *, data_directory: Path, project_id: str) -> None:
    """Discard derived copies when the current runtime cannot rebuild them."""
    with _write_lock(data_directory, project_id):
        path = _index_path(data_directory, project_id)
        manifest = _metadata_path(data_directory, project_id)
        for artifact in (manifest, path):
            artifact.unlink(missing_ok=True)
            artifact.with_suffix(artifact.suffix + ".tmp").unlink(missing_ok=True)
        with _CACHE_LOCK:
            _INDEX_CACHE.pop(str(path), None)
        with db:
            db.execute("DELETE FROM index_shards WHERE name=? AND project_id=?", (f"global-chunks:{project_id}", project_id))


def update_project_index(
    db: Any,
    *,
    data_directory: Path,
    project_id: str,
    model: str,
    dimension: int,
) -> dict[str, Any]:
    """Append newly embedded rows, rebuilding when index provenance changed."""

    np, Index = _imports()
    path = _index_path(data_directory, project_id)
    shard_name = f"global-chunks:{project_id}"
    with _write_lock(data_directory, project_id):
        current = metadata(data_directory, project_id)
        shard = db.execute("SELECT generation_token FROM index_shards WHERE name=?", (shard_name,)).fetchone()
        if (
            current is None
            or current.get("embedding_model") != model
            or int(current.get("dimension", 0)) != dimension
            or shard is None
            or shard["generation_token"] != current["generation_token"]
        ):
            return _rebuild_locked(
                db, data_directory=data_directory, project_id=project_id, model=model, dimension=dimension,
            )
        through = int(current.get("indexed_through_seq", 0))
        rows = db.execute(
            """SELECT seq, id, turn_id, embedding FROM turn_chunks
               WHERE project_id=? AND evicted=0 AND embedding IS NOT NULL
                 AND embedding_model=? AND seq>? ORDER BY seq""",
            (project_id, model, through),
        ).fetchall()
        if not rows:
            return current
        try:
            index = Index.restore(str(path), view=False)
        except (RuntimeError, ValueError, OSError):
            return _rebuild_locked(
                db, data_directory=data_directory, project_id=project_id, model=model, dimension=dimension,
            )
        accepted: list[Any] = []
        vectors: list[list[float]] = []
        for row in rows:
            try:
                vector = json.loads(row["embedding"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(vector, list) and len(vector) == dimension:
                accepted.append(row)
                vectors.append([float(value) for value in vector])
        if not accepted:
            return current
        index.add(
            np.asarray([int(row["seq"]) for row in accepted], dtype=np.uint64),
            np.asarray(vectors, dtype=np.float32),
        )
        new_through = max(int(row["seq"]) for row in accepted)
        result = _publish(
            index,
            data_directory=data_directory,
            project_id=project_id,
            model=model,
            dimension=dimension,
            indexed_through_seq=new_through,
            count=len(index),
        )
        with db:
            db.execute(
                """UPDATE index_shards SET document_count=?, backend=?,
                   generation_token=?, updated_at=datetime('now') WHERE name=?""",
                (len(index), INDEX_BACKEND, result["generation_token"], shard_name),
            )
            db.executemany(
                """INSERT OR REPLACE INTO index_documents
                   (shard_name, document_id, chunk_id, turn_id)
                   VALUES (?, ?, ?, ?)""",
                [
                    (shard_name, str(row["seq"]), str(row["id"]), str(row["turn_id"]))
                    for row in accepted
                ],
            )
        return result


def search(
    *,
    data_directory: Path,
    project_id: str,
    model: str,
    vector: Sequence[float],
    limit: int,
) -> tuple[list[tuple[int, float]], dict[str, Any]]:
    """Return ANN sequence keys and cosine similarities without SQLite scans."""

    np, Index = _imports()
    info = metadata(data_directory, project_id)
    path = _index_path(data_directory, project_id)
    if (
        info is None
        or info.get("embedding_model") != model
        or int(info.get("dimension", 0)) != len(vector)
        or not path.exists()
        or int(info.get("document_count", 0)) == 0
    ):
        return [], {
            "backend": INDEX_BACKEND,
            "available": False,
            "document_count": 0,
            "indexed_through_seq": 0,
            "candidates_visited": 0,
        }
    cache_key = str(path)
    identity = info["index_file_identity"]
    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(cache_key)
        if cached is None or cached[0] != identity:
            cached = (identity, Index.restore(str(path), view=True))
            if _file_identity(path) != identity:
                # Publication raced the reader between manifest validation and
                # mmap. Never pair one model's metadata with another binary.
                return [], {
                    "backend": INDEX_BACKEND, "available": False, "document_count": 0,
                    "indexed_through_seq": 0, "candidates_visited": 0,
                }
            _INDEX_CACHE[cache_key] = cached
        index = cached[1]
    count = min(max(1, int(limit)), len(index))
    exact = len(index) <= 1000
    matches = index.search(np.asarray(vector, dtype=np.float32), count, exact=exact)
    result = [
        (int(key), max(-1.0, min(1.0, 1.0 - float(distance))))
        for key, distance in zip(matches.keys, matches.distances)
    ]
    return result, {
        "backend": INDEX_BACKEND,
        "available": True,
        "document_count": int(info.get("document_count", len(index))),
        "indexed_through_seq": int(info.get("indexed_through_seq", 0)),
        "candidates_visited": len(result),
        "search_mode": "exact_small_index" if exact else "hnsw",
    }

