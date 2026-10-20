"""Opt-in generic proposals, never customer transcripts or automatic merges."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

from .workspace import atomic_write_json, load_workspace, locked_workspace, now, read_json, workspace_path


class FeedbackError(ValueError):
    pass


_FIELDS = {"summary", "expected", "observed", "reproduction", "product_version", "platform"}
_SENSITIVE = re.compile(
    r"(?:/(?:Users|home)/\S+|[A-Z]:[\\/]Users[\\/]\S+|"
    r"linkedin\.com/in/(?!example-|synthetic-)\S+|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|"
    r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----)", re.I)
_EMAIL = re.compile(r"[\w.+-]+@([\w.-]+\.[A-Za-z]{2,})")


def _safe_text(text):
    if _SENSITIVE.search(text):
        raise FeedbackError("Proposal has a sensitive marker; keep it local")
    for match in _EMAIL.finditer(text):
        domain=match[1].lower()
        if domain not in {"example.com", "example.org", "example.net"} and not domain.endswith(".invalid"):
            raise FeedbackError("Use reserved synthetic contact addresses")


def _safe(payload):
    if set(payload) != _FIELDS or not all(isinstance(v, str) and 0 < len(v) <= 12000 for v in payload.values()):
        raise FeedbackError("Use only the six documented generic proposal fields")
    for value in payload.values():
        _safe_text(value)
    return payload


def consent(root, enabled, repository, actor):
    config = load_workspace(root)
    if actor != (config.get("operator") if config["mode"] == "managed" else config["owner"]):
        raise FeedbackError("Only the workspace controller can set feedback consent")
    if not isinstance(enabled, bool) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise FeedbackError("Explicit boolean consent and owner/repository are required")
    with locked_workspace(root):
        value = {"schema_version": 1, "state": "enabled" if enabled else "disabled",
                 "repository": repository, "actor": actor, "at": now(), "disclosure_version": 1}
        atomic_write_json(workspace_path(root, "runtime", "feedback-consent.json"), value)
    return value


def prepare(root, payload):
    load_workspace(root)
    _safe(payload)
    proposal_id = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
    value = {"id": proposal_id, "payload": payload, "review": None, "state": "local"}
    with locked_workspace(root):
        path = workspace_path(root, "runtime", "feedback", proposal_id + ".json")
        if path.exists():
            return read_json(path)
        atomic_write_json(path, value)
    return value


def review(root, proposal_id, reviewer, synthetic):
    if not reviewer or synthetic is not True:
        raise FeedbackError("An explicit synthetic-content review is required")
    with locked_workspace(root):
        path = workspace_path(root, "runtime", "feedback", proposal_id + ".json")
        value = read_json(path)
        _safe(value["payload"])
        value["review"] = {"reviewer": reviewer, "synthetic": True, "at": now(),
                           "payload_hash": hashlib.sha256(json.dumps(value["payload"], sort_keys=True).encode()).hexdigest()}
        atomic_write_json(path, value)
    return value


def _patch_snapshot(source_root, base_ref, branch):
    source=Path(source_root).resolve()
    def git(*args):
        try:
            return subprocess.check_output(["git", "-C", str(source), *args],stderr=subprocess.PIPE).decode()
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise FeedbackError("Cannot inspect the feedback branch") from None
    if not re.fullmatch(r"codex/feedback/[A-Za-z0-9_-]+",branch) or base_ref.startswith('-'):
        raise FeedbackError("Use a dedicated feedback branch and explicit base revision")
    if git("branch","--show-current").strip()!=branch or git("status","--porcelain").strip():
        raise FeedbackError("Review a clean checked-out feedback branch")
    base=git("rev-parse","--verify",base_ref+'^{commit}').strip()
    head=git("rev-parse","HEAD").strip()
    try:
        allowed=set(json.loads(git("show",head+":.public-files.json")))
    except (ValueError,TypeError):
        raise FeedbackError("Feedback branch needs an explicit reviewed public-file manifest") from None
    files=git("diff","--name-only",base,head,"--").splitlines()
    if not files or any(path not in allowed for path in files):
        raise FeedbackError("Patch contains unapproved paths or no changes")
    for path in files:
        if path not in git("ls-tree","--name-only",head,"--",path).splitlines():continue
        _safe_text(git("show",head+":"+path))
    diff=git("diff","--binary",base,head,"--")
    _safe_text(diff)
    return {"source_root":str(source),"base":base,"head":head,"branch":branch,
            "diff_sha256":hashlib.sha256(diff.encode()).hexdigest(),"files":files}


def review_patch(root,proposal_id,source_root,base_ref,branch,reviewer):
    if not reviewer:raise FeedbackError("Name the independent patch/privacy reviewer")
    snapshot=_patch_snapshot(source_root,base_ref,branch)
    with locked_workspace(root):
        path=workspace_path(root,"runtime","feedback",proposal_id+'.json')
        value=read_json(path)
        value["patch_review"]={**snapshot,"reviewer":reviewer,"at":now()}
        atomic_write_json(path,value)
    return snapshot


def submit(root, proposal_id, *, pr_branch=None, source_root=None, runner=subprocess.run):
    """A network side effect. Call only under enabled scoped feedback permission."""
    with locked_workspace(root):
        consent_path = workspace_path(root, "runtime", "feedback-consent.json")
        if not consent_path.exists() or read_json(consent_path).get("state") != "enabled":
            raise FeedbackError("Feedback is not explicitly enabled")
        setting = read_json(consent_path)
        path = workspace_path(root, "runtime", "feedback", proposal_id + ".json")
        value = read_json(path)
        _safe(value["payload"])
        expected = hashlib.sha256(json.dumps(value["payload"], sort_keys=True).encode()).hexdigest()
        if not value.get("review") or value["review"].get("payload_hash") != expected:
            raise FeedbackError("Review the unchanged synthetic proposal first")
        if value["state"] != "local":
            raise FeedbackError("Proposal already dispatched or delivery is uncertain; reconcile it before retrying")
        body = "\n\n".join(f"### {key.replace('_', ' ').title()}\n{val}" for key, val in value["payload"].items() if key != "summary")
        body_path = workspace_path(root, "runtime", "feedback", proposal_id + ".body.md")
        body_path.write_text(body, encoding="utf-8")
        body_path.chmod(0o600)
        if pr_branch is None:
            cmd = ["gh", "issue", "create", "--repo", setting["repository"], "--title", value["payload"]["summary"], "--body-file", str(body_path)]
        else:
            if not source_root or not re.fullmatch(r"[A-Za-z0-9_.-]+:codex/feedback/[A-Za-z0-9_-]+", pr_branch):
                raise FeedbackError("Use an already pushed isolated own-account feedback branch")
            patch=value.get("patch_review")
            owner,branch=pr_branch.split(":",1)
            if not patch or _patch_snapshot(source_root,patch["base"],branch)!={k:v for k,v in patch.items() if k not in {"reviewer","at"}}:
                raise FeedbackError("Review the exact current branch diff before proposing a PR")
            try:
                login=runner(["gh","api","user","--jq",".login"],capture_output=True,text=True,check=True,timeout=30).stdout.strip()
                remote=runner(["gh","api",f"repos/{owner}/{setting['repository'].split('/')[1]}/git/ref/heads/{branch}","--jq",".object.sha"],capture_output=True,text=True,check=True,timeout=30).stdout.strip()
            except (OSError,subprocess.SubprocessError):
                raise FeedbackError("Cannot verify the own-account remote branch") from None
            if login!=owner or remote!=patch["head"]:
                raise FeedbackError("Own-account remote branch differs from reviewed local revision")
            cmd = ["gh", "pr", "create", "--draft", "--repo", setting["repository"], "--head", pr_branch,
                   "--title", value["payload"]["summary"], "--body-file", str(body_path)]
        value["state"] = "delivery_unknown"
        atomic_write_json(path, value)
        try:
            result = runner(cmd, cwd=source_root, capture_output=True, text=True, check=True, timeout=90)
        except (subprocess.SubprocessError, OSError):
            raise FeedbackError("Feedback delivery is uncertain; inspect your GitHub account before retrying") from None
        url = result.stdout.strip()
        prefix = "https://github.com/" + setting["repository"] + "/"
        if not url.startswith(prefix) or not re.fullmatch(r"(?:issues|pull)/\d+", url[len(prefix):]):
            raise FeedbackError("Unexpected GitHub response; reconcile before retrying")
        value.update(state="submitted", url=url, at=now())
        atomic_write_json(path, value)
        return value
