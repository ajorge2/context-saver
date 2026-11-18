"""Run the portable regression suite with isolated synthetic data."""

from pathlib import Path
import faulthandler
import json
import os
import platform
import sys
import tempfile
import unittest

import _support

if __name__ == "__main__":
    faulthandler.dump_traceback_later(60, repeat=True)
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
        report_path = os.environ.get("CONTEXT_SAVER_TEST_REPORTS")
        if report_path:
            reports = Path(report_path)
            reports.mkdir(parents=True, exist_ok=True)
            summary = {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "tests": result.testsRun,
                "failures": [(str(case), error) for case, error in result.failures],
                "errors": [(str(case), error) for case, error in result.errors],
                "skipped": [(str(case), reason) for case, reason in result.skipped],
                "passed": result.wasSuccessful(),
            }
            (reports / "regression.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        sys.exit(not result.wasSuccessful())
