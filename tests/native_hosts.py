"""Install real coding hosts into disposable profiles using synthetic chats only."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from _support import PACKAGE_ROOT
from thread_tree_scope import save_scope_config


CLAUDE_FIXTURE_ANSWER = "The synthetic integration answer is AZURE-947."


def npm_entrypoint(host: str, shim: Path) -> list[str]:
    package_name = "@openai/codex" if host == "codex" else "@anthropic-ai/claude-code"
    package = shim.parent / "node_modules" / package_name
    manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
    declared_bin = manifest["bin"]
    entry = package / (declared_bin[host] if isinstance(declared_bin, dict) else declared_bin)
    if not entry.is_file():
        raise RuntimeError(f"Missing declared npm host entrypoint {entry}")
    if entry.suffix.lower() in (".js", ".mjs", ".cjs"):
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Missing Node.js for the declared coding host entrypoint")
        return [node, str(entry)]
    return [str(entry)]


def host_command(host: str) -> list[str]:
    executable = shutil.which(host)
    if executable is None:
        raise RuntimeError(f"Missing native test host {host}")
    if os.name == "nt" and Path(executable).suffix.lower() in (".cmd", ".ps1"):
        return npm_entrypoint(host, Path(executable))
    return [executable]


def isolated_environment(root: Path) -> dict[str, str]:
    root = root.resolve()
    paths = {name: root / name for name in ("profile", "codex", "claude", "security", "context-data", "cache")}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for name in ("CODEX_SQLITE_HOME", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                 "CODEX_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        environment.pop(name, None)
    environment.update(
        CODEX_HOME=str(paths["codex"]),
        CLAUDE_CONFIG_DIR=str(paths["claude"]),
        CLAUDE_SECURESTORAGE_CONFIG_DIR=str(paths["security"]),
        CODEX_STATE_DB=str(root / "isolated-state.sqlite"),
        THREAD_HISTORY_TREE_DATA=str(paths["context-data"]),
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        CLAUDE_CODE_DISABLE_AUTO_MEMORY="1",
        DO_NOT_TRACK="1",
        DISABLE_AUTOUPDATER="1",
        GIT_TERMINAL_PROMPT="0",
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return environment


def run_host(host: str, *args: str, project: Path, env: dict[str, str], timeout: int = 120) -> str:
    command = host_command(host) + (["--no-daemon"] if host == "codex" else []) + list(args)
    result = subprocess.run(command, cwd=project, env=env, capture_output=True,
                            encoding="utf-8", timeout=timeout, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise AssertionError(f"{host} {args!r} failed ({result.returncode})\n{result.stdout}\n{result.stderr}")
    return result.stdout


def install_marketplace(root: Path, project: Path, env: dict[str, str], host: str) -> Path:
    """Install the current package through the host's real marketplace commands."""
    market = root / f"{host} marketplace é & spaces"
    source = market / "plugins" / "thread-tree"
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PACKAGE_ROOT, source, ignore=shutil.ignore_patterns("__pycache__"))
    marketplace_id = f"context-saver-{host}-fixture"
    if host == "codex":
        metadata = market / ".agents" / "plugins"
        catalog = {"name": marketplace_id, "plugins": [{
            "name": "thread-tree", "source": {"source": "local", "path": "./plugins/thread-tree"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        }]}
    else:
        metadata = market / ".claude-plugin"
        catalog = {"name": marketplace_id, "owner": {"name": "Synthetic platform test"},
                   "plugins": [{"name": "thread-tree", "source": "./plugins/thread-tree"}]}
    metadata.mkdir(parents=True)
    (metadata / "marketplace.json").write_text(json.dumps(catalog), encoding="utf-8")
    run_host(host, "plugin", "marketplace", "add", str(market), "--json", project=project, env=env)
    command = "add" if host == "codex" else "install"
    run_host(host, "plugin", command, f"thread-tree@{marketplace_id}", "--json", project=project, env=env)
    version = json.loads((source / f".{host}-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    profile = Path(env["CODEX_HOME" if host == "codex" else "CLAUDE_CONFIG_DIR"])
    installed = profile / "plugins" / "cache" / marketplace_id / "thread-tree" / version
    assert (installed / f".{host}-plugin" / "plugin.json").is_file(), installed
    return installed


class ClaudeFixtureAPI(BaseHTTPRequestHandler):
    """Respond to the real CLI on loopback with a predetermined synthetic answer."""

    requests_seen = 0

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests_seen += 1
        path = urlsplit(self.path).path
        if path == "/v1/messages" and request.get("stream"):
            events = [
                ("message_start", {"message": {
                    "id": "msg_fixture", "type": "message", "role": "assistant",
                    "model": "claude-sonnet-4-5", "content": [], "stop_reason": None,
                    "stop_sequence": None, "usage": {"input_tokens": 25, "output_tokens": 0},
                }}),
                ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": CLAUDE_FIXTURE_ANSWER}}),
                ("content_block_stop", {"index": 0}),
                ("message_delta", {"delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 11}}),
                ("message_stop", {}),
            ]
            body = "".join(f"event: {name}\ndata: {json.dumps({'type': name, **fields})}\n\n"
                           for name, fields in events).encode()
            content_type = "text/event-stream"
        elif path == "/v1/messages/count_tokens":
            body = b'{"input_tokens":25}'
            content_type = "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


async def verify_installed_mcp(installed: Path, project: Path, env: dict[str, str], host: str) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = json.loads((installed / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["thread-tree"]
    args = [arg.replace("${CLAUDE_PLUGIN_ROOT}", str(installed)) for arg in server["args"]] if host == "claude" else server["args"]
    environment = {**env, "CLAUDE_PLUGIN_ROOT": str(installed), "PLUGIN_ROOT": str(installed)}
    parameters = StdioServerParameters(command=server["command"], args=args,
                                      cwd=str(installed if host == "codex" else project), env=environment)
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {"prepare_current_chat", "search_project_history"}
            result = await session.call_tool("search_project_history", {"query": "synthetic absent marker", "project_root": str(project)})
            assert result.isError, result
            assert any("not configured" in getattr(item, "text", "") for item in result.content)


def verify_claude_turn(project: Path, root: Path, env: dict[str, str]) -> None:
    store = Path(env["THREAD_HISTORY_TREE_DATA"])
    save_scope_config(store, {"configured": True, "projects": [{"path": str(project), "includeNewChats": True}]})
    (store / "config.json").write_text('{"embedding_provider":"disabled"}', encoding="utf-8")
    with ThreadingHTTPServer(("127.0.0.1", 0), ClaudeFixtureAPI) as server:
        serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        serving.start()
        environment = {**env, "ANTHROPIC_API_KEY": "synthetic-context-saver-testing",
                       "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}"}
        try:
            output = run_host("claude", "-p", "Return the synthetic integration answer.",
                              "--model", "sonnet", "--output-format", "stream-json", "--verbose",
                              "--include-hook-events", "--tools", "", project=project, env=environment)
        finally:
            server.shutdown()
            serving.join(timeout=5)
    (root / "claude-output.jsonl").write_text(output, encoding="utf-8")
    events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    hooks = [(event["hook_event"], event.get("outcome"))
             for event in events if event.get("subtype") == "hook_response"]
    assert hooks == [("UserPromptSubmit", "success"), ("Stop", "success")], hooks
    assert any(event.get("result") == CLAUDE_FIXTURE_ANSWER for event in events), events
    assert not (store / "hook-errors.jsonl").exists()
    with closing(sqlite3.connect(store / "index.sqlite3")) as db:
        deadline = time.monotonic() + 30
        while True:
            turns = db.execute("SELECT state, transcript_path FROM turn_ingestion").fetchall()
            if any(state == "indexed" for state, _ in turns) or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        assert len(turns) == 1 and turns[0][0] == "indexed", turns
        assert Path(turns[0][1]).resolve().is_relative_to(Path(env["CLAUDE_CONFIG_DIR"]).resolve()), turns
        assert db.execute("SELECT state FROM staged_user_prompts").fetchall() == [("reconciled",)]
        assert db.execute("SELECT 1 FROM turn_chunks WHERE instr(text, ?) > 0", (CLAUDE_FIXTURE_ANSWER,)).fetchone()


def main() -> None:
    reports = Path(os.environ.get("CONTEXT_SAVER_TEST_REPORTS", tempfile.mkdtemp(prefix="context-saver-reports-")))
    reports.mkdir(parents=True, exist_ok=True)
    outcomes = {}
    for host in ("codex", "claude"):
        with tempfile.TemporaryDirectory(prefix=f"context-saver-native-{host}-") as directory:
            root = Path(directory)
            project = root / "Synthetic Project é & spaces"
            project.mkdir()
            env = isolated_environment(root)
            installed = install_marketplace(root, project, env, host)
            asyncio.run(asyncio.wait_for(verify_installed_mcp(installed, project, env, host), timeout=120))
            if host == "claude":
                verify_claude_turn(project, root, env)
            outcomes[host] = {"installed": True, "mcp_connected": True, "completed_turn": host == "claude"}
            print(f"{host}: native install and MCP passed", flush=True)
    (reports / "native-hosts.json").write_text(json.dumps(outcomes, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
