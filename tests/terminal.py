"""Drive actual host trust dialogs in disposable native terminal sessions."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time


ESCAPES = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[()][0-9AB]|\x1b[78]")


class Terminal:
    def __init__(self, command: list[str], project: Path, environment: dict[str, str], log: Path):
        self.log = log
        self.output = ""
        self.chunks: queue.Queue[str | None] = queue.Queue()
        self.windows = os.name == "nt"
        if self.windows:
            from winpty import PtyProcess

            self.process = PtyProcess.spawn(
                subprocess.list2cmdline(command), cwd=str(project), env=environment,
                dimensions=(45, 125),
            )
        else:
            import fcntl
            import pty
            import struct
            import termios

            self.master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 125, 0, 0))
            try:
                self.process = subprocess.Popen(
                    [sys.executable, "-c",
                     "import fcntl,os,sys,termios;fcntl.ioctl(0,termios.TIOCSCTTY,0);"
                     "os.tcsetpgrp(0,os.getpgrp());os.execv(sys.argv[1],sys.argv[1:])",
                     *command],
                    cwd=project, env=environment, stdin=slave, stdout=slave, stderr=slave,
                    start_new_session=True,
                )
            finally:
                os.close(slave)
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()

    def _read_output(self) -> None:
        try:
            while True:
                chunk = self.process.read(65536) if self.windows else os.read(self.master, 65536).decode("utf-8", errors="replace")
                if not chunk:
                    break
                self.chunks.put(chunk)
        except (EOFError, OSError):
            pass
        finally:
            self.chunks.put(None)

    @property
    def display(self) -> str:
        self.read()
        return ESCAPES.sub("", self.output)

    def read(self) -> None:
        while True:
            try:
                chunk = self.chunks.get_nowait()
            except queue.Empty:
                return
            if chunk is None:
                return
            previous = self.output[-8:]
            self.output += chunk
            joined = previous + chunk
            for request, reply in (("\x1b[c", "\x1b[?1;2c"), ("\x1b[6n", "\x1b[1;1R")):
                if any(match.end() > len(previous) for match in re.finditer(re.escape(request), joined)):
                    self.send(reply)
            self.log.parent.mkdir(parents=True, exist_ok=True)
            self.log.write_text(ESCAPES.sub("", self.output), encoding="utf-8")

    def send(self, text: str) -> None:
        if self.windows:
            self.process.write(text)
        else:
            os.write(self.master, text.encode("utf-8"))

    def alive(self) -> bool:
        return self.process.isalive() if self.windows else self.process.poll() is None

    def wait(self, condition, description: str, timeout: float = 45) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.read()
            if condition():
                return
            if not self.alive():
                break
            time.sleep(0.05)
        self.read()
        if not condition():
            raise AssertionError(f"{description} failed. Terminal log {self.log}\n{self.display[-4000:]}")

    def close(self, *, entered: bool = True) -> None:
        try:
            if self.alive():
                self.send("/exit\r" if entered else "\x1b")
                deadline = time.monotonic() + 2
                while self.alive() and time.monotonic() < deadline:
                    self.read()
                    time.sleep(0.05)
            if self.alive():
                if self.windows:
                    subprocess.run(
                        ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10,
                    )
                    if self.alive():
                        raise AssertionError(f"Native terminal process {self.process.pid} did not exit")
                else:
                    os.killpg(self.process.pid, signal.SIGKILL)
        finally:
            if self.windows:
                with suppress(PermissionError, ProcessLookupError):
                    self.process.close(force=True)
            else:
                self.process.wait(timeout=8)
                os.close(self.master)
            self.read()
