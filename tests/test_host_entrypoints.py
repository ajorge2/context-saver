"""Respect the installed npm package's native or JavaScript entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from native_hosts import npm_entrypoint


class HostEntrypointTests(unittest.TestCase):
    def fixture(self, host: str, bin_value) -> tuple[Path, Path]:
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="synthetic-npm-host-"))
        prefix = Path(directory)
        package = prefix / "node_modules" / ("@openai/codex" if host == "codex" else "@anthropic-ai/claude-code")
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"bin": bin_value}), encoding="utf-8")
        target = bin_value[host] if isinstance(bin_value, dict) else bin_value
        entry = package / target
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_bytes(b"synthetic executable fixture")
        return prefix / f"{host}.cmd", entry

    def test_native_claude_binary_runs_directly(self) -> None:
        shim, entry = self.fixture("claude", {"claude": "bin/claude.exe"})
        self.assertEqual(npm_entrypoint("claude", shim), [str(entry)])

    def test_codex_javascript_bin_runs_with_node(self) -> None:
        shim, entry = self.fixture("codex", {"codex": "bin/codex.js"})
        with patch("native_hosts.shutil.which", return_value="synthetic-node.exe"):
            self.assertEqual(npm_entrypoint("codex", shim), ["synthetic-node.exe", str(entry)])

    def test_single_string_bin_is_respected(self) -> None:
        shim, entry = self.fixture("claude", "bin/claude.exe")
        self.assertEqual(npm_entrypoint("claude", shim), [str(entry)])


if __name__ == "__main__":
    unittest.main()
