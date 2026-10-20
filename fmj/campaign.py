"""Scoped authority, search screening, dispatch intent, recovery and human handoffs.

The send callback is an agent adapter, not a transport implemented here. A real
adapter must verify current documents, form fields, recipients and tool permission
immediately before its outbound action. Controlled fixtures explicitly opt out of
external document verification and must never be used as a production transport.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import json
from pathlib import Path
import re
import uuid

from .records import (RecordError, _digest, _no_secrets, append_event, contact_key, identifier,
                      confirmed_answer, list_records, load_record, opportunity_key, save_record, validate_record)
from .workspace import atomic_write_json, load_workspace, locked_workspace, now, read_json, workspace_path


class CampaignBlocked(ValueError):
    pass


class AuthorityError(CampaignBlocked):
    pass


HUMAN_RESERVED = frozenset({"accept_offer", "reject_offer", "confirm_appointment", "agree_compensation",
    "agree_terms", "withdraw_application", "paid_action", "material_commitment"})
OPERATOR_ACTIONS = frozenset({"change_campaign", "manage_access", "manage_resources", "commercial_terms", "stop_campaign"})
CLIENT_ACTIONS = frozenset({"pause", "resume", "answer_personal", "status", "read_materials"})
SEND_ACTIONS = frozenset({"apply", "send_message", "connect", "follow_up", "submit_proposal"})


def _state(root):
    path = workspace_path(root, "runtime", "campaign.json")
    return read_json(path) if path.exists() else {"pauses":[], "blockers":[], "authority":{}}


def _save_state(root, state):
    _no_secrets(state)
    atomic_write_json(workspace_path(root, "runtime", "campaign.json"), state)


def grant_authority(root, actor, actions, by, policy_id=None, policy_version=None):
    """An authenticated owner/operator explicitly delegates named action classes."""
    config = load_workspace(root)
    responsible = config["operator"] if config["mode"] == "managed" else config["owner"]
    if by != responsible or set(actions) - (SEND_ACTIONS | CLIENT_ACTIONS):
        raise AuthorityError("Only the responsible person can delegate supported routine actions")
    if policy_id:
        policy = load_record(root, "campaign-policy", policy_id)
        if policy_version != policy["version"]:
            raise AuthorityError("Grant must bind the current policy version")
    with locked_workspace(root):
        state = _state(root)
        state["authority"][actor] = {"actions":sorted(set(actions)), "granted_by":by,
            "granted_at":now(), "policy_id":policy_id, "policy_version":policy_version}
        _save_state(root, state)
        append_event(root, "authority_granted", actor=by, data={"actor":actor, **state["authority"][actor]})


def require_action_authority(root, actor, action, policy=None):
    config = load_workspace(root)
    if action in HUMAN_RESERVED:
        raise AuthorityError("Responsible human decision required; prepare a draft handoff")
    responsible = config["operator"] if config["mode"] == "managed" else config["owner"]
    if action in OPERATOR_ACTIONS:
        if actor != responsible:
            raise AuthorityError("Service and campaign management belongs to the operator/owner")
        return True
    if config["mode"] == "self_hosted" and actor == config["owner"]:
        return True
    if config["mode"] == "managed" and actor == responsible:
        return True
    if action in CLIENT_ACTIONS and config["mode"] == "managed":
        binding = _binding(root)
        if binding and binding["enabled"] and binding["confirmed"] and binding["client"] == actor:
            return True
    grant = _state(root)["authority"].get(actor)
    if not grant or action not in grant["actions"]:
        raise AuthorityError("Action has no current scoped delegation")
    if grant.get("policy_id") and (not policy or policy["id"] != grant["policy_id"] or policy["version"] != grant["policy_version"]):
        raise AuthorityError("Action delegation is bound to another policy version")
    return True


def _normalized(value):
    return " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())


def _employer(value):
    parts = _normalized(value).split()
    while parts and parts[-1] in {"gmbh", "ag", "inc", "incorporated", "ltd", "limited", "ab", "llc", "corp", "corporation"}:
        parts.pop()
    return " ".join(parts)


def screen_opportunity(policy, opportunity):
    reasons = []
    if not policy.get("approved") or policy.get("contradictions"):
        return {"decision":"needs_confirmation", "reasons":["Campaign strategy must be approved without unresolved contradictions"]}
    exclusions = policy.get("hard_exclusions", {})
    employers = [_employer(opportunity.get(key, "")) for key in ("employer", "end_employer")]
    blocked_employers = {_employer(item) for item in exclusions.get("employers", [])}
    for alias, employer in policy.get("employer_aliases", {}).items():
        if _employer(alias) in employers:
            employers.append(_employer(employer))
    if any(item and item in blocked_employers for item in employers):
        reasons.append("Employer excluded by campaign policy")
    title = _normalized(opportunity.get("title", ""))
    duties = [_normalized(item) for item in opportunity.get("duties", [])]
    if any(_normalized(item) in title for item in exclusions.get("titles", [])):
        reasons.append("Title excluded by campaign policy")
    if any(_normalized(item) in duty for item in exclusions.get("duties", []) for duty in duties):
        reasons.append("Duties violate a hard exclusion")
    for field in ("countries", "locations"):
        value = _normalized(opportunity.get(field[:-1], ""))
        if value and value in {_normalized(item) for item in exclusions.get(field, [])}:
            reasons.append(f"{field[:-1].capitalize()} excluded")
    if reasons:
        return {"decision":"excluded", "reasons":reasons, "policy_version":policy.get("version")}
    allowed_locations = {_normalized(item) for item in policy.get("allowed_locations", [])}
    if allowed_locations and _normalized(opportunity.get("location", "")) not in allowed_locations:
        reasons.append("Location requires confirmation")
    approved_titles = {_normalized(item) for item in policy.get("approved_titles", [])}
    if title not in approved_titles and not policy.get("expansion_authority"):
        reasons.append("Title is outside approved variants")
    source = opportunity.get("resource_class")
    if source not in policy.get("resource_classes", []) and not policy.get("expansion_authority"):
        reasons.append("Source is outside approved resource classes")
    return {"decision":"needs_confirmation" if reasons else "eligible", "reasons":reasons,
            "policy_version":policy.get("version"), "preferences": [item for item in policy.get("disliked_duties", [])
                if any(_normalized(item) in duty for duty in duties)]}


def _operation_path(root, operation_id):
    return workspace_path(root, "operations", identifier(operation_id) + ".json")


def load_operation(root, operation_id):
    value = read_json(_operation_path(root, operation_id))
    if value.get("workspace_id") != load_workspace(root)["id"] or value.get("intent_hash") != _digest(value["intent"]):
        raise CampaignBlocked("Operation intent is corrupted or belongs to another workspace")
    return value


def operations(root):
    return [load_operation(root, path.stem) for path in sorted(workspace_path(root, "operations").glob("*.json"))]


def create_operation(root, opportunity, policy_id, bundle=None, answers=None, recipient=None,
                     action="apply", actor="owner", attachments=None, form_values=None,
                     purpose="application", contact_identity=None):
    """Persist immutable versions before any dispatch; repeated identity returns intent."""
    if action not in SEND_ACTIONS:
        raise AuthorityError("Unsupported outbound action; human decisions cannot be dispatched")
    with locked_workspace(root):
        config = load_workspace(root)
        policy = load_record(root, "campaign-policy", policy_id)
        screening = screen_opportunity(policy, opportunity)
        if screening["decision"] != "eligible":
            raise CampaignBlocked("Opportunity has not passed the current campaign policy")
        opp_id = opportunity_key(opportunity["employer"], opportunity.get("requisition_id"), opportunity.get("url"))
        recipient_id = contact_key(recipient.get("channel"), recipient.get("address"), contact_identity) if recipient else None
        identity = _digest([opp_id if action in {"apply", "submit_proposal"} else recipient_id, action, purpose])
        for previous in operations(root):
            if previous["identity"] == identity:
                return previous
        if action in {"send_message", "connect", "follow_up"} and not recipient_id:
            raise CampaignBlocked("Communication requires an exact recipient")
        if bundle is not None and bundle.get("workspace_id") != config["id"]:
            raise CampaignBlocked("Documents belong to a different workspace")
        snapshots = []
        for answer in answers or []:
            current = load_record(root, "answer", answer["id"])
            if answer.get("version", current["version"]) != current["version"]:
                raise CampaignBlocked("Form answer changed after it was selected")
            selected = confirmed_answer(root, current["question"], current["scope"])
            if selected["id"] != current["id"]:
                raise CampaignBlocked("Form answer was superseded")
            answer_scope = current["scope"]
            if answer_scope["type"] == "employer" and _employer(answer_scope.get("employer", "")) != _employer(opportunity["employer"]):
                raise CampaignBlocked("Employer-specific answer belongs to another employer")
            if answer_scope["type"] == "campaign" and answer_scope.get("campaign_id", policy_id) != policy_id:
                raise CampaignBlocked("Answer belongs to another campaign")
            if current["confirmation"] not in {"confirmed", "confirmed_absent"}:
                raise CampaignBlocked("Unknown or conflicting form answers need clarification")
            snapshots.append(current)
        intent = {"opportunity":deepcopy(opportunity), "opportunity_id":opp_id, "policy":policy,
                  "bundle":deepcopy(bundle), "answers":snapshots, "recipient":deepcopy(recipient),
                  "recipient_id":recipient_id, "action":action, "purpose":purpose,
                  "attachments":deepcopy(attachments or []), "form_values":deepcopy(form_values or {})}
        operation = {"schema_version":1, "id":uuid.uuid4().hex, "workspace_id":config["id"],
                     "identity":identity, "intent":intent, "intent_hash":_digest(intent),
                     "stage":"ready", "acknowledgement":"unmatched", "lifecycle":"pending", "created_at":now()}
        append_event(root, "operation_prepared", actor=actor, operation_id=operation["id"], data={"intent":intent})
        atomic_write_json(_operation_path(root, operation["id"]), operation)
        return deepcopy(operation)


def _save_operation(root, operation):
    _no_secrets(operation)
    atomic_write_json(_operation_path(root, operation["id"]), operation)


def _active_blockers(state, operation=None):
    active = []
    for blocker in state["blockers"]:
        if blocker.get("resolved_at") or blocker.get("expires_at") and blocker["expires_at"] <= now():
            continue
        scope = blocker["scope"]
        if operation is None:
            active.append(blocker)
            continue
        opportunity = operation["intent"]["opportunity"]
        if (not scope or all((operation["id"] if key == "operation_id" else opportunity.get(key)) == value for key, value in scope.items())):
            active.append(blocker)
    return active


def status(root):
    with locked_workspace(root):
        state = _state(root)
        items = operations(root)
        return {"schema_version":1, "workspace_id":load_workspace(root)["id"], "paused":bool(state["pauses"]),
                "pauses":deepcopy(state["pauses"]), "blockers":deepcopy(_active_blockers(state)),
                "operations":[{"id":item["id"], "action":item["intent"]["action"], "stage":item["stage"], "acknowledgement":item["acknowledgement"], "lifecycle":item["lifecycle"]} for item in items],
                "submission_count":sum(item["stage"] == "submission_observed" and item["intent"]["action"] in {"apply", "submit_proposal"} for item in items),
                "acknowledgement_count":sum(item["acknowledgement"] == "matched" and item["intent"]["action"] in {"apply", "submit_proposal"} for item in items),
                "communication_count":sum(item["stage"] == "submission_observed" and item["intent"]["action"] in {"send_message", "connect", "follow_up"} for item in items)}


def set_pause(root, actor, reason="Requested pause"):
    require_action_authority(root, actor, "pause")
    with locked_workspace(root):
        config = load_workspace(root)
        ownership = "operator" if actor == (config["operator"] if config["mode"] == "managed" else config["owner"]) else "client"
        state = _state(root)
        existing = next((item for item in state["pauses"] if item["actor"] == actor), None)
        if not existing:
            state["pauses"].append({"actor":actor, "owner":ownership, "reason":reason, "created_at":now()})
            _save_state(root, state)
            append_event(root, "campaign_paused", actor=actor, data={"reason":reason,"owner":ownership,"notify_operator":config["mode"] == "managed"})
        return status(root)


def resume_campaign(root, actor):
    require_action_authority(root, actor, "resume")
    with locked_workspace(root):
        if any(item["stage"] in {"dispatching", "delivery_unknown"} for item in operations(root)):
            raise CampaignBlocked("Reconcile pending delivery before resuming")
        state = _state(root)
        previous = len(state["pauses"])
        state["pauses"] = [item for item in state["pauses"] if item["actor"] != actor]
        if len(state["pauses"]) != previous:
            _save_state(root, state)
            append_event(root, "own_pause_removed", actor=actor)
        return status(root)


def add_blocker(root, blocker_type, scope, evidence, invalidate_when, responsible_actor,
                actor="owner", expires_at=None):
    if not scope or set(scope) - {"operation_id", "portal", "session", "capability"}:
        raise CampaignBlocked("Blockers need an exact operation/portal/session/capability scope")
    if not evidence or not invalidate_when:
        raise CampaignBlocked("Blockers require observed evidence and an invalidation condition")
    if expires_at:
        datetime.fromisoformat(expires_at)
    with locked_workspace(root):
        state = _state(root)
        for item in _active_blockers(state):
            if item["type"] == blocker_type and item["scope"] == scope and item["evidence"] == evidence:
                return deepcopy(item)
        value = {"id":uuid.uuid4().hex, "type":blocker_type, "scope":deepcopy(scope),
                 "evidence":deepcopy(evidence), "invalidate_when":invalidate_when,
                 "responsible_actor":responsible_actor, "first_observed":now(), "expires_at":expires_at}
        state["blockers"].append(value)
        _save_state(root, state)
        append_event(root, "blocker_observed", actor=actor, data=value)
        return deepcopy(value)


def resolve_blocker(root, blocker_id, actor, evidence):
    if not evidence:
        raise CampaignBlocked("Resolution requires evidence")
    with locked_workspace(root):
        state = _state(root)
        blocker = next((item for item in state["blockers"] if item["id"] == blocker_id), None)
        if not blocker:
            raise CampaignBlocked("Unknown blocker")
        if actor != blocker["responsible_actor"]:
            require_action_authority(root, actor, "change_campaign")
        blocker.update(resolved_at=now(), resolved_by=actor, resolution_evidence=deepcopy(evidence))
        _save_state(root, state)
        append_event(root, "blocker_resolved", actor=actor, data=blocker)
        return deepcopy(blocker)


def preflight_attachments(root, expected, actual, constraints=None):
    """Inspect current files, field ownership, count, type, size and exact hashes."""
    constraints = constraints or {}
    declared_keys = {(item.get("field"), item.get("path")) for item in expected}
    observed_keys = {(item.get("field"), item.get("path")) for item in actual}
    if len(declared_keys) != len(expected) or len(observed_keys) != len(actual) or observed_keys - declared_keys:
        raise CampaignBlocked("Actual form has unexpected or duplicate attachments")
    inspected = []
    for declared in expected:
        observed = next((item for item in actual if item.get("field") == declared.get("field") and item.get("path") == declared.get("path")), None)
        if observed is None:
            if declared.get("required", True):
                raise CampaignBlocked("Actual form is missing a required attachment")
            append_event(root, "optional_attachment_skipped", data={"field":declared.get("field"), "reason":"Not present in actual form"})
            continue
        for field in ("path", "field", "sha256"):
            if declared.get(field) != observed.get(field):
                raise CampaignBlocked("Actual form has a stale or wrong attachment")
        if observed.get("workspace_id") != load_workspace(root)["id"]:
            raise CampaignBlocked("Attachment ownership is not verified")
        path = Path(observed["path"])
        try:
            try:
                relative = path.absolute().relative_to(Path(root).absolute())
            except ValueError:
                relative = path.absolute().relative_to(Path(root).resolve())
        except ValueError as error:
            raise CampaignBlocked("Attachment is outside the candidate workspace") from error
        resolved = workspace_path(root, *relative.parts)
        if not resolved.is_file():
            raise CampaignBlocked("Attachment file is missing")
        payload = resolved.read_bytes()
        if observed.get("mime_type") == "application/pdf" and not payload.startswith(b"%PDF-"):
            raise CampaignBlocked("Attachment does not contain a PDF")
        if hashlib.sha256(payload).hexdigest() != observed["sha256"]:
            raise CampaignBlocked("Attachment changed since preparation")
        rule = constraints.get(observed["field"], {})
        if rule.get("accepted_extensions") and path.suffix.casefold() not in {item.casefold() for item in rule["accepted_extensions"]}:
            raise CampaignBlocked("Attachment extension is not accepted")
        if rule.get("accepted_types") and observed.get("mime_type") not in rule["accepted_types"]:
            raise CampaignBlocked("Attachment type is not accepted")
        if resolved.stat().st_size > rule.get("max_bytes", float("inf")):
            raise CampaignBlocked("Attachment exceeds accepted size")
        if observed["field"] == "cv" and observed.get("role", "cv") != "cv" or observed["field"] == "letter" and observed.get("role", "letter") != "letter":
            raise CampaignBlocked("Supporting documents cannot be routed into CV/letter fields")
        inspected.append(deepcopy(observed))
    for field, rule in constraints.items():
        count = sum(item["field"] == field for item in actual)
        if count > rule.get("max_count", float("inf")) or rule.get("required") and count == 0:
            raise CampaignBlocked("Required attachment or permitted field count is not satisfied")
    return inspected


def _final_preflight(root, operation, actor, actual_form, verify_documents, controlled):
    state = _state(root)
    if state["pauses"] or _active_blockers(state, operation):
        raise CampaignBlocked("Campaign pause or applicable blocker prevents dispatch")
    policy = load_record(root, "campaign-policy", operation["intent"]["policy"]["id"])
    if policy["version"] != operation["intent"]["policy"]["version"]:
        raise CampaignBlocked("Policy changed after operation preparation")
    require_action_authority(root, actor, operation["intent"]["action"], policy)
    for answer in operation["intent"]["answers"]:
        current = confirmed_answer(root, answer["question"], answer["scope"])
        if current["id"] != answer["id"] or current["version"] != answer["version"]:
            raise CampaignBlocked("A prepared answer changed or was superseded before dispatch")
    if screen_opportunity(policy, operation["intent"]["opportunity"])["decision"] != "eligible":
        raise CampaignBlocked("Opportunity fails immediate policy preflight")
    if operation["intent"]["action"] == "submit_proposal" and not operation["intent"].get("opportunity", {}).get("substantive_approval"):
        raise CampaignBlocked("Complex proposals require substantive human approval")
    if operation["intent"]["recipient"] and operation["intent"]["recipient"].get("refused"):
        raise CampaignBlocked("Recipient refused further contact")
    if not controlled and verify_documents is None:
        raise CampaignBlocked("Production dispatch requires a live document/permission verifier")
    if verify_documents is not None and verify_documents(deepcopy(operation["intent"])) is not True:
        raise CampaignBlocked("Current document/permission verification did not pass")
    if actual_form is None:
        raise CampaignBlocked("Inspect actual form fields and recipients immediately before dispatch")
    if actual_form.get("fields", {}) != operation["intent"]["form_values"]:
        raise CampaignBlocked("Actual form values differ from prepared intent")
    for field in ("cc", "bcc"):
        if actual_form.get(field, []) != (operation["intent"]["recipient"] or {}).get(field, []):
            raise CampaignBlocked("Unexpected copied recipients; inspect Reply all")
    if operation["intent"]["purpose"] == "reply" and actual_form.get("quoted_history") and actual_form.get("new_text_position") != "above_quote":
        raise CampaignBlocked("New reply text must appear above quoted history")
    if actual_form.get("recipient") != operation["intent"]["recipient"]:
        raise CampaignBlocked("Actual recipients differ from prepared intent")
    if actual_form.get("validation_errors"):
        raise CampaignBlocked("Current form has unresolved validation errors")
    preflight_attachments(root, operation["intent"]["attachments"], actual_form.get("attachments", []), actual_form.get("constraints"))


def dispatch_operation(root, operation_id, actor, send, actual_form=None, verify_documents=None, controlled=False):
    """Only one outbound callback per workspace, even while controls remain writable."""
    with locked_workspace(root, "runtime/.dispatch.lock"):
        with locked_workspace(root):
            operation = load_operation(root, operation_id)
            _require_idle_dispatcher(root, operation_id)
            if operation["stage"] not in {"ready", "not_sent"}:
                raise CampaignBlocked("Operation is already sent, in-flight or awaiting delivery reconciliation")
            _final_preflight(root, operation, actor, actual_form, verify_documents, controlled)
            operation.update(stage="dispatching", dispatch_started_at=now())
            _save_operation(root, operation)
            append_event(root, "dispatch_started", actor=actor, operation_id=operation_id,
                         data={"intent_hash":operation["intent_hash"]})
        try:
            result = send(deepcopy(operation["intent"]))
            if not isinstance(result, dict) or result.get("status") not in {"submission_observed", "not_sent", "delivery_unknown"}:
                result = {"status":"delivery_unknown", "evidence":{"reason":"Adapter returned no unambiguous delivery observation"}}
            if result["status"] in {"submission_observed", "not_sent"} and not result.get("evidence"):
                result = {"status":"delivery_unknown", "evidence":{"reason":"Adapter did not supply observed delivery evidence"}}
        except BaseException as error:
            with locked_workspace(root):
                operation.update(stage="delivery_unknown", dispatch_ended_at=now())
                _save_operation(root, operation)
                append_event(root, "delivery_unknown", actor=actor, operation_id=operation_id,
                             data={"failure_class":type(error).__name__})
            if not isinstance(error, Exception):
                raise
            return deepcopy(operation)
        with locked_workspace(root):
            operation.update(stage=result["status"], dispatch_ended_at=now(), delivery_evidence=deepcopy(result.get("evidence")))
            _save_operation(root, operation)
            append_event(root, result["status"], actor=actor, operation_id=operation_id,
                         evidence=result.get("evidence"), data={"intent_hash":operation["intent_hash"]})
        return deepcopy(operation)


def recover_dispatches(root, actor="owner"):
    with locked_workspace(root, "runtime/.dispatch.lock"):
        with locked_workspace(root):
            recovered = []
            for item in operations(root):
                if item["stage"] == "dispatching":
                    item["stage"] = "delivery_unknown"
                    _save_operation(root, item)
                    append_event(root, "delivery_unknown", actor=actor, operation_id=item["id"], data={"reason":"Interrupted dispatch; reconcile portal and mailbox before retry"})
                    recovered.append(item["id"])
            return recovered


def reconcile_operation(root, operation_id, outcome, evidence, actor="owner"):
    if outcome not in {"submission_observed", "not_sent"} or not evidence:
        raise CampaignBlocked("Reconciliation requires a definite observed outcome and evidence")
    with locked_workspace(root, "runtime/.dispatch.lock"):
        with locked_workspace(root):
            operation = load_operation(root, operation_id)
            if operation["stage"] != "delivery_unknown":
                raise CampaignBlocked("Only ambiguous delivery can be reconciled")
            operation.update(stage=outcome, delivery_evidence=deepcopy(evidence), reconciled_at=now())
            _save_operation(root, operation)
            append_event(root, "delivery_reconciled", actor=actor, operation_id=operation_id,
                         evidence=evidence, data={"outcome":outcome})
            return deepcopy(operation)


def match_receipt(root, operation_id, receipt, actor="owner"):
    with locked_workspace(root):
        operation = load_operation(root, operation_id)
        expected = operation["intent"]["opportunity"]
        if not receipt.get("evidence") or not receipt.get("requisition_id") or str(receipt["requisition_id"]).casefold() != str(expected.get("requisition_id", "")).casefold() or _employer(receipt.get("employer", "")) != _employer(expected["employer"]):
            append_event(root, "receipt_unmatched", actor=actor, operation_id=operation_id,
                         evidence=receipt.get("evidence"), data={"reason":"No unambiguous employer/requisition match"})
            return False
        operation.update(acknowledgement="matched", acknowledgement_evidence=deepcopy(receipt))
        _save_operation(root, operation)
        append_event(root, "acknowledgement_matched", actor=actor, operation_id=operation_id, evidence=receipt)
        return True


def _binding(root):
    items = list_records(root, "client-binding")
    return items[0] if len(items) == 1 else None


def bind_client(root, client, operator, chat_id, user_id, browser_profile, bot_secret_ref=None):
    with locked_workspace(root):
        config = load_workspace(root)
        if config["mode"] != "managed" or operator != config["operator"]:
            raise AuthorityError("Only the managed workspace operator can bind a client")
        existing = _binding(root)
        if existing and existing["client"] != client:
            raise AuthorityError("A workspace is permanently bound to one client; provision a separate workspace")
        profile = workspace_path(root, "runtime", "browser", identifier(browser_profile))
        binding = {"id":"client", "client":client, "operator":operator, "allowed_chat_id":chat_id,
                   "allowed_user_id":user_id, "confirmed":True, "enabled":True,
                   "browser_profile":str(profile), "processed_update_ids":[]}
        if bot_secret_ref:
            binding["bot_secret_ref"] = bot_secret_ref
        return save_record(root, "client-binding", binding, actor=operator)


def authorize_client(root, chat_id, user_id):
    binding = _binding(root)
    if not binding or not binding["enabled"] or not binding["confirmed"] or str(chat_id) != str(binding["allowed_chat_id"]) or str(user_id) != str(binding["allowed_user_id"]):
        raise AuthorityError("Telegram identity is not bound to this workspace")
    return deepcopy(binding)


def answer_clarification(root, clarification_id, answer, actor, update_id=None):
    require_action_authority(root, actor, "answer_personal")
    with locked_workspace(root):
        item = load_record(root, "clarification", clarification_id)
        if item["intended_actor"] != actor or item["status"] != "pending":
            raise AuthorityError("Only the intended client can answer a pending factual question")
        if item["scope"].get("type") in {"service", "campaign", "access", "price", "commercial"}:
            raise AuthorityError("Service/campaign/access questions belong to operator")
        item.update(status="answered", answer=deepcopy(answer), answer_version=item.get("answer_version", 0) + 1)
        if update_id is not None:
            item["originating_update"] = update_id
        return save_record(root, "clarification", item, actor=actor, expected_version=item["version"])


def verify_operation_documents(root, intent):
    """Re-run document gates and require precisely the prepared artifact bytes."""
    bundle = intent.get("bundle")
    if bundle is None:
        # Text-only correspondence still passes authority, recipient and actual-form
        # preflight; applications and messages carrying files need verified documents.
        return intent.get("action") in {"send_message", "connect", "follow_up"} and not intent.get("attachments")
    if not bundle or bundle.get("workspace_id") != load_workspace(root)["id"]:
        return False
    directory = bundle.get("bundle_dir", bundle.get("directory"))
    if not directory or not bundle.get("artifact_hashes"):
        return False
    try:
        try:
            relative = Path(directory).absolute().relative_to(Path(root).absolute())
        except ValueError:
            relative = Path(directory).absolute().relative_to(Path(root).resolve())
        directory = workspace_path(root, *relative.parts)
    except (ValueError, OSError):
        return False
    from .documents import finalize_bundle
    result = finalize_bundle(directory)
    return result.get("ready") is True and result.get("post_check", {}).get("artifact_hashes") == bundle["artifact_hashes"]


def observe_lifecycle(root, operation_id, lifecycle, evidence, actor="owner"):
    if lifecycle not in {"reply", "interview", "offer", "rejected"} or not evidence:
        raise CampaignBlocked("Record observed replies/invitations/outcomes; human decisions need a handoff")
    with locked_workspace(root):
        item = load_operation(root, operation_id)
        item["lifecycle"] = lifecycle
        _save_operation(root, item)
        append_event(root, "lifecycle_observed", actor=actor, operation_id=operation_id,
                     evidence=evidence, data={"lifecycle":lifecycle})
        return deepcopy(item)


def human_handoff(root, action, context, actor="owner"):
    if action not in HUMAN_RESERVED:
        raise CampaignBlocked("Unknown human-reserved action")
    config = load_workspace(root)
    binding = _binding(root) if config["mode"] == "managed" else None
    responsible = binding["client"] if binding else config["owner"]
    return append_event(root, "human_decision_required", actor=actor,
                        data={"action":action, "responsible_actor":responsible, "context":deepcopy(context)})


def checkpoint(root, operation_id, canonical_url, progress, attachments, next_step, actor="owner"):
    """Persist resumable browser context without cookies, passwords or page captures."""
    from .records import canonical_url as normalize_url
    item = load_operation(root, operation_id)
    value = {"operation_id":operation_id, "canonical_url":normalize_url(canonical_url),
             "progress":deepcopy(progress), "attachments":deepcopy(attachments),
             "next_step":next_step, "intent_hash":item["intent_hash"], "saved_at":now()}
    with locked_workspace(root):
        append_event(root, "checkpoint_saved", actor=actor, operation_id=operation_id, data=value)
        atomic_write_json(workspace_path(root, "runtime", "checkpoints", identifier(operation_id) + ".json"), value)
    return value


def read_material(root, relative_path, actor):
    """Return a copy of an allowed artifact or journal entry, never private secrets."""
    require_action_authority(root, actor, "read_materials")
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or path.parts[0] not in {"artifacts", "events"}:
        raise AuthorityError("Only document artifacts and journal entries may be exported")
    safe = workspace_path(root, *path.parts)
    if not safe.is_file():
        raise CampaignBlocked("Requested material does not exist")
    return safe.read_bytes()


def _require_idle_dispatcher(root, operation_id):
    if any(item["id"] != operation_id and item["stage"] in {"dispatching", "delivery_unknown"} for item in operations(root)):
        raise CampaignBlocked("Another operation is in-flight or requires delivery reconciliation")


def begin_dispatch(root, operation_id, actor, actual_form, verify_documents):
    """Issue a one-use ticket for exactly one agent-native browser/tool action.

    No process lock can span two CLI invocations. Durable dispatching state keeps
    other operations out until the caller completes or explicitly reconciles it.
    """
    with locked_workspace(root, "runtime/.dispatch.lock"):
        with locked_workspace(root):
            operation = load_operation(root, operation_id)
            _require_idle_dispatcher(root, operation_id)
            if operation["stage"] not in {"ready", "not_sent"}:
                raise CampaignBlocked("Operation already dispatched or requires delivery reconciliation")
            _final_preflight(root, operation, actor, actual_form, verify_documents, controlled=False)
            ticket = secrets.token_urlsafe(32)
            operation.update(stage="dispatching", dispatch_started_at=now(),
                bridge_ticket_hash=hashlib.sha256(ticket.encode()).hexdigest(),
                bridge_intent_hash=operation["intent_hash"], bridge_actor=actor)
            _save_operation(root, operation)
            append_event(root, "native_dispatch_authorized", actor=actor, operation_id=operation_id,
                         data={"intent_hash":operation["intent_hash"]})
            return {"operation_id":operation_id, "ticket":ticket,
                    "intent":deepcopy(operation["intent"]), "intent_hash":operation["intent_hash"]}


def complete_dispatch(root, operation_id, ticket, outcome, evidence):
    """Observe one authorized native action; ambiguity consumes its ticket too."""
    if outcome not in {"submission_observed", "not_sent", "delivery_unknown"}:
        raise CampaignBlocked("Native completion needs a supported observed delivery outcome")
    with locked_workspace(root, "runtime/.dispatch.lock"):
        with locked_workspace(root):
            operation = load_operation(root, operation_id)
            token_hash = hashlib.sha256(ticket.encode()).hexdigest() if isinstance(ticket, str) else ""
            if operation["stage"] != "dispatching" or not operation.get("bridge_ticket_hash") or not hmac.compare_digest(operation["bridge_ticket_hash"], token_hash):
                raise AuthorityError("Invalid, spent or recovered native dispatch ticket")
            if operation.get("bridge_intent_hash") != operation["intent_hash"]:
                raise CampaignBlocked("Prepared intent changed after native action authorization")
            if outcome != "delivery_unknown" and not evidence:
                outcome = "delivery_unknown"
            operation.update(stage=outcome, dispatch_ended_at=now(), delivery_evidence=deepcopy(evidence))
            operation.pop("bridge_ticket_hash")
            _save_operation(root, operation)
            append_event(root, outcome, actor=operation["bridge_actor"], operation_id=operation_id,
                         evidence=evidence, data={"intent_hash":operation["intent_hash"], "adapter":"agent_native"})
            return deepcopy(operation)
