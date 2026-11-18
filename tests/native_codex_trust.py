"""Review actual Codex hooks, exercise their trust gate and retain data on upgrade."""

from __future__ import annotations

import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from native_hosts import host_command, install_marketplace, isolated_environment, run_host
from terminal import Terminal
from thread_tree_scope import save_scope_config


ANSWER = "The synthetic integration answer is COBALT-314."
FIRST_PROMPT = "Retain the synthetic decision JADE-741 and return the fixture answer."


class CodexFixtureAPI(BaseHTTPRequestHandler):
    """Serve the Responses protocol on loopback, using fixed synthetic text."""

    requests_seen = 0

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:
        body = json.dumps({"object": "list", "data": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).requests_seen += 1
        response_id = f"resp_context_saver_{type(self).requests_seen}"
        message = {"id": f"msg_{response_id}", "type": "message", "role": "assistant",
                   "status": "completed", "content": [{"type": "output_text", "text": ANSWER,
                                                            "annotations": []}]}
        response = {"id": response_id, "object": "response", "created_at": int(time.time()),
                    "status": "completed", "model": "context-saver-fixture", "output": [message],
                    "usage": {"input_tokens": 25, "output_tokens": 11, "total_tokens": 36,
                              "input_tokens_details": {"cached_tokens": 0}}}
        events = [
            {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
            {"type": "response.output_item.added", "output_index": 0,
             "item": {**message, "status": "in_progress", "content": []}},
            {"type": "response.content_part.added", "item_id": message["id"], "output_index": 0,
             "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}},
            {"type": "response.output_text.delta", "item_id": message["id"], "output_index": 0,
             "content_index": 0, "delta": ANSWER},
            {"type": "response.output_text.done", "item_id": message["id"], "output_index": 0,
             "content_index": 0, "text": ANSWER},
            {"type": "response.content_part.done", "item_id": message["id"], "output_index": 0,
             "content_index": 0, "part": message["content"][0]},
            {"type": "response.output_item.done", "output_index": 0, "item": message},
            {"type": "response.completed", "response": response},
        ]
        body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def read_trusts(profile: Path) -> dict:
    return tomllib.loads((profile / "config.toml").read_text(encoding="utf-8")).get("hooks", {}).get("state", {})


def native_request(project: Path, environment: dict[str, str], method: str, params: dict, log: Path) -> dict:
    """Call the installed Codex API with this fixture's disposable profile."""
    with log.open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(host_command("codex") + ["--no-daemon", "app-server", "--stdio"],
                                   cwd=project, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=errors, encoding="utf-8")
        received: queue.Queue[dict] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    received.put(json.loads(line))
                except json.JSONDecodeError:
                    continue

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()

        def request(identifier: int, method: str, params: dict) -> dict:
            assert process.stdin is not None
            process.stdin.write(json.dumps({"id": identifier, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    message = received.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                if message.get("id") == identifier:
                    assert "error" not in message, message
                    return message["result"]
            raise AssertionError(f"Native Codex {method} timed out. See {log}")

        try:
            request(1, "initialize", {"clientInfo": {"name": "context-saver-native-test", "version": "1"},
                                      "capabilities": {"experimentalApi": True}})
            assert process.stdin is not None
            process.stdin.write(json.dumps({"method": "initialized"}) + "\n")
            process.stdin.flush()
            return request(2, method, params)
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            reader.join(timeout=3)


def list_hooks(project: Path, environment: dict[str, str], log: Path) -> list[dict]:
    """Read native status through the same API used by the /hooks browser."""
    result = native_request(project, environment, "hooks/list", {"cwds": [str(project)]}, log)
    assert len(result["data"]) == 1, result
    entry = result["data"][0]
    assert not entry["errors"], entry
    return entry["hooks"]


def approve_native_hook(project: Path, environment: dict[str, str], profile: Path, hook: dict, log: Path) -> None:
    """Approve one exact command through the native API used by Codex's UI."""
    assert hook["trustStatus"] in {"untrusted", "modified"}, hook
    before = read_trusts(profile)
    native_request(project, environment, "config/batchWrite", {
        "edits": [{"keyPath": "hooks.state", "value": {hook["key"]: {"trusted_hash": hook["currentHash"]}},
                   "mergeStrategy": "upsert"}],
        "reloadUserConfig": True,
    }, log)
    after = read_trusts(profile)
    assert after[hook["key"]]["trusted_hash"] == hook["currentHash"], after
    assert {key: value for key, value in after.items() if key != hook["key"]} == {
        key: value for key, value in before.items() if key != hook["key"]}, (before, after)


def wait_until(condition, description: str, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError(description)


def indexed_turns(store: Path) -> list[tuple]:
    database = store / "index.sqlite3"
    if not database.exists():
        return []
    with closing(sqlite3.connect(database)) as db:
        return db.execute("SELECT id, state, transcript_path FROM turn_ingestion ORDER BY created_at, id").fetchall()


def run_answer(project: Path, environment: dict[str, str], prompt: str, log: Path) -> None:
    output = run_host("codex", "exec", "--skip-git-repo-check", "--json", prompt,
                      project=project, env=environment, timeout=90)
    log.write_text(output, encoding="utf-8")
    assert ANSWER in output, output


def review_hooks(project: Path, environment: dict[str, str], profile: Path,
                 expected_count: int, log: Path) -> None:
    """Approve each selected command individually in Codex's actual /hooks UI."""
    command = host_command("codex") + ["--no-daemon", "--no-alt-screen", "-C", str(project)]
    for index in range(expected_count):
        terminal = Terminal(command, project, environment, log.with_stem(f"{log.stem}-{index + 1}"))
        try:
            terminal.wait(lambda: "Hooks need review" in terminal.display or "context-saver-fixture" in terminal.display,
                          "Displaying native Codex hook review or the initialized session")
            if "Hooks need review" in terminal.display:
                # Let the protected startup screen finish draining terminal
                # replies. Escape safely continues without granting trust.
                time.sleep(0.3)
                for _ in range(4):
                    if "context-saver-fixture" in terminal.display:
                        break
                    terminal.send("\x1b")
                    time.sleep(0.3)
            terminal.wait(lambda: "context-saver-fixture" in terminal.display,
                          "Finishing Codex session initialization")
            time.sleep(0.3)
            terminal.send("/hooks")
            time.sleep(0.15)
            terminal.send("\r")
            terminal.wait(lambda: "hooks need review before" in terminal.display or "hook needs review before" in terminal.display,
                          "Opening the /hooks event browser")
            before = read_trusts(profile)
            time.sleep(0.15)
            terminal.send("\r")
            terminal.wait(lambda: "review required" in terminal.display and "Trust" in terminal.display,
                          "Reviewing the selected hook command")
            terminal.send("t")
            terminal.wait(lambda: read_trusts(profile) != before, "Persisting one native hook approval")
            after = read_trusts(profile)
            assert len(after) == len(before) + 1, (before, after)
            assert all(after[key] == value for key, value in before.items()), (before, after)
            terminal.send("\x1b")
            time.sleep(0.15)
            terminal.send("\x1b")
        finally:
            terminal.close()


async def verify_retained_source(installed: Path, project: Path, environment: dict[str, str]) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = json.loads((installed / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["thread-tree"]
    parameters = StdioServerParameters(command=server["command"], args=server["args"], cwd=str(installed),
                                      env={**environment, "CLAUDE_PLUGIN_ROOT": str(installed)})
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool("search_project_history", {"query": "JADE-741", "project_root": str(project)})
            assert not result.isError, result
            payload = json.loads(next(block.text for block in result.content if getattr(block, "type", "") == "text"))
            evidence = payload["evidence"]
            assert evidence and any("JADE-741" in row["text"] for row in evidence), payload
            assert any(row.get("source", {}).get("verified") for row in evidence), payload
            return payload


def main() -> None:
    reports = Path(os.environ.get("CONTEXT_SAVER_TEST_REPORTS", tempfile.mkdtemp(prefix="context-saver-codex-reports-")))
    reports.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="context-saver-codex-trust-") as temporary:
        root = Path(temporary).resolve()
        project = root / "Synthetic Codex Project é & spaces"
        project.mkdir()
        environment = isolated_environment(root)
        environment.update(TERM="xterm-256color", LANG="C.UTF-8")
        profile = Path(environment["CODEX_HOME"])
        store = Path(environment["THREAD_HISTORY_TREE_DATA"])
        with ThreadingHTTPServer(("127.0.0.1", 0), CodexFixtureAPI) as server:
            serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            serving.start()
            (profile / "config.toml").write_text(
                'model = "context-saver-fixture"\nmodel_provider = "context-saver-fixture"\n'
                'approval_policy = "never"\nsandbox_mode = "danger-full-access"\ncheck_for_update_on_startup = false\n'
                '[model_providers.context-saver-fixture]\nname = "Synthetic loopback fixture"\n'
                f'base_url = "http://127.0.0.1:{server.server_port}/v1"\nwire_api = "responses"\n'
                'requires_openai_auth = false\nrequest_max_retries = 0\nstream_max_retries = 0\n'
                f'[projects.{json.dumps(str(project))}]\ntrust_level = "trusted"\n', encoding="utf-8")
            try:
                installed = install_marketplace(root, project, environment, "codex")
                hooks = list_hooks(project, environment, reports / "codex-inventory-new.log")
                assert len(hooks) == 3 and {row["trustStatus"] for row in hooks} == {"untrusted"}, hooks
                (reports / "codex-hooks-new.json").write_text(json.dumps(hooks, indent=2), encoding="utf-8")
                save_scope_config(store, {"configured": True, "projects": [{"path": str(project), "includeNewChats": True}]})
                (store / "config.json").write_text('{"embedding_provider":"disabled"}', encoding="utf-8")
                run_answer(project, environment, "Return a synthetic answer before hook approval.", reports / "codex-untrusted-turn.jsonl")
                assert not indexed_turns(store), indexed_turns(store)
                assert not read_trusts(profile)

                review_hooks(project, environment, profile, 1, reports / "codex-review-first.txt")
                remaining = list_hooks(project, environment, reports / "codex-inventory-after-ui.log")
                assert sum(row["trustStatus"] == "trusted" for row in remaining) == 1, remaining
                for hook in remaining:
                    if hook["trustStatus"] == "untrusted":
                        approve_native_hook(project, environment, profile, hook,
                                            reports / f"codex-approve-{hook['eventName']}.log")
                trusted = list_hooks(project, environment, reports / "codex-inventory-trusted.log")
                assert {row["trustStatus"] for row in trusted} == {"trusted"}, trusted
                run_answer(project, environment, FIRST_PROMPT, reports / "codex-trusted-turn.jsonl")
                wait_until(lambda: len(indexed_turns(store)) == 1 and indexed_turns(store)[0][1] == "indexed",
                           "The approved Codex turn did not index exactly once")
                original = indexed_turns(store)[0]
                assert Path(original[2]).is_relative_to(profile), original

                source = root / "codex marketplace é & spaces" / "plugins" / "thread-tree"
                manifest_path = source / ".codex-plugin/plugin.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                current = manifest["version"]
                major, minor, patch = current.split(".")
                upgraded = f"{major}.{minor}.{int(patch) + 1}"
                for name in (".codex-plugin", ".claude-plugin"):
                    path = source / name / "plugin.json"
                    metadata = json.loads(path.read_text(encoding="utf-8"))
                    metadata["version"] = upgraded
                    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
                runtime = source / "scripts/thread_tree.py"
                runtime.write_text(runtime.read_text(encoding="utf-8").replace(
                    f'PLUGIN_VERSION = "{current}"', f'PLUGIN_VERSION = "{upgraded}"'), encoding="utf-8")
                hook_path = source / "hooks/hooks.json"
                definitions = json.loads(hook_path.read_text(encoding="utf-8"))
                definitions["hooks"]["Stop"][0]["hooks"][0]["command"] += " context-saver-upgrade-fixture"
                hook_path.write_text(json.dumps(definitions, indent=2), encoding="utf-8")
                run_host("codex", "plugin", "add", "thread-tree@context-saver-codex-fixture", "--json",
                         project=project, env=environment)
                installed = installed.parent / upgraded
                assert (installed / ".codex-plugin/plugin.json").is_file(), installed
                changed = list_hooks(project, environment, reports / "codex-inventory-upgraded.log")
                assert {row["eventName"]: row["trustStatus"] for row in changed} == {
                    "preCompact": "trusted", "userPromptSubmit": "trusted", "stop": "modified"}, changed
                (reports / "codex-hooks-upgraded.json").write_text(json.dumps(changed, indent=2), encoding="utf-8")
                run_answer(project, environment, "Return a synthetic answer before approving the changed Stop hook.",
                           reports / "codex-modified-stop-turn.jsonl")
                assert indexed_turns(store) == [original], indexed_turns(store)

                modified, = [row for row in changed if row["trustStatus"] == "modified"]
                approve_native_hook(project, environment, profile, modified, reports / "codex-approve-upgrade.log")
                run_answer(project, environment, "Retain the synthetic follow-up decision UMBER-852.",
                           reports / "codex-upgraded-turn.jsonl")
                wait_until(lambda: len(indexed_turns(store)) == 2 and all(row[1] == "indexed" for row in indexed_turns(store)),
                           "The upgraded Codex turn did not index exactly once")
                assert original in indexed_turns(store)
                assert not (store / "hook-errors.jsonl").exists()
                evidence = asyncio.run(asyncio.wait_for(verify_retained_source(installed, project, environment), timeout=90))
                (reports / "codex-upgrade-retrieval.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            finally:
                server.shutdown()
                serving.join(timeout=5)
        (reports / "codex-trust.json").write_text(json.dumps({
            "platform": sys.platform, "untrusted_hooks_skipped": True, "individual_hook_approval": True,
            "first_approval_through_terminal": True, "remaining_approvals_through_native_api": True,
            "trusted_turn_indexed_once": True, "only_changed_hook_requires_review": True,
            "changed_hook_skipped_until_review": True, "upgraded_turn_indexed_once": True,
            "original_source_verified_after_upgrade": True,
        }, indent=2), encoding="utf-8")
        print("PASS Codex native hook review, skipped untrusted turns, upgrade and retained source", flush=True)


if __name__ == "__main__":
    main()
