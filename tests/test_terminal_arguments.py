"""Keep Windows terminal arguments intact across ConPTY process creation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import subprocess
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

    def test_exit_wait_observes_delayed_native_process_termination(self) -> None:
        terminal = Terminal.__new__(Terminal)
        terminal.read = Mock()
        terminal.alive = Mock(side_effect=[True, True, False])
        with patch("terminal.time.sleep") as sleep:
            self.assertTrue(terminal._wait_for_exit(10))
        self.assertEqual(sleep.call_count, 2)

    def test_forced_windows_cleanup_waits_and_records_the_taskkill_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-terminal-cleanup-") as directory:
            terminal = Terminal.__new__(Terminal)
            terminal.windows = True
            terminal.process = Mock(pid=1360)
            terminal.log = Path(directory) / "terminal.txt"
            terminal.alive = Mock(return_value=True)
            terminal.read = Mock()
            terminal.send = Mock()
            terminal._wait_for_exit = Mock(side_effect=[False, True])
            result = subprocess.CompletedProcess(["taskkill"], 0, "SUCCESS: terminated\n", "")
            with patch("terminal.subprocess.run", return_value=result) as run:
                terminal.close(entered=False)
            self.assertEqual(terminal._wait_for_exit.call_args_list[1].args, (10,))
            self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "1360", "/T", "/F"])
            diagnostic = json.loads(terminal.log.with_suffix(".cleanup.json").read_text(encoding="utf-8"))
            self.assertTrue(diagnostic["observed_exit"])
            self.assertEqual(diagnostic["returncode"], 0)
            self.assertIn("terminated", diagnostic["stdout"])
            terminal.process.close.assert_called_once_with(force=True)

    def test_forced_windows_cleanup_fails_if_the_process_remains_alive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-terminal-still-alive-") as directory:
            terminal = Terminal.__new__(Terminal)
            terminal.windows = True
            terminal.process = Mock(pid=1360)
            terminal.log = Path(directory) / "terminal.txt"
            terminal.alive = Mock(return_value=True)
            terminal.read = Mock()
            terminal.send = Mock()
            terminal._wait_for_exit = Mock(return_value=False)
            result = subprocess.CompletedProcess(["taskkill"], 1, "", "Access denied\n")
            with patch("terminal.subprocess.run", return_value=result):
                with self.assertRaisesRegex(AssertionError, "survived taskkill"):
                    terminal.close(entered=False)
            diagnostic = json.loads(terminal.log.with_suffix(".cleanup.json").read_text(encoding="utf-8"))
            self.assertFalse(diagnostic["observed_exit"])
            self.assertEqual(diagnostic["returncode"], 1)
            self.assertEqual(diagnostic["stderr"], "Access denied\n")
            terminal.process.close.assert_called_once_with(force=True)


if __name__ == "__main__":
    unittest.main()
