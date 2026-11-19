"""Exercise the real viewer HTTP handler against an isolated, synthetic index."""

from __future__ import annotations

from _support import PACKAGE_ROOT, SCRIPTS_ROOT

import errno
import hashlib
import http.client
import io
import json
import os
import socket
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode

import stop
import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_rebuild as rebuild
import thread_tree_state as state
import thread_tree_tools as model_tools
import thread_tree_vector_index as vector_index


class BoundaryResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary).resolve()
        self.data = self.root / "data"
        self.data.mkdir()
        self.enterContext(patch.dict(os.environ, {"THREAD_HISTORY_TREE_DATA": str(self.data)}))
        (self.data / "config.json").write_text(
            json.dumps({"embedding_provider": "none", "fit_thresholds": {"span": 2, "specific": 2, "broad": 2}}),
            encoding="utf-8",
        )
        self.enterContext(patch.object(thread_tree.SemanticProvider, "_check"))
        self.enterContext(patch.object(thread_tree, "discover_codex_project_chats", return_value=[]))
        self.enterContext(patch.object(thread_tree, "codex_state_db_path", return_value=self.root / "unused-state.sqlite"))
        self.enterContext(patch.object(thread_tree, "discover_session_metadata", return_value=([], {})))
        self.launch_backfill = self.enterContext(patch.object(thread_tree, "launch_scope_backfill"))
        # Capture the worker command so tests can inspect the durable queued state
        # before deliberately running the real worker entry point.
        self.launch_process = self.enterContext(patch.object(thread_tree.subprocess, "Popen"))

        self.alpha = self.root / "alpha"
        self.beta = self.root / "beta"
        self.alpha.mkdir()
        self.beta.mkdir()
        self.alpha_id = state.project_id_for(str(self.alpha))
        self.beta_id = state.project_id_for(str(self.beta))
        self.configure(self.alpha, self.beta)
        self.keep = self.index_fixture(self.alpha, "retained-chat", "opalfixture")
        self.remove = self.index_fixture(self.alpha, "removable-chat", "saffronfixture")
        self.foreign = self.index_fixture(self.beta, "other-project-chat", "tulipfixture")

    def configure(self, *projects: Path, alpha_chats: list[str] | None = None, paused: bool = False) -> None:
        thread_tree.save_scope_config({
            "schemaVersion": 1,
            "configured": bool(projects),
            "paused": paused,
            "projects": [
                {
                    "path": str(project),
                    "includeNewChats": project != self.alpha or alpha_chats is None,
                    "includedChatIds": alpha_chats if project == self.alpha and alpha_chats is not None else [],
                    "excludedChatIds": [],
                    "backfillExisting": False,
                }
                for project in projects
            ],
        })

    def index_fixture(self, project: Path, chat: str, word: str) -> Path:
        transcript = self.root / f"{chat}.jsonl"
        rows = [{"type": "session_meta", "payload": {"id": chat, "cwd": str(project)}}]
        for role, content in (
            ("user", f"What did the {word} archive record?"),
            ("assistant", f"The {word} archive recorded a local partition marker."),
        ):
            rows.append({
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "id": f"{chat}-{role}",
                    "role": role,
                    "content": [{"type": "input_text" if role == "user" else "output_text", "text": content}],
                },
            })
        transcript.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
        queued = pipeline.enqueue_transcript(transcript)
        self.assertEqual(pipeline.process_project(queued["project_id"])["processed_turns"], 1)
        return transcript

    def request(
        self,
        method: str,
        path: str,
        payload=None,
        *,
        raw_body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, object]:
        """Feed raw bytes into BaseHTTPRequestHandler without opening a host port."""
        if payload is not None:
            raw_body = json.dumps(payload).encode()
        request_headers = {"Host": "localhost:8765", "Connection": "close"}
        if method == "POST":
            request_headers.update({"Content-Type": "application/json", "Content-Length": str(len(raw_body))})
        request_headers.update(headers or {})
        header_lines = "".join(f"{key}: {value}\r\n" for key, value in request_headers.items())
        wire = f"{method} {path} HTTP/1.1\r\n{header_lines}\r\n".encode() + raw_body
        failures = []
        client, server = socket.socketpair()

        def handle() -> None:
            with server:
                try:
                    thread_tree.ViewerHandler(server, ("127.0.0.1", 0), None)
                except Exception as error:
                    failures.append(error)

        with client:
            client.settimeout(5)
            worker = threading.Thread(target=handle, daemon=True)
            worker.start()
            try:
                client.sendall(wire)
                try:
                    client.shutdown(socket.SHUT_WR)
                except OSError as error:
                    # A rejection can close the peer as soon as the headers
                    # arrive. Read its response even if half-close is too late.
                    if error.errno != errno.ENOTCONN:
                        raise
                with closing(http.client.HTTPResponse(client)) as reply:
                    reply.begin()
                    status = reply.status
                    body = reply.read()
                    if reply.headers.get("Content-Type", "").startswith("application/json"):
                        self.assertEqual(reply.headers.get("Cache-Control"), "no-store")
                        parsed = json.loads(body)
                    else:
                        parsed = body.decode("utf-8", errors="replace")
            finally:
                worker.join(timeout=5)
        self.assertFalse(worker.is_alive(), "viewer request failed to terminate")
        self.assertEqual(failures, [])
        return status, parsed

    def get(self, endpoint: str, **params):
        query = "?" + urlencode(params) if params else ""
        return self.request("GET", f"/api/{endpoint}{query}")

    def connection(self, action: str, project: Path, chat: str | None = None):
        payload = {"action": action, "kind": "chat" if chat else "project", "projectPath": str(project)}
        if chat:
            payload["threadId"] = chat
        return self.request("POST", "/api/connections/action", payload)

    def message_id(self, chat: str) -> str:
        with closing(thread_tree.connect_db()) as db:
            chunk_id = db.execute("SELECT id FROM turn_chunks WHERE thread_id=? ORDER BY seq", (chat,)).fetchone()[0]
        return f"message:{chunk_id}"

    def snapshot(self, *, ignore_plugin_recency: str | None = None) -> str:
        with closing(thread_tree.connect_db()) as db:
            if ignore_plugin_recency:
                # Accepted MCP calls may update one usage stamp. Normalize
                # only that field in a copy; canonical evidence stays exact.
                with closing(sqlite3.connect(":memory:")) as copied:
                    db.backup(copied)
                    copied.execute("UPDATE projects SET last_plugin_invoked_at=NULL WHERE id=?", (ignore_plugin_recency,))
                    state_dump = "\n".join(copied.iterdump()).encode()
            else:
                state_dump = "\n".join(db.iterdump()).encode()
        return hashlib.sha256(state_dump).hexdigest()

    @staticmethod
    def message_rows(payload):
        return payload.get("layers", {}).get("specific_message", [])

    def test_malformed_and_oversized_mutation_bodies_do_not_change_scope_or_store(self) -> None:
        baseline = thread_tree.load_scope_config()
        before = self.snapshot()
        for path, size in (("/api/scope", 64_001), ("/api/viewer-config", 64_001), ("/api/connections/action", 16_001)):
            with self.subTest(path=path, mode="malformed"):
                self.assertEqual(self.request("POST", path, raw_body=b"{,")[0], 400)
            with self.subTest(path=path, mode="size"):
                self.assertEqual(self.request("POST", path, headers={"Content-Length": str(size)})[0], 413)
            with self.subTest(path=path, mode="invalid length"):
                self.assertEqual(self.request("POST", path, headers={"Content-Length": "oops"})[0], 400)
        self.assertEqual(thread_tree.load_scope_config(), baseline)
        self.assertEqual(self.snapshot(), before)
        self.launch_process.assert_not_called()
        self.launch_backfill.assert_not_called()

    def test_unselected_project_is_indistinguishable_from_missing_for_content_reads(self) -> None:
        message = self.message_id("other-project-chat")
        self.configure(self.alpha)
        self.assertEqual({row["id"] for row in self.get("threads", include_all="1")[1]}, {self.alpha_id})
        comparisons = [
            ("explore", {"q": "tulipfixture", "thread_id": self.beta_id}, {"q": "tulipfixture", "thread_id": "unknown"}),
            ("tree", {"thread_id": self.beta_id}, {"thread_id": "unknown"}),
        ]
        for endpoint, private, unknown in comparisons:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.get(endpoint, **private), self.get(endpoint, **unknown))
        for view in ("explorer", ""):
            with self.subTest(view=view):
                self.assertEqual(self.get(f"node/{quote(message)}", view=view)[0], 404)
        self.assertEqual(self.get("search", q="tulipfixture", thread_id=self.beta_id), (200, []))
        status, retained = self.get("explore", q="opalfixture", thread_id=self.alpha_id)
        self.assertEqual(status, 200)
        self.assertTrue(self.message_rows(retained))

    def test_missing_or_malformed_consent_fails_closed_with_existing_data(self) -> None:
        message = self.message_id("retained-chat")
        scope_path = thread_tree.scope.scope_config_path(self.data)
        for condition in ("missing", "unconfigured", "malformed"):
            if condition == "missing":
                scope_path.unlink()
            elif condition == "unconfigured":
                self.configure()
            else:
                scope_path.write_text("{broken", encoding="utf-8")
            with self.subTest(condition=condition):
                self.assertEqual(self.get("threads"), (200, []))
                self.assertEqual(self.get(f"node/{quote(message)}", view="explorer")[0], 404)
                self.assertEqual(self.get("explore", q="opalfixture", thread_id=self.alpha_id)[0], 404)
                with self.assertRaisesRegex(ValueError, "not configured"):
                    model_tools.search_project_history("opalfixture", project_root=str(self.alpha))

    def test_explicit_chat_allowlist_holds_in_explorer_and_direct_source_route(self) -> None:
        private = self.message_id("removable-chat")
        self.configure(self.alpha, alpha_chats=["retained-chat"])
        status, payload = self.get("explore", q="saffronfixture", thread_id=self.alpha_id)
        self.assertEqual(status, 200)
        self.assertEqual(self.message_rows(payload), [])
        for view in ("explorer", ""):
            with self.subTest(view=view):
                self.assertEqual(self.get(f"node/{quote(private)}", view=view)[0], 404)
        allowed = self.message_id("retained-chat")
        self.assertEqual(self.get(f"node/{quote(allowed)}", view="explorer")[0], 200)
        result = model_tools.search_project_history("archive", project_root=str(self.alpha))
        self.assertEqual({hit["thread_id"] for hit in result["evidence"]}, {"retained-chat"})

    def test_legacy_windows_search_tree_and_detail_respect_chat_allowlist(self) -> None:
        indexed = thread_tree.index_range(self.remove, 1, None, "boundary fixture")
        self.assertEqual(indexed["status"], "indexed")
        with closing(thread_tree.connect_db()) as db:
            node = db.execute("SELECT id FROM nodes WHERE thread_id='removable-chat' AND kind='span'").fetchone()[0]
        self.configure(self.alpha, alpha_chats=["retained-chat"])
        with self.subTest(endpoint="project-search"):
            self.assertEqual(self.get("search", q="saffronfixture", thread_id=self.alpha_id), (200, []))
        with self.subTest(endpoint="raw-thread-search"):
            self.assertEqual(self.get("search", q="saffronfixture", thread_id="removable-chat"), (200, []))
        with self.subTest(endpoint="windows"):
            self.assertEqual(self.get("windows", thread_id="removable-chat"), (200, []))
        with self.subTest(endpoint="node"):
            self.assertEqual(self.get(f"node/{quote(node)}")[0], 404)
        with self.subTest(endpoint="tree"):
            snapshot = self.get("tree", thread_id=self.alpha_id)
            self.assertNotIn("saffronfixture", json.dumps(snapshot).casefold())

    def test_historical_corpus_is_read_only_and_paused_project_still_browses(self) -> None:
        before = self.snapshot()
        evidence_before = self.snapshot(ignore_plugin_recency=self.alpha_id)
        status, pause = self.connection("pause", self.alpha)
        self.assertEqual(status, 200)
        self.assertTrue(any(item["status"] == "paused" for item in pause["connections"] if item["id"] == self.alpha_id))
        with self.assertRaisesRegex(ValueError, "project_paused"):
            model_tools.search_project_history("opalfixture", project_root=str(self.alpha))
        self.assertTrue(self.message_rows(self.get("explore", q="opalfixture", thread_id=self.alpha_id)[1]))
        self.assertIn(self.alpha_id, {row["id"] for row in self.get("threads")[1]})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.connection("resume", self.alpha)[0], 200)
        self.assertTrue(model_tools.search_project_history("opalfixture", project_root=str(self.alpha))["evidence"])
        self.assertEqual(self.snapshot(ignore_plugin_recency=self.alpha_id), evidence_before)
        self.launch_process.assert_not_called()

    def test_chat_pause_and_resume_preserve_chunks_and_other_chat_eligibility(self) -> None:
        for allowlist in (None, ["removable-chat", "retained-chat"]):
            with self.subTest(explicit_allowlist=allowlist is not None):
                self.configure(self.alpha, self.beta, alpha_chats=allowlist)
                before = self.snapshot(ignore_plugin_recency=self.alpha_id)
                self.assertEqual(self.connection("pause", self.alpha, "removable-chat")[0], 200)
                results = model_tools.search_project_history("archive", project_root=str(self.alpha))["evidence"]
                self.assertEqual({item["thread_id"] for item in results}, {"retained-chat"})
                self.assertEqual(self.connection("resume", self.alpha, "removable-chat")[0], 200)
                results = model_tools.search_project_history("saffronfixture", project_root=str(self.alpha))["evidence"]
                self.assertEqual({item["thread_id"] for item in results}, {"removable-chat"})
                self.assertEqual(self.snapshot(ignore_plugin_recency=self.alpha_id), before)

    def test_retained_unselected_folder_is_paused_and_folder_resume_restores_consent(self) -> None:
        before = self.snapshot()
        config = thread_tree.load_scope_config()
        config["projects"] = [item for item in config["projects"] if item["path"] == str(self.alpha)]
        self.assertEqual(self.request("POST", "/api/scope", config)[0], 200)
        rows = {item["id"]: item for item in self.get("connections")[1]["connections"]}
        self.assertEqual(rows[self.alpha_id]["status"], "connected")
        self.assertEqual(rows[self.beta_id]["status"], "paused")
        self.assertEqual({item["status"] for item in rows[self.beta_id]["chats"]}, {"paused"})
        self.assertEqual({item["id"] for item in self.get("threads")[1]}, {self.alpha_id})
        self.assertEqual(self.get("explore", thread_id=self.beta_id)[0], 404)
        self.assertEqual(self.snapshot(), before)

        status, result = self.connection("resume", self.beta)
        self.assertEqual(status, 200)
        row = next(item for item in result["connections"] if item["id"] == self.beta_id)
        self.assertEqual(row["status"], "connected")
        self.assertEqual({item["status"] for item in row["chats"]}, {"connected"})
        self.assertEqual(self.get("explore", thread_id=self.beta_id)[0], 200)
        self.assertEqual(self.snapshot(), before)

    def test_resuming_one_retained_chat_does_not_activate_unselected_siblings(self) -> None:
        self.index_fixture(self.beta, "other-paused-chat", "jadefixture")
        self.configure(self.alpha)
        status, result = self.connection("resume", self.beta, "other-project-chat")
        self.assertEqual(status, 200)
        row = next(item for item in result["connections"] if item["id"] == self.beta_id)
        self.assertEqual(row["status"], "connected")
        self.assertEqual(
            {chat["id"]: chat["status"] for chat in row["chats"]},
            {"other-project-chat": "connected", "other-paused-chat": "paused"},
        )
        self.assertFalse(self.message_rows(self.get("explore", q="jadefixture", thread_id=self.beta_id)[1]))
        self.assertTrue(self.message_rows(self.get("explore", q="tulipfixture", thread_id=self.beta_id)[1]))

    def test_disconnect_redelivery_does_not_reindex_and_sources_survive_rebuild(self) -> None:
        forbidden = self.message_id("removable-chat")
        original = {path: path.read_bytes() for path in (self.keep, self.remove, self.foreign)}
        status, reply = self.connection("disconnect", self.alpha, "removable-chat")
        self.assertEqual(status, 200)
        job_id = reply["refreshJobId"]
        self.assertEqual(self.get("connections/refresh-status", job=job_id)[1]["state"], "queued")
        self.assertEqual(self.get(f"node/{quote(forbidden)}", view="explorer")[0], 404)
        self.assertFalse(self.message_rows(self.get("explore", q="saffronfixture", thread_id=self.alpha_id)[1]))
        self.assertEqual(rebuild.main([job_id, self.alpha_id]), 0)
        self.assertEqual(self.get("connections/refresh-status", job=job_id)[1]["state"], "complete")
        self.assertEqual(self.request("POST", "/api/connections/refresh-retry", {"jobId": job_id})[1]["state"], "complete")
        self.assertEqual(self.launch_process.call_count, 1)
        self.assertEqual(self.get("connections/refresh-status")[1]["state"], "idle")
        event = {"cwd": str(self.alpha), "session_id": "removable-chat", "transcript_path": str(self.remove)}
        with patch.object(stop.sys, "stdin", io.StringIO(json.dumps(event))), patch.object(stop, "launch_worker") as launch, redirect_stdout(io.StringIO()):
            self.assertEqual(stop.main(), 0)
        launch.assert_not_called()
        self.assertFalse(self.message_rows(self.get("explore", q="saffronfixture", thread_id=self.alpha_id)[1]))
        self.assertTrue(self.message_rows(self.get("explore", q="tulipfixture", thread_id=self.beta_id)[1]))
        for path, contents in original.items():
            self.assertEqual(path.read_bytes(), contents)

    def test_mismatched_project_chat_pair_cannot_delete_foreign_legacy_rows(self) -> None:
        self.assertEqual(thread_tree.index_range(self.foreign, 1, None, "boundary fixture")["status"], "indexed")
        before = self.snapshot()
        for action in ("pause", "resume", "disconnect"):
            with self.subTest(action=action):
                status, _ = self.connection(action, self.alpha, "other-project-chat")
                self.assertIn(status, (400, 404))
                self.assertEqual(self.snapshot(), before)
        self.launch_process.assert_not_called()

    def test_worker_launch_failure_cannot_leave_refresh_stuck_queued(self) -> None:
        forbidden = self.message_id("removable-chat")
        self.launch_process.side_effect = OSError("injected spawn failure")
        status, reply = self.connection("disconnect", self.alpha, "removable-chat")
        self.assertEqual(status, 200)
        job_id = reply["refreshJobId"]
        self.assertIn(self.get("connections/refresh-status", job=job_id)[1]["state"], ("failed", "idle"))
        self.assertEqual(self.get(f"node/{quote(forbidden)}", view="explorer")[0], 404)
        self.assertEqual(self.get("connections/refresh-status")[1]["id"], job_id)
        self.launch_process.side_effect = None
        status, retried = self.request("POST", "/api/connections/refresh-retry", {"jobId": job_id})
        self.assertEqual(status, 200)
        self.assertEqual(retried["id"], job_id)
        self.assertEqual(retried["projectIds"], [self.alpha_id])
        self.assertEqual(retried["state"], "queued")
        self.assertEqual(self.request("POST", "/api/connections/refresh-retry", {"jobId": job_id})[1]["state"], "queued")
        self.assertEqual(self.launch_process.call_count, 2)
        self.assertEqual(rebuild.main([job_id, self.alpha_id]), 0)
        self.assertEqual(self.get("connections/refresh-status", job=job_id)[1]["state"], "complete")
        self.assertEqual(self.get("connections/refresh-status")[1]["state"], "idle")

    def test_interrupted_after_scope_finalization_still_exposes_refresh_for_retry(self) -> None:
        forbidden = self.message_id("removable-chat")
        with patch.object(thread_tree, "_launch_connection_rebuild", side_effect=OSError("interrupted before spawn")):
            self.assertEqual(self.connection("disconnect", self.alpha, "removable-chat")[0], 500)
        selected = thread_tree.scope.selected_project(thread_tree.load_scope_config(), str(self.alpha))
        self.assertFalse(selected.get("pendingDisconnectChatIds"))
        self.assertEqual(self.get(f"node/{quote(forbidden)}", view="explorer")[0], 404)
        status, job = self.get("connections/refresh-status")
        self.assertEqual(status, 200)
        self.assertEqual(job["state"], "pending")
        self.assertTrue(job["retryable"])
        self.assertEqual(self.request("POST", "/api/connections/refresh-retry", {"jobId": job["id"]})[0], 200)
        self.assertEqual(rebuild.main([job["id"], self.alpha_id]), 0)
        self.assertEqual(self.get("connections/refresh-status")[1]["state"], "idle")

    def test_abandoned_refresh_remains_visible_and_cannot_change_retry_scope(self) -> None:
        status, reply = self.connection("disconnect", self.alpha, "removable-chat")
        self.assertEqual(status, 200)
        job_id = reply["refreshJobId"]
        thread_tree.write_connection_refresh_job(
            job_id, "running", [self.alpha_id], tracks_worker=True, retryable=True,
        )
        observed = self.get("connections/refresh-status")[1]
        self.assertEqual(observed["id"], job_id)
        self.assertEqual(observed["state"], "failed")
        self.assertTrue(observed["retryable"])
        endpoint = "/api/connections/refresh-retry"
        self.assertEqual(self.request("POST", endpoint, {"jobId": job_id}, headers={"Origin": "https://foreign.invalid"})[0], 403)
        self.assertEqual(self.request("POST", endpoint, {"jobId": "refresh_" + "0" * 32})[0], 400)
        self.assertEqual(self.request("POST", endpoint, {"jobId": "../scope-config"})[0], 400)
        self.assertEqual(self.launch_process.call_count, 1)
        status, retried = self.request("POST", endpoint, {"jobId": job_id, "projectIds": [self.beta_id]})
        self.assertEqual(status, 200)
        self.assertEqual(retried["projectIds"], [self.alpha_id])
        self.assertEqual(self.launch_process.call_args.args[0][-2:], [job_id, self.alpha_id])
        self.assertEqual(self.launch_process.call_count, 2)

    def test_failed_scope_write_cannot_delete_chunks_or_enqueue_refresh(self) -> None:
        before = self.snapshot()
        before_scope = thread_tree.load_scope_config()
        for chat in (None, "removable-chat"):
            with self.subTest(kind="chat" if chat else "project"):
                with patch.object(thread_tree, "save_scope_config", side_effect=OSError("injected write failure")):
                    self.assertEqual(self.connection("disconnect", self.alpha, chat)[0], 500)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(thread_tree.load_scope_config(), before_scope)
        self.launch_process.assert_not_called()

    def test_project_disconnect_invalidates_only_its_vectors_and_retained_rows(self) -> None:
        artifacts = {}
        for identifier in (self.alpha_id, self.beta_id):
            path = self.data / "vector-indexes" / identifier / vector_index.INDEX_FILENAME
            path.parent.mkdir(parents=True)
            path.write_bytes(b"synthetic native index placeholder")
            artifacts[identifier] = path
        original = {path: path.read_bytes() for path in (self.keep, self.remove, self.foreign)}
        self.assertEqual(thread_tree.index_range(self.keep, 1, None, "boundary fixture")["status"], "indexed")
        status, result = self.connection("disconnect", self.alpha)
        self.assertEqual(status, 200)
        self.assertEqual(self.get("connections/refresh-status", job=result["refreshJobId"])[1]["projectIds"], [self.beta_id])
        self.assertFalse(artifacts[self.alpha_id].exists())
        self.assertTrue(artifacts[self.beta_id].is_file())
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual({row["id"] for row in db.execute("SELECT id FROM projects")}, {self.beta_id})
            self.assertEqual({row["project_id"] for row in db.execute("SELECT project_id FROM turn_chunks_fts")}, {self.beta_id})
            self.assertIsNone(db.execute("SELECT 1 FROM threads WHERE cwd=?", (str(self.alpha),)).fetchone())
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
        self.assertEqual({row["id"] for row in self.get("threads")[1]}, {self.beta_id})
        for path, contents in original.items():
            self.assertEqual(path.read_bytes(), contents)

    def test_failed_tree_refresh_never_republishes_revoked_chat_or_vectors(self) -> None:
        path = self.data / "vector-indexes" / self.alpha_id / vector_index.INDEX_FILENAME
        path.parent.mkdir(parents=True)
        path.write_bytes(b"stale vector fixture")
        forbidden = self.message_id("removable-chat")
        status, reply = self.connection("disconnect", self.alpha, "removable-chat")
        self.assertEqual(status, 200)
        self.assertFalse(path.exists())
        with patch.object(rebuild.pipeline, "rebuild_project", side_effect=RuntimeError("injected rebuild failure")):
            self.assertEqual(rebuild.main([reply["refreshJobId"], self.alpha_id]), 1)
        self.assertEqual(self.get("connections/refresh-status", job=reply["refreshJobId"])[1]["state"], "failed")
        self.assertEqual(self.get("connections/refresh-status")[1]["id"], reply["refreshJobId"])
        self.assertEqual(self.get(f"node/{quote(forbidden)}", view="explorer")[0], 404)
        self.assertFalse(self.message_rows(self.get("explore", q="saffronfixture", thread_id=self.alpha_id)[1]))
        self.assertTrue(self.message_rows(self.get("explore", q="opalfixture", thread_id=self.alpha_id)[1]))
        self.assertEqual(self.request("POST", "/api/connections/refresh-retry", {"jobId": reply["refreshJobId"]})[0], 200)
        self.assertEqual(rebuild.main([reply["refreshJobId"], self.alpha_id]), 0)
        self.assertEqual(self.get("connections/refresh-status")[1]["state"], "idle")

    def test_untrusted_origin_cannot_change_scope_or_connections(self) -> None:
        config_before = thread_tree.load_scope_config()
        attack_headers = {"Origin": "https://other.invalid", "Content-Type": "text/plain"}
        for endpoint, payload in (
            ("/api/scope", {"configured": False}),
            ("/api/connections/action", {"action": "pause", "kind": "project", "projectPath": str(self.alpha)}),
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.request("POST", endpoint, payload, headers=attack_headers)[0], 403)
                self.assertEqual(thread_tree.load_scope_config(), config_before)
        self.launch_backfill.assert_not_called()

    def test_host_rebind_and_malformed_ipv6_host_are_refused_before_reading_data(self) -> None:
        endpoint = f"/api/explore?{urlencode({'q': 'opalfixture', 'thread_id': self.alpha_id})}"
        for host in ("malicious.invalid:8765", "[a]:8765", "localhost.invalid:8765"):
            with self.subTest(host=host):
                status, response = self.request("GET", endpoint, headers={"Host": host})
                self.assertEqual(status, 403)
                self.assertNotIn("opalfixture", json.dumps(response))
        status, _ = self.request("GET", endpoint, headers={"Origin": "http://localhost:8765"})
        self.assertEqual(status, 200)

    def test_verbose_logging_omits_search_text(self) -> None:
        trace = io.StringIO()
        marker = "synthetic_query_log_marker"
        with patch.dict(os.environ, {"THREAD_HISTORY_TREE_VERBOSE": "1"}), redirect_stderr(trace):
            self.assertEqual(self.get("explore", q=marker, thread_id=self.alpha_id)[0], 200)
        self.assertIn("GET response 200", trace.getvalue())
        self.assertNotIn(marker, trace.getvalue())

    def test_partial_chat_scope_does_not_expose_cached_mixed_cluster_titles(self) -> None:
        with closing(thread_tree.connect_db()) as db, db:
            result = db.execute(
                """UPDATE semantic_nodes SET title='revokedtitlefixture', summary='revokedsummaryfixture'
                   WHERE project_id=?""",
                (self.alpha_id,),
            )
            self.assertGreater(result.rowcount, 0, "fixture requires derived clusters before consent changes")
        self.configure(self.alpha, alpha_chats=["retained-chat"])
        result = model_tools.search_project_history("opalfixture", project_root=str(self.alpha))
        self.assertTrue(result["evidence"])
        for response in (
            result,
            self.get("explore", thread_id=self.alpha_id),
            self.get("search", q="opalfixture", thread_id=self.alpha_id),
            self.get("tree", thread_id=self.alpha_id),
            self.get(f"node/{quote(self.message_id('retained-chat'))}", view="explorer"),
        ):
            self.assertNotIn("revokedtitlefixture", json.dumps(response))
            self.assertNotIn("revokedsummaryfixture", json.dumps(response))

    def test_ineligible_lexical_hits_do_not_exhaust_candidate_limit(self) -> None:
        with closing(thread_tree.connect_db()) as db, db:
            source = db.execute("SELECT * FROM turn_chunks WHERE thread_id='removable-chat' LIMIT 1").fetchone()
            for index in range(110):
                chunk_id = f"disallowed_fixture_{index}"
                text = "opalfixture uniquecontrolterm"
                db.execute(
                    """INSERT INTO turn_chunks (id, project_id, turn_id, thread_id, text, content_hash,
                       byte_count, source_message_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk_id, self.alpha_id, source["turn_id"], "removable-chat", text, chunk_id,
                        len(text), source["source_message_ids"], source["created_at"],
                    ),
                )
                db.execute(
                    "INSERT INTO turn_chunks_fts (chunk_id, project_id, thread_id, text) VALUES (?, ?, ?, ?)",
                    (chunk_id, self.alpha_id, "removable-chat", text),
                )
        self.configure(self.alpha, alpha_chats=["retained-chat"])
        result = model_tools.search_project_history("opalfixture uniquecontrolterm", project_root=str(self.alpha))
        self.assertEqual({row["thread_id"] for row in result["evidence"]}, {"retained-chat"})

    def test_disconnect_cannot_be_overtaken_by_hook_that_already_checked_consent(self) -> None:
        queued = threading.Event()
        release = threading.Event()
        original_enqueue = stop.enqueue_transcript
        event = {"cwd": str(self.alpha), "session_id": "removable-chat", "transcript_path": str(self.remove)}

        def delayed_enqueue(*args, **kwargs):
            queued.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test barrier never released")
            return original_enqueue(*args, **kwargs)

        with (
            patch.object(stop, "enqueue_transcript", side_effect=delayed_enqueue),
            patch.object(stop.sys, "stdin", io.StringIO(json.dumps(event))),
            patch.object(stop, "launch_worker"),
            redirect_stdout(io.StringIO()),
        ):
            hook = threading.Thread(target=stop.main, daemon=True)
            hook.start()
            try:
                self.assertTrue(queued.wait(timeout=5), "hook did not reach pre-enqueue barrier")
                self.assertEqual(self.connection("disconnect", self.alpha, "removable-chat")[0], 200)
            finally:
                release.set()
                hook.join(timeout=5)
        self.assertFalse(hook.is_alive())
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM turn_ingestion WHERE thread_id='removable-chat'").fetchone()[0],
                0,
                "a completed disconnect must not retain a newly queued copy",
            )

    def test_failed_purge_does_not_allow_resume_to_republish_retained_data(self) -> None:
        identifier = self.message_id("removable-chat")
        with closing(thread_tree.connect_db()) as db, db:
            db.execute(
                """CREATE TRIGGER fault_purge BEFORE DELETE ON turn_ingestion
                   WHEN OLD.thread_id='removable-chat'
                   BEGIN SELECT RAISE(ABORT, 'synthetic purge failure'); END"""
            )
        self.assertEqual(self.connection("disconnect", self.alpha, "removable-chat")[0], 500)
        self.assertEqual(self.get(f"node/{quote(identifier)}", view="explorer")[0], 404)
        pending = thread_tree.scope.selected_project(thread_tree.load_scope_config(), str(self.alpha))
        self.assertEqual(pending["pendingDisconnectChatIds"], ["removable-chat"])
        self.assertIn(self.connection("resume", self.alpha, "removable-chat")[0], (400, 409))
        with self.assertRaisesRegex(ValueError, "Disconnection is pending"):
            model_tools._activate_scope_for_chat(str(self.alpha), "removable-chat")
        self.assertEqual(self.request("POST", "/api/scope", {"configured": False})[0], 409)
        self.assertEqual(self.get(f"node/{quote(identifier)}", view="explorer")[0], 404)
        with closing(thread_tree.connect_db()) as db, db:
            db.execute("DROP TRIGGER fault_purge")
        self.assertEqual(self.connection("disconnect", self.alpha, "removable-chat")[0], 200)
        selected = thread_tree.scope.selected_project(thread_tree.load_scope_config(), str(self.alpha))
        self.assertFalse(selected.get("pendingDisconnectChatIds"))
        self.assertIn("removable-chat", selected["excludedChatIds"])
        with closing(thread_tree.connect_db()) as db:
            self.assertFalse(db.execute("SELECT 1 FROM turn_ingestion WHERE thread_id='removable-chat'").fetchall())
        self.assertEqual(self.get(f"node/{quote(identifier)}", view="explorer")[0], 404)

    def test_interrupted_disconnect_finalization_remains_discoverable_and_idempotently_retryable(self) -> None:
        original = thread_tree.save_scope_config
        calls = 0

        def fail_after_purge(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("interrupted after database purge, before consent finalization")
            return original(value)

        with patch.object(thread_tree, "save_scope_config", side_effect=fail_after_purge):
            self.assertEqual(self.connection("disconnect", self.alpha, "removable-chat")[0], 500)
        self.launch_process.assert_not_called()
        self.assertEqual(calls, 2)
        status, listing = self.get("connections")
        self.assertEqual(status, 200)
        folder = next(item for item in listing["connections"] if item["id"] == self.alpha_id)
        retry_row = next(chat for chat in folder["chats"] if chat["id"] == "removable-chat")
        self.assertEqual(retry_row["status"], "paused")
        self.assertTrue(retry_row["disconnectPending"])
        self.assertEqual(self.connection("resume", self.alpha, "removable-chat")[0], 400)
        with closing(thread_tree.connect_db()) as db:
            self.assertFalse(db.execute("SELECT 1 FROM turn_ingestion WHERE thread_id='removable-chat'").fetchall())
        job = self.get("connections/refresh-status")[1]
        self.assertEqual(job["state"], "pending")
        status, reply = self.connection("disconnect", self.alpha, "removable-chat")
        self.assertEqual(status, 200)
        self.assertEqual(reply["refreshJobId"], job["id"])
        self.assertEqual(len(list(thread_tree.connection_refresh_directory().glob("refresh_*.json"))), 1)
        self.assertEqual(rebuild.main([job["id"], self.alpha_id]), 0)
        self.assertEqual(self.get("connections/refresh-status")[1]["state"], "idle")
        _, listing = self.get("connections")
        folder = next(item for item in listing["connections"] if item["id"] == self.alpha_id)
        self.assertNotIn("removable-chat", {chat["id"] for chat in folder["chats"]})

    def test_transient_search_query_cannot_write_semantic_content_or_expand_sql_wildcards(self) -> None:
        before = self.snapshot(ignore_plugin_recency=self.alpha_id)
        terms = ("transient_boundary_marker_2197", "%", "_")
        for term in terms:
            with self.subTest(term=term):
                http_before = self.snapshot()
                self.assertFalse(self.message_rows(self.get("explore", q=term, thread_id=self.alpha_id)[1]))
                self.assertEqual(self.snapshot(), http_before)
                self.assertFalse(model_tools.search_project_history(term, project_root=str(self.alpha))["evidence"])
        self.assertEqual(self.snapshot(ignore_plugin_recency=self.alpha_id), before)


if __name__ == "__main__":
    unittest.main()
