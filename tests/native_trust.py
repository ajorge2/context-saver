"""Exercise workspace trust using the installed hosts and native terminals."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

from native_hosts import CLAUDE_FIXTURE_ANSWER, ClaudeFixtureAPI, host_command, install_marketplace, isolated_environment
from terminal import Terminal
from thread_tree_scope import save_scope_config


SYNTHETIC_KEY = "synthetic-context-saver-testing"


def verify_claude_trust(reports: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="context-saver-trust-") as directory:
        root = Path(directory).resolve()
        project = root / "Synthetic workspace é & spaces"
        project.mkdir()
        environment = isolated_environment(root)
        environment.update(TERM="xterm-256color", LANG="C.UTF-8")
        settings = Path(environment["CLAUDE_CONFIG_DIR"])
        store = Path(environment["THREAD_HISTORY_TREE_DATA"])
        install_marketplace(root, project, environment, "claude")
        config_path = settings / ".claude.json"
        profile = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        assert not any(row.get("hasTrustDialogAccepted") for row in profile.get("projects", {}).values())
        profile.update({
            "hasCompletedOnboarding": True, "theme": "dark", "autoUpdates": False,
            "customApiKeyResponses": {"approved": [SYNTHETIC_KEY[-20:]], "rejected": []},
        })
        config_path.write_text(json.dumps(profile), encoding="utf-8")
        save_scope_config(store, {"configured": True, "projects": [{"path": str(project), "includeNewChats": True}]})
        (store / "config.json").write_text('{"embedding_provider":"disabled"}', encoding="utf-8")

        def workspace_trusted() -> bool:
            state = json.loads(config_path.read_text(encoding="utf-8"))
            return any(
                os.path.normcase(os.path.realpath(path)) == os.path.normcase(str(project.resolve()))
                and row.get("hasTrustDialogAccepted") is True
                for path, row in state.get("projects", {}).items()
            )

        def chat_ready(terminal: Terminal) -> bool:
            text = terminal.display
            return "Claude Code v" in text and re.search(r"(?:^|\n)\s*[$❯>]", text) is not None

        def choose(terminal: Terminal, option: str) -> None:
            terminal.wait(lambda: "Quick safety check" in terminal.display and "Enter y/n" in terminal.display,
                          "Displaying the native workspace trust dialog")
            assert not workspace_trusted()
            terminal.send(option + "\r")

        ClaudeFixtureAPI.requests_seen = 0
        with ThreadingHTTPServer(("127.0.0.1", 0), ClaudeFixtureAPI) as server:
            serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            serving.start()
            environment.update(ANTHROPIC_API_KEY=SYNTHETIC_KEY,
                               ANTHROPIC_BASE_URL=f"http://127.0.0.1:{server.server_port}")
            command = host_command("claude") + ["--ax-screen-reader", "--model", "sonnet", "--tools", ""]
            try:
                refused = Terminal(command, project, environment, reports / "claude-trust-refused.txt")
                try:
                    choose(refused, "n")
                    refused.wait(lambda: not refused.alive(), "Refusing workspace trust")
                    assert not workspace_trusted()
                    assert not (store / "index.sqlite3").exists()
                    assert ClaudeFixtureAPI.requests_seen == 0
                finally:
                    refused.close(entered=False)

                accepted = Terminal(command, project, environment, reports / "claude-trust-accepted.txt")
                try:
                    choose(accepted, "y")
                    accepted.wait(lambda: workspace_trusted() and chat_ready(accepted), "Accepting workspace trust")
                    accepted.send("Return the synthetic integration answer.\r")
                    accepted.wait(lambda: CLAUDE_FIXTURE_ANSWER in accepted.display, "Completing a synthetic answer")

                    def indexed() -> bool:
                        database = store / "index.sqlite3"
                        if not database.exists():
                            return False
                        with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as db:
                            turns = db.execute("SELECT state, transcript_path FROM turn_ingestion").fetchall()
                            if not turns or turns[0][0] != "indexed":
                                return False
                            assert len(turns) == 1, turns
                            assert Path(turns[0][1]).is_relative_to(settings)
                            assert db.execute("SELECT state FROM staged_user_prompts").fetchall() == [("reconciled",)]
                            assert db.execute("SELECT COUNT(*) FROM turn_chunks WHERE instr(text, ?) > 0",
                                              (CLAUDE_FIXTURE_ANSWER,)).fetchone() == (1,)
                        assert not (store / "hook-errors.jsonl").exists()
                        return True

                    accepted.wait(indexed, "Indexing exactly one trusted conversation", timeout=60)
                finally:
                    accepted.close()

                reopened = Terminal(command, project, environment, reports / "claude-trust-reopened.txt")
                try:
                    reopened.wait(lambda: chat_ready(reopened), "Reopening the trusted workspace")
                    assert "Quick safety check" not in reopened.display
                    assert workspace_trusted()
                finally:
                    reopened.close()
            finally:
                server.shutdown()
                serving.join(timeout=5)
        (reports / "claude-trust.json").write_text(json.dumps({
            "platform": sys.platform, "refused_before_model_and_index": True,
            "accepted_exactly_one_turn": True, "trust_persists_on_reopen": True,
        }, indent=2), encoding="utf-8")
        print("PASS Claude native trust refusal, acceptance, indexed turn and relaunch", flush=True)


def main() -> None:
    reports = Path(os.environ.get("CONTEXT_SAVER_TEST_REPORTS", tempfile.mkdtemp(prefix="context-saver-trust-reports-")))
    reports.mkdir(parents=True, exist_ok=True)
    verify_claude_trust(reports)
    subprocess.run([sys.executable, str(Path(__file__).with_name("native_codex_trust.py"))], check=True, timeout=420)


if __name__ == "__main__":
    main()
