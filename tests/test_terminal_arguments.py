"""Keep Windows terminal arguments intact across ConPTY process creation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from terminal import Terminal


class WindowsTerminalArgumentsTests(unittest.TestCase):
    def test_windows_project_argument_reaches_pty_without_an_extra_quoting_pass(self) -> None:
        project_argument = r"C:\Users\Test User\Synthetic Project é Ω & spaces"
        command = [r"C:\Program Files\nodejs\node.exe", r"C:\npm\prefix\codex.js",
                   "--no-daemon", "--no-alt-screen", "-C", project_argument]
        process = Mock()
        process.read.side_effect = EOFError
        process.isalive.return_value = False
        process_type = Mock()
        process_type.spawn.return_value = process
        with tempfile.TemporaryDirectory(prefix="synthetic-terminal-argv-") as directory, \
             patch.dict("sys.modules", {"winpty": SimpleNamespace(PtyProcess=process_type)}), \
             patch("terminal.os", SimpleNamespace(name="nt")):
            root = Path(directory)
            terminal = Terminal(command, root, {"SYNTHETIC_FIXTURE": "1"}, root / "terminal.log")
            terminal.reader.join(timeout=2)
            terminal.close()
            arguments, = process_type.spawn.call_args.args
            self.assertIsInstance(arguments, list)
            self.assertEqual(arguments, command)
            self.assertEqual(arguments[-1], project_argument)


if __name__ == "__main__":
    unittest.main()
