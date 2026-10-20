import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fmj.workspace import (WorkspaceError, WorkspaceBusy, atomic_write_json,
                           create_workspace, load_workspace, locked_workspace, workspace_path)


def hold_lock(path, ready):
    with locked_workspace(path):
        ready.set()
        import time
        time.sleep(20)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.root = self.base / "private"

    def test_reject_overlap_and_alias(self):
        for path in (self.source, self.source / "private", self.base):
            with self.assertRaises(WorkspaceError):
                create_workspace(path, source_root=self.source)
        alias = self.base / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(WorkspaceError):
            create_workspace(alias / "private", source_root=self.source)

    def test_permissions_and_no_overwrite(self):
        config = create_workspace(self.root, source_root=self.source)
        self.assertEqual(load_workspace(self.root), config)
        if os.name != "nt":
            self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.root / "workspace.json").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(WorkspaceError):
            create_workspace(self.root, source_root=self.source)

    def test_failed_replace_preserves_snapshot(self):
        path = self.base / "snapshot.json"
        atomic_write_json(path, {"version": 1})
        with patch("fmj.workspace.os.replace", side_effect=OSError("interruption")):
            with self.assertRaises(OSError):
                atomic_write_json(path, {"version": 2})
        self.assertEqual(json.loads(path.read_text()), {"version": 1})
        self.assertEqual(list(self.base.glob(".write-*")), [])

    def test_single_writer_released_after_process_crash(self):
        create_workspace(self.root, source_root=self.source)
        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        process = ctx.Process(target=hold_lock, args=(str(self.root), ready))
        process.start()
        try:
            self.assertTrue(ready.wait(10))
            with self.assertRaises(WorkspaceBusy):
                with locked_workspace(self.root):
                    pass
        finally:
            process.terminate()
            process.join(10)
        with locked_workspace(self.root):
            with locked_workspace(self.root):
                pass

    def test_private_subtree_alias_rejected(self):
        create_workspace(self.root, source_root=self.source)
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "alias").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(WorkspaceError):
            workspace_path(self.root, "alias", "secret.json")
        with self.assertRaises(WorkspaceError):
            workspace_path(self.root, "..", "source")


if __name__ == "__main__":
    unittest.main()
