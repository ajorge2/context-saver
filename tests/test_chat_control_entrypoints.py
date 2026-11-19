"""Exercise chat controls through real CLI processes and the stdio MCP boundary."""

from __future__ import annotations

import _support

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

import thread_tree
import thread_tree_pipeline as pipeline
import thread_tree_state as state


class ChatControlEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = self.root / "Project é & spaces"
        self.project.mkdir()
        self.data = self.root / "data"
        self.data.mkdir()
        self.environment = dict(os.environ)
        for name in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CLAUDE_SESSION_ID"):
            self.environment.pop(name, None)
        self.environment.update(
            THREAD_HISTORY_TREE_DATA=str(self.data),
            CODEX_HOME=str(self.root / "codex"),
            CLAUDE_CONFIG_DIR=str(self.root / "claude"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        self.enterContext(patch.dict(os.environ, self.environment, clear=True))
        (self.data / "config.json").write_text(json.dumps({
            "embedding_provider": "none", "ollama_url": "fixture-no-network:",
        }), encoding="utf-8")
        self.chat = "control-chat"
        self.transcript = self.project / "synthetic.jsonl"
        self.rows = [{"type": "session_meta", "payload": {
            "session_id": self.chat, "cwd": str(self.project),
        }}]
        self.add_turn("before", "A pre-control message exists.")
        with closing(thread_tree.connect_db()) as db:
            state.observe_session(db, project_root=str(self.project), thread_id=self.chat,
                                  transcript_path=str(self.transcript))

    def add_turn(self, identifier, text):
        for role, value in (("user", text), ("assistant", f"Recorded {identifier}.")):
            self.rows.append({"type": "response_item", "payload": {
                "type": "message", "id": f"{identifier}-{role}", "role": role,
                "content": [{"type": "input_text" if role == "user" else "output_text", "text": value}],
            }})
        self.transcript.write_text("\n".join(json.dumps(row) for row in self.rows) + "\n", encoding="utf-8")

    def cli(self, action, *, identity=True, environment=None):
        args = [sys.executable, "-X", "utf8", str(_support.SCRIPTS_ROOT / "thread_tree.py"), action,
                "--project", str(self.project), "--json"]
        if identity:
            args += ["--thread-id", self.chat]
        result = subprocess.run(args, env=environment or self.environment, cwd=self.project,
                                capture_output=True, encoding="utf-8", timeout=20)
        self.assertIn(result.returncode, (0, 2), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def canonical_snapshot(self):
        with closing(thread_tree.connect_db()) as db:
            return {table: [tuple(row) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                    for table in ("projects", "turn_ingestion", "turn_chunks", "staged_user_prompts")}

    def test_cli_off_survives_fresh_process_and_status_does_not_activate(self):
        code, result = self.cli("off")
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "off")
        self.assertFalse(result["enabled"])
        self.assertIn("OFF", result["message"])
        self.assertIn("chat", result["message"])
        self.assertEqual(result["thread_id"], self.chat)
        saved = self.canonical_snapshot()
        for action in ("status", "off", "status"):
            scope_path = self.data / "scope-config.json"
            scope_before = scope_path.read_bytes() if scope_path.exists() else None
            code, subsequent = self.cli(action)
            self.assertEqual(code, 0)
            self.assertEqual(subsequent["status"], "off")
            self.assertFalse(subsequent["enabled"])
            if action == "status":
                self.assertEqual(scope_path.read_bytes() if scope_path.exists() else None, scope_before)
        self.assertEqual(self.canonical_snapshot(), saved)

    def test_cli_missing_identity_does_not_choose_latest_observed_chat(self):
        before = self.canonical_snapshot()
        code, result = self.cli("off", identity=False)
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "session_unavailable")
        self.assertEqual(self.canonical_snapshot(), before)
        self.assertFalse((self.data / "scope-config.json").exists())

    def test_cli_can_use_exact_host_identity_without_thread_argument(self):
        for variable in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CLAUDE_SESSION_ID"):
            with self.subTest(variable=variable):
                environment = {**self.environment, variable: self.chat}
                code, result = self.cli("off", identity=False, environment=environment)
                self.assertEqual(code, 0)
                self.assertEqual(result["status"], "off")
                self.assertEqual(result["thread_id"], self.chat)

    def test_actual_hook_entrypoints_stay_quiet_and_save_nothing_after_off(self):
        self.assertEqual(self.cli("off")[0], 0)
        before = self.canonical_snapshot()
        self.add_turn("off-period", "PRIVATE-OFF-PERIOD-9f42 must not be saved.")
        event = {"cwd": str(self.project), "session_id": self.chat,
                 "transcript_path": str(self.transcript), "turn_id": "off-period",
                 "prompt": "PRIVATE-OFF-PERIOD-9f42 must not be staged."}
        for script in ("user_prompt_submit.py", "stop.py", "pre_compact.py"):
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(_support.SCRIPTS_ROOT / script)],
                                        input=json.dumps(event), env=self.environment, cwd=self.project,
                                        capture_output=True, encoding="utf-8", timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertTrue(output["continue"])
                self.assertNotIn("systemMessage", output)
        self.assertEqual(self.canonical_snapshot(), before)
        self.assertFalse((self.data / "hook-errors.jsonl").exists())

    def test_cli_on_resumes_without_saving_off_period_and_keeps_on_status(self):
        self.assertEqual(self.cli("off")[0], 0)
        self.add_turn("off-period", "PRIVATE-OFF-PERIOD-5921")
        code, resumed = self.cli("on")
        self.assertEqual(code, 0)
        self.assertTrue(resumed["enabled"])
        self.assertEqual(resumed["status"], "on")
        code, status = self.cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(status["status"], "on")
        self.assertTrue(status["enabled"])
        with closing(thread_tree.connect_db()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM turn_chunks WHERE instr(text, ?) > 0",
                                        ("PRIVATE-OFF-PERIOD-5921",)).fetchone()[0], 0)

    def test_cli_off_and_viewer_resume_share_one_state_and_capture_cutoff(self):
        self.assertEqual(self.cli("on")[0], 0)
        self.assertEqual(self.cli("off")[0], 0)
        connections = thread_tree.connections_payload()["connections"]
        project = next(item for item in connections if item["path"] == str(self.project))
        self.assertEqual(next(chat for chat in project["chats"] if chat["id"] == self.chat)["status"], "paused")
        self.add_turn("ui-off-period", "PRIVATE-UI-OFF-PERIOD-72a3")
        resumed = thread_tree.update_connection({
            "kind": "chat", "action": "resume", "projectPath": str(self.project), "threadId": self.chat,
        })
        self.assertTrue(resumed["ok"])
        project = next(item for item in resumed["connections"] if item["path"] == str(self.project))
        self.assertEqual(next(chat for chat in project["chats"] if chat["id"] == self.chat)["status"], "connected")
        self.assertEqual(self.cli("status")[1]["status"], "on")
        self.add_turn("ui-after-resume", "PUBLIC-AFTER-RESUME-91b4")
        queued = pipeline.enqueue_transcript(self.transcript, enforce_scope=True)
        pipeline.process_project(queued["project_id"])
        with closing(thread_tree.connect_db()) as db:
            texts = "\n".join(row[0] for row in db.execute("SELECT text FROM turn_chunks"))
        self.assertNotIn("PRIVATE-UI-OFF-PERIOD-72a3", texts)
        self.assertIn("PUBLIC-AFTER-RESUME-91b4", texts)

    def test_viewer_resume_does_not_override_parent_project_or_global_pause(self):
        self.assertEqual(self.cli("on")[0], 0)
        self.assertEqual(self.cli("off")[0], 0)
        for pause_parent in ("project", "global"):
            with self.subTest(pause_parent=pause_parent):
                config = thread_tree.load_scope_config()
                config["paused"] = pause_parent == "global"
                config["projects"][0]["paused"] = pause_parent == "project"
                thread_tree.save_scope_config(config)
                with self.assertRaisesRegex(ValueError, "Resume its project|still off"):
                    thread_tree.update_connection({"kind": "chat", "action": "resume",
                        "projectPath": str(self.project), "threadId": self.chat})
                unchanged = thread_tree.load_scope_config()
                self.assertEqual(unchanged["paused"], pause_parent == "global")
                self.assertEqual(unchanged["projects"][0]["paused"], pause_parent == "project")
                self.assertEqual(self.cli("status")[1]["status"], "off")

    def test_mcp_control_boundary_persists_off_and_rejects_recall_after_reopen(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        # The explicit off command is valid before the first prompt hook has
        # observed this chat. Its saved status must still be authoritative.
        with closing(thread_tree.connect_db()) as db, db:
            db.execute("DELETE FROM session_observations")

        def payload(result):
            self.assertFalse(result.isError, result)
            return json.loads(next(item.text for item in result.content if getattr(item, "type", None) == "text"))

        async def verify():
            parameters = StdioServerParameters(command=sys.executable,
                args=[str(_support.PACKAGE_ROOT / "server" / "thread_tree_mcp.py"), "stdio"],
                cwd=str(self.project), env={**self.environment, "CODEX_THREAD_ID": self.chat})
            identity = {"project_root": str(self.project), "thread_id": self.chat}
            for iteration in range(2):
                async with stdio_client(parameters) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        inventory = await session.list_tools()
                        self.assertIn("control_current_chat", {tool.name for tool in inventory.tools})
                        control = payload(await session.call_tool("control_current_chat",
                            {"action": "off" if iteration == 0 else "status", **identity}))
                        self.assertEqual(control["status"], "off")
                        self.assertFalse(control["enabled"])
                        prepared = payload(await session.call_tool("prepare_current_chat", identity))
                        self.assertEqual(prepared["status"], "off")
                        searched = payload(await session.call_tool("search_project_history", {
                            "query": "pre-control message", "project_root": str(self.project),
                        }))
                        self.assertEqual(searched["status"], "off")
                        self.assertFalse(searched.get("evidence"))
            with closing(thread_tree.connect_db()) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM turn_chunks").fetchone()[0], 0)

        asyncio.run(asyncio.wait_for(verify(), timeout=30))


if __name__ == "__main__":
    unittest.main()
