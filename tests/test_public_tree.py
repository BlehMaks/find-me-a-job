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

    def test_service_contact_is_exact_and_page_scoped(self):
        address = guard.PUBLIC_SERVICE_CONTACT.encode()
        for path in guard.PUBLIC_CONTACT_PATHS:
            self.assertEqual([], guard.inspect_blob(path, "100644", address, {path}))
            for other in (b"other@" + b"gmail.com", b"prefix." + address, address + b".test"):
                self.assertTrue(guard.inspect_blob(path, "100644", other, {path}))
        self.assertTrue(guard.inspect_blob("fmj/store.py", "100644", address, {"fmj/store.py"}))

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

    def test_history_catches_removed_marker_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            def git(*args):
                subprocess.run(["git", "-C", temp, *args], check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.name", "Synthetic Maintainer")
            git("config", "user.email", "maintainer@example.invalid")
            readme = Path(temp) / "README.md"
            readme.write_text("candidate@" + "mail.test")
            git("add", "README.md")
            git("commit", "-qm", "fixture")
            readme.write_text("candidate@example.org")
            git("add", "README.md")
            git("commit", "-qm", "replace fixture")
            result = subprocess.run(["python3", str(ROOT / "scripts/check_public_tree.py"), "--history"],
                                    cwd=temp, capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertNotIn("mail.test", result.stderr)

    def test_manifest_cannot_authorize_private_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(["git", "init", "-q", temp], check=True)
            (Path(temp) / ".public-files.json").write_text('["private/person.json"]')
            subprocess.run(["git", "-C", temp, "add", ".public-files.json"], check=True)
            result = subprocess.run(["python3", str(ROOT / "scripts/check_public_tree.py")],
                                    cwd=temp, capture_output=True, text=True)
            self.assertEqual(1, result.returncode)


if __name__ == "__main__":
    unittest.main()
