#!/usr/bin/env python3
"""Inspect staged blobs without displaying possibly sensitive content."""

import re
import subprocess
import sys

PUBLIC_FILES = {
    ".gitignore", "README.md", ".githooks/pre-commit",
    "scripts/check_public_tree.py", "tests/test_public_tree.py",
}
PATTERNS = {
    "private key": r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----",
    "access token": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,})\b",
    "personal home path": r"(?:/(?:Users|home)/[^\s/]+|[A-Z]:[\\/]Users[\\/][^\s\\/]+)",
    "personal profile URL": r"linkedin\.com/in/(?!example(?:[-/\s]|$)|synthetic-)[\w%-]+",
}
EMAIL = re.compile(r"[\w.+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def inspect_blob(path, mode, blob):
    issues = []
    if path not in PUBLIC_FILES:
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


def main():
    try:
        root = git("rev-parse", "--show-toplevel").decode().strip()
        entries = git("-C", root, "ls-files", "--stage", "-z").split(b"\x00")
        failures = []
        count = 0
        for entry in filter(None, entries):
            meta, raw_path = entry.split(b"\t", 1)
            mode, oid, stage = meta.decode().split()
            count += 1
            if stage != "0":
                failures.append(f"index entry {count}: unresolved merge")
                continue
            blob = git("-C", root, "cat-file", "blob", oid)
            issues = inspect_blob(raw_path.decode("utf-8"), mode, blob)
            if issues:
                failures.append(f"index entry {count}: {', '.join(issues)}")
        if failures:
            print("Public-content check blocked the commit:", file=sys.stderr)
            print("\n".join(failures), file=sys.stderr)
            return 1
        print(f"Public-content check passed for {count} staged files; manual review still required.")
        return 0
    except (subprocess.CalledProcessError, UnicodeError, ValueError, OSError):
        print("Public-content check could not inspect the index; commit blocked.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
