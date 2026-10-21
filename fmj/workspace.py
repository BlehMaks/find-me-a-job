"""Private external workspaces, durable writes and a cross-process writer lock.

Directory permissions protect files from ordinary local users on POSIX. They are
not a sandbox against an agent, administrator, or processes running as the owner.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid


class WorkspaceError(ValueError):
    pass


class WorkspaceBusy(WorkspaceError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def _overlap(first, second):
    return first == second or first in second.parents or second in first.parents


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise WorkspaceError("Private directories cannot be symbolic links")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def atomic_write_json(path, value):
    """Replace one JSON snapshot atomically; an interrupted write keeps the old one."""
    path = Path(path)
    if path.is_symlink():
        raise WorkspaceError("Refusing to replace a symbolic link")
    private_directory(path.parent)
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    path = Path(path)
    if path.is_symlink():
        raise WorkspaceError("Refusing to read a symbolic link")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def create_workspace(path, mode="self_hosted", source_root=None, workspace_id=None,
                     owner="owner", operator=None, locale="en", time_zone="UTC", agent=None):
    source = Path(source_root or Path(__file__).resolve().parent.parent).expanduser().resolve()
    root = Path(path).expanduser().resolve()
    mode = mode.replace("-", "_")
    if mode not in {"self_hosted", "managed"}:
        raise WorkspaceError("Mode must be self_hosted or managed")
    if _overlap(root, source) or root == Path(root.anchor):
        raise WorkspaceError("Private workspace and source checkout must not overlap or alias")
    if mode == "managed" and not operator:
        raise WorkspaceError("Managed workspaces require an operator identity")
    if (root / "workspace.json").exists():
        raise WorkspaceError("Workspace already exists; load it rather than overwriting it")
    if root.exists() and any(root.iterdir()):
        raise WorkspaceError("Provision an empty private directory")
    from zoneinfo import ZoneInfo
    ZoneInfo(time_zone)
    private_directory(root)
    config = {"schema_version": 2, "id": workspace_id or uuid.uuid4().hex,
              "mode": mode, "external_root": str(root), "owner": owner,
              "operator": operator, "locale": locale, "time_zone": time_zone,
              "agent": agent, "created_at": now(),
              "permission_status": "posix_owner_only" if os.name != "nt" else "acl_review_required"}
    atomic_write_json(root / "workspace.json", config)
    for directory in ("records", "events", "operations", "artifacts", "secrets", "runtime"):
        private_directory(root / directory)
    with locked_workspace(root):
        pass
    return config


def load_workspace(path):
    root = Path(path).expanduser().resolve()
    config = read_json(root / "workspace.json")
    if config.get("schema_version") not in {1, 2} or Path(config.get("external_root", "")).resolve() != root:
        raise WorkspaceError("Invalid workspace version or root binding")
    if config.get("mode") not in {"self_hosted", "managed"}:
        raise WorkspaceError("Invalid workspace mode")
    return config


_local = threading.local()


@contextmanager
def locked_workspace(path, lock_name=".writer.lock", transactional=True):
    """Non-blocking, reentrant per-thread lock. OS releases it after a crash.

    Never delete the lock file: unlinking it would permit two independent locks.
    """
    root = Path(path).expanduser().resolve()
    config = load_workspace(root)
    transactional = transactional and lock_name == ".writer.lock"
    if transactional and config["schema_version"] == 1:
        raise WorkspaceError("Legacy workspace needs: fmj storage migrate --apply --workspace PATH")
    held = getattr(_local, "held", {})
    key = str(root) + ":" + lock_name
    if key in held:
        if transactional:
            from .store import transaction
            with transaction(root):
                yield root
        else:
            yield root
        return
    lock_path = workspace_path(root, lock_name)
    private_directory(lock_path.parent)
    if lock_path.is_symlink():
        raise WorkspaceError("Invalid writer lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    stream = os.fdopen(fd, "r+b", buffering=0)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"\0")
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise WorkspaceBusy("Another workspace writer is active") from error
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise WorkspaceBusy("Another workspace writer is active") from error
        acquired = True
        held[key] = True
        _local.held = held
        if transactional:
            from .store import transaction
            with transaction(root):
                yield root
        else:
            yield root
    finally:
        held.pop(key, None)
        if acquired:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def workspace_path(root, *parts):
    """Return a contained path without following a private subtree alias."""
    root = Path(root).expanduser().resolve()
    target = root.joinpath(*parts)
    if not target.is_relative_to(root):
        raise WorkspaceError("Path escapes workspace")
    current = root
    for part in target.relative_to(root).parts:
        if part in {"", ".", ".."}:
            raise WorkspaceError("Invalid private path")
        current = current / part
        if current.is_symlink():
            raise WorkspaceError("Private subtree cannot contain symbolic links")
    if not target.resolve().is_relative_to(root):
        raise WorkspaceError("Path escapes workspace")
    return target


def contained_path(root, value):
    """Accept host root aliases, but never follow a client subtree symlink."""
    path, supplied = Path(value).absolute(), Path(root).absolute()
    try:
        relative = path.relative_to(supplied)
    except ValueError:
        try:
            relative = path.relative_to(supplied.resolve())
        except ValueError:
            raise WorkspaceError("Path is outside the selected private workspace") from None
    return workspace_path(root, *relative.parts)
