"""Versioned knowledge snapshots and append-only, integrity-checked observations."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sysconfig
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

from .workspace import (WorkspaceError, atomic_write_json, load_workspace,
                        locked_workspace, now, read_json, workspace_path)


class RecordError(ValueError):
    pass


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SECRET_KEYS = {"password", "passwd", "bot_token", "access_token", "refresh_token",
                "verification_code", "cookie", "cookies", "secret_value", "authorization"}
_ALIASES = {"evidence_source": "evidence", "question_answer": "answer", "policy": "campaign-policy"}
_KINDS = {"evidence", "fact", "claim", "answer", "campaign-policy", "client-binding", "clarification"}


def identifier(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise RecordError("Identifiers must contain only letters, digits, dots, underscores or hyphens")
    return value


def _kind(value):
    value = _ALIASES.get(value, value.replace("_", "-"))
    if value not in _KINDS:
        raise RecordError("Unsupported record kind")
    return value


def _no_secrets(value):
    if isinstance(value, dict):
        if _SECRET_KEYS.intersection(key.casefold() for key in value):
            raise RecordError("Store secret references, never secret values, in records")
        for child in value.values():
            _no_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _no_secrets(child)


def _schema_check(value, schema, path="record"):
    types = {"object": dict, "array": list, "string": str, "boolean": bool,
             "integer": int, "null": type(None), "number": (int, float)}
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(isinstance(value, types[kind]) and not (kind in {"integer", "number"} and isinstance(value, bool)) for kind in allowed):
            raise RecordError(f"{path}: invalid type")
    if "enum" in schema and value not in schema["enum"]:
        raise RecordError(f"{path}: invalid choice")
    if "const" in schema and value != schema["const"]:
        raise RecordError(f"{path}: invalid version")
    if isinstance(value, dict):
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise RecordError(f"{path}: missing {', '.join(sorted(missing))}")
        for key, child in value.items():
            _schema_check(child, schema.get("properties", {}).get(key, {}), f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise RecordError(f"{path}: not enough entries")
        for child in value:
            _schema_check(child, schema.get("items", {}), f"{path}[]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or ("pattern" in schema and not re.fullmatch(schema["pattern"], value)):
            raise RecordError(f"{path}: invalid text")
    elif isinstance(value, (int, float)) and value < schema.get("minimum", value):
        raise RecordError(f"{path}: below minimum")


def validate_record(kind, record):
    """Validate the documented schema subset and evidence-specific constraints."""
    kind = "event" if kind == "event" else _kind(kind)
    _no_secrets(record)
    schema_root = Path(__file__).resolve().parent.parent / "schemas"
    if not (schema_root / f"{kind}.json").is_file():
        schema_root = Path(sysconfig.get_path("data")) / "share" / "find-me-a-job" / "schemas"
    schema = read_json(schema_root / f"{kind}.json")
    _schema_check(record, schema)
    if kind == "fact":
        if record["status"] == "document_supported" and not record.get("sources"):
            raise RecordError("Document-supported facts require evidence sources")
        if record["status"] in {"candidate_confirmed", "confirmed_absent"} and not all(record.get(field) for field in ("confirmed_by", "confirmed_at")):
            raise RecordError("Candidate confirmation must record who and when")
        if record["status"] == "confirmed_absent" and record["value"] is not None:
            raise RecordError("Confirmed absence is distinct from a positive value")
    if kind == "answer" and record["confirmation"] in {"confirmed", "confirmed_absent"}:
        if not record.get("confirmed_by") or not record.get("confirmed_at"):
            raise RecordError("Confirmed answers require who and when")
    if kind == "campaign-policy" and record["approved"] and record.get("contradictions"):
        raise RecordError("Resolve contradictions before approving campaign policy")
    return deepcopy(record)


def _directory(root, kind, record_id):
    return workspace_path(root, "records", _kind(kind), identifier(record_id))


def load_record(root, kind, record_id, version=None):
    directory = _directory(root, kind, record_id)
    if version is not None and (not isinstance(version, int) or isinstance(version, bool) or version < 1):
        raise RecordError("Invalid record version")
    files = sorted(directory.glob("v[0-9]*.json"))
    if not files:
        raise RecordError("Record does not exist")
    path = directory / f"v{version:08d}.json" if version else files[-1]
    value = read_json(workspace_path(root, *path.relative_to(Path(root).resolve()).parts))
    if value.get("workspace_id") != load_workspace(root)["id"]:
        raise RecordError("Record belongs to another workspace")
    return validate_record(_kind(kind), value)


def list_records(root, kind):
    directory = workspace_path(root, "records", _kind(kind))
    return [load_record(root, kind, item.name) for item in sorted(directory.iterdir()) if item.is_dir()] if directory.exists() else []


def validate_claim(root, claim):
    if claim.get("status") != "approved":
        raise RecordError("Only approved claims are eligible")
    superseded = {item["supersedes"] for item in list_records(root, "fact") if item.get("supersedes")}
    for fact_id in claim["fact_ids"]:
        if fact_id in superseded:
            raise RecordError("Claim refers to a superseded fact and must be reviewed")
        fact = load_record(root, "fact", fact_id)
        if fact["status"] not in {"document_supported", "candidate_confirmed"}:
            raise RecordError("Unknown, absent or conflicting facts cannot support a positive claim")
        if claim.get("fact_versions", {}).get(fact_id) != fact["version"]:
            raise RecordError("Claim must be reviewed after its supporting fact changes")
    return True


def save_record(root, kind, record, actor="owner", expected_version=None):
    kind = _kind(kind)
    value = deepcopy(record)
    with locked_workspace(root):
        config = load_workspace(root)
        identifier(value.get("id"))
        directory = _directory(root, kind, value["id"])
        versions = sorted(directory.glob("v[0-9]*.json"))
        previous = read_json(versions[-1]) if versions else None
        prior_version = previous["version"] if previous else 0
        if expected_version is not None and expected_version != prior_version:
            raise RecordError("Record changed since it was read")
        if value.get("workspace_id", config["id"]) != config["id"]:
            raise RecordError("Cannot import another workspace's private record")
        value.update(schema_version=1, workspace_id=config["id"], version=prior_version + 1)
        if value.get("supersedes"):
            if value["supersedes"] == value["id"]:
                raise RecordError("A new ID must supersede the prior record; same-ID changes already have versions")
            prior = load_record(root, kind, value["supersedes"])
            seen = {value["id"]}
            while prior.get("supersedes"):
                if prior["id"] in seen:
                    raise RecordError("Supersession cannot contain cycles")
                seen.add(prior["id"])
                prior = load_record(root, kind, prior["supersedes"])
            if prior["id"] in seen:
                raise RecordError("Supersession cannot contain cycles")
        if kind == "claim" and value.get("status") == "approved":
            value["fact_versions"] = {fact_id: load_record(root, "fact", fact_id)["version"] for fact_id in value.get("fact_ids", [])}
            validate_claim(root, value)
        if kind == "fact":
            for source_id in value.get("sources", []):
                load_record(root, "evidence", source_id)
        validate_record(kind, value)
        target = workspace_path(root, "records", kind, value["id"], f"v{value['version']:08d}.json")
        if target.exists():
            raise RecordError("Refusing to overwrite immutable history")
        atomic_write_json(target, value)
        append_event(root, "record_saved", actor=actor, entity_id=value["id"],
                     data={"kind": kind, "version": value["version"]})
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_events(root):
    from . import store
    config = load_workspace(root)
    events = []
    previous_hash = None
    for sequence, event in enumerate(store.payloads(root, "events", " ORDER BY sequence"), start=1):
        expected = event.pop("hash", None)
        if event.get("sequence") != sequence or event.get("previous_hash") != previous_hash or _digest(event) != expected:
            raise RecordError("Event chain is corrupted or incomplete")
        if event.get("workspace_id") != config["id"]:
            raise RecordError("Foreign workspace event")
        validate_record("event", event)
        event["hash"] = expected
        events.append(event)
        previous_hash = expected
    return events


def append_event(root, event_type, actor="owner", entity_id=None, operation_id=None,
                 observed=True, evidence=None, data=None, occurred_at=None):
    from . import store
    if occurred_at and datetime.fromisoformat(occurred_at).tzinfo is None:
        raise RecordError("Event occurrence time must include timezone")
    with locked_workspace(root):
        config = load_workspace(root)
        previous = store.connection(root).execute("SELECT sequence,payload FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        head = json.loads(previous["payload"]) if previous else None
        if head and _digest({k:v for k,v in head.items() if k != "hash"}) != head["hash"]:
            raise RecordError("Event chain head is corrupted")
        timestamp = now()
        event = {"schema_version": 1, "id": uuid.uuid4().hex, "workspace_id": config["id"],
                 "type": event_type, "timestamp": timestamp, "observed_at":timestamp,
                 "occurred_at":occurred_at, "time_zone": config["time_zone"],
                 "actor": actor, "operation_id": operation_id, "observed": observed,
                 "evidence": deepcopy(evidence), "data": deepcopy(data or {}),
                 "sequence": previous["sequence"] + 1 if previous else 1, "previous_hash":head["hash"] if head else None}
        if entity_id is not None:
            event["entity_id"] = entity_id
        validate_record("event", event)
        event["hash"] = _digest(event)
        store.insert_event(root, event)
        return deepcopy(event)


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise RecordError("Use a public HTTP(S) URL without credentials")
    host = parts.hostname.casefold().encode("idna").decode()
    port = parts.port
    if ":" in host:
        host = f"[{host}]"
    if port and not (parts.scheme.casefold() == "https" and port == 443 or parts.scheme.casefold() == "http" and port == 80):
        host += f":{port}"
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if not key.casefold().startswith("utm_") and key.casefold() not in {"trk", "trackingid", "fbclid", "gclid"}]
    return urlunsplit((parts.scheme.casefold(), host, parts.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def _employer_identity(employer):
    words = re.sub(r"[^\w]+", " ", employer.casefold()).split()
    while words and words[-1] in {"gmbh", "ag", "inc", "incorporated", "ltd", "limited", "ab", "llc", "corp", "corporation"}:
        words.pop()
    return " ".join(words)


def opportunity_key(employer, requisition_id=None, url=None):
    if not employer or not (requisition_id or url):
        raise RecordError("Opportunity identity requires employer and requisition or URL")
    identity = [_employer_identity(employer), str(requisition_id).strip().casefold()] if requisition_id else [_employer_identity(employer), canonical_url(url)]
    return "opp-" + _digest(identity)[:32]


def contact_key(channel, recipient, verified_identity=None):
    if not channel or not recipient:
        raise RecordError("Contact identity requires channel and recipient")
    return "contact-" + _digest(["verified", verified_identity] if verified_identity else [channel.casefold(), recipient.strip().casefold()])[:32]


def confirmed_answer(root, question, scope, at=None):
    """Exact question and scope only; unknown and superseded answers never leak through."""
    at = _timestamp(at or now())
    answers = list_records(root, "answer")
    superseded = {item["supersedes"] for item in answers if item.get("supersedes")}
    matches = [item for item in answers if item["id"] not in superseded and item["question"] == question
               and item["scope"] == scope and item["confirmation"] in {"confirmed", "confirmed_absent"}
               and (not item.get("expires_at") or _timestamp(item["expires_at"]) > at)]
    if len(matches) != 1:
        raise RecordError("An unambiguous current confirmed answer is required")
    return deepcopy(matches[0])


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("Time zone required")
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError) as error:
        raise RecordError("Record timestamps require ISO dates with an explicit time zone") from error
