"""Adversarial regressions for caller identity, prompt replay and effective status."""

from __future__ import annotations

import _support

import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_scope as scope
import thread_tree_state as state
import thread_tree_tools as tools
import user_prompt_submit as prompt_hook


OLD_TIME = "2000-01-01T00:00:00+00:00"


class ChatControlReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.data = self.root / "data"
        self.data.mkdir()
        self.projects = {name: self.root / name for name in ("alpha", "beta")}
        for project in self.projects.values():
            project.mkdir()
        self.enterContext(patch.dict(os.environ, {
            "THREAD_HISTORY_TREE_DATA": str(self.data),
            "CODEX_HOME": str(self.root / "codex"),
            "CLAUDE_CONFIG_DIR": str(self.root / "claude"),
            "CODEX_THREAD_ID": "", "CODEX_SESSION_ID": "", "CLAUDE_SESSION_ID": "",
        }))
        self.enterContext(patch.object(thread_tree.SemanticProvider, "_check"))
        (self.data / "config.json").write_text(json.dumps({
            "embedding_provider": "none", "ollama_url": "fixture-no-network:",
            "fit_thresholds": {"span": 100000, "specific": 100000, "broad": 100000},
        }), encoding="utf-8")
        thread_tree.save_scope_config({"schemaVersion": 1, "configured": True, "paused": False,
            "projects": [{"path": str(project), "includeNewChats": True, "activatedAt": OLD_TIME}
                         for project in self.projects.values()], "setupAt": OLD_TIME})
        self.rows = {}
        self.paths = {}
        for project, chat, text in (
            ("alpha", "chat-a", "ORIGINAL-ALPHA-381 saved project evidence"),
            ("alpha", "chat-b", "SIBLING-ALPHA-627 available sibling evidence"),
            ("beta", "chat-c", "OTHER-PROJECT-924 available remote evidence"),
        ):
            self.paths[chat] = self.projects[project] / f"{chat}.jsonl"
            self.rows[chat] = [{"type": "session_meta", "payload": {
                "session_id": chat, "cwd": str(self.projects[project]),
            }}]
            self.append_turn(chat, "original", text)
            queued = pipeline.enqueue_transcript(self.paths[chat], enforce_scope=True)
            processed = pipeline.process_project(queued["project_id"])
            self.assertFalse(processed["failures"])
            with closing(thread_tree.connect_db()) as db:
                state.observe_session(db, project_root=str(self.projects[project]), thread_id=chat,
                                      transcript_path=str(self.paths[chat]))

    def append_turn(self, chat, identifier, text):
        for role, content in (("user", text), ("assistant", f"Confirmed {identifier} for {chat}.")):
            self.rows[chat].append({"type": "response_item", "payload": {
                "type": "message", "id": f"{chat}-{identifier}-{role}", "role": role,
                "content": [{"type": "input_text" if role == "user" else "output_text", "text": content}],
            }})
        self.paths[chat].write_text("\n".join(json.dumps(row) for row in self.rows[chat]) + "\n", encoding="utf-8")

    def control(self, action):
        result = tools.control_current_chat(action, project_root=str(self.projects["alpha"]), thread_id="chat-a")
        self.assertTrue(result["ok"], result)
        return result

    def test_no_identity_cannot_recall_sibling_or_other_project_after_off(self):
        self.control("off")
        for project, query in (("alpha", "SIBLING-ALPHA-627"), ("beta", "OTHER-PROJECT-924")):
            with self.subTest(project=project), patch.object(pipeline, "search_project", side_effect=AssertionError("must not search without caller identity")):
                result = tools.search_project_history(query, project_root=str(self.projects[project]))
                self.assertEqual(result["status"], "session_unavailable")
                self.assertFalse(result["ok"])
                self.assertEqual(result["evidence"], [])
                self.assertEqual(result["trace"]["global_lookup_count"], 0)
                self.assertNotIn(query, json.dumps(result))
        # A known enabled caller is still allowed to use the shared project.
        enabled = tools.search_project_history("SIBLING-ALPHA-627", project_root=str(self.projects["alpha"]), thread_id="chat-b")
        self.assertEqual(enabled["status"], "supported")
        self.assertTrue(any("SIBLING-ALPHA-627" in item["text"] for item in enabled["evidence"]))

    def test_no_identity_preparation_does_not_pick_newer_enabled_sibling(self):
        self.control("off")
        with closing(thread_tree.connect_db()) as db, db:
            db.execute("UPDATE session_observations SET observed_at=? WHERE thread_id='chat-a'", (OLD_TIME,))
            db.execute("UPDATE session_observations SET observed_at=? WHERE thread_id='chat-b'", (state.utc_now(),))
        before = (self.data / "scope-config.json").read_bytes()
        with patch.object(tools, "_resolve_current_session", side_effect=AssertionError("must not guess latest observed chat")):
            result = tools.prepare_current_chat(project_root=str(self.projects["alpha"]))
        self.assertEqual(result["status"], "session_unavailable")
        self.assertFalse(result["ok"])
        self.assertEqual((self.data / "scope-config.json").read_bytes(), before)
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_plugin_activations").fetchone()[0], 0)

    def test_replayed_off_period_prompt_after_on_is_not_retained_but_new_turn_is(self):
        self.control("off")
        private = "PRIVATE-OFF-REPLAY-593 never retain this prompt"
        self.append_turn("chat-a", "off-period", private)
        self.control("on")
        stale_event = {"cwd": str(self.projects["alpha"]), "session_id": "chat-a",
                       "turn_id": "off-period", "transcript_path": str(self.paths["chat-a"]), "prompt": private}
        # Arrival order is deliberately reversed: the old hook delivery arrives
        # after reconnection has made the scope active again.
        for _ in range(2):
            with patch.object(prompt_hook.sys, "stdin", io.StringIO(json.dumps(stale_event))), patch.object(prompt_hook.sys, "stdout", io.StringIO()) as output:
                self.assertEqual(prompt_hook.main(), 0)
                self.assertTrue(json.loads(output.getvalue())["continue"])
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM staged_user_prompts WHERE instr(prompt, ?) > 0", (private,)).fetchone()[0], 0)
        self.append_turn("chat-a", "post-resume", "NEW-AFTER-RECONNECT-861 remains searchable")
        queued = pipeline.enqueue_transcript(self.paths["chat-a"], enforce_scope=True)
        self.assertFalse(pipeline.process_project(queued["project_id"])["failures"])
        with closing(thread_tree.connect_db()) as db:
            texts = "\n".join(row[0] for row in db.execute("SELECT text FROM turn_chunks WHERE evicted=0"))
        self.assertNotIn(private, texts)
        self.assertIn("ORIGINAL-ALPHA-381", texts)
        self.assertIn("NEW-AFTER-RECONNECT-861", texts)
        self.assertFalse((self.data / "hook-errors.jsonl").exists())

    def test_inactivity_status_uses_recent_project_activity_like_hooks(self):
        config = thread_tree.load_scope_config()
        config["pausePolicy"] = {"mode": "inactivity", "pauseOn": None, "inactivityDays": 30}
        # Simulate a long-installed project whose recent chat activity keeps it
        # enabled; activation dates alone would incorrectly report it as off.
        config["setupAt"] = OLD_TIME
        for item in config["projects"]:
            item["activatedAt"] = OLD_TIME
        (self.data / "scope-config.json").write_text(json.dumps(config), encoding="utf-8")
        project_id = state.project_id_for(str(self.projects["alpha"]))
        with closing(thread_tree.connect_db()) as db, db:
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (state.utc_now(), project_id))
        status = tools.control_current_chat("status", project_root=str(self.projects["alpha"]), thread_id="chat-a")
        self.assertEqual(status["status"], "on")
        self.assertTrue(status["enabled"])
        event = {"cwd": str(self.projects["alpha"]), "session_id": "chat-a", "turn_id": "recent-staged",
                 "transcript_path": str(self.paths["chat-a"]), "prompt": "Recent activity stays active."}
        with patch.object(prompt_hook.sys, "stdin", io.StringIO(json.dumps(event))), patch.object(prompt_hook.sys, "stdout", io.StringIO()):
            self.assertEqual(prompt_hook.main(), 0)
        with closing(thread_tree.connect_db()) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM staged_user_prompts WHERE codex_turn_id='recent-staged'").fetchone()[0], 1)
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (OLD_TIME, project_id))
        inactive = tools.control_current_chat("status", project_root=str(self.projects["alpha"]), thread_id="chat-a")
        self.assertEqual(inactive["status"], "off")
        self.assertEqual(inactive["reason"], "inactive_too_long")

    def _search_with_control_race(self, *, reconnect):
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_plugin_controls").fetchone()[0], 0)
        search = pipeline.search_project
        callback_ran = False

        def during_lookup(*args, **kwargs):
            nonlocal callback_ran
            self.assertFalse(callback_ran, "the fixture should issue a single global lookup")
            callback_ran = True
            self.control("off")
            if reconnect:
                self.control("on")
            return search(*args, **kwargs)

        with patch.object(pipeline, "search_project", side_effect=during_lookup):
            result = tools.search_project_history("SIBLING-ALPHA-627", project_root=str(self.projects["alpha"]))
        self.assertTrue(callback_ran)
        self.assertEqual(result["evidence"], [])
        self.assertIn(result["status"], {"off", "session_unavailable"})
        self.assertNotIn("SIBLING-ALPHA-627", json.dumps(result))

    def test_no_identity_lookup_discards_results_if_off_begins_inflight(self):
        self._search_with_control_race(reconnect=False)

    def test_no_identity_lookup_discards_results_after_inflight_off_on_cycle(self):
        self._search_with_control_race(reconnect=True)

    def test_failed_off_scope_write_still_appears_paused_in_connections(self):
        with patch.object(thread_tree, "save_scope_config", side_effect=OSError("synthetic scope write failure")):
            with self.assertRaisesRegex(OSError, "synthetic scope write failure"):
                tools.control_current_chat("off", project_root=str(self.projects["alpha"]), thread_id="chat-a")
        # The durable off marker committed before the scope write failed. The
        # viewer must reflect that effective state rather than offer a false ON.
        config = thread_tree.load_scope_config()
        self.assertTrue(scope.chat_is_selected(scope.selected_project(config, str(self.projects["alpha"])), "chat-a"))
        project = next(item for item in thread_tree.connections_payload()["connections"] if item["path"] == str(self.projects["alpha"]))
        self.assertEqual(next(chat for chat in project["chats"] if chat["id"] == "chat-a")["status"], "paused")
        status = tools.control_current_chat("status", project_root=str(self.projects["alpha"]), thread_id="chat-a")
        self.assertEqual(status["status"], "off")

    def test_database_rejects_legacy_writer_while_off_and_after_resume_cutoff(self):
        self.control("off")
        project_id = state.project_id_for(str(self.projects["alpha"]))
        # Simulate an already-running older process that does not know about
        # chat controls and queues/claims through the previous state API.
        with closing(thread_tree.connect_db()) as db:
            state.queue_turn(db, turn_id="legacy-late-turn", project_id=project_id, thread_id="chat-a",
                transcript_path=str(self.paths["chat-a"]), line_start=2, line_end=3,
                content_hash="legacy-late-turn-content")
            claim = state.claim_next_turn(db, project_id, thread_id="chat-a")
            self.assertEqual(claim["id"], "legacy-late-turn")
            before = [tuple(row) for row in db.execute("SELECT id,text FROM turn_chunks ORDER BY id")]
            for resumed in (False, True):
                with self.subTest(resumed=resumed):
                    if resumed:
                        self.control("on")
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "chat capture is off|resumed window"):
                        state.complete_turn_ingestion(db, claim["id"], [{
                            "id": "legacy-forbidden-chunk", "text": "LEGACY-PRIVATE-773 cannot be published",
                            # A chunk starting after the cutoff does not rescue
                            # an old source turn that crosses the cutoff.
                            "line_start": 999, "line_end": 999,
                        }], lease_token=claim["lease_token"])
                    self.assertEqual([tuple(row) for row in db.execute("SELECT id,text FROM turn_chunks ORDER BY id")], before)


if __name__ == "__main__":
    unittest.main()
