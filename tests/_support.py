"""Locate shipped runtime modules from tests without reading host profiles."""

from pathlib import Path
import queue
import sys
import threading

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "thread-tree"
SCRIPTS_ROOT = PACKAGE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


def process_line(process, timeout: float = 15) -> str:
    """Bound readiness waits so a broken child yields a useful test failure."""
    result = queue.Queue()
    reader = threading.Thread(target=lambda: result.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        return result.get(timeout=timeout).strip()
    except queue.Empty as error:
        raise AssertionError(f"Child {process.pid} produced no readiness line within {timeout}s; exit={process.poll()}") from error
