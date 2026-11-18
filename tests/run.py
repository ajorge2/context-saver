"""Run the portable regression suite with isolated synthetic data."""

from pathlib import Path
import os
import sys
import tempfile
import unittest

import _support

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="context-saver-test-profile-") as directory:
        root = Path(directory)
        for name in ("profile", "codex", "claude", "context-data"):
            (root / name).mkdir()
        os.environ.update(
            THREAD_HISTORY_TREE_DATA=str(root / "context-data"),
            CODEX_HOME=str(root / "codex"),
            CLAUDE_CONFIG_DIR=str(root / "claude"),
            PYTHONDONTWRITEBYTECODE="1",
            UV_PYTHON="3.12",
        )
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern="test_*.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(not result.wasSuccessful())
