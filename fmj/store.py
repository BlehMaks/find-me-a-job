"""Private SQLite operational state. Knowledge source files remain versioned.

The existing workspace lock owns short, nested SQL transactions. External sends
must happen outside that lock; a persisted unknown send is never an automatic retry.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import zipfile

from .workspace import (WorkspaceError, atomic_write_json, load_workspace,
                        locked_workspace, now, workspace_path, contained_path)

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS companies (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT REFERENCES companies(id), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS company_aliases (
 kind TEXT NOT NULL, value TEXT NOT NULL, company_id TEXT NOT NULL REFERENCES companies(id),
 PRIMARY KEY(kind,value));
CREATE TABLE IF NOT EXISTS opportunities (
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id), title TEXT NOT NULL,
 discovered_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunity_aliases (
 company_id TEXT NOT NULL REFERENCES companies(id), kind TEXT NOT NULL, value TEXT NOT NULL,
 opportunity_id TEXT NOT NULL REFERENCES opportunities(id), PRIMARY KEY(company_id,kind,value));
CREATE TABLE IF NOT EXISTS applications (
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 application_class TEXT NOT NULL, campaign_id TEXT NOT NULL, submitted_at TEXT,
 historical INTEGER NOT NULL DEFAULT 0, UNIQUE(opportunity_id,application_class));
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, identity TEXT NOT NULL, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 application_id TEXT REFERENCES applications(id), revision INTEGER NOT NULL CHECK(revision>0),
 action TEXT NOT NULL, stage TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(application_id,revision));
CREATE INDEX IF NOT EXISTS operation_identity ON operations(identity);
CREATE INDEX IF NOT EXISTS operation_stage ON operations(stage);
CREATE TABLE IF NOT EXISTS attempts (
 id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES operations(id),
 started_at TEXT NOT NULL, stage TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, directory TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS preparation_documents (
 operation_id TEXT NOT NULL REFERENCES operations(id), document_id TEXT NOT NULL REFERENCES documents(id),
 field TEXT NOT NULL, variant TEXT NOT NULL, sha256 TEXT NOT NULL,
 PRIMARY KEY(operation_id,field));
CREATE TABLE IF NOT EXISTS contacts (
 id TEXT PRIMARY KEY, company_id TEXT REFERENCES companies(id), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations (
 id TEXT PRIMARY KEY, contact_id TEXT NOT NULL REFERENCES contacts(id), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES conversations(id), turn_id TEXT NOT NULL,
 operation_id TEXT NOT NULL REFERENCES operations(id), UNIQUE(thread_id,turn_id));
CREATE TABLE IF NOT EXISTS events (
 sequence INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, type TEXT NOT NULL,
 operation_id TEXT, entity_id TEXT, observed_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_operation ON events(operation_id,sequence);
CREATE INDEX IF NOT EXISTS event_entity ON events(entity_id,sequence);
CREATE TABLE IF NOT EXISTS receipts (
 id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actions (
 id TEXT PRIMARY KEY, operation_id TEXT REFERENCES operations(id), owner TEXT NOT NULL,
 status TEXT NOT NULL, due_at TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS action_queue ON actions(status,due_at);
CREATE TABLE IF NOT EXISTS referral_waits (
 opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_reviews (
 campaign_id TEXT NOT NULL, threshold INTEGER NOT NULL CHECK(threshold>0 AND threshold%50=0),
 status TEXT NOT NULL DEFAULT 'pending', payload TEXT NOT NULL, PRIMARY KEY(campaign_id,threshold));
CREATE TABLE IF NOT EXISTS inbox_requests (
 id TEXT PRIMARY KEY, origin TEXT NOT NULL UNIQUE, status TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runtime_state (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL);
"""
_local = threading.local()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _connect(root):
    path = workspace_path(root, "career.sqlite3")
    for suffix in ("", "-journal", "-wal", "-shm"):
        if Path(str(path) + suffix).is_symlink():
            raise WorkspaceError("Operational database cannot be a symbolic link")
    db = sqlite3.connect(path, timeout=2, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    if os.name != "nt":
        path.chmod(0o600)
    return db


@contextmanager
def transaction(root):
    key = str(Path(root).resolve())
    active = getattr(_local, "connections", {})
    if key in active:
        yield active[key]
        return
    if load_workspace(root)["schema_version"] != 2:
        raise WorkspaceError("Legacy workspace needs: fmj storage migrate --apply --workspace PATH")
    db = _connect(root)
    try:
        schema_version = db.execute("PRAGMA user_version").fetchone()[0]
        if schema_version not in {0, 1}:
            raise WorkspaceError("Unsupported operational schema version")
        if schema_version == 0:
            db.executescript(SCHEMA)
            db.execute("PRAGMA user_version=1")
        db.execute("BEGIN IMMEDIATE")
        config = load_workspace(root)
        binding = db.execute("SELECT value FROM metadata WHERE key='workspace_id'").fetchone()
        if binding and binding[0] != config["id"]:
            raise WorkspaceError("Operational database belongs to another workspace")
        db.execute("INSERT OR IGNORE INTO metadata VALUES('workspace_id',?)", (config["id"],))
        version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if version and version[0] != "1":
            raise WorkspaceError("Unsupported operational schema version")
        db.execute("INSERT OR IGNORE INTO metadata VALUES('schema_version','1')")
        active[key] = db
        _local.connections = active
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        active.pop(key, None)
        db.close()


def connection(root):
    try:
        return _local.connections[str(Path(root).resolve())]
    except (AttributeError, KeyError):
        raise WorkspaceError("Operational writes require the workspace transaction") from None


def rows(root, sql, parameters=()):
    with locked_workspace(root):
        return [dict(row) for row in connection(root).execute(sql, parameters)]


def payloads(root, table, where="", parameters=()):
    # Callers supply only internal table names and SQL; CLI never accepts raw SQL.
    return [json.loads(row["payload"]) for row in rows(root, "SELECT payload FROM " + table + where, parameters)]


def state(root, key, default=None):
    values = payloads(root, "runtime_state", " WHERE key=?", (key,))
    return values[0] if values else default


def save_state(root, key, value):
    from .records import _no_secrets
    _no_secrets(value)
    with locked_workspace(root):
        connection(root).execute("INSERT INTO runtime_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload", (key, encode(value)))


def inspect_legacy(root):
    """Validate old sources without creating or changing a database."""
    from .records import _digest, validate_record
    root = Path(root).resolve()
    config = load_workspace(root)
    previous, events, operations, sources = None, [], [], []
    for sequence, path in enumerate(sorted(workspace_path(root, "events").glob("*.json")), 1):
        value = json.loads(workspace_path(root, "events", path.name).read_text())
        digest = value.pop("hash", None)
        if value.get("sequence") != sequence or value.get("previous_hash") != previous or _digest(value) != digest or value.get("workspace_id") != config["id"]:
            raise WorkspaceError("Legacy event chain is corrupted; original files preserved")
        validate_record("event", value)
        value["hash"] = previous = digest
        events.append(value)
    for path in sorted(workspace_path(root, "operations").glob("*.json")):
        value = json.loads(workspace_path(root, "operations", path.name).read_text())
        if value.get("workspace_id") != config["id"] or value.get("intent_hash") != _digest(value["intent"]):
            raise WorkspaceError("Legacy operation is corrupted; original files preserved")
        operations.append(value)
    for folder in ("events", "operations", "records", "runtime"):
        for path in sorted(workspace_path(root, folder).rglob("*.json")):
            safe = workspace_path(root, *path.relative_to(Path(root).resolve()).parts)
            sources.append((str(path.relative_to(root)), hashlib.sha256(safe.read_bytes()).hexdigest()))
    return {"events":events, "operations":operations, "sources":sources}


def migrate(root, apply=False):
    """One locked cutover; v2 binding prevents older runtimes from dual-writing."""
    with locked_workspace(root, "runtime/.dispatch.lock", transactional=False):
        return _migrate(root, apply)


def _migrate(root, apply):
    with locked_workspace(root, transactional=False):
        config = load_workspace(root)
        if config["schema_version"] == 2:
            return {"status":"already_current", "workspace_id":config["id"]}
        legacy = inspect_legacy(root)
        summary = {"status":"validated_dry_run", "events":len(legacy["events"]),
                   "operations":len(legacy["operations"]), "source_hashes":dict(legacy["sources"])}
        if not apply:
            return summary
        archive = workspace_path(root, "runtime", "legacy-before-sqlite.zip")
        if not archive.exists():
            with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as output:
                output.write(workspace_path(root, "workspace.json"), "workspace.json")
                for relative, _ in legacy["sources"]:
                    output.write(workspace_path(root, *Path(relative).parts), relative)
            if os.name != "nt":
                archive.chmod(0o600)
        # No external operation runs while the shared writer lock is held.
        atomic_write_json(workspace_path(root, "workspace.json"), {**config, "schema_version":2})
        try:
            with transaction(root) as db:
                from .tracking import import_operation
                for operation in legacy["operations"]:
                    import_operation(root, operation)
                for event in legacy["events"]:
                    insert_event(root, event)
                if db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] != len(legacy["operations"]) or db.execute("SELECT COUNT(*) FROM events").fetchone()[0] != len(legacy["events"]):
                    raise WorkspaceError("Migration counts differ; originals preserved")
                for relative, digest in legacy["sources"]:
                    db.execute("INSERT INTO imports VALUES(?,?)", (relative, digest))
                for key, filename in (("campaign", "campaign.json"), ("telegram", "telegram-state.json")):
                    path = workspace_path(root, "runtime", filename)
                    if path.exists():
                        save_state(root, key, json.loads(path.read_text()))
                if db.execute("PRAGMA foreign_key_check").fetchall():
                    raise WorkspaceError("Migration relationships failed validation")
        except BaseException:
            atomic_write_json(workspace_path(root, "workspace.json"), config)
            raise
        return {**summary, "status":"migrated", "backup":str(archive)}


