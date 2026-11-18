"""Exercise native OS boundaries with real processes and synthetic paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from unittest.mock import patch

from _support import PACKAGE_ROOT, SCRIPTS_ROOT, process_line
from native_hosts import isolated_environment
import thread_tree
from thread_tree_scope import save_scope_config
from thread_tree_state import project_id_for


LOCK_CHILD = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from thread_tree_state import exclusive_process_lock
try:
    with exclusive_process_lock(Path(sys.argv[2]), blocking=sys.argv[3] == 'blocking'):
        print('acquired', flush=True)
        sys.stdin.readline()
except BlockingIOError:
    print('blocked', flush=True)
    raise SystemExit(2)
"""


class NativePlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = self.enterContext(tempfile.TemporaryDirectory(prefix="context-saver-native-runtime-"))
        self.root = Path(self.directory)
        self.project = self.root / "Project é Ω & spaces"
        self.project.mkdir()
        self.env = isolated_environment(self.root)

    def lock_child(self, lock: Path, *, blocking: bool = True) -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-c", LOCK_CHILD, str(SCRIPTS_ROOT), str(lock),
             "blocking" if blocking else "nonblocking"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", env=self.env,
        )
        self.addCleanup(self.close_child, process)
        return process

    @staticmethod
    def close_child(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def test_native_lock_excludes_competitor_and_releases_after_process_death(self) -> None:
        lock = self.root / "State é & spaces" / "owner.lock"
        owner = self.lock_child(lock)
        self.assertEqual(process_line(owner), "acquired")
        competitor = self.lock_child(lock, blocking=False)
        stdout, stderr = competitor.communicate(timeout=10)
        self.assertEqual((competitor.returncode, stdout.strip(), stderr), (2, "blocked", ""))
        owner.kill()
        owner.communicate(timeout=10)
        replacement = self.lock_child(lock, blocking=False)
        self.assertEqual(process_line(replacement), "acquired")
        replacement.communicate("release\n", timeout=10)
        self.assertEqual(replacement.returncode, 0)

    def test_blocking_lock_waits_for_existing_owner(self) -> None:
        lock = self.root / "contended.lock"
        owner = self.lock_child(lock)
        self.assertEqual(process_line(owner), "acquired")
        competitor = self.lock_child(lock)
        time.sleep(0.25)
        self.assertIsNone(competitor.poll())
        owner.communicate("release\n", timeout=10)
        self.assertEqual(process_line(competitor), "acquired")
        competitor.communicate("release\n", timeout=10)
        self.assertEqual(competitor.returncode, 0)

    def test_detached_worker_finishes_after_its_launcher_exits(self) -> None:
        finished = self.root / "completed é Ω.txt"
        launcher = """
import subprocess, sys
sys.path.insert(0, sys.argv[1])
from thread_tree_runtime import detached_process_options
subprocess.Popen([sys.executable, '-X', 'utf8', '-c',
    'import pathlib,sys,time;time.sleep(0.5);pathlib.Path(sys.argv[1]).write_text("finished",encoding="utf-8")',
    sys.argv[2]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    **detached_process_options())
"""
        subprocess.run([sys.executable, "-X", "utf8", "-c", launcher, str(SCRIPTS_ROOT), str(finished)],
                       check=True, env=self.env, timeout=10)
        deadline = time.monotonic() + 10
        while not finished.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(finished.read_text(encoding="utf-8"), "finished")

    def test_project_identity_survives_path_normalization(self) -> None:
        canonical = project_id_for(str(self.project))
        self.assertEqual(canonical, project_id_for(str(self.project / ".")))
        self.assertEqual(canonical, project_id_for(str(self.project / "unused" / "..")))
        if os.name == "nt":
            self.assertEqual(canonical, project_id_for(str(self.project).swapcase()))
            self.assertEqual(canonical, project_id_for(self.project.as_posix()))
        self.assertNotEqual(canonical, project_id_for(str(self.root / "other project")))

    def test_native_shell_runs_all_hooks_from_unicode_package_and_project_paths(self) -> None:
        self.assert_hook_shell_contract()

    @unittest.skipUnless(os.name == "nt", "exercises native Windows PowerShell")
    def test_powershell_runs_all_hooks_from_unicode_package_and_project_paths(self) -> None:
        self.assert_hook_shell_contract(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"])

    def assert_hook_shell_contract(self, shell_prefix: list[str] | None = None) -> None:
        installed = self.root / "Installer é Ω & spaces" / "thread-tree"
        installed.parent.mkdir()
        shutil.copytree(PACKAGE_ROOT, installed, ignore=shutil.ignore_patterns("__pycache__"))
        environment = {**self.env, "CLAUDE_PLUGIN_ROOT": str(installed), "PLUGIN_ROOT": str(installed)}
        store = Path(environment["THREAD_HISTORY_TREE_DATA"])
        hooks = json.loads((installed / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]

        def invoke(command: str, event: dict) -> subprocess.CompletedProcess:
            return subprocess.run([*shell_prefix, command] if shell_prefix else command,
                                  shell=shell_prefix is None,
                                  input=json.dumps(event, ensure_ascii=False),
                                  env=environment, cwd=self.project, encoding="utf-8",
                                  capture_output=True, timeout=30)

        for host in ("codex", "claude"):
            transcript = self.project / f"{host} transcript.jsonl"
            if host == "codex":
                record = {"type": "session_meta", "payload": {"session_id": "synthetic-codex", "cwd": str(self.project)}}
            else:
                record = {"type": "user", "sessionId": "synthetic-claude", "cwd": str(self.project),
                          "uuid": "synthetic-user", "message": {"role": "user", "content": "Synthetic fixture"}}
            transcript.write_text(json.dumps(record) + "\n", encoding="utf-8")
            event = {"prompt": "Synthetic prompt café Ω", "cwd": str(self.project),
                     "session_id": f"synthetic-{host}", "transcript_path": str(transcript), "trigger": "manual"}
            for hook in ("UserPromptSubmit", "Stop", "PreCompact"):
                with self.subTest(host=host, hook=hook):
                    result = invoke(hooks[hook][0]["hooks"][0]["command"], event)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout), {"continue": True, "suppressOutput": True})
        self.assertFalse((store / "hook-errors.jsonl").exists())
        with closing(sqlite3.connect(store / "index.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM session_observations").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM staged_user_prompts").fetchone()[0], 0)
        save_scope_config(store, {"configured": True, "projects": [{"path": str(self.project), "includeNewChats": True}]})
        for _ in range(2):
            result = invoke(hooks["UserPromptSubmit"][0]["hooks"][0]["command"], event)
            self.assertEqual(result.returncode, 0, result.stderr)
        with closing(sqlite3.connect(store / "index.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT prompt FROM staged_user_prompts").fetchall(), [("Synthetic prompt café Ω",)])

    def test_required_local_semantic_runtime_is_available(self) -> None:
        # A platform release must not silently pass by skipping its native model.
        if not os.environ.get("CONTEXT_SAVER_REQUIRE_NATIVE_MODEL"):
            self.skipTest("enable native model requirement in the platform release matrix")
        with patch.dict(os.environ, self.env):
            provider = thread_tree.SemanticProvider(thread_tree.load_config())
            self.assertTrue(provider.can_embed)
            embedding = provider.embed(["Synthetic release guardrail ALPHA-617."])
            self.assertEqual(len(embedding), 1)
            self.assertEqual(len(embedding[0]), thread_tree.FASTEMBED_DIMENSION)


if __name__ == "__main__":
    unittest.main()
