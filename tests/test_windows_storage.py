"""Native storage regressions for process ownership and Windows file sharing."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "thread-tree" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import thread_tree_state as state
import thread_tree_vector_index as vectors


class WindowsStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="context-saver-storage-")))
        self.children: list[subprocess.Popen] = []
        self.addCleanup(self.close_children)

    def close_children(self) -> None:
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        vectors._INDEX_CACHE.clear()

    def child(self, code: str, *arguments: str) -> subprocess.Popen:
        environment = dict(os.environ, PYTHONPATH=str(SCRIPTS), PYTHONUTF8="1")
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", code, *arguments],
            env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        self.children.append(child)
        return child

    def held_lock(self) -> subprocess.Popen:
        child = self.child(
            "from pathlib import Path; import sys; "
            "from thread_tree_state import exclusive_process_lock; "
            "lock=exclusive_process_lock(Path(sys.argv[1])); lock.__enter__(); "
            "print('owned', flush=True); sys.stdin.readline(); lock.__exit__(None,None,None)",
            str(self.root / "ownership.lock"),
        )
        self.assertEqual(child.stdout.readline().strip(), "owned")
        return child

    def test_live_owner_excludes_competitor_and_death_releases_lock(self) -> None:
        child = self.held_lock()
        with self.assertRaises(BlockingIOError):
            with state.exclusive_process_lock(self.root / "ownership.lock", blocking=False):
                self.fail("another process owned this lock")
        child.kill()
        child.wait(timeout=5)
        with state.exclusive_process_lock(self.root / "ownership.lock", blocking=False):
            pass

    def test_windows_blocking_lock_retries_contention_and_preserves_other_errors(self) -> None:
        calls = [PermissionError(errno.EACCES, "owned"), BlockingIOError(errno.EAGAIN, "owned"), None]
        fake = SimpleNamespace(LK_NBLCK=2)

        def acquire(_descriptor: int, mode: int, length: int) -> None:
            self.assertEqual((mode, length), (2, 1))
            outcome = calls.pop(0)
            if outcome is not None:
                raise outcome

        fake.locking = acquire
        with patch.object(state, "os", SimpleNamespace(name="nt")), \
             patch.dict(sys.modules, {"msvcrt": fake}), \
             patch.object(state.time, "sleep") as sleep:
            with state.exclusive_process_lock(self.root / "retry.lock"):
                pass
            self.assertEqual(sleep.call_count, 2)
            calls[:] = [OSError(errno.EIO, "storage failure")]
            with self.assertRaises(OSError) as error:
                with state.exclusive_process_lock(self.root / "retry.lock"):
                    self.fail("a genuine I/O failure must propagate")
            self.assertEqual(error.exception.errno, errno.EIO)

    @unittest.skipUnless(os.name == "nt", "exercises the Windows CRT contention deadline")
    def test_windows_blocking_lock_outlives_the_crt_retry_deadline(self) -> None:
        owner = self.held_lock()
        timer = threading.Timer(11.5, lambda: owner.communicate(input="release\n", timeout=5))
        timer.start()
        self.addCleanup(timer.join)
        started = time.monotonic()
        with state.exclusive_process_lock(self.root / "ownership.lock"):
            self.assertGreater(time.monotonic() - started, 10)

    @unittest.skipUnless(vectors.available(), "requires the shipped native USearch dependency")
    def test_windows_restore_copies_under_the_project_publication_lock(self) -> None:
        import numpy as np

        index = vectors._new_index(2)
        index.add(np.asarray([1], dtype=np.uint64), np.asarray([[1, 0]], dtype=np.float32))
        vectors._publish(
            index, data_directory=self.root, project_id="project-fixture",
            model="fixture", dimension=2, indexed_through_seq=1, count=1,
        )
        numpy, index_class = vectors._imports()
        restore = index_class.restore

        def copy_index(path: str, *, view: bool):
            self.assertFalse(view)
            lock_name = state.stable_id("vector", "project-fixture")
            with self.assertRaises(BlockingIOError):
                with state.exclusive_process_lock(self.root / "maintenance-locks" / lock_name, blocking=False):
                    self.fail("restoring must exclude a publisher")
            return restore(path, view=view)

        with patch.object(vectors, "os", SimpleNamespace(name="nt")), \
             patch.object(vectors, "_imports", return_value=(numpy, SimpleNamespace(restore=copy_index))):
            hits, info = vectors.search(
                data_directory=self.root, project_id="project-fixture",
                model="fixture", vector=[1, 0], limit=1,
            )
        self.assertEqual(hits[0][0], 1)
        self.assertTrue(info["available"])

    @unittest.skipUnless(vectors.available(), "requires the shipped native USearch dependency")
    def test_cached_reader_allows_republish_and_invalidation_in_another_process(self) -> None:
        import numpy as np

        def publish(key: int) -> None:
            index = vectors._new_index(2)
            index.add(np.asarray([key], dtype=np.uint64), np.asarray([[1, 0]], dtype=np.float32))
            with vectors._write_lock(self.root, "project-fixture"):
                vectors._publish(
                    index, data_directory=self.root, project_id="project-fixture",
                    model="fixture", dimension=2, indexed_through_seq=key, count=1,
                )

        publish(1)
        reader = self.child(
            "from pathlib import Path; import sys; import thread_tree_vector_index as v; "
            "hits,info=v.search(data_directory=Path(sys.argv[1]),project_id='project-fixture',"
            "model='fixture',vector=[1,0],limit=1); assert hits[0][0]==1 and info['available']; "
            "print('cached',flush=True); sys.stdin.readline()",
            str(self.root),
        )
        self.assertEqual(reader.stdout.readline().strip(), "cached")
        publish(2)
        hits, info = vectors.search(
            data_directory=self.root, project_id="project-fixture",
            model="fixture", vector=[1, 0], limit=1,
        )
        self.assertEqual(hits[0][0], 2)
        self.assertTrue(info["available"])
        with sqlite3.connect(self.root / "fixture.sqlite3") as database:
            database.execute("CREATE TABLE index_shards(name TEXT, project_id TEXT)")
            vectors.invalidate_project_index(database, data_directory=self.root, project_id="project-fixture")
        self.assertFalse(vectors._index_path(self.root, "project-fixture").exists())
        self.assertFalse(vectors._metadata_path(self.root, "project-fixture").exists())
        self.assertIsNone(reader.poll(), "the reader must retain its loaded index while publication finishes")
        reader.communicate(input="done\n", timeout=5)
        self.assertEqual(reader.returncode, 0)


if __name__ == "__main__":
    unittest.main()