def insert_event(root, event):
    connection(root).execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)", (
        event["sequence"], event["id"], event["type"], event.get("operation_id"),
        event.get("entity_id"), event.get("observed_at", event["timestamp"]), encode(event)))


def backup(root, destination):
    with locked_workspace(root, transactional=False):
        load_workspace(root)
        target = contained_path(root, destination)
        if target.exists():
            raise WorkspaceError("Backup destination must be new")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with transaction(root):
            pass
        source = _connect(root)
        output = sqlite3.connect(target)
        try:
            source.backup(output)
        finally:
            output.close()
            source.close()
        if os.name != "nt":
            target.chmod(0o600)
        return {"backup":str(target), "sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
                "scope":"Operational database; keep referenced knowledge/artifact files with it"}


def restore(root, source):
    """Refuse rollback of observed/uncertain sends; keep a pre-restore backup."""
    with locked_workspace(root, "runtime/.dispatch.lock", transactional=False):
        with locked_workspace(root, transactional=False):
            path = contained_path(root, source)
            if path == workspace_path(root, "career.sqlite3"):
                raise WorkspaceError("Restore requires a separate backup")
            candidate = sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True)
            current = _connect(root)
            try:
                if candidate.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or candidate.execute("PRAGMA foreign_key_check").fetchall():
                    raise WorkspaceError("Backup integrity validation failed")
                binding = candidate.execute("SELECT value FROM metadata WHERE key='workspace_id'").fetchone()
                if not binding or binding[0] != load_workspace(root)["id"]:
                    raise WorkspaceError("Backup belongs to another workspace")
                for row in current.execute("SELECT id,stage,payload FROM operations"):
                    old = candidate.execute("SELECT stage,payload FROM operations WHERE id=?", (row[0],)).fetchone()
                    if row[1] in {"dispatching", "delivery_unknown"} or row[1] == "submission_observed" and (not old or old != (row[1], row[2])):
                        raise WorkspaceError("Restore would erase a later observed or uncertain send; reconcile first")
                before = workspace_path(root, "runtime", "before-restore-" + now().replace(":", "-") + ".sqlite3")
                backup(root, before)
                candidate.backup(current)
            finally:
                current.close()
                candidate.close()
            return {"status":"restored", "preserved_current":str(before)}
