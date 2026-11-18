"""Locate shipped runtime modules from tests without reading host profiles."""

from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "thread-tree"
SCRIPTS_ROOT = PACKAGE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
