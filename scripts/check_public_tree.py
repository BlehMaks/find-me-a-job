#!/usr/bin/env python3
"""Inspect staged blobs without displaying possibly sensitive content."""

import re
import argparse
import os
import json
from pathlib import PurePosixPath
import subprocess
import sys

PUBLIC_FILES = {
    ".gitignore", ".public-files.json", "README.md", ".githooks/pre-commit",
    "scripts/check_public_tree.py", "tests/test_public_tree.py",
}
PATTERNS = {
    "private key": r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----",
    "access token": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,})\b",
    "personal home path": r"(?:/(?:Users|home)/[^\s/]+|[A-Z]:[\\/]Users[\\/][^\s\\/]+)",
    "personal profile URL": r"linkedin\.com/in/(?!example(?:[-/\s]|$)|synthetic-)[\w%-]+",
}
EMAIL = re.compile(r"[\w.+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def inspect_blob(path, mode, blob, approved=None):
    issues = []
    if path not in (PUBLIC_FILES if approved is None else approved):
        issues.append("path is not approved public source")
    if mode not in {"100644", "100755"}:
        issues.append("links and submodules are not allowed")
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return issues + ["non-text content requires a separate publication policy"]
    if "\x00" in text:
        issues.append("binary content is not allowed")
    for label, pattern in PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(label)
    for match in EMAIL.finditer(text):
        domain = match.group(1).lower()
        if domain not in {"example.com", "example.org", "example.net"} and not domain.endswith(".invalid"):
            issues.append("non-synthetic email address")
            break
    return issues


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE)


def approved_paths():
    try:
        values = json.loads(git("show", ":.public-files.json"))
    except subprocess.CalledProcessError:
        return PUBLIC_FILES
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise ValueError("Invalid public manifest")
    blocked = {"..", ".git", ".specify", "private", "clients", "resume_system", "plans", "sessions", "secrets"}
    for value in values:
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or set(path.parts) & blocked or any(c in value for c in "*?\\\n\r"):
            raise ValueError("Unsafe public path")
    return set(values) | PUBLIC_FILES


def inspect_tree(ref, approved):
    failures = []
    entries = git("ls-tree", "-rz", ref).split(b"\x00")
    for count, entry in enumerate(filter(None, entries), 1):
        meta, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        if kind != "blob":
            failures.append(f"tree entry {count}: links or submodules are not allowed")
            continue
        issues = inspect_blob(raw_path.decode(), mode, git("cat-file", "blob", oid), approved)
        if issues:
            failures.append(f"tree entry {count}: {', '.join(issues)}")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also scan all reachable commits and email metadata")
    args = parser.parse_args()
    try:
        os.chdir(git("rev-parse", "--show-toplevel").decode().strip())
        approved = approved_paths()
        failures = []
        count = 0
        for entry in filter(None, git("ls-files", "--stage", "-z").split(b"\x00")):
            meta, raw_path = entry.split(b"\t", 1)
            mode, oid, stage = meta.decode().split()
            count += 1
            if stage != "0":
                failures.append(f"index entry {count}: unresolved merge")
                continue
            issues = inspect_blob(raw_path.decode(), mode, git("cat-file", "blob", oid), approved)
            if issues:
                failures.append(f"index entry {count}: {', '.join(issues)}")
        if args.history:
            for number, commit in enumerate(git("rev-list", "--all").decode().splitlines(), 1):
                failures.extend(f"commit {number}: {issue}" for issue in inspect_tree(commit, approved))
                for address in git("show", "-s", "--format=%ae%n%ce", commit).decode().splitlines():
                    domain = address.rsplit("@", 1)[-1].lower()
                    if domain not in {"example.com", "example.org", "example.net", "users.noreply.github.com"} and not domain.endswith(".invalid"):
                        failures.append(f"commit {number}: review public author/committer email")
        if failures:
            print("Public-content check blocked publication:\n" + "\n".join(failures), file=sys.stderr)
            return 1
        print(f"Public-content check passed for {count} staged files; manual review still required.")
        return 0
    except (subprocess.CalledProcessError, UnicodeError, ValueError, OSError):
        print("Public-content check could not inspect the tree; publication blocked.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
