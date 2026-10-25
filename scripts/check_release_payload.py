#!/usr/bin/env python3
"""Check product wheel/sdist members against reviewed public source and privacy rules.

No extraction or publication occurs. Dependency wheels are outside this product
archive policy. Passing does not replace manual rights/content review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import stat
import sys
import tarfile
import zipfile

try:
    from .check_public_tree import inspect_blob
except ImportError:
    from check_public_tree import inspect_blob

ROOT = Path(__file__).resolve().parents[1]
DIST = "find_me_a_job"
WHEEL_METADATA = {"METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD"}
EGG_METADATA = {"PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt"}
MAX_MEMBER_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_MEMBERS = 10000


def _parts(value):
    if not isinstance(value, str) or not value or any(c in value for c in "\\\x00\r\n"):
        raise ValueError("invalid archive path")
    value = value[:-1] if value.endswith("/") else value
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or value.startswith("/") or ":" in parts[0]:
        raise ValueError("unsafe archive path")
    return parts


def load_manifest(path):
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("public manifest must be a path list")
    blocked = {".git", ".specify", "private", "clients", "resume_system", "plans", "sessions", "secrets"}
    for value in values:
        parts = _parts(value)
        if set(parts) & blocked or any(c in value for c in "*?"):
            raise ValueError("unsafe public manifest entry")
    return set(values)


def required_payload(approved):
    return {"AGENTS.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "skills/humanizer/SKILL.md", "skills/humanizer/LICENSE",
            "fmj/__init__.py", "fmj/__main__.py"} | {path for path in approved if path.startswith(("schemas/", "templates/"))}


def _scan_generated(blob):
    # Generated metadata has an exact filename exception, never a content exception.
    return inspect_blob("generated-metadata", "100644", blob, {"generated-metadata"})


def _wheel_path(name, distribution, approved):
    parts = _parts(name)
    metadata_root = distribution + ".dist-info"
    data_root = distribution + ".data"
    if len(parts) == 2 and parts[0] == metadata_root and parts[1] in WHEEL_METADATA:
        return None
    if parts == [metadata_root, "licenses", "LICENSE"] and "LICENSE" in approved:
        return "LICENSE"
    if len(parts) > 4 and parts[:4] == [data_root, "data", "share", "find-me-a-job"]:
        mapped = "/".join(parts[4:])
    elif parts[0] == "fmj":
        mapped = "/".join(parts)
    else:
        raise ValueError("unexpected wheel member")
    if mapped not in approved:
        raise ValueError("member is not reviewed public source")
    return mapped


def _sdist_path(name, prefix, approved):
    parts = _parts(name)
    if parts[0] != prefix or len(parts) < 2:
        raise ValueError("unexpected source distribution prefix")
    relative = parts[1:]
    if len(relative) == 1 and relative[0] in {"PKG-INFO", "setup.cfg"}:
        return None
    if len(relative) == 2 and relative[0] == DIST + ".egg-info" and relative[1] in EGG_METADATA:
        return None
    mapped = "/".join(relative)
    if mapped not in approved:
        raise ValueError("member is not reviewed public source")
    return mapped


def inspect_archive(archive, approved=None, *, manifest=None):
    """Return safe diagnostics without echoing untrusted paths or file contents."""
    archive = Path(archive)
    if approved is None:
        approved = load_manifest(manifest or ROOT / ".public-files.json")
    approved = set(approved)
    for path in approved:
        _parts(path)
    failures, present, seen = [], set(), set()
    total = 0

    def inspect_member(number, name, blob, mode, mapper):
        nonlocal total
        if name in seen:
            failures.append(f"entry {number}: duplicate member")
        seen.add(name)
        total += len(blob)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("archive exceeds inspected size budget")
        mapped = mapper(name)
        if mapped is None:
            issues = _scan_generated(blob)
        else:
            issues = inspect_blob(mapped, mode, blob, approved)
            present.add(mapped)
        if issues:
            failures.append(f"entry {number}: " + ", ".join(issues))

    try:
        if archive.name.endswith(".whl"):
            match = re.fullmatch(r"(find_me_a_job-[A-Za-z0-9_.+!]+)-(?:[0-9][A-Za-z0-9_.]*-)?[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+\.whl", archive.name)
            if not match:
                raise ValueError("not a product wheel")
            distribution = match.group(1)
            mapper = lambda name: _wheel_path(name, distribution, approved)
            with zipfile.ZipFile(archive) as zipped:
                if len(zipped.infolist()) > MAX_MEMBERS:
                    raise ValueError("too many archive members")
                if zipped.comment:
                    # Comments are not needed in generated product wheels.
                    failures.extend("archive comment: " + issue for issue in _scan_generated(zipped.comment))
                    failures.append("archive comment: unreviewed metadata")
                for number, member in enumerate(zipped.infolist(), 1):
                    _parts(member.filename)
                    if member.orig_filename != member.filename:
                        raise ValueError("ambiguous original archive path")
                    filemode = member.external_attr >> 16
                    if filemode & 0o7000 or stat.S_ISLNK(filemode) or (stat.S_IFMT(filemode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
                        raise ValueError("archive links or special files are forbidden")
                    if member.comment or member.extra:
                        failures.extend(f"entry {number} metadata: " + issue for issue in _scan_generated(member.comment + member.extra))
                        failures.append(f"entry {number}: unreviewed extra metadata")
                    if member.flag_bits & 1:
                        raise ValueError("encrypted archive member")
                    if member.is_dir():
                        # Empty private directories are also outside the release.
                        prefix = member.filename.rstrip("/") + "/"
                        allowed_names = {distribution + ".dist-info/" + name for name in WHEEL_METADATA}
                        if "LICENSE" in approved:
                            allowed_names.add(distribution + ".dist-info/licenses/LICENSE")
                        allowed_names |= {distribution + ".data/data/share/find-me-a-job/" + path for path in approved}
                        allowed_names |= {path for path in approved if path.startswith("fmj/")}
                        if member.file_size != 0 or not any(name.startswith(prefix) for name in allowed_names):
                            raise ValueError("unexpected directory or hidden directory payload")
                        continue
                    if member.file_size > MAX_MEMBER_BYTES:
                        raise ValueError("archive member exceeds inspected size budget")
                    inspect_member(number, member.filename, zipped.read(member), "100755" if filemode & 0o111 else "100644", mapper)
        elif archive.name.endswith(".tar.gz"):
            prefix = archive.name[:-7]
            if not re.fullmatch(r"find[_-]me[_-]a[_-]job-[A-Za-z0-9_.+!]+", prefix):
                raise ValueError("not a product source distribution")
            mapper = lambda name: _sdist_path(name, prefix, approved)
            failures.extend(_gzip_metadata(archive))
            with tarfile.open(archive, "r:gz") as tar:
                for number, member in enumerate(tar, 1):
                    if number > MAX_MEMBERS:
                        raise ValueError("too many archive members")
                    parts = _parts(member.name)
                    if member.uid != 0 or member.gid != 0 or member.uname not in {"", "root"} or member.gname not in {"", "root"}:
                        failures.append(f"entry {number}: non-neutral archive owner metadata")
                    for key, value in member.pax_headers.items():
                        if key in {"mtime", "atime", "ctime"} and re.fullmatch(r"-?\d+(?:\.\d+)?", value):
                            continue
                        if key == "path" and _parts(value) == parts:
                            continue
                        failures.extend(f"entry {number} pax metadata: " + issue for issue in _scan_generated((key + "=" + value).encode("utf-8")))
                        failures.append(f"entry {number}: unreviewed pax metadata")
                    if member.isdir():
                        if member.size != 0:
                            raise ValueError("hidden directory payload")
                        if parts[0] != prefix:
                            raise ValueError("unexpected directory prefix")
                        relative = "/".join(parts[1:])
                        if relative and relative != DIST + ".egg-info" and not any(p.startswith(relative + "/") for p in approved):
                            raise ValueError("unexpected directory")
                        continue
                    if not member.isfile() or member.mode & 0o7000:
                        raise ValueError("archive links, special files or special permissions are forbidden")
                    if member.size > MAX_MEMBER_BYTES:
                        raise ValueError("archive member exceeds inspected size budget")
                    stream = tar.extractfile(member)
                    if stream is None:
                        raise ValueError("unreadable archive member")
                    inspect_member(number, member.name, stream.read(), "100755" if member.mode & 0o111 else "100644", mapper)
        else:
            raise ValueError("only product wheel and tar.gz archives are supported")
        missing = required_payload(approved) - present
        if missing:
            failures.append(f"required workflow, notice, schema or template files missing: {len(missing)}")
        return failures
    except (ValueError, OSError, KeyError, UnicodeError, zipfile.BadZipFile, tarfile.TarError, RuntimeError):
        return failures + ["archive inspection failed or unapproved member/metadata detected"]



def _gzip_metadata(path):
    """Gzip's original filename/comment sit outside tar member inspection."""
    issues = []
    with Path(path).open("rb") as stream:
        header = stream.read(10)
        if len(header) != 10 or header[:3] != b"\x1f\x8b\x08" or header[3] & 0xE0:
            raise ValueError("invalid gzip header")
        flags = header[3]
        if flags & 4:
            length_bytes = stream.read(2)
            if len(length_bytes) != 2:
                raise ValueError("truncated gzip extra field")
            length = int.from_bytes(length_bytes, "little")
            issues.extend("gzip metadata: " + issue for issue in _scan_generated(stream.read(length)))
            issues.append("gzip contains unreviewed extra metadata")
        for flag, label in ((8, "filename"), (16, "comment")):
            if not flags & flag:
                continue
            value = bytearray()
            while True:
                char = stream.read(1)
                if char == b"\0":
                    break
                if not char or len(value) >= 4096:
                    raise ValueError("invalid gzip text metadata")
                value.extend(char)
            issues.extend("gzip " + label + ": " + issue for issue in _scan_generated(bytes(value)))
            if label == "comment" or (value and bytes(value) != Path(path).name[:-3].encode("utf-8")):
                issues.append("gzip contains unreviewed " + label)
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--manifest", type=Path, default=ROOT / ".public-files.json")
    args = parser.parse_args(argv)
    try:
        approved = load_manifest(args.manifest)
        failures = [f"archive {number}: {issue}" for number, path in enumerate(args.archives, 1) for issue in inspect_archive(path, approved)]
    except (ValueError, OSError, UnicodeError):
        failures = ["cannot load reviewed public manifest"]
    if failures:
        print("Release payload check blocked:\n" + "\n".join(failures), file=sys.stderr)
        return 1
    print(f"Release payload check passed for {len(args.archives)} product archives; manual review still required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
