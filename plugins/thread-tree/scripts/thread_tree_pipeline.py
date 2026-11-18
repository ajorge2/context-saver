#!/usr/bin/env python3
"""Operational project-wide ingestion, fitting, retrieval, and tree projection.

SQLite is authoritative. Optional local embeddings improve assignment and
search; the lexical path remains complete and rebuildable when no model or Moss
credentials are present.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
import sqlite3
import time
from collections import Counter
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import thread_tree_state as state
import thread_tree_scope as scope
import thread_tree_vector_index as vector_index


DEFAULT_FIT_THRESHOLDS = {"span": 8, "specific": 16, "broad": 32}
FORMATION_SIZES = {"span": 2, "specific": 3, "broad": 4}
DETERMINISTIC_FALLBACK_MAX_ROWS = 999
LOCK_SIZES = {"span": 6, "specific": 12, "broad": 24}
SIMILARITY_THRESHOLDS = {"span": 0.58, "specific": 0.38, "broad": 0.22}
LOCK_PERSISTENCE = {"span": 0.58, "specific": 0.48, "broad": 0.38}
ASSIGN_THRESHOLDS = {"span": 0.72, "specific": 0.62, "broad": 0.52}
ASSIGN_MARGIN = 0.08
CHUNKER_VERSION = "fallback-semantic-v2"
RETRYABLE_SQLITE_ERRORS = {
    sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_FULL, sqlite3.SQLITE_CANTOPEN,
}


class TranscriptChangedError(RuntimeError):
    """The queued evidence does not match its current source."""


def _tree_module():
    import thread_tree

    return thread_tree


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _turn_content_hash(messages: Sequence[Mapping[str, Any]]) -> str:
    return _hash("\n\n".join(f"{item['role']}: {item['text']}" for item in messages))


def _turn_source_fingerprint(messages: Sequence[Mapping[str, Any]]) -> str:
    evidence = [[item["id"], item["role"], item["text"], item.get("timestamp")] for item in messages]
    return _hash(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")))


def _tokens(text: str) -> list[str]:
    tree = _tree_module()
    return tree.tokenize(text)


def _vector(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return [float(item) for item in value] if isinstance(value, list) else []


def _normalize(vector: Sequence[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    return [value / magnitude for value in vector] if magnitude else list(vector)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    left_norm_sq = sum(value * value for value in left)
    right_norm_sq = sum(value * value for value in right)
    dot = sum(a * b for a, b in zip(left, right))
    # Query and stored passage embeddings are normalized before persistence.
    # Preserve their native dot-product ordering instead of normalizing twice:
    # the redundant floating-point pass measurably destabilizes near ties.
    if abs(left_norm_sq - 1.0) <= 1e-5 and abs(right_norm_sq - 1.0) <= 1e-5:
        return dot
    denominator = math.sqrt(left_norm_sq * right_norm_sq)
    return dot / denominator if denominator else 0.0


def _lexical_similarity(left: str, right: str) -> float:
    a, b = set(_tokens(left)), set(_tokens(right))
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def _looks_lexically_exact(query: str, tokens: Sequence[str], decision_query: bool) -> bool:
    """Identify queries where exact lexical evidence deserves fusion weight."""

    if decision_query:
        return True
    if re.search(r"[`\"'][^`\"']{3,}[`\"']", query):
        return True
    if re.search(r"(?:^|\s)[\w./-]+\.[a-zA-Z0-9]{1,8}(?:\s|$)", query):
        return True
    return any(
        any(character.isdigit() for character in token)
        or "_" in token
        for token in tokens
    )


def _similarity(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    dense = _cosine(_vector(left.get("embedding")), _vector(right.get("embedding")))
    lexical = _lexical_similarity(str(left.get("text", "")), str(right.get("text", "")))
    return dense * 0.78 + lexical * 0.22 if dense else lexical


def semantic_chunks(messages: Sequence[Mapping[str, Any]], maximum_chars: int = 1_800) -> list[dict[str, Any]]:
    """Deterministically split a completed turn without crossing provenance."""

    units: list[dict[str, Any]] = []
    for message in messages:
        text = str(message.get("text") or "").strip()
        if not text:
            continue
        # Code fences and paragraph breaks are stable semantic boundaries. Very
        # long units fall back to sentence boundaries without overlap.
        parts = [part.strip() for part in re.split(r"\n\s*\n|(?<=```)[ \t]*\n|\n[ \t]*(?=```)", text) if part.strip()]
        for part in parts:
            if len(part) <= maximum_chars:
                fragments = [part]
            else:
                sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9`])", part) if item.strip()]
                fragments, current = [], ""
                for sentence in sentences or [part]:
                    if current and len(current) + len(sentence) + 1 > maximum_chars:
                        fragments.append(current)
                        current = ""
                    current = f"{current} {sentence}".strip()
                if current:
                    fragments.append(current)
            for fragment in fragments:
                units.append(
                    {
                        "text": f"{str(message.get('role', 'message')).upper()}: {fragment}",
                        "source_message_ids": [str(message.get("id"))],
                        "line_start": message.get("line"),
                        "line_end": message.get("line"),
                        "chunker_version": CHUNKER_VERSION,
                    }
                )
    # Short acknowledgements are not independently searchable; fold them into
    # their nearest substantial neighbor while retaining both message IDs.
    merged: list[dict[str, Any]] = []
    for unit in units:
        if merged and len(_tokens(unit["text"])) < 4:
            merged[-1]["text"] += "\n" + unit["text"]
            merged[-1]["source_message_ids"] += unit["source_message_ids"]
            merged[-1]["line_end"] = unit["line_end"]
        else:
            merged.append(unit)
    for ordinal, unit in enumerate(merged):
        unit["content_hash"] = _hash(unit["text"])
        # The worker adds the immutable turn ID. Content alone is insufficient:
        # two chats may contain identical evidence and both must remain sourced.
        unit["ordinal"] = ordinal
    return merged


def _project_config() -> dict[str, Any]:
    config = _tree_module().load_config()
    configured = config.get("fit_thresholds")
    thresholds = dict(DEFAULT_FIT_THRESHOLDS)
    if isinstance(configured, dict):
        thresholds.update({key: int(value) for key, value in configured.items() if key in state.LAYERS})
    config["fit_thresholds"] = thresholds
    return config


def enqueue_transcript(
    transcript_path: Path,
    *,
    supplied_thread_id: str | None = None,
    supplied_cwd: str | None = None,
    include_active: bool = True,
    mark_incomplete_partial: bool = False,
    enforce_scope: bool = False,
) -> dict[str, Any]:
    """Queue all unrecorded turns from one transcript without model work."""

    tree = _tree_module()
    transcript_path = transcript_path.expanduser().resolve()
    parsed = tree.parse_transcript_lines(transcript_path)
    thread_id = supplied_thread_id or parsed["thread_id"]
    if not thread_id:
        raise RuntimeError("Could not determine thread ID")
    project_root = parsed["cwd"] or supplied_cwd
    project_id = state.project_id_for(project_root)
    action_lock = tree.scope_mutation_lock() if enforce_scope else nullcontext()
    with action_lock, closing(tree.connect_db()) as db:
        if enforce_scope:
            if parsed["thread_id"] and supplied_thread_id and parsed["thread_id"] != supplied_thread_id:
                raise ValueError("transcript chat does not match the hook")
            row = db.execute("SELECT updated_at FROM projects WHERE id=?", (project_id,)).fetchone()
            decision = scope.scope_decision(
                tree.load_scope_config(), project_root, thread_id,
                last_activity_at=row["updated_at"] if row else None,
            )
            if not decision["active"]:
                return {"scope_blocked": True, "reason": decision["reason"], "project_id": project_id, "queued_turns": 0}
        return _queue_parsed_transcript(
            db, transcript_path, parsed, thread_id, project_root, project_id,
            include_active=include_active, mark_incomplete_partial=mark_incomplete_partial,
        )


def _queue_parsed_transcript(
    db: sqlite3.Connection,
    transcript_path: Path,
    parsed: Mapping[str, Any],
    thread_id: str,
    project_root: str | None,
    project_id: str,
    *,
    include_active: bool,
    mark_incomplete_partial: bool,
) -> dict[str, Any]:
    tree = _tree_module()
    config = _project_config()
    state.ensure_project(
        db,
        project_id,
        project_root,
        fit_thresholds=config["fit_thresholds"],
        high_chunks=int(config.get("retention_high_chunks", 10_000)),
        low_chunks=int(config.get("retention_low_chunks", 8_500)),
        byte_ceiling=config.get("retention_byte_ceiling"),
    )
    groups = [group for group in tree.group_dialogue(parsed["messages"]) if any(item["role"] == "user" for item in group)]
    queued = 0
    approx_tokens = 0
    turn_ids: list[str] = []
    for index, group in enumerate(groups):
        is_last = index == len(groups) - 1
        has_assistant_output = any(item["role"] == "assistant" for item in group)
        is_incomplete = is_last and not has_assistant_output
        if is_incomplete and not include_active:
            continue
        is_partial = is_incomplete and mark_incomplete_partial
        line_start = min(int(item["line"]) for item in group)
        line_end = max(int(item["line"]) for item in group)
        content_hash = _turn_content_hash(group)
        turn_id = state.stable_id("turn", project_id, thread_id, line_start, line_end, content_hash, CHUNKER_VERSION)
        before = db.execute(
            "SELECT state FROM turn_ingestion WHERE project_id = ? AND thread_id = ? AND content_hash = ?",
            (project_id, thread_id, content_hash),
        ).fetchone()
        if not is_partial:
            # A PreCompact recovery record may have captured the user-only
            # prefix. It is never processed, and the completed Stop delivery
            # supersedes it at the same turn boundary.
            partials = db.execute(
                """SELECT id FROM turn_ingestion
                   WHERE project_id=? AND thread_id=? AND line_start=? AND partial=1
                     AND state IN ('queued','failed')""",
                (project_id, thread_id, line_start),
            ).fetchall()
            for partial in partials:
                state.transition_turn(db, partial["id"], "evicted", "superseded by completed turn")
        queued_row = state.queue_turn(
            db,
            turn_id=turn_id,
            project_id=project_id,
            thread_id=thread_id,
            transcript_path=str(transcript_path),
            line_start=line_start,
            line_end=line_end,
            content_hash=content_hash,
            source_fingerprint=_turn_source_fingerprint(group),
            partial=is_partial,
            chunker_version=CHUNKER_VERSION,
            revalidate_replay=True,
        )
        turn_ids.append(queued_row["id"])
        if before is None or (before["state"] != "queued" and queued_row["state"] == "queued"):
            queued += 1
            approx_tokens += tree.estimate_message_tokens(list(group))
    tree.ensure_thread(db, thread_id, tree.first_user_title(parsed["messages"]), project_root, str(transcript_path))
    db.commit()
    return {
        "project_id": project_id,
        "thread_id": thread_id,
        "queued_turns": queued,
        "approx_tokens": approx_tokens,
        "line_end": parsed["last_line"],
        "turn_ids": turn_ids,
    }


def _read_turn_messages(turn: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not turn["transcript_path"] or turn["line_start"] is None or turn["line_end"] is None:
        raise ValueError("Queued turn has no transcript range")
    path = Path(turn["transcript_path"])
    start, end = int(turn["line_start"]), int(turn["line_end"])
    parse = _tree_module().parse_transcript_lines
    expected_source = turn["source_fingerprint"]

    def verified(parsed: Mapping[str, Any]) -> list[dict[str, Any]] | None:
        if parsed["thread_id"] and parsed["thread_id"] != turn["thread_id"]:
            raise TranscriptChangedError("Queued transcript belongs to a different chat")
        if parsed["cwd"] and state.project_id_for(parsed["cwd"]) != turn["project_id"]:
            raise TranscriptChangedError("Queued transcript belongs to a different project")
        messages = [item for item in parsed["messages"] if item["line"] >= start]
        if not messages or _turn_content_hash(messages) != turn["content_hash"]:
            return None
        if expected_source is not None and _turn_source_fingerprint(messages) != expected_source:
            return None
        return messages

    bounded = parse(path, start, end, include_header_metadata=True)
    if messages := verified(bounded):
        return messages
    if start > 1 and bounded["messages"]:
        # Some rollouts repeat message IDs from earlier turns. Replay the
        # prefix when the bounded read alone cannot reproduce deduplication.
        if messages := verified(parse(path, 1, end)):
            return messages
    raise TranscriptChangedError("Queued transcript evidence has changed or is unavailable")


def _retryable_turn_error(error: Exception) -> bool:
    if isinstance(error, (OSError, TranscriptChangedError)):
        return True
    return isinstance(error, sqlite3.Error) and (
        (getattr(error, "sqlite_errorcode", 0) & 0xFF) in RETRYABLE_SQLITE_ERRORS
    )


def _node_candidates(db: sqlite3.Connection, project_id: str, layer: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            "SELECT * FROM semantic_nodes WHERE project_id = ? AND layer = ? AND lifecycle IN ('locked','unlocked')",
            (project_id, layer),
        )
    ]


def _initial_states(db: sqlite3.Connection, project_id: str, chunks: list[dict[str, Any]]) -> None:
    for chunk in chunks:
        layer_states: dict[str, Any] = {}
        for layer in state.LAYERS:
            if layer != "span":
                # Upper ancestry is inherited from the accepted span. Writing
                # independent chunk->specific or chunk->broad assignments can
                # produce contradictory parent paths.
                layer_states[layer] = "unassigned"
                continue
            scored = sorted(
                ((_similarity(chunk, {**node, "text": f"{node['title']} {node['summary']}"}), node) for node in _node_candidates(db, project_id, layer)),
                key=lambda item: item[0],
                reverse=True,
            )
            best = scored[0] if scored else None
            second = scored[1][0] if len(scored) > 1 else 0.0
            if best and best[0] >= ASSIGN_THRESHOLDS[layer] and best[0] - second >= ASSIGN_MARGIN:
                layer_states[layer] = {
                    "state": best[1]["lifecycle"],
                    "target_id": best[1]["id"],
                    "membership_confidence": min(1.0, best[0]),
                }
            else:
                layer_states[layer] = "unassigned"
        chunk["layer_states"] = layer_states


def _centroid(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    vectors = [_vector(row.get("embedding")) for row in rows]
    vectors = [vector for vector in vectors if vector]
    if not vectors or len({len(vector) for vector in vectors}) != 1:
        return []
    return _normalize([sum(vector[index] for vector in vectors) / len(vectors) for index in range(len(vectors[0]))])


def _components(rows: list[dict[str, Any]], threshold: float) -> list[list[dict[str, Any]]]:
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    vectors = [_vector(row.get("embedding")) for row in rows]
    dense_matrix: Any | None = None
    if rows and all(vectors) and len({len(vector) for vector in vectors}) == 1:
        try:
            import numpy as np

            matrix = np.asarray(vectors, dtype=np.float64)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            matrix /= norms
            dense_matrix = matrix @ matrix.T
        except ImportError:
            dense_matrix = None
    token_sets = [set(_tokens(str(row.get("text", "")))) for row in rows]
    token_norms = [math.sqrt(len(tokens)) for tokens in token_sets]
    for left in range(len(rows)):
        for right in range(left + 1, len(rows)):
            if dense_matrix is None:
                similarity = _similarity(rows[left], rows[right])
            else:
                denominator = token_norms[left] * token_norms[right]
                lexical = (
                    len(token_sets[left] & token_sets[right]) / denominator
                    if denominator else 0.0
                )
                similarity = float(dense_matrix[left, right]) * 0.78 + lexical * 0.22
            if similarity >= threshold:
                union(left, right)
    groups: dict[int, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(find(index), []).append(row)
    return list(groups.values())


def _cluster_persistence(rows: Sequence[Mapping[str, Any]]) -> float:
    if len(rows) < 2:
        return 0.0
    vectors = [_vector(row.get("embedding")) for row in rows]
    if all(vectors) and len({len(vector) for vector in vectors}) == 1:
        try:
            import numpy as np

            matrix = np.asarray(vectors, dtype=np.float64)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            matrix /= norms
            # The squared norm of summed unit vectors contains each distinct
            # pair's dot product twice. Subtract the diagonal instead of
            # constructing the complete pairwise matrix. Normalized token
            # presence vectors follow the same identity without a dense matrix.
            pair_count = len(rows) * (len(rows) - 1)
            vector_sum = matrix.sum(axis=0)
            dense = float(vector_sum @ vector_sum - np.square(matrix).sum()) / pair_count
            token_totals: dict[str, float] = {}
            nonempty_rows = 0
            for row in rows:
                tokens = set(_tokens(str(row.get("text", ""))))
                if tokens:
                    nonempty_rows += 1
                    weight = 1.0 / math.sqrt(len(tokens))
                    for token in tokens:
                        token_totals[token] = token_totals.get(token, 0.0) + weight
            lexical = (math.fsum(value * value for value in token_totals.values()) - nonempty_rows) / pair_count
            return dense * 0.78 + lexical * 0.22
        except ImportError:
            pass
    scores = [
        _similarity(rows[left], rows[right])
        for left in range(len(rows))
        for right in range(left + 1, len(rows))
    ]
    return sum(scores) / len(scores) if scores else 0.0


def _deterministic_cluster_groups(
    rows: list[dict[str, Any]],
    layer: str,
) -> list[dict[str, Any]]:
    """Cluster small inputs without optional native dependencies.

    Persistence is a property of the group, so compute it once and reuse it
    for each member confidence. Recomputing the same pairwise score per member
    made a connected group effectively cubic.
    """

    result: list[dict[str, Any]] = []
    for group in _components(rows, SIMILARITY_THRESHOLDS[layer]):
        persistence = _cluster_persistence(group)
        result.append({
            "rows": group,
            "persistence": persistence,
            "confidences": {row["id"]: persistence for row in group},
            "provider": "deterministic-fallback",
        })
    return result


def _guard_deterministic_fallback_size(row_count: int) -> None:
    if row_count > DETERMINISTIC_FALLBACK_MAX_ROWS:
        raise RuntimeError(
            "Scalable clustering runtime is unavailable for "
            f"{row_count} rows; install the pinned NumPy/USearch runtime."
        )


def _usearch_cluster_groups(
    rows: list[dict[str, Any]],
    vectors: list[list[float]],
    layer: str,
) -> list[dict[str, Any]]:
    """Bound the deterministic fallback for large embedded fit inputs.

    The pairwise fallback is useful and reproducible for small groups, but it
    is quadratic and previously timed out on a 2,383-chunk project. USearch's
    native centroid clustering keeps the shipped no-BERTopic runtime bounded;
    BERTopic/HDBSCAN still remains the preferred path when installed.
    """

    if len(rows) < 1_000:
        return []
    import numpy as np
    from usearch.index import Index

    target_count = max(2, min(512, math.ceil(len(rows) / LOCK_SIZES[layer])))
    index = Index(
        ndim=len(vectors[0]),
        metric="cos",
        dtype="f32",
        connectivity=16,
        expansion_add=128,
        expansion_search=96,
    )
    keys = np.arange(len(rows), dtype=np.uint64)
    index.add(keys, np.asarray(vectors, dtype=np.float32))
    clustered = index.cluster(min_count=target_count, max_count=target_count)
    centroid_keys = np.asarray(clustered.matches.keys).reshape(-1)
    distances = np.asarray(clustered.matches.distances).reshape(-1)
    grouped: dict[int, list[tuple[dict[str, Any], float]]] = {}
    for row_key, centroid_key, distance in zip(
        np.asarray(clustered.queries).reshape(-1),
        centroid_keys,
        distances,
    ):
        grouped.setdefault(int(centroid_key), []).append(
            (rows[int(row_key)], max(0.0, min(1.0, 1.0 - float(distance))))
        )
    result: list[dict[str, Any]] = []
    for members in grouped.values():
        member_rows = [row for row, _ in members]
        persistence = _cluster_persistence(member_rows)
        result.append(
            {
                "rows": member_rows,
                "persistence": persistence,
                "confidences": {
                    str(row["id"]): confidence for row, confidence in members
                },
                "provider": "usearch-centroid-fallback",
            }
        )
    return result


def _cluster_groups(rows: list[dict[str, Any]], layer: str) -> list[dict[str, Any]]:
    """Use BERTopic/HDBSCAN when installed, otherwise a deterministic fallback."""

    vectors = [_vector(row.get("embedding")) for row in rows]
    if rows and all(vectors) and len({len(vector) for vector in vectors}) == 1:
        try:
            import numpy as np
            from bertopic import BERTopic
            from hdbscan import HDBSCAN
            from umap import UMAP

            minimum = FORMATION_SIZES[layer]
            hdbscan_model = HDBSCAN(
                min_cluster_size=minimum,
                min_samples=max(1, minimum // 2),
                metric="euclidean",
                cluster_selection_method="eom",
                prediction_data=True,
            )
            reducer = UMAP(
                n_neighbors=max(2, min(15, len(rows) - 1)),
                n_components=max(2, min(5, len(rows) - 1)),
                min_dist=0.0,
                metric="cosine",
                random_state=42,
            )
            model = BERTopic(
                embedding_model=None,
                umap_model=reducer,
                hdbscan_model=hdbscan_model,
                calculate_probabilities=True,
                verbose=False,
            )
            topics, probabilities = model.fit_transform([row["text"] for row in rows], np.asarray(vectors))
            persistence_values = list(getattr(hdbscan_model, "cluster_persistence_", []))
            grouped: dict[int, list[tuple[int, dict[str, Any]]]] = {}
            for index, topic in enumerate(topics):
                if int(topic) >= 0:
                    grouped.setdefault(int(topic), []).append((index, rows[index]))
            result = []
            assigned_ids: set[str] = set()
            for topic, members in grouped.items():
                persistence = float(persistence_values[topic]) if topic < len(persistence_values) else 0.0
                confidences: dict[str, float] = {}
                for index, row in members:
                    probability = probabilities[index] if probabilities is not None else persistence
                    if hasattr(probability, "__len__") and not isinstance(probability, (str, bytes)):
                        probability = max(float(value) for value in probability) if len(probability) else persistence
                    confidences[row["id"]] = max(0.0, min(1.0, float(probability)))
                member_rows = [row for _, row in members]
                assigned_ids.update(str(row["id"]) for row in member_rows)
                result.append({"rows": member_rows, "persistence": persistence, "confidences": confidences, "provider": "bertopic+hdbscan"})
            if layer != "span":
                # Every semantic child needs one structural parent even when
                # HDBSCAN considers it an outlier. A singleton parent stays
                # unlocked until enough descendant evidence supports locking.
                for row in rows:
                    if str(row["id"]) not in assigned_ids:
                        result.append({
                            "rows": [row],
                            "persistence": 0.0,
                            "confidences": {str(row["id"]): 0.0},
                            "provider": "bertopic-outlier-wrapper",
                        })
            return result
        except (ImportError, ValueError, RuntimeError):
            pass
        try:
            scalable = _usearch_cluster_groups(rows, vectors, layer)
            if scalable:
                return scalable
        except (ImportError, ValueError, RuntimeError):
            pass
    _guard_deterministic_fallback_size(len(rows))
    return _deterministic_cluster_groups(rows, layer)


def _representation(rows: Sequence[Mapping[str, Any]]) -> tuple[str, str, list[str]]:
    counts = Counter(token for row in rows for token in _tokens(str(row["text"])))
    keywords = [token for token, _ in counts.most_common(8)]
    title = " · ".join(word.replace("-", " ").title() for word in keywords[:3]) or "Conversation topic"
    samples = [str(row["text"]).splitlines()[0][:180] for row in rows[:3]]
    return title, "; ".join(samples)[:720], keywords


def _fit_rows_for_layer(
    db: sqlite3.Connection,
    run: Mapping[str, Any],
    layer: str,
    materialized: Mapping[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str]:
    """Return evidence-first fit units for one hierarchy layer."""

    if layer == "span":
        ids = state.fit_input_chunk_ids(db, str(run["id"]), layer)
        rows = [dict(row) for row in db.execute(
            f"SELECT * FROM turn_chunks WHERE id IN ({','.join('?' for _ in ids)}) ORDER BY seq",
            ids,
        )] if ids else []
        for row in rows:
            row["descendant_members"] = [(str(row["id"]), 1.0)]
        return rows, "chunk"

    child_layer = "span" if layer == "specific" else "specific"
    rows = []
    for child in materialized.get(child_layer, []):
        rows.append({
            "id": str(child["id"]),
            "text": f"{child['title']}\n{child['summary']}",
            "embedding": child.get("embedding"),
            "descendant_members": list(child.get("members") or []),
        })
    return rows, child_layer


def _descendant_members(
    group: Sequence[Mapping[str, Any]],
    confidences: Mapping[str, float],
    persistence: float,
) -> list[tuple[str, float]]:
    descendants: dict[str, float] = {}
    for row in group:
        row_confidence = float(confidences.get(str(row["id"]), persistence))
        for chunk_id, inherited_confidence in row.get("descendant_members") or [(row["id"], 1.0)]:
            combined = max(0.0, min(1.0, row_confidence * float(inherited_confidence)))
            descendants[str(chunk_id)] = max(descendants.get(str(chunk_id), 0.0), combined)
    return sorted(descendants.items())


def _materialize_layer(
    db: sqlite3.Connection,
    project_id: str,
    layer: str,
    clusters: Sequence[Mapping[str, Any]],
    *,
    replace_all: bool = False,
    manage_transaction: bool = True,
) -> None:
    now = state.utc_now()
    with db if manage_transaction else nullcontext():
        lifecycle_filter = "" if replace_all else "AND lifecycle = 'unlocked'"
        stale = [row["id"] for row in db.execute(
            f"SELECT id FROM semantic_nodes WHERE project_id = ? AND layer = ? {lifecycle_filter}",
            (project_id, layer),
        )]
        if stale:
            db.executemany("DELETE FROM semantic_nodes WHERE id = ?", [(node_id,) for node_id in stale])
        for cluster in clusters:
            db.execute(
                """INSERT INTO semantic_nodes
                   (id, project_id, layer, lifecycle, title, summary, keywords, persistence,
                    embedding, generation_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, summary=excluded.summary,
                     keywords=excluded.keywords, persistence=excluded.persistence,
                     embedding=excluded.embedding, generation_id=excluded.generation_id,
                     lifecycle=excluded.lifecycle, updated_at=excluded.updated_at""",
                (
                    cluster["id"], project_id, layer, cluster["lifecycle"], cluster["title"],
                    cluster["summary"], json.dumps(cluster["keywords"]), cluster["persistence"],
                    json.dumps(cluster["embedding"]) if cluster["embedding"] else None,
                    cluster.get("generation_id"), now, now,
                ),
            )
            db.execute("DELETE FROM semantic_node_memberships WHERE node_id = ?", (cluster["id"],))
            db.executemany(
                "INSERT INTO semantic_node_memberships(node_id, chunk_id, membership_confidence) VALUES (?, ?, ?)",
                [(cluster["id"], chunk_id, confidence) for chunk_id, confidence in cluster["members"]],
            )


def _start_fit_phase(
    db: sqlite3.Connection,
    run_id: str,
    phase: str,
    *,
    layer: str = "",
    input_count: int | None = None,
    estimated_pair_comparisons: int | None = None,
) -> float:
    with db:
        db.execute(
            """INSERT INTO fit_run_phase_metrics
               (run_id, phase, layer, status, started_at, input_count,
                estimated_pair_comparisons, details)
               VALUES (?, ?, ?, 'running', ?, ?, ?, '{}')
               ON CONFLICT(run_id, phase, layer) DO UPDATE SET
                 status='running', started_at=excluded.started_at,
                 completed_at=NULL, elapsed_ms=NULL,
                 input_count=excluded.input_count, output_count=NULL,
                 estimated_pair_comparisons=excluded.estimated_pair_comparisons,
                 provider=NULL, details='{}'""",
            (
                run_id,
                phase,
                layer,
                state.utc_now(),
                input_count,
                estimated_pair_comparisons,
            ),
        )
    return time.perf_counter()


def _finish_fit_phase(
    db: sqlite3.Connection,
    run_id: str,
    phase: str,
    started: float,
    *,
    layer: str = "",
    output_count: int | None = None,
    provider: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    with db:
        db.execute(
            """UPDATE fit_run_phase_metrics
               SET status='completed', completed_at=?, elapsed_ms=?,
                   output_count=?, provider=?, details=?
               WHERE run_id=? AND phase=? AND layer=?""",
            (
                state.utc_now(),
                round((time.perf_counter() - started) * 1000, 3),
                output_count,
                provider,
                json.dumps(dict(details or {}), sort_keys=True),
                run_id,
                phase,
                layer,
            ),
        )


def _fail_fit_phase(
    db: sqlite3.Connection,
    run_id: str,
    phase: str,
    started: float,
    error: Exception,
    *,
    layer: str = "",
) -> None:
    with db:
        db.execute(
            """UPDATE fit_run_phase_metrics
               SET status='failed', completed_at=?, elapsed_ms=?, details=?
               WHERE run_id=? AND phase=? AND layer=?""",
            (
                state.utc_now(),
                round((time.perf_counter() - started) * 1000, 3),
                json.dumps({"error": str(error)}, sort_keys=True),
                run_id,
                phase,
                layer,
            ),
        )


def _rebuild_edges(
    db: sqlite3.Connection,
    project_id: str,
    *,
    manage_transaction: bool = True,
) -> None:
    with db if manage_transaction else nullcontext():
        db.execute(
            "DELETE FROM semantic_edges WHERE child_id IN (SELECT id FROM semantic_nodes WHERE project_id = ?)",
            (project_id,),
        )
        for child_layer, parent_layer in (("span", "specific"), ("specific", "broad")):
            children = db.execute(
                "SELECT id FROM semantic_nodes WHERE project_id = ? AND layer = ? AND lifecycle != 'retired'",
                (project_id, child_layer),
            ).fetchall()
            parents = db.execute(
                "SELECT id FROM semantic_nodes WHERE project_id = ? AND layer = ? AND lifecycle != 'retired'",
                (project_id, parent_layer),
            ).fetchall()
            parent_sets = {
                row["id"]: {item[0] for item in db.execute("SELECT chunk_id FROM semantic_node_memberships WHERE node_id = ?", (row["id"],))}
                for row in parents
            }
            for child in children:
                child_chunks = {item[0] for item in db.execute("SELECT chunk_id FROM semantic_node_memberships WHERE node_id = ?", (child["id"],))}
                if not child_chunks:
                    continue
                scored = sorted(
                    ((len(child_chunks & chunks) / len(child_chunks), parent_id) for parent_id, chunks in parent_sets.items()),
                    reverse=True,
                )
                if scored and scored[0][0] > 0:
                    coverage, parent_id = scored[0]
                    db.execute(
                        "INSERT INTO semantic_edges(child_id, parent_id, primary_edge, coverage) VALUES (?, ?, 1, ?)",
                        (child["id"], parent_id, coverage),
                    )


@contextmanager
def _project_maintenance_lock(db: sqlite3.Connection, project_id: str) -> Iterator[None]:
    """Serialize fit publication and cleanup, with ownership released on exit."""
    database = next(
        (Path(row[2]) for row in db.execute("PRAGMA database_list") if row[1] == "main" and row[2]), None,
    )
    if database is None:
        yield
        return
    lock_name = state.stable_id("fit", database.name, project_id)
    with state.exclusive_process_lock(database.parent / "maintenance-locks" / lock_name):
        yield


def run_fit(db: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    run = db.execute("SELECT project_id FROM fit_runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise KeyError(run_id)
    with _project_maintenance_lock(db, run["project_id"]):
        return _run_fit_locked(db, run_id)


def rebuild_project(
    db: sqlite3.Connection, project_id: str, *, reason: str, operation_id: str | None = None,
) -> dict[str, Any]:
    """Drain older work, then take a fresh watermark once per operation."""
    with _project_maintenance_lock(db, project_id):
        if operation_id:
            reason = f"{reason}: {operation_id}"
            completed = db.execute(
                """SELECT * FROM fit_runs WHERE project_id=? AND kind='rebalance'
                   AND reason=? AND state='committed' ORDER BY rowid DESC LIMIT 1""",
                (project_id, reason),
            ).fetchone()
            if completed:
                return dict(completed)
        previous = state._active_fit(db, project_id)
        if previous is not None:
            result = _run_fit_locked(db, previous["id"])
            if operation_id and previous["kind"] == "rebalance" and previous["reason"] == reason:
                return result
        run = state.schedule_global_rebuild(db, project_id, reason=reason)
        return _run_fit_locked(db, run["id"])


def _run_fit_locked(db: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    current = db.execute("SELECT * FROM fit_runs WHERE id=?", (run_id,)).fetchone()
    if current and current["state"] == "committed":
        return dict(current)
    # The kernel lock excludes a live previous worker. A persisted running
    # state now means its immutable watermark can safely be retried.
    run = state.claim_fit_run(db, run_id, resume=True)
    layers = json.loads(run["layers"])
    assignments: dict[str, dict[str, Any]] = {}
    materialized: dict[str, list[dict[str, Any]]] = {}
    active_phase: tuple[str, str, float] | None = None
    try:
        for layer in layers:
            started = _start_fit_phase(db, run_id, "load_input", layer=layer)
            active_phase = ("load_input", layer, started)
            rows, input_unit = _fit_rows_for_layer(db, run, layer, materialized)
            _finish_fit_phase(
                db,
                run_id,
                "load_input",
                started,
                layer=layer,
                output_count=len(rows),
                details={"input_unit": input_unit},
            )
            active_phase = None
            assignments[layer] = {}
            materialized[layer] = []
            claimed_previous_ids: set[str] = set()
            started = _start_fit_phase(
                db,
                run_id,
                "cluster",
                layer=layer,
                input_count=len(rows),
                estimated_pair_comparisons=len(rows) * (len(rows) - 1) // 2,
            )
            active_phase = ("cluster", layer, started)
            fitted_groups = _cluster_groups(rows, layer)
            providers = sorted({str(group.get("provider") or "unknown") for group in fitted_groups})
            _finish_fit_phase(
                db,
                run_id,
                "cluster",
                started,
                layer=layer,
                output_count=len(fitted_groups),
                provider=",".join(providers),
            )
            active_phase = None
            started = _start_fit_phase(db, run_id, "assign", layer=layer, input_count=len(fitted_groups))
            active_phase = ("assign", layer, started)
            for fitted in fitted_groups:
                group = fitted["rows"]
                if layer == "span" and len(group) < FORMATION_SIZES[layer]:
                    continue
                persistence = fitted["persistence"]
                descendants = _descendant_members(group, fitted["confidences"], persistence)
                descendant_count = len(descendants)
                lifecycle = "locked" if descendant_count >= LOCK_SIZES[layer] and persistence >= LOCK_PERSISTENCE[layer] else "unlocked"
                node_id = state.stable_id(lifecycle, run["project_id"], layer, run_id, *(row["id"] for row in group))
                if run["kind"] != "routine":
                    new_members = {chunk_id for chunk_id, _ in descendants}
                    best_overlap, best_id = 0.0, None
                    for previous in db.execute(
                        "SELECT id FROM semantic_nodes WHERE project_id=? AND layer=? AND lifecycle!='retired'",
                        (run["project_id"], layer),
                    ):
                        if previous["id"] in claimed_previous_ids:
                            continue
                        old_members = {row[0] for row in db.execute("SELECT chunk_id FROM semantic_node_memberships WHERE node_id=?", (previous["id"],))}
                        union = new_members | old_members
                        overlap = len(new_members & old_members) / len(union) if union else 0.0
                        if overlap > best_overlap:
                            best_overlap, best_id = overlap, previous["id"]
                    if best_overlap >= 0.5 and best_id:
                        node_id = best_id
                        claimed_previous_ids.add(best_id)
                title, summary, keywords = _representation(group)
                materialized[layer].append(
                    {
                        "id": node_id,
                        "lifecycle": lifecycle,
                        "title": title,
                        "summary": summary,
                        "keywords": keywords,
                        "persistence": persistence,
                        "embedding": _centroid(group),
                        "members": descendants,
                        "child_ids": [str(row["id"]) for row in group],
                        "input_unit": input_unit,
                    }
                )
                if layer == "span":
                    for row in group:
                        assignments[layer][row["id"]] = {
                            "state": lifecycle,
                            "target_id": node_id,
                            "membership_confidence": fitted["confidences"].get(row["id"], min(1.0, max(0.0, persistence))),
                        }
            _finish_fit_phase(
                db,
                run_id,
                "assign",
                started,
                layer=layer,
                output_count=len(materialized[layer]),
            )
            active_phase = None
        commit_started = _start_fit_phase(
            db,
            run_id,
            "commit_state",
            input_count=sum(len(value) for value in assignments.values()),
        )
        materialize_started = {
            layer: _start_fit_phase(
                db,
                run_id,
                "materialize",
                layer=layer,
                input_count=len(materialized[layer]),
            )
            for layer in layers
        }
        edges_started = _start_fit_phase(db, run_id, "rebuild_edges")
        publish_started = _start_fit_phase(db, run_id, "publish_tree")

        # Semantic nodes, edges, chunk state, active generations, and the
        # project-visible tree token publish in one SQLite transaction. The UI
        # may keep rendering the previous completed snapshot until this commit.
        active_phase = ("commit_state", "", commit_started)
        with db:
            committed = state.commit_fit_run(
                db,
                run_id,
                assignments,
                manage_transaction=False,
            )
            for layer in layers:
                active_phase = ("materialize", layer, materialize_started[layer])
                generation = db.execute(
                    "SELECT id FROM cluster_generations WHERE fit_run_id = ? AND layer = ?",
                    (run_id, layer),
                ).fetchone()
                for cluster in materialized[layer]:
                    cluster["generation_id"] = generation["id"] if generation else None
                _materialize_layer(
                    db,
                    run["project_id"],
                    layer,
                    materialized[layer],
                    replace_all=run["kind"] != "routine",
                    manage_transaction=False,
                )
            active_phase = ("rebuild_edges", "", edges_started)
            _rebuild_edges(db, run["project_id"], manage_transaction=False)
            edge_count = db.execute(
                """SELECT COUNT(*) FROM semantic_edges
                   WHERE child_id IN (SELECT id FROM semantic_nodes WHERE project_id=?)""",
                (run["project_id"],),
            ).fetchone()[0]
            active_phase = ("publish_tree", "", publish_started)
            db.execute(
                """INSERT INTO project_active_tree(project_id, generation_token, updated_at)
                   VALUES (?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET
                   generation_token=excluded.generation_token, updated_at=excluded.updated_at""",
                (run["project_id"], run_id, state.utc_now()),
            )

        _finish_fit_phase(
            db,
            run_id,
            "commit_state",
            commit_started,
            details={"atomic_publication": True},
        )
        for layer in layers:
            _finish_fit_phase(
                db,
                run_id,
                "materialize",
                materialize_started[layer],
                layer=layer,
                output_count=len(materialized[layer]),
                details={"atomic_publication": True},
            )
        _finish_fit_phase(
            db,
            run_id,
            "rebuild_edges",
            edges_started,
            output_count=edge_count,
            details={"atomic_publication": True},
        )
        _finish_fit_phase(
            db,
            run_id,
            "publish_tree",
            publish_started,
            output_count=1,
            details={"atomic_publication": True},
        )
        active_phase = None
        return committed
    except Exception as error:
        if active_phase is not None:
            phase, layer, started = active_phase
            _fail_fit_phase(db, run_id, phase, started, error, layer=layer)
        current = db.execute("SELECT state FROM fit_runs WHERE id = ?", (run_id,)).fetchone()
        if current and current["state"] == "running":
            state.fail_fit_run(db, run_id, str(error))
        raise


def _model_upgrade_needed(db: sqlite3.Connection, project_id: str, model: str) -> bool:
    return db.execute(
        """SELECT 1 FROM turn_chunks WHERE project_id=? AND evicted=0
           AND embedding IS NOT NULL AND (embedding_model IS NULL OR embedding_model!=?) LIMIT 1""",
        (project_id, model),
    ).fetchone() is not None


def _migrate_project_embeddings(
    db: sqlite3.Connection, project_id: str, provider: Any, batch_size: int,
) -> int:
    """Stage a new vector space before replacing the complete live snapshot."""
    model = provider.embedding_model
    dimension = int(provider.embedding_dimension)
    # TEMP storage is private to this connection and can spill to disk. A
    # stopped worker loses staging work while leaving every old vector intact.
    db.execute("DROP TABLE IF EXISTS temp.embedding_upgrade_staging")
    db.execute("""CREATE TEMP TABLE embedding_upgrade_staging (
        id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, embedding TEXT NOT NULL
    )""")
    try:
        with _project_maintenance_lock(db, project_id):
            while True:
                rows = db.execute(
                    """SELECT c.id, c.text, c.content_hash FROM turn_chunks c
                       WHERE c.project_id=? AND c.evicted=0
                         AND (c.embedding IS NULL OR c.embedding_model IS NULL OR c.embedding_model!=?)
                         AND NOT EXISTS (SELECT 1 FROM temp.embedding_upgrade_staging s
                                         WHERE s.id=c.id AND s.content_hash=c.content_hash)
                       ORDER BY c.seq LIMIT ?""",
                    (project_id, model, batch_size),
                ).fetchall()
                if rows:
                    vectors = provider.embed([str(row["text"]) for row in rows], task="passage")
                    if len(vectors) != len(rows) or provider.embedding_model != model:
                        raise RuntimeError("The embedding model upgrade returned an incomplete batch")
                    if any(len(vector) != dimension or not all(math.isfinite(value) for value in vector)
                           or not any(vector) for vector in vectors):
                        raise RuntimeError("The embedding model upgrade returned an invalid vector")
                    with db:
                        db.executemany(
                            """INSERT OR REPLACE INTO temp.embedding_upgrade_staging
                               (id, content_hash, embedding) VALUES (?, ?, ?)""",
                            [(row["id"], row["content_hash"], json.dumps(_normalize(vector)))
                             for row, vector in zip(rows, vectors)],
                        )
                    continue

                with db:
                    db.execute("BEGIN IMMEDIATE")
                    if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                        return 0
                    # A concurrent turn or source correction may have committed
                    # between the last batch and acquiring the write lock.
                    unstaged = db.execute(
                        """SELECT 1 FROM turn_chunks c WHERE c.project_id=? AND c.evicted=0
                           AND (c.embedding IS NULL OR c.embedding_model IS NULL OR c.embedding_model!=?)
                           AND NOT EXISTS (SELECT 1 FROM temp.embedding_upgrade_staging s
                                           WHERE s.id=c.id AND s.content_hash=c.content_hash) LIMIT 1""",
                        (project_id, model),
                    ).fetchone()
                    if unstaged:
                        continue
                    published = db.execute(
                        """UPDATE turn_chunks SET embedding=(
                               SELECT s.embedding FROM temp.embedding_upgrade_staging s
                               WHERE s.id=turn_chunks.id AND s.content_hash=turn_chunks.content_hash
                           ), embedding_model=?
                           WHERE project_id=? AND evicted=0
                             AND (embedding IS NULL OR embedding_model IS NULL OR embedding_model!=?)
                             AND EXISTS (SELECT 1 FROM temp.embedding_upgrade_staging s
                                         WHERE s.id=turn_chunks.id AND s.content_hash=turn_chunks.content_hash)""",
                        (model, project_id, model),
                    ).rowcount
                    if published:
                        # Keep the completed tree readable. Its previous model's
                        # centroids cannot guide assignment in the new space.
                        db.execute("UPDATE semantic_nodes SET embedding=NULL WHERE project_id=?", (project_id,))
                        db.execute(
                            """UPDATE fit_runs SET state='cancelled', error=?, completed_at=?
                               WHERE project_id=? AND state IN ('queued','running')""",
                            (f"Superseded by embedding model upgrade to {model}", state.utc_now(), project_id),
                        )
                        state.schedule_global_rebuild(
                            db, project_id, reason=f"embedding model upgrade to {model}", manage_transaction=False,
                        )
                    return published
    finally:
        db.execute("DROP TABLE IF EXISTS temp.embedding_upgrade_staging")


def _backfill_project_embeddings(
    db: sqlite3.Connection,
    project_id: str,
    provider: Any,
    *,
    batch_size: int = 32,
) -> int:
    """Embed missing/stale live chunks in bounded background batches."""

    if not provider.can_embed:
        return 0
    if _model_upgrade_needed(db, project_id, provider.embedding_model):
        return _migrate_project_embeddings(db, project_id, provider, batch_size)
    total = 0
    while True:
        rows = db.execute(
            """SELECT id, text FROM turn_chunks
               WHERE project_id=? AND evicted=0
                 AND (embedding IS NULL OR embedding_model IS NULL OR embedding_model!=?)
               ORDER BY seq LIMIT ?""",
            (project_id, provider.embedding_model, batch_size),
        ).fetchall()
        if not rows:
            break
        vectors = provider.embed([str(row["text"]) for row in rows], task="passage")
        if len(vectors) != len(rows):
            break
        normalized = [_normalize(vector) for vector in vectors]
        if normalized:
            provider.embedding_dimension = len(normalized[0])
        with db:
            db.executemany(
                "UPDATE turn_chunks SET embedding=?, embedding_model=? WHERE id=?",
                [
                    (json.dumps(vector), provider.embedding_model, str(row["id"]))
                    for row, vector in zip(rows, normalized)
                ],
            )
        total += len(rows)
    return total


def process_project(
    project_id: str,
    *,
    max_turns: int | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    tree = _tree_module()
    with closing(tree.connect_db()) as db:
        return _process_project(db, project_id, max_turns=max_turns, thread_id=thread_id)


def _process_project(
    db: sqlite3.Connection,
    project_id: str,
    *,
    max_turns: int | None,
    thread_id: str | None,
) -> dict[str, Any]:
    tree = _tree_module()
    config = _project_config()
    provider = tree.SemanticProvider(config)
    processed = 0
    failures: list[str] = []
    embedded_chunks = 0
    migration_failed = False
    if provider.can_embed and _model_upgrade_needed(db, project_id, provider.embedding_model):
        try:
            # Upgrade before assigning new chunks to existing topic centroids.
            embedded_chunks = _backfill_project_embeddings(db, project_id, provider)
        except Exception as error:
            migration_failed = True
            failures.append(f"embedding model upgrade: {error}")
    if max_turns is None or max_turns > 0:
        state.requeue_retryable_turns(db, project_id, thread_id)
    while max_turns is None or processed < max_turns:
        turn = state.claim_next_turn(db, project_id, thread_id=thread_id)
        if not turn:
            break
        try:
            chunks = semantic_chunks(_read_turn_messages(turn))
            for chunk in chunks:
                chunk["id"] = state.stable_id(
                    "chunk",
                    turn["id"],
                    chunk.get("line_start"),
                    chunk.get("line_end"),
                    chunk["content_hash"],
                    chunk.pop("ordinal", 0),
                    CHUNKER_VERSION,
                )
            if provider.can_embed and not migration_failed and chunks:
                vectors = provider.embed([chunk["text"] for chunk in chunks], task="passage")
                if vectors:
                    provider.embedding_dimension = len(vectors[0])
                for chunk, vector in zip(chunks, vectors):
                    chunk["embedding"] = _normalize(vector)
                    chunk["embedding_model"] = provider.embedding_model
            _initial_states(db, project_id, chunks)
            state.complete_turn_ingestion(db, turn["id"], chunks, lease_token=turn["lease_token"])
            processed += 1
        except state.LostTurnLeaseError:
            # A newer claim won while a provider call was in flight.
            continue
        except Exception as error:
            try:
                state.transition_turn(
                    db, turn["id"], "failed", str(error), lease_token=turn["lease_token"],
                    retryable=_retryable_turn_error(error),
                )
            except state.LostTurnLeaseError:
                continue
            failures.append(f"{turn['id']}: {error}")

    index_result: dict[str, Any] | None = None
    if provider.can_embed and not migration_failed:
        try:
            embedded_chunks += _backfill_project_embeddings(db, project_id, provider)
            if vector_index.available():
                index_result = vector_index.update_project_index(
                    db,
                    data_directory=tree.data_dir(),
                    project_id=project_id,
                    model=provider.embedding_model,
                    dimension=provider.embedding_dimension,
                )
        except Exception as error:
            # The ANN structure is derived and rebuildable. Preserve completed
            # source ingestion and the complete SQLite FTS fallback.
            failures.append(f"embedding index: {error}")

    evicted: list[str] = []
    with _project_maintenance_lock(db, project_id):
        while True:
            run = state.schedule_routine_fit(db, project_id)
            if not run:
                break
            _run_fit_locked(db, run["id"])
            # New debt can schedule the next snapshot.
            if not any(row["debt_count"] >= row["threshold"] for row in state.debt_status(db, project_id)):
                break
        try:
            eviction_plan = state.plan_capacity_eviction(db, project_id)
            if eviction_plan:
                token = state.stable_id("eviction", project_id, state.utc_now())
                evicted = state.mark_turns_evicted(db, project_id, eviction_plan, eviction_generation=token)
        except state.StateTransitionError as error:
            failures.append(str(error))
        try:
            cleanup_index = _finish_eviction(db, project_id, provider)
            if cleanup_index is not None:
                index_result = cleanup_index
        except state.StateTransitionError as error:
            failures.append(str(error))
    snapshot = state.state_snapshot(db, project_id)
    return {
        "processed_turns": processed,
        "embedded_chunks": embedded_chunks,
        "vector_index": index_result,
        "evicted_turns": evicted,
        "failures": failures,
        "state": snapshot,
    }


def _finish_eviction(db: sqlite3.Connection, project_id: str, provider: Any) -> dict[str, Any] | None:
    pending = db.execute(
        """SELECT e.turn_id, r.state AS rebuild_state FROM evicted_turns e
           LEFT JOIN fit_runs r ON r.id=e.eviction_generation AND r.project_id=e.project_id
             AND r.kind='capacity_rebuild'
           WHERE e.project_id=? AND EXISTS (
               SELECT 1 FROM turn_chunks c WHERE c.turn_id=e.turn_id AND c.evicted=1
           )""",
        (project_id,),
    ).fetchall()
    if not pending:
        return None
    if any(row["rebuild_state"] != "committed" for row in pending):
        # Pair the rebuild and its pending deletion batch in one transaction.
        # Older tombstones without a paired fit are recovered here as well.
        with db:
            run = state.schedule_global_rebuild(
                db, project_id, kind="capacity_rebuild", reason="retention capacity", manage_transaction=False,
            )
            db.executemany(
                "UPDATE evicted_turns SET eviction_generation=? WHERE turn_id=?",
                [(run["id"], row["turn_id"]) for row in pending],
            )
        _run_fit_locked(db, run["id"])
    index_result = None
    if provider.can_embed and vector_index.available():
        # Keep the deletion batch recoverable until the derived index is
        # rebuilt as well. Search membership excludes these tombstones now.
        index_result = vector_index.rebuild_project_index(
            db,
            data_directory=_tree_module().data_dir(),
            project_id=project_id,
            model=provider.embedding_model,
            dimension=provider.embedding_dimension,
        )
    else:
        vector_index.invalidate_project_index(
            db, data_directory=_tree_module().data_dir(), project_id=project_id,
        )
    turns = [(row["turn_id"],) for row in pending]
    with db:
        db.executemany(
            "DELETE FROM turn_chunks_fts WHERE chunk_id IN (SELECT id FROM turn_chunks WHERE turn_id=? AND evicted=1)",
            turns,
        )
        db.executemany("DELETE FROM turn_chunks WHERE turn_id=? AND evicted=1", turns)
    return index_result


def process_all_pending(*, max_turns_per_project: int | None = None) -> list[dict[str, Any]]:
    tree = _tree_module()
    db = tree.connect_db()
    projects = [row[0] for row in db.execute("SELECT id FROM projects ORDER BY updated_at")]
    db.close()
    return [{"project_id": project_id, **process_project(project_id, max_turns=max_turns_per_project)} for project_id in projects]


def search_project(
    project_id: str,
    query: str,
    limit: int = 12,
    *,
    exclude_chunk_ids: Iterable[str] = (),
    chunk_watermark: int | None = None,
    allowed_thread_ids: Iterable[str] | None = None,
    excluded_thread_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    tree = _tree_module()
    db = tree.connect_db()
    scores: dict[str, float] = {}
    lexical_scores: dict[str, float] = {}
    semantic_scores: dict[str, float] = {}
    diagnostics: dict[str, dict[str, Any]] = {}
    excluded = {str(chunk_id) for chunk_id in exclude_chunk_ids}
    allowed_threads = None if allowed_thread_ids is None else {str(thread_id) for thread_id in allowed_thread_ids}
    excluded_threads = {str(thread_id) for thread_id in excluded_thread_ids}
    if allowed_threads is not None:
        allowed_threads.difference_update(excluded_threads)
        if not allowed_threads:
            db.close()
            return []
        permission_sql = f"AND c.thread_id IN ({','.join('?' for _ in allowed_threads)})"
        permission_values = sorted(allowed_threads)
    elif excluded_threads:
        permission_sql = f"AND c.thread_id NOT IN ({','.join('?' for _ in excluded_threads)})"
        permission_values = sorted(excluded_threads)
    else:
        permission_sql = ""
        permission_values = []

    def thread_allowed(thread_id: Any) -> bool:
        identifier = str(thread_id)
        return identifier not in excluded_threads and (allowed_threads is None or identifier in allowed_threads)
    watermark = chunk_watermark
    if watermark is None:
        watermark = db.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM turn_chunks WHERE project_id = ? AND evicted = 0",
            (project_id,),
        ).fetchone()[0]
    config = _project_config()
    tokens = _tokens(query)
    token_set = set(tokens)
    decision_query = bool(
        token_set & {"decide", "decided", "choose", "chose", "chosen", "term", "final", "scope"}
        or (
            "user" in token_set
            and token_set & {"request", "requested", "replace", "replaced"}
        )
    )
    lexical_exact_query = _looks_lexically_exact(query, tokens, decision_query)
    if tokens:
        unique_tokens = list(dict.fromkeys(tokens))
        if len(unique_tokens) > 32:
            fts_tokens = unique_tokens[:16] + unique_tokens[-16:]
        else:
            fts_tokens = unique_tokens
        fts_query = " OR ".join(f'"{token}"' for token in fts_tokens)
        try:
            for position, row in enumerate(db.execute(
                f"""SELECT f.chunk_id, c.thread_id, c.text, bm25(turn_chunks_fts) AS fts_rank
                   FROM turn_chunks_fts f
                   JOIN turn_chunks c ON c.id = f.chunk_id
                   WHERE turn_chunks_fts MATCH ? AND f.project_id = ?
                     AND c.evicted = 0 AND c.seq <= ? {permission_sql}
                   ORDER BY fts_rank LIMIT 100""",
                (fts_query, project_id, watermark, *permission_values),
            )):
                if row["chunk_id"] not in excluded and thread_allowed(row["thread_id"]):
                    direct_user_evidence = str(row["text"]).lstrip().startswith("USER:")
                    authority_boost = 0.10 if decision_query and direct_user_evidence else 0.0
                    lowered_chunk = str(row["text"]).casefold()
                    decision_declaration = int(
                        decision_query
                        and direct_user_evidence
                        and any(
                            phrase in lowered_chunk
                            for phrase in (
                                "stick with the term",
                                "use the term",
                                "let's call",
                                "lets call",
                                "we'll call",
                                "we will call",
                                "rename it",
                                "final decision",
                            )
                        )
                    )
                    decision_declaration_boost = 0.35 * decision_declaration
                    chunk_token_sequence = _tokens(str(row["text"]))
                    chunk_tokens = set(chunk_token_sequence)
                    query_tokens = set(tokens)
                    query_bigrams = set(zip(tokens, tokens[1:]))
                    chunk_bigrams = set(zip(chunk_token_sequence, chunk_token_sequence[1:]))
                    base_score = max(0.25, 0.96 - position * 0.02)
                    coverage = len(query_tokens & chunk_tokens) / len(query_tokens) if query_tokens else 0.0
                    bigram_coverage = (
                        len(query_bigrams & chunk_bigrams) / len(query_bigrams) if query_bigrams else 0.0
                    )
                    lexical_similarity = _lexical_similarity(query, str(row["text"]))
                    exact_phrase = int(query.casefold() in str(row["text"]).casefold())
                    query_echo_candidate = int(
                        direct_user_evidence
                        and exact_phrase
                        and "?" in str(row["text"])
                        and coverage >= 0.8
                    )
                    rerank_score = (
                        base_score * 0.55
                        + coverage * 0.20
                        + lexical_similarity * 0.15
                        + bigram_coverage * 0.10
                        + authority_boost
                        + decision_declaration_boost
                        + exact_phrase * 0.10
                    )
                    lexical_scores[row["chunk_id"]] = min(1.0, rerank_score)
                    diagnostics[row["chunk_id"]] = {
                        "fts_position": position + 1,
                        "fts_rank": round(float(row["fts_rank"]), 6),
                        "base_score": round(base_score, 4),
                        "query_token_coverage": round(coverage, 4),
                        "query_bigram_coverage": round(bigram_coverage, 4),
                        "lexical_similarity": round(lexical_similarity, 4),
                        "exact_phrase": exact_phrase,
                        "query_echo_candidate": query_echo_candidate,
                        "direct_user_evidence": int(direct_user_evidence),
                        "decision_query": int(decision_query),
                        "authority_boost": authority_boost,
                        "decision_declaration": decision_declaration,
                        "decision_declaration_boost": decision_declaration_boost,
                        "rerank_score": round(rerank_score, 4),
                        "lexical_exact_query": int(lexical_exact_query),
                        "query_tokens_total": len(unique_tokens),
                        "fts_tokens_used": len(fts_tokens),
                    }
        except sqlite3.OperationalError:
            pass
    provider = tree.SemanticProvider(config)
    ann_stats: dict[str, Any] = {
        "backend": vector_index.INDEX_BACKEND,
        "available": False,
        "document_count": 0,
        "indexed_through_seq": 0,
        "candidates_visited": 0,
    }
    delta_vectors_scanned = 0
    # A local model being installed does not mean this project has vectors.
    # Use the partial live-embedding index before computing a query vector.
    has_embeddings = provider.can_embed and db.execute(
        f"""SELECT 1 FROM turn_chunks c
            WHERE c.project_id=? AND c.evicted=0 AND c.seq<=?
              AND c.embedding IS NOT NULL AND c.embedding_model=? {permission_sql}
            LIMIT 1""",
        (project_id, watermark, provider.embedding_model, *permission_values),
    ).fetchone() is not None
    if has_embeddings:
        vectors = provider.embed([query], timeout=30, task="query")
        if vectors:
            query_vector = _normalize(vectors[0])
            ann_limit = max(limit * 12, int(config.get("ann_candidate_limit", 100)))
            try:
                ann_matches, ann_stats = vector_index.search(
                    data_directory=tree.data_dir(),
                    project_id=project_id,
                    model=provider.embedding_model,
                    vector=query_vector,
                    limit=ann_limit,
                )
            except Exception as error:
                ann_matches = []
                ann_stats["error"] = str(error)
            if ann_matches:
                seq_scores = {int(seq): float(score) for seq, score in ann_matches}
                placeholders = ",".join("?" for _ in seq_scores)
                for row in db.execute(
                    f"""SELECT seq, id, thread_id, embedding FROM turn_chunks
                        WHERE project_id=? AND evicted=0 AND seq<=?
                          AND seq IN ({placeholders})""",
                    (project_id, watermark, *seq_scores),
                ):
                    chunk_id = str(row["id"])
                    if chunk_id not in excluded and thread_allowed(row["thread_id"]):
                        # USearch generates a bounded candidate set; rerank
                        # those candidates with SQLite's authoritative f32
                        # vectors so ANN quantization/tie order cannot degrade
                        # the final grounded ranking.
                        semantic_scores[chunk_id] = _cosine(
                            query_vector,
                            _vector(row["embedding"]),
                        )
                ann_stats["vectors_reranked"] = len(semantic_scores)

            # Chunks committed after the persisted ANN watermark stay
            # immediately searchable. The bounded delta is the only SQLite
            # embedding fetch permitted on the live query path.
            delta_limit = int(config.get("ann_delta_limit", 1000))
            indexed_through = int(ann_stats.get("indexed_through_seq", 0))
            delta_rows = db.execute(
                """SELECT id, thread_id, embedding FROM turn_chunks
                   WHERE project_id=? AND evicted=0 AND seq>? AND seq<=?
                     AND embedding IS NOT NULL AND embedding_model=?
                   ORDER BY seq DESC LIMIT ?""",
                (
                    project_id,
                    indexed_through,
                    watermark,
                    provider.embedding_model,
                    delta_limit + 1,
                ),
            ).fetchall()
            delta_overflow = len(delta_rows) > delta_limit
            for row in delta_rows[:delta_limit]:
                chunk_id = str(row["id"])
                if chunk_id in excluded or not thread_allowed(row["thread_id"]):
                    continue
                delta_vectors_scanned += 1
                semantic_scores[chunk_id] = max(
                    semantic_scores.get(chunk_id, -1.0),
                    _cosine(query_vector, _vector(row["embedding"])),
                )
            ann_stats["delta_overflow"] = delta_overflow

    semantic_min_score = float(config.get("semantic_min_score", 0.78))
    semantic_top_score = max(semantic_scores.values(), default=-1.0)
    ordered_semantic_scores = sorted(semantic_scores.values(), reverse=True)
    contrast_index = min(
        len(ordered_semantic_scores) - 1,
        max(1, math.ceil(len(ordered_semantic_scores) * 0.10)),
    ) if ordered_semantic_scores else 0
    semantic_contrast = (
        semantic_top_score - ordered_semantic_scores[contrast_index]
        if len(ordered_semantic_scores) > 1
        else semantic_top_score
    )
    semantic_min_contrast = float(config.get("semantic_min_contrast", 0.01))
    # A long one-token query is most often an identifier or sentinel. If that
    # exact token is absent, dense similarity to a related identifier must not
    # manufacture evidence (or make another project's vocabulary look local).
    strict_unmatched_identifier = (
        len(tokens) == 1
        and len(tokens[0]) >= 12
        and not lexical_scores
    )
    semantic_covered = (
        semantic_top_score >= semantic_min_score
        and not strict_unmatched_identifier
    )
    if not semantic_covered:
        semantic_scores = {}

    if semantic_scores:
        if lexical_exact_query:
            for chunk_id in set(semantic_scores) | set(lexical_scores):
                semantic = semantic_scores.get(chunk_id, 0.0)
                lexical = lexical_scores.get(chunk_id, 0.0)
                scores[chunk_id] = semantic * 0.65 + lexical * 0.35
                diagnostics.setdefault(chunk_id, {}).update(
                    {
                        "fusion_mode": "exact_hybrid",
                        "semantic_score": round(semantic, 4),
                        "semantic_top_score": round(semantic_top_score, 4),
                        "semantic_threshold": semantic_min_score,
                        "semantic_contrast": round(semantic_contrast, 4),
                        "semantic_contrast_threshold": semantic_min_contrast,
                    }
                )
        else:
            # Lexical-disjoint paraphrases keep the dense ordering. The old
            # unconditional 35% lexical weight promoted incidental overlap and
            # measurably reduced Recall@5.
            scores.update(semantic_scores)
            for chunk_id, semantic in semantic_scores.items():
                diagnostics.setdefault(chunk_id, {}).update(
                    {
                        "fusion_mode": "semantic",
                        "semantic_score": round(semantic, 4),
                        "semantic_top_score": round(semantic_top_score, 4),
                        "semantic_threshold": semantic_min_score,
                        "semantic_contrast": round(semantic_contrast, 4),
                        "semantic_contrast_threshold": semantic_min_contrast,
                    }
                )
    elif lexical_scores and (not has_embeddings or lexical_exact_query):
        # FTS is the complete fallback when the local provider is unavailable.
        # With a healthy provider, only an exact/identifier-shaped query may
        # bypass a failed semantic coverage test. Allowing ordinary lexical
        # overlap to do so returned confident-looking evidence for unrelated
        # questions and defeated the calibrated uncovered threshold.
        scores.update(lexical_scores)
        for chunk_id in lexical_scores:
            diagnostics.setdefault(chunk_id, {})["fusion_mode"] = "lexical_fallback"

    for detail in diagnostics.values():
        detail.setdefault("ann_backend", ann_stats.get("backend"))
        detail.setdefault("ann_available", int(bool(ann_stats.get("available"))))
        detail.setdefault("ann_document_count", int(ann_stats.get("document_count", 0)))
        detail.setdefault("ann_candidates_visited", int(ann_stats.get("candidates_visited", 0)))
        detail.setdefault("delta_vectors_scanned", delta_vectors_scanned)
    if not scores:
        for row in db.execute(
            f"""SELECT c.id, c.thread_id FROM turn_chunks c
               WHERE c.project_id=? AND c.evicted=0 AND c.seq<=?
                 AND instr(lower(c.text), lower(?)) > 0 {permission_sql} LIMIT 100""",
            (project_id, watermark, query, *permission_values),
        ):
            if row["id"] not in excluded and thread_allowed(row["thread_id"]):
                scores[row["id"]] = 0.4

    # Multiple independently relevant chunks from one completed turn provide
    # contextual support. A capped boost lets framing and answer chunks travel
    # together without allowing a long turn to dominate the ranking.
    if scores:
        placeholders = ",".join("?" for _ in scores)
        turn_chunks: dict[str, list[str]] = {}
        for row in db.execute(
            f"SELECT id, turn_id FROM turn_chunks WHERE id IN ({placeholders})",
            tuple(scores),
        ):
            turn_chunks.setdefault(str(row["turn_id"]), []).append(str(row["id"]))
        for chunk_ids in turn_chunks.values():
            support_scores = sorted((scores[chunk_id] for chunk_id in chunk_ids), reverse=True)
            secondary_support = [score for score in support_scores[1:3] if score >= 0.35]
            boost = min(0.12, 0.12 * sum(secondary_support))
            if boost <= 0:
                continue
            for chunk_id in chunk_ids:
                # The same-turn boost is intentionally additive. Clamping at
                # 1.0 collapsed distinct high semantic scores into insertion-
                # order ties and degraded MRR without adding evidence.
                scores[chunk_id] = scores[chunk_id] + boost
                diagnostics.setdefault(chunk_id, {})["turn_support_boost"] = round(boost, 4)
                diagnostics[chunk_id]["turn_supporting_hits"] = len(secondary_support)
    results = []
    for chunk_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]:
        row = db.execute(
            """SELECT c.*, t.transcript_path FROM turn_chunks c
               JOIN turn_ingestion t ON t.id = c.turn_id
               WHERE c.id = ? AND c.evicted = 0""",
            (chunk_id,),
        ).fetchone()
        if not row or not thread_allowed(row["thread_id"]):
            continue
        nodes = [dict(item) for item in db.execute(
            """SELECT n.id, n.layer, n.title, m.membership_confidence
               FROM semantic_node_memberships m JOIN semantic_nodes n ON n.id = m.node_id
               WHERE m.chunk_id = ? AND n.lifecycle != 'retired' ORDER BY n.layer""",
            (chunk_id,),
        )]
        results.append(
            {
                **dict(row),
                "score": round(score, 4),
                "nodes": nodes,
                "retrieval_diagnostics": diagnostics.get(chunk_id, {}),
            }
        )
    db.close()
    return results


def search_project_nodes(
    project_id: str,
    query: str,
    limit: int = 12,
    *,
    allowed_thread_ids: Iterable[str] | None = None,
    excluded_thread_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Map source-chunk retrieval onto visible project-tree nodes."""

    allowed = None if allowed_thread_ids is None else set(allowed_thread_ids)
    excluded = set(excluded_thread_ids)
    restricted = allowed is not None or bool(excluded)
    merged: dict[str, dict[str, Any]] = {}
    for result in search_project(
        project_id,
        query,
        limit=max(limit * 3, 24),
        allowed_thread_ids=allowed,
        excluded_thread_ids=excluded,
    ):
        candidates = [node for node in result["nodes"] if node["layer"] == "span"] or result["nodes"]
        if candidates:
            candidate = candidates[0]
            node_id = candidate["id"]
            title = _source_preview_title(result["text"]) if restricted else candidate["title"]
            kind = "span" if candidate["layer"] == "span" else "topic"
        else:
            node_id = f"frontier:{result['id']}"
            title = result["text"].splitlines()[0][:80]
            kind = "span"
        current = merged.get(node_id)
        if current is None or result["score"] > current["score"]:
            merged[node_id] = {
                "id": node_id,
                "thread_id": project_id,
                "kind": kind,
                "title": title,
                "summary": result["text"][:720],
                "score": result["score"],
            }
    # During the migration window, legacy compaction-window nodes remain part
    # of the one project tree. Search them directly so creating the first
    # project record never makes previously indexed history disappear.
    tree = _tree_module()
    db = tree.connect_db()
    project = db.execute("SELECT cwd FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project:
        thread_ids = [
            row["id"]
            for row in db.execute("SELECT id FROM threads WHERE cwd = ?", (project["cwd"],))
            if row["id"] not in excluded and (allowed is None or row["id"] in allowed)
        ]
        tokens = tree.tokenize(query)
        legacy_scores: dict[str, float] = {}
        if thread_ids and tokens:
            placeholders = ",".join("?" for _ in thread_ids)
            fts_query = " OR ".join(f'"{token}"' for token in tokens[:12])
            try:
                rows = db.execute(
                    f"""SELECT node_id FROM nodes_fts
                        WHERE nodes_fts MATCH ? AND thread_id IN ({placeholders})
                        ORDER BY bm25(nodes_fts, 0.0, 6.0, 3.0, 1.0, 1.0) LIMIT ?""",
                    (fts_query, *thread_ids, max(limit * 3, 24)),
                ).fetchall()
                for position, row in enumerate(rows):
                    legacy_scores[row["node_id"]] = max(0.35, 0.955 - position * 0.025)
            except sqlite3.OperationalError:
                pass
        if thread_ids and not legacy_scores:
            placeholders = ",".join("?" for _ in thread_ids)
            for row in db.execute(
                f"""SELECT id FROM nodes WHERE thread_id IN ({placeholders})
                    AND kind != 'root' AND (instr(lower(title), lower(?)) > 0
                    OR instr(lower(summary), lower(?)) > 0 OR instr(lower(content_preview), lower(?)) > 0)
                    LIMIT ?""",
                (*thread_ids, query, query, query, max(limit * 3, 24)),
            ):
                legacy_scores[row["id"]] = 0.4
        for node_id, score in legacy_scores.items():
            row = db.execute("SELECT * FROM nodes WHERE id = ? AND kind != 'root'", (node_id,)).fetchone()
            if not row:
                continue
            candidate = {
                "id": row["id"],
                "thread_id": project_id,
                "kind": row["kind"],
                "title": row["title"],
                "summary": row["summary"],
                "score": round(score, 4),
            }
            current = merged.get(node_id)
            if current is None or candidate["score"] > current["score"]:
                merged[node_id] = candidate
    db.close()
    return sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:limit]


EXPLORER_BROWSE_MESSAGE_LIMIT = 36


EXPLORER_LAYER_KEYS = {
    "broad": "subject",
    "specific": "broad_topic",
    "span": "specific_topic",
}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _source_message_ids(chunk: Mapping[str, Any]) -> set[str]:
    return {value for value in _json_list(chunk["source_message_ids"]) if isinstance(value, str) and value.strip()}


def _explorer_evidence(
    db: sqlite3.Connection, project_id: str,
    project_scope: Mapping[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, str], dict[str, set[str]]]:
    """Project the hierarchy from live span memberships and primary edges."""

    columns = "id, seq, thread_id, source_message_ids"
    if scope.restricts_chats(project_scope):
        columns += ", substr(text, 1, 160) AS preview"
    chunks = {
        row["id"]: dict(row)
        for row in db.execute(
            f"SELECT {columns} FROM turn_chunks WHERE project_id=? AND evicted=0",
            (project_id,),
        )
        if project_scope is None or scope.chat_is_selected(project_scope, row["thread_id"])
    }
    assignments: dict[str, str] = {}
    for row in db.execute(
        """SELECT m.chunk_id, n.id AS span_id FROM semantic_nodes n
           JOIN semantic_node_memberships m ON m.node_id=n.id
           WHERE n.project_id=? AND n.layer='span' AND n.lifecycle!='retired'
           ORDER BY COALESCE(m.membership_confidence, 0) DESC, n.id""",
        (project_id,),
    ):
        if row["chunk_id"] in chunks:
            assignments.setdefault(row["chunk_id"], row["span_id"])
    parents = {
        row["child_id"]: row["parent_id"]
        for row in db.execute(
            """SELECT e.child_id, e.parent_id FROM semantic_edges e
               JOIN semantic_nodes child ON child.id=e.child_id
               JOIN semantic_nodes parent ON parent.id=e.parent_id
               WHERE child.project_id=? AND parent.project_id=child.project_id
                 AND e.primary_edge=1 AND child.lifecycle!='retired' AND parent.lifecycle!='retired'""",
            (project_id,),
        )
    }
    node_chunks: dict[str, set[str]] = {}
    for chunk_id, span_id in assignments.items():
        for node_id in _primary_ancestors(span_id, parents):
            node_chunks.setdefault(node_id, set()).add(chunk_id)
    return chunks, assignments, parents, node_chunks


def _primary_ancestors(node_id: str, parents: Mapping[str, str]) -> Iterable[str]:
    visited = set()
    while node_id and node_id not in visited:
        visited.add(node_id)
        yield node_id
        node_id = parents.get(node_id, "")


def _evidence_counts(chunks: Iterable[Mapping[str, Any]]) -> tuple[int | None, int]:
    messages = set()
    chats = set()
    complete = True
    for chunk in chunks:
        chat = chunk["thread_id"]
        chats.add(chat)
        ids = _source_message_ids(chunk)
        complete = complete and bool(ids)
        messages.update((chat, message_id) for message_id in ids)
    return (len(messages) if complete and messages else None), len(chats)


def _source_preview_title(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return re.sub(r"^(USER|ASSISTANT|SYSTEM):\s*", "", first_line, flags=re.IGNORECASE)[:120] or "Conversation topic"


def _visible_topic_title(
    title: str, member_ids: set[str], chunks: Mapping[str, Mapping[str, Any]], restricted: bool,
) -> str:
    if not restricted:
        return title
    return _source_preview_title(str(chunks[min(member_ids)]["preview"]))


def _recent_explorer_hits(
    db: sqlite3.Connection,
    project_id: str,
    chunks: Mapping[str, Mapping[str, Any]],
    node_chunks: Mapping[str, set[str]],
    browse_nodes: Sequence[str],
    browse_message: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    if len(browse_nodes) > len(EXPLORER_LAYER_KEYS) or any(node not in node_chunks for node in browse_nodes):
        return []
    if browse_nodes:
        smallest, *others = sorted((node_chunks[node] for node in browse_nodes), key=len)
        eligible = {chunk_id for chunk_id in smallest if all(chunk_id in group for group in others)}
    else:
        eligible = chunks.keys()
    ids = heapq.nlargest(limit, eligible, key=lambda chunk_id: chunks[chunk_id]["seq"])
    if browse_message and browse_message.startswith("message:"):
        anchor = browse_message.removeprefix("message:")
        if anchor in eligible and anchor not in ids:
            ids = [*ids[:limit - 1], anchor]
    if not ids:
        return []

    # Fetch the body previews only for the selected sample, within the same
    # snapshot as the allowed messages and their primary memberships.
    placeholders = ",".join("?" for _ in ids)
    return [dict(row) for row in db.execute(
        f"""SELECT id, substr(text, 1, 1200) AS text, source_message_ids, created_at
            FROM turn_chunks WHERE project_id=? AND evicted=0 AND id IN ({placeholders})
            ORDER BY seq DESC""",
        (project_id, *ids),
    )]


def project_explorer_payload(
    project_id: str,
    query: str,
    limit: int = 80,
    *,
    project_scope: Mapping[str, Any] | None = None,
    browse_nodes: Sequence[str] = (),
    browse_message: str | None = None,
) -> dict[str, Any]:
    """Project matching evidence, or browse active topics and recent messages.

    Search uses the same ranking as grounded recall. Browsing samples recent
    messages within the selected topics and retains the full topic hierarchy.
    Both modes read the index without writing questions or browse filters.
    """

    query = query.strip()
    empty_layers = {key: [] for key in (*EXPLORER_LAYER_KEYS.values(), "specific_message")}
    allowed = None if project_scope is None or project_scope.get("includeNewChats", True) else project_scope.get("includedChatIds", [])
    excluded = (
        [*project_scope.get("excludedChatIds", []), *project_scope.get("pendingDisconnectChatIds", [])]
        if project_scope else ()
    )
    hits = search_project(
        project_id, query, limit=max(1, min(int(limit), 100)),
        allowed_thread_ids=allowed, excluded_thread_ids=excluded,
    ) if query else []
    tree = _tree_module()
    db = tree.connect_db()
    project = db.execute("SELECT id, cwd, updated_at FROM projects WHERE id=?", (project_id,)).fetchone()
    if not project:
        db.close()
        return {"query": query, "project": None, "layers": empty_layers, "edges": [], "counts": {key: 0 for key in empty_layers}}

    db.execute("BEGIN")
    chunks, assignments, primary_parent, node_chunks = _explorer_evidence(db, project_id, project_scope)
    if query:
        # A disconnect can land between retrieval and projection.
        hits = [hit for hit in hits if hit["id"] in chunks]
    else:
        hits = _recent_explorer_hits(
            db, project_id, chunks, node_chunks, browse_nodes, browse_message,
            max(1, min(int(limit), EXPLORER_BROWSE_MESSAGE_LIMIT)),
        )
    hit_spans = {hit["id"]: assignments[hit["id"]] for hit in hits if hit["id"] in assignments}
    descendant_hit_scores: dict[str, float] = {}
    for hit in hits:
        score = float(hit.get("score") or 0)
        for node_id in _primary_ancestors(hit_spans.get(hit["id"], ""), primary_parent):
            descendant_hit_scores[node_id] = max(descendant_hit_scores.get(node_id, score), score)

    included_node_ids = descendant_hit_scores.keys() if query else node_chunks.keys()
    semantic_rows = [
        row for row in db.execute(
            """SELECT id, layer, title, persistence, lifecycle, created_at, updated_at
               FROM semantic_nodes WHERE project_id=? AND lifecycle!='retired'""",
            (project_id,),
        ) if row["id"] in included_node_ids
    ]

    layers = {key: [] for key in empty_layers}
    restricted = scope.restricts_chats(project_scope)
    for row in semantic_rows:
        layer_key = EXPLORER_LAYER_KEYS.get(str(row["layer"]))
        if not layer_key:
            continue
        member_ids = node_chunks[row["id"]]
        message_count, chat_count = _evidence_counts(chunks[chunk_id] for chunk_id in member_ids)
        layers[layer_key].append({
            "id": str(row["id"]),
            "layer": layer_key,
            "title": _visible_topic_title(str(row["title"]), member_ids, chunks, restricted),
            "confidence": round(float(row["persistence"] or 0), 4),
            "lifecycle": str(row["lifecycle"]),
            "memberCount": len(member_ids),
            "messageCount": message_count,
            "sourceChatCount": chat_count,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "score": round(descendant_hit_scores.get(row["id"], 0), 4),
        })

    for hit in hits:
        text = str(hit.get("text") or "").strip()
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Message")
        title = re.sub(r"^(USER|ASSISTANT|SYSTEM):\s*", "", first_line, flags=re.IGNORECASE)
        layers["specific_message"].append({
            "id": f"message:{hit['id']}",
            "layer": "specific_message",
            "title": title[:120],
            "summary": text[:1200],
            "keywords": [],
            "confidence": round(float(hit.get("score") or 0), 4),
            "memberCount": 1,
            "messageCount": len(_source_message_ids(hit)) or None,
            "sourceChatCount": 1,
            "createdAt": hit.get("created_at"),
            "updatedAt": hit.get("created_at"),
            "score": round(float(hit.get("score") or 0), 4),
        })

    for layer_key, values in layers.items():
        if query or layer_key != "specific_message":
            values.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("title") or "").casefold()))

    edges = [
        {"child_id": child, "parent_id": parent}
        for child, parent in primary_parent.items()
        if child in included_node_ids and parent in included_node_ids
    ]
    edges.extend(
        {"child_id": f"message:{chunk_id}", "parent_id": span_id}
        for chunk_id, span_id in hit_spans.items()
    )
    result = {
        "query": query,
        "project": {
            "id": str(project["id"]),
            "title": Path(str(project["cwd"] or "")).name or "Project",
            "updatedAt": project["updated_at"],
        },
        "layers": layers,
        "edges": edges,
        "counts": {key: len(value) for key, value in layers.items()},
    }
    db.close()
    return result


def _source_ids_verified(transcript_path: str, message_ids: Sequence[str]) -> bool:
    """Verify that a chunk's immutable source-message references still exist."""

    path = Path(transcript_path)
    if not path.exists() or not message_ids:
        return False
    try:
        parsed = _tree_module().parse_transcript_lines(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    present = {str(message["id"]) for message in parsed["messages"]}
    return set(map(str, message_ids)).issubset(present)


def _readable_overview(sources: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Choose intact, attributed sentences from retained excerpts for the viewer."""

    question = ""
    example: dict[str, str] | None = None
    reply: dict[str, str] | None = None
    for source in sources:
        parts = re.split(r"(?:^|\n)(USER|ASSISTANT):[ \t]*", str(source["text"]))
        for role, body in zip(parts[1::2], parts[2::2]):
            body = re.sub(r"(?ms)^[ \t]*\x60{3}[^\n]*\n.*?(?:^[ \t]*\x60{3}[^\n]*$|\Z)", "", body)
            body = re.sub(r"\[([^\]]+)\]\([^\s)]+\)", r"\1", body)
            body = re.sub(r"(\*\*|__|\x60)(.+?)\1", r"\2", body)
            for paragraph in re.split(r"\n\s*\n", body):
                paragraph = re.sub(r"(?m)^\s*(?:#{1,6}|>|[-*])\s+", "", paragraph)
                paragraph = " ".join(paragraph.split())
                sentences = re.findall(r".+?[.!?](?=\s|$)", paragraph)
                if not sentences and 20 <= len(paragraph) <= 240:
                    sentences = [paragraph]
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not 20 <= len(sentence) <= 240 or not re.search(r"[^\W\d_]", sentence):
                        continue
                    if role == "USER" and sentence.endswith("?") and not question:
                        question = sentence
                    if role == "ASSISTANT" and reply is None:
                        reply = {"label": "Excerpt from a reply", "text": sentence}
                    if example is None:
                        example = {"label": "Excerpt from a chat", "text": sentence}
    if question:
        overview = [{"label": "Example question", "text": question}]
        if reply is not None:
            overview.append(reply)
        return overview
    return [reply or example] if reply or example else []


def project_node_detail(
    node_id: str,
    *,
    include_sources: bool = True,
    explorer: bool = False,
    scope_config: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    tree = _tree_module()
    db = tree.connect_db()
    db.execute("BEGIN")
    chunk_id = (
        node_id.removeprefix("frontier:") if node_id.startswith("frontier:")
        else node_id.removeprefix("message:") if node_id.startswith("message:")
        else None
    )
    node = db.execute("SELECT * FROM semantic_nodes WHERE id = ? AND lifecycle!='retired'", (node_id,)).fetchone()
    chunk = db.execute(
        "SELECT * FROM turn_chunks WHERE id=? AND evicted=0", (chunk_id,),
    ).fetchone() if chunk_id else None
    if not node and not chunk:
        db.close()
        return None
    project_id = (node or chunk)["project_id"]
    project_scope = None
    if scope_config is not None:
        project = db.execute("SELECT cwd FROM projects WHERE id=?", (project_id,)).fetchone()
        if scope_config.get("configured") and project:
            project_scope = scope.selected_project(scope_config, project["cwd"])
        if (
            project_scope is None or project_scope.get("disconnectPending")
            or (chunk and not scope.chat_is_selected(project_scope, chunk["thread_id"]))
        ):
            db.close()
            return None
    chunks, assignments, _, node_chunks = _explorer_evidence(db, project_id, project_scope)
    member_ids = node_chunks.get(node_id, set()) if node else {chunk_id}
    if not member_ids:
        db.close()
        return None
    if node:
        result = {**dict(node), "kind": "span" if node["layer"] == "span" else "topic"}
        restricted = scope.restricts_chats(project_scope)
        if explorer or restricted:
            for key in ("summary", "keywords", "embedding", "generation_id"):
                result.pop(key, None)
        else:
            result["keywords"] = _json_list(result.get("keywords"))
        result["title"] = _visible_topic_title(result["title"], member_ids, chunks, restricted)
        result["parents"] = [dict(row) for row in db.execute(
            """SELECT n.id, n.layer, n.title, e.coverage FROM semantic_edges e
               JOIN semantic_nodes n ON n.id=e.parent_id
               WHERE e.child_id=? AND e.primary_edge=1""",
            (node_id,),
        ) if row["id"] in node_chunks]
        result["children"] = [dict(row) for row in db.execute(
            """SELECT n.id, n.layer, n.title, e.coverage FROM semantic_edges e
               JOIN semantic_nodes n ON n.id=e.child_id
               WHERE e.parent_id=? AND e.primary_edge=1 ORDER BY n.title""",
            (node_id,),
        ) if row["id"] in node_chunks]
        for relation in (*result["parents"], *result["children"]):
            relation["title"] = _visible_topic_title(
                relation["title"], node_chunks[relation["id"]], chunks, restricted,
            )
    else:
        text = str(chunk["text"] or "")
        title = _source_preview_title(text)
        result = {
            "id": node_id,
            "kind": "message",
            "layer": "specific_message",
            "title": title[:120],
            "summary": text[:1200],
            "created_at": chunk["created_at"],
            "keywords": [],
            "parents": [dict(row) for row in db.execute(
                """SELECT n.id, n.layer, n.title, m.membership_confidence AS coverage
                   FROM semantic_node_memberships m JOIN semantic_nodes n ON n.id=m.node_id
                   WHERE m.chunk_id=? AND n.id=?""",
                (chunk_id, assignments.get(chunk_id)),
            )],
            "children": [],
        }
        for parent in result["parents"]:
            parent["title"] = _visible_topic_title(
                parent["title"], node_chunks[parent["id"]], chunks, scope.restricts_chats(project_scope),
            )
    result["member_count"] = len(member_ids)
    result["message_count"], result["source_chat_count"] = _evidence_counts(chunks[item_id] for item_id in member_ids)
    if include_sources:
        # The viewer previews recent excerpts. Preserve chronological order for the CLI.
        source_ids = [
            row["id"] for row in db.execute(
                "SELECT id FROM turn_chunks WHERE project_id=? AND evicted=0 ORDER BY seq DESC",
                (project_id,),
            ) if row["id"] in member_ids
        ]
        transcript_cache = {}
        sources = []
        for item_id in (source_ids[:12] if explorer else reversed(source_ids)):
            source = tree.chunk_source_detail(item_id, db=db, transcript_cache=transcript_cache)
            if source:
                sources.append(source)
        result["sources"] = sources
        if explorer:
            overview = _readable_overview(sources)
            result["overview"] = overview
            if node and node["layer"] == "span" and overview and overview[0]["label"] == "Example question":
                question = overview[0]["text"]
                if len(question) <= 120:
                    result["display_title"] = question[0].upper() + question[1:]
            result["source_excerpt_count"] = len(source_ids)
            for source in sources:
                source.pop("transcript_path", None)
    db.close()
    return result


def project_tree_payload(
    project_id: str, *, project_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tree = _tree_module()
    db = tree.connect_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        db.close()
        return {"thread": None, "nodes": [], "edges": [], "stats": {}}
    root_id = f"project-root:{project_id}"
    title = Path(project["cwd"]).name if project["cwd"] else "Project"
    nodes = [{"id": root_id, "thread_id": project_id, "kind": "root", "title": title, "summary": "Project-wide Context Saver index.", "confidence": 1.0}]
    chunks, _, _, node_chunks = _explorer_evidence(db, project_id, project_scope) if project_scope is not None else ({}, {}, {}, {})
    restricted = scope.restricts_chats(project_scope)
    semantic = [dict(row) for row in db.execute("SELECT * FROM semantic_nodes WHERE project_id = ? AND lifecycle != 'retired'", (project_id,))]
    if project_scope is not None:
        semantic = [node for node in semantic if node["id"] in node_chunks]
    semantic_ids = {node["id"] for node in semantic}
    for node in semantic:
        nodes.append({
            "id": node["id"], "thread_id": project_id,
            "kind": "span" if node["layer"] == "span" else "topic",
            "title": _visible_topic_title(node["title"], node_chunks.get(node["id"], set()), chunks, restricted),
            "summary": "" if restricted else node["summary"],
            "confidence": node["persistence"] or 0.0, "layer": node["layer"],
        })
    edges = [
        {"child_id": row["child_id"], "parent_id": row["parent_id"], "relation": "primary" if row["primary_edge"] else "related", "coverage": row["coverage"]}
        for row in db.execute(
            """SELECT e.* FROM semantic_edges e JOIN semantic_nodes n ON n.id=e.child_id
               WHERE n.project_id = ?""",
            (project_id,),
        )
        if row["child_id"] in semantic_ids and row["parent_id"] in semantic_ids
    ]
    parented = {edge["child_id"] for edge in edges if edge["relation"] == "primary"}
    for node in semantic:
        if node["layer"] == "broad" or node["id"] not in parented:
            edges.append({"child_id": node["id"], "parent_id": root_id, "relation": "primary", "coverage": 1.0})

    # Merge the pre-pipeline representation into this project root. Legacy
    # thread roots are structural only, so their children attach directly to
    # the single project root rather than creating per-chat subtrees.
    legacy_threads = [
        row["id"] for row in db.execute("SELECT id FROM threads WHERE cwd = ?", (project["cwd"],))
        if project_scope is None or scope.chat_is_selected(project_scope, row["id"])
    ]
    legacy_windows = 0
    if legacy_threads:
        placeholders = ",".join("?" for _ in legacy_threads)
        legacy_rows = [dict(row) for row in db.execute(
            f"SELECT * FROM nodes WHERE thread_id IN ({placeholders})", legacy_threads
        )]
        legacy_roots = {row["id"] for row in legacy_rows if row["kind"] == "root"}
        existing_ids = {node["id"] for node in nodes}
        for node in legacy_rows:
            if node["id"] in legacy_roots or node["id"] in existing_ids:
                continue
            nodes.append({
                "id": node["id"], "thread_id": project_id, "kind": node["kind"],
                "title": node["title"], "summary": node["summary"],
                "confidence": node["confidence"], "legacy": True,
            })
            existing_ids.add(node["id"])
        legacy_edges = [dict(row) for row in db.execute(
            f"""SELECT p.child_id, p.parent_id, p.relation FROM node_parents p
                JOIN nodes n ON n.id=p.child_id WHERE n.thread_id IN ({placeholders})""",
            legacy_threads,
        )]
        legacy_parented: set[str] = set()
        for edge in legacy_edges:
            if edge["child_id"] in legacy_roots or edge["child_id"] not in existing_ids:
                continue
            parent_id = root_id if edge["parent_id"] in legacy_roots else edge["parent_id"]
            if parent_id != root_id and parent_id not in existing_ids:
                parent_id = root_id
            edges.append({
                "child_id": edge["child_id"], "parent_id": parent_id,
                "relation": edge["relation"], "coverage": 1.0,
            })
            if edge["relation"] == "primary":
                legacy_parented.add(edge["child_id"])
        for node in legacy_rows:
            if node["id"] not in legacy_roots and node["id"] in existing_ids and node["id"] not in legacy_parented:
                edges.append({"child_id": node["id"], "parent_id": root_id, "relation": "primary", "coverage": 1.0})
        legacy_windows = db.execute(
            f"SELECT COUNT(*) FROM windows WHERE thread_id IN ({placeholders})", legacy_threads
        ).fetchone()[0]
    frontier = [
        row for row in state.frontier_chunks(db, project_id)
        if project_scope is None or scope.chat_is_selected(project_scope, row["thread_id"])
    ]
    if frontier:
        unresolved_id = f"unclustered:{project_id}"
        nodes.append({"id": unresolved_id, "thread_id": project_id, "kind": "topic", "title": "Unclustered", "summary": "Searchable chunks awaiting a clustering fit.", "confidence": 0.0, "layer": "frontier"})
        edges.append({"child_id": unresolved_id, "parent_id": root_id, "relation": "primary", "coverage": 1.0})
        for chunk in frontier:
            node_id = f"frontier:{chunk['id']}"
            nodes.append({"id": node_id, "thread_id": project_id, "kind": "span", "title": chunk["text"].splitlines()[0][:80], "summary": chunk["text"][:720], "confidence": 0.0, "chunk_id": chunk["id"]})
            edges.append({"child_id": node_id, "parent_id": unresolved_id, "relation": "primary", "coverage": 1.0})
    visible_turns = sum(
        int(row["total"]) for row in db.execute(
            """SELECT thread_id, COUNT(*) AS total FROM turn_ingestion
               WHERE project_id=? AND state='indexed' GROUP BY thread_id""",
            (project_id,),
        ) if project_scope is None or scope.chat_is_selected(project_scope, row["thread_id"])
    )
    stats = {
        "windows": visible_turns + legacy_windows,
        "topics": sum(1 for node in nodes if node["kind"] == "topic"),
        "spans": sum(1 for node in nodes if node["kind"] == "span"),
        "frontier": len(frontier),
    }
    db.close()
    return {"thread": {"id": project_id, "title": title, "cwd": project["cwd"]}, "nodes": nodes, "edges": edges, "stats": stats}


def list_projects() -> list[dict[str, Any]]:
    tree = _tree_module()
    db = tree.connect_db()
    rows = [
        {
            "id": row["id"],
            "title": Path(row["cwd"]).name if row["cwd"] else "Project",
            "cwd": row["cwd"],
            "updated_at": row["updated_at"],
            "windows": row["turns"],
            "nodes": row["nodes"],
        }
        for row in db.execute(
            """SELECT p.*, COUNT(DISTINCT t.id) AS turns, COUNT(DISTINCT n.id) AS nodes
               FROM projects p LEFT JOIN turn_ingestion t ON t.project_id=p.id
               LEFT JOIN semantic_nodes n ON n.project_id=p.id
               GROUP BY p.id ORDER BY p.updated_at DESC"""
        )
    ]
    db.close()
    return rows
