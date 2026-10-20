"""Synthetic checks; no candidate records or live credentials."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("guard", ROOT / "scripts/check_public_tree.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class PublicTreeTest(unittest.TestCase):
    def test_safe_examples(self):
        self.assertEqual([], guard.inspect_blob("README.md", "100644", b"candidate@example.com"))

    def test_sensitive_content(self):
        samples = [
            b"candidate@" + b"mail.test", b"/" + b"Users/example/private",
            b"C:" + b"\\Users\\example\\private", b"ghp_" + b"x" * 30,
            b"https://www.linkedin.com/" + b"in/private-example", b"\x00",
        ]
        for sample in samples:
            with self.subTest(sample_type=samples.index(sample)):
                self.assertTrue(guard.inspect_blob("README.md", "100644", sample))

    def test_paths_links_and_binary(self):
        for path, mode, blob in [
            ("plans/discovery.md", "100644", b"notes"),
            ("README.md", "120000", b"external"),
            ("README.md", "100644", b"\xff"),
        ]:
            self.assertTrue(guard.inspect_blob(path, mode, blob))

    def test_index_not_working_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(["git", "init", "-q", temp], check=True)
            readme = Path(temp) / "README.md"
            readme.write_text("candidate@" + "mail.test")
            subprocess.run(["git", "-C", temp, "add", "README.md"], check=True)
            readme.write_text("candidate@example.org")
            result = subprocess.run(
                ["python3", str(ROOT / "scripts/check_public_tree.py")],
                cwd=temp, capture_output=True, text=True,
            )
            self.assertEqual(1, result.returncode)
            self.assertNotIn("mail.test", result.stderr)


if __name__ == "__main__":
    unittest.main()
