"""Linked operational records and derived queues; no model calls for bookkeeping."""
from datetime import datetime, timedelta
import json
import re
import uuid
from zoneinfo import ZoneInfo

from . import store
from .records import _digest, _no_secrets, canonical_url, contact_key
from .workspace import WorkspaceError, load_workspace, locked_workspace, now


def _effect(root, kind, entity_id, value, previous=None):
    if value == previous or load_workspace(root).get('migration_pending'):
        return
    from .records import append_event
    # State transitions are captured by code; agents do not write a second report.
    summary={key:value[key] for key in ('status','owner','due_at','deadline_source','selected_contact','direct_reason') if key in value}
    append_event(root,kind,actor='runtime',entity_id=entity_id,data={'record_hash':_digest(value),**summary})


def _company_name(value):
    value = " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())
    return re.sub(r"\s+(gmbh|ag|inc|ltd|limited|ab|llc|corp|corporation)$", "", value)


def company(root, name, aliases=None, parent_id=None, group_evidence=None, **details):
    if not isinstance(name, str) or not name.strip():
        raise WorkspaceError("Company name is required")
    if set(details)&{'id','created_at'}:
        raise WorkspaceError('Company identity and creation time are runtime-owned')
    _no_secrets(details)
    with locked_workspace(root):
        db = store.connection(root)
        normalized = {_company_name(item) for item in [name, *(aliases or [])]}
        if "" in normalized:
            raise WorkspaceError("Company aliases must be nonempty")
        matches = {row[0] for alias in normalized for row in db.execute(
            "SELECT company_id FROM company_aliases WHERE kind='name' AND value=?", (alias,))}
        if len(matches) > 1:
            raise WorkspaceError("Company aliases conflict; review identity before linking")
        key = next(iter(matches), uuid.uuid4().hex)
        prior = db.execute("SELECT payload FROM companies WHERE id=?", (key,)).fetchone()
        value = json.loads(prior[0]) if prior else {"id":key, "name":name, "created_at":now()}
        if parent_id and (parent_id == key or not group_evidence):
            raise WorkspaceError("Company group relationship requires distinct parent and evidence")
        if parent_id:
            cursor, seen = parent_id, {key}
            while cursor:
                if cursor in seen:
                    raise WorkspaceError("Company groups cannot contain cycles")
                seen.add(cursor)
                parent = db.execute("SELECT parent_id FROM companies WHERE id=?", (cursor,)).fetchone()
                if not parent:
                    raise WorkspaceError("Parent company must be registered first")
                cursor = parent[0]
            value.update(parent_id=parent_id, group_evidence=group_evidence)
        value.update(details)
        db.execute("INSERT INTO companies VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id,payload=excluded.payload",
                   (key, value["name"], value.get("parent_id"), store.encode(value)))
        for alias in normalized:
            db.execute("INSERT OR IGNORE INTO company_aliases VALUES('name',?,?)", (alias, key))
        _effect(root,'company_recorded',key,value,json.loads(prior[0]) if prior else None)
        return value


def opportunity(root, value):
    _no_secrets(value)
    for field in ('discovered_at','published_at','deadline'):
        if value.get(field) and datetime.fromisoformat(value[field]).tzinfo is None:
            raise WorkspaceError('Opportunity dates must include timezone')
    with locked_workspace(root):
        db = store.connection(root)
        employer = company(root, value["employer"])
        aliases = []
        if value.get("requisition_id"):
            aliases.append(("requisition", str(value["requisition_id"]).strip().casefold()))
        if value.get("url"):
            aliases.append(("url", canonical_url(value["url"])))
        if not aliases:
            raise WorkspaceError("Opportunity needs a requisition ID or canonical URL")
        matches = {row[0] for kind, alias in aliases for row in db.execute(
            "SELECT opportunity_id FROM opportunity_aliases WHERE company_id=? AND kind=? AND value=?",
            (employer["id"], kind, alias))}
        if len(matches) > 1:
            raise WorkspaceError("Opportunity aliases conflict; preserve both histories for identity review")
        key = next(iter(matches), uuid.uuid4().hex)
        prior = db.execute("SELECT payload FROM opportunities WHERE id=?", (key,)).fetchone()
        result = json.loads(prior[0]) if prior else {"id":key, "discovered_at":now()}
        result.update(value)
        result.update(id=key, company_id=employer["id"])
        db.execute("INSERT INTO opportunities VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,payload=excluded.payload",
                   (key, employer["id"], result.get("title", ""), result["discovered_at"], store.encode(result)))
        for kind, alias in aliases:
            db.execute("INSERT OR IGNORE INTO opportunity_aliases VALUES(?,?,?,?)", (employer["id"], kind, alias, key))
        _effect(root,'opportunity_recorded',key,result,json.loads(prior[0]) if prior else None)
        return result


def application(root, opp_id, policy_id, application_class="employment", historical=False):
    db = store.connection(root)
    prior = db.execute("SELECT id FROM applications WHERE opportunity_id=? AND application_class=?", (opp_id, application_class)).fetchone()
    if prior:
        return prior[0]
    key = uuid.uuid4().hex
    db.execute("INSERT INTO applications VALUES(?,?,?,?,NULL,?)", (key, opp_id, application_class, policy_id, int(historical)))
    return key


def contact(root, channel, address, identity=None, company_id=None, refused=False, **details):
    if 'id' in details:
        raise WorkspaceError('Contact identity is runtime-owned')
    with locked_workspace(root):
        key = contact_key(channel, address, identity)
        db = store.connection(root)
        prior = db.execute("SELECT payload FROM contacts WHERE id=?", (key,)).fetchone()
        value = json.loads(prior[0]) if prior else {"id":key, "channel":channel, "address":address}
        value.update(details, refused=bool(refused or value.get("refused")))
        if company_id:
            value["company_id"] = company_id
        _no_secrets(value)
        db.execute("INSERT INTO contacts VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET company_id=excluded.company_id,payload=excluded.payload",
                   (key, value.get("company_id"), store.encode(value)))
        _effect(root,'contact_recorded',key,value,json.loads(prior[0]) if prior else None)
        return value


def conversation(root, person, opportunity_id, policy_id, thread_id=None):
    db = store.connection(root)
    key = _digest([person["id"], person["channel"], thread_id or [policy_id, opportunity_id]])
    value = {"id":key, "contact_id":person["id"], "external_thread":thread_id,
             "opportunity_id":opportunity_id, "campaign_id":policy_id}
    db.execute("INSERT OR IGNORE INTO conversations VALUES(?,?,?)", (key, person["id"], store.encode(value)))
    return key


def save_operation(root, operation, historical=False):
    _no_secrets(operation)
    db = store.connection(root)
    app_id = operation.get("application_id")
    if app_id and operation["stage"] == "submission_observed" and not operation.get("route_snapshot"):
        wait = db.execute("SELECT payload FROM referral_waits WHERE opportunity_id=?", (operation["opportunity_id"],)).fetchone()
        referral_state = json.loads(wait[0]) if wait else None
        operation["route_snapshot"] = {"route":"unknown" if operation.get("submission_basis") == "matched_receipt" else "referral" if referral_state and referral_state["status"] == "selected" else "direct",
                                       "referral":referral_state}
    db.execute("INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET stage=excluded.stage,payload=excluded.payload",
        (operation["id"], operation["identity"], operation.get("opportunity_id", operation["intent"]["opportunity_id"]),
         app_id, operation.get("revision", 1), operation["intent"]["action"], operation["stage"],
         operation["created_at"], store.encode(operation)))
    if operation.get("dispatch_started_at"):
        attempt_id = _digest([operation["id"], operation["dispatch_started_at"]])
        elapsed=None
        if operation.get('dispatch_ended_at'):
            duration=(datetime.fromisoformat(operation['dispatch_ended_at'])-datetime.fromisoformat(operation['dispatch_started_at'])).total_seconds()
            elapsed=duration if duration>=0 else None
        db.execute("INSERT INTO attempts VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET stage=excluded.stage,payload=excluded.payload",
                   (attempt_id, operation["id"], operation["dispatch_started_at"], operation["stage"], store.encode({
                       "outcome":operation["stage"], "evidence":operation.get("delivery_evidence"),'elapsed_seconds':elapsed})))
    if app_id and operation["stage"] == "submission_observed":
        db.execute("UPDATE applications SET submitted_at=COALESCE(submitted_at,?) WHERE id=?",
                   (operation.get("dispatch_ended_at", operation.get("reconciled_at", now())), app_id))
        if not historical:
            campaign_id = db.execute("SELECT campaign_id FROM applications WHERE id=?", (app_id,)).fetchone()[0]
            count = db.execute("SELECT COUNT(*) FROM applications WHERE campaign_id=? AND historical=0 AND submitted_at IS NOT NULL", (campaign_id,)).fetchone()[0]
            for threshold in range(50, count + 1, 50):
                value = {"campaign_id":campaign_id, "threshold":threshold, "created_at":now(),
                         "questions":["Are the opportunities relevant?", "Which unexpected directions interest you?", "What should change or be excluded?"]}
                db.execute("INSERT OR IGNORE INTO campaign_reviews(campaign_id,threshold,payload) VALUES(?,?,?)", (campaign_id, threshold, store.encode(value)))


def import_operation(root, operation):
    """Retain original immutable intent/hash even when canonical identity improves."""
    value = dict(operation)
    opp = opportunity(root, value["intent"]["opportunity"])
    value["opportunity_id"] = opp["id"]
    value["revision"] = 1
    if value["intent"]["action"] in {"apply", "submit_proposal"}:
        value["application_id"] = application(root, opp["id"], value["intent"]["policy"]["id"],
            "proposal" if value["intent"]["action"] == "submit_proposal" else "employment", historical=True)
        value["revision"] = store.connection(root).execute("SELECT COUNT(*)+1 FROM operations WHERE application_id=?", (value["application_id"],)).fetchone()[0]
    save_operation(root, value, historical=True)
    if value.get('application_id') and value.get('historical_submission_at'):
        store.connection(root).execute('UPDATE applications SET submitted_at=COALESCE(submitted_at,?) WHERE id=?',
            (value['historical_submission_at'],value['application_id']))


def action(root, kind, owner, operation_id=None, due_at=None, deadline_source=None,
           evidence=None, action_id=None, status="pending", blocker=None, **details):
    if not kind or not owner or status not in {"pending", "blocked", "completed", "cancelled"}:
        raise WorkspaceError("Action requires kind, owner and supported status")
    if due_at and (datetime.fromisoformat(due_at).tzinfo is None or not deadline_source):
        raise WorkspaceError("Deadline requires timezone and its source")
    if status in {"completed", "cancelled"} and not evidence:
        raise WorkspaceError("Resolving an action requires evidence")
    with locked_workspace(root):
        db = store.connection(root)
        key = action_id or uuid.uuid4().hex
        prior = db.execute("SELECT payload FROM actions WHERE id=?", (key,)).fetchone()
        if prior and (json.loads(prior[0])["kind"] != kind or json.loads(prior[0])["operation_id"] != operation_id):
            raise WorkspaceError("Action identity belongs to another obligation")
        if prior and json.loads(prior[0])["status"] == "completed" and status in {"pending", "blocked"}:
            raise WorkspaceError("Completed action cannot reopen without a separate contrary-evidence observation")
        previous = json.loads(prior[0]) if prior else {}
        if previous.get("status") == "selected" and (status == "waiting" or selected_contact and selected_contact != previous.get("selected_contact")):
            raise WorkspaceError("A chosen referral route cannot silently become another request")
        value = {**previous, **details, "id":key, "kind":kind, "owner":owner, "operation_id":operation_id,
            "due_at":due_at, "deadline_source":deadline_source, "time_zone":load_workspace(root)["time_zone"],
            "status":status, "evidence":evidence, "blocker":blocker, "updated_at":now()}
        _no_secrets(value)
        db.execute("INSERT INTO actions VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,status=excluded.status,due_at=excluded.due_at,payload=excluded.payload",
                   (key, operation_id, owner, status, due_at, store.encode(value)))
        _effect(root,'action_recorded',key,value,previous)
        return value


def referral(root, opportunity_id, contacts=None, status="waiting", selected_contact=None,
             evidence=None, direct_reason=None, policy=None, clock=None, policy_id=None):
    with locked_workspace(root):
        db = store.connection(root)
        opp_row = db.execute("SELECT payload FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
        if not opp_row:
            raise WorkspaceError("Unknown referral opportunity")
        opp = json.loads(opp_row[0])
        from .records import load_record
        approved = load_record(root,"campaign-policy",policy_id).get("referral_policy",{}) if policy_id else {}
        company_row = db.execute("SELECT payload FROM companies WHERE id=?", (opp["company_id"],)).fetchone()
        company_data = json.loads(company_row[0])
        company_rules = company_data.get("referral_policy",{}) if company_data.get("referral_evidence") else {}
        rules = {"max_contacts":3, "business_days":3, "fresh_hours":48, "fresh_direct":True, **approved, **company_rules}
        if policy and any(policy.get(k,rules[k]) != rules[k] for k in rules):
            raise WorkspaceError("Referral overrides belong in approved campaign or verified company rules")
        if any(type(rules[k]) is not int or rules[k] < 1 for k in ("max_contacts", "business_days", "fresh_hours")):
            raise WorkspaceError("Referral limits must be positive integers")
        prior = db.execute("SELECT payload FROM referral_waits WHERE opportunity_id=?", (opportunity_id,)).fetchone()
        previous = json.loads(prior[0]) if prior else {}
        people = list(dict.fromkeys([*previous.get("contacts", []), *(contacts or [])]))
        if len(people) > rules["max_contacts"]:
            raise WorkspaceError("Referral parallel contact limit exceeded")
        for person_id in people:
            person = db.execute("SELECT payload,company_id FROM contacts WHERE id=?", (person_id,)).fetchone()
            if not person or json.loads(person[0]).get("refused") or person[1] != opp["company_id"]:
                raise WorkspaceError("Referral contact must be relevant, registered and not refused")
        current = clock or datetime.now(ZoneInfo(load_workspace(root)["time_zone"]))
        if current.tzinfo is None:
            raise WorkspaceError("Referral clock must include a timezone")
        until = current
        for _ in range(rules["business_days"]):
            until += timedelta(days=1)
            while until.weekday() >= 5:
                until += timedelta(days=1)
        if opp.get("deadline"):
            cutoff = datetime.fromisoformat(opp["deadline"])
            if cutoff.tzinfo is None:
                raise WorkspaceError("Opportunity deadline must include timezone")
            until = min(until, cutoff)
        if status not in {"waiting", "selected", "direct"}:
            raise WorkspaceError("Unsupported referral state")
        if company_rules.get("application_first") and status == "waiting":
            status="direct"
            direct_reason="employer_requires_application_first"
            evidence=company_data["referral_evidence"]
        if status == "selected" and (selected_contact not in people or not evidence):
            raise WorkspaceError("Selected referral needs a tracked contact and observed evidence")
        if status == "direct":
            published = datetime.fromisoformat(opp["published_at"]) if opp.get("published_at") else None
            fresh = bool(published and published.tzinfo and opp.get("publication_evidence") and timedelta(0) <= current-published <= timedelta(hours=rules["fresh_hours"]))
            elapsed = bool(previous.get("wait_until") and current >= datetime.fromisoformat(previous["wait_until"]))
            unavailable = direct_reason in {"no_relevant_contacts", "employer_requires_application_first"}
            if not direct_reason or not evidence or not (fresh and rules["fresh_direct"] or elapsed or opp.get("deadline") and until <= current or unavailable):
                raise WorkspaceError("Direct exception needs verified freshness, elapsed wait or deadline and a documented reason")
        value = {"opportunity_id":opportunity_id, "contacts":people, "status":status,
            "started_at":previous.get("started_at", current.isoformat()),
            "wait_until":previous.get("wait_until", until.isoformat()), "selected_contact":selected_contact,
            "evidence":evidence, "direct_reason":direct_reason, "policy":rules}
        _no_secrets(value)
        db.execute("INSERT INTO referral_waits VALUES(?,?) ON CONFLICT(opportunity_id) DO UPDATE SET payload=excluded.payload", (opportunity_id, store.encode(value)))
        _effect(root,'referral_recorded',opportunity_id,value,previous)
        return value


def review(root, campaign_id, threshold, response, actor):
    from .campaign import require_action_authority
    require_action_authority(root,actor,"change_campaign")
    if not response:
        raise WorkspaceError("Direction review needs the person's response")
    with locked_workspace(root):
        db=store.connection(root)
        row=db.execute("SELECT payload FROM campaign_reviews WHERE campaign_id=? AND threshold=?",(campaign_id,threshold)).fetchone()
        if not row:
            raise WorkspaceError("Unknown direction review boundary")
        value={**json.loads(row[0]),"response":response,"actor":actor,"answered_at":now(),"status":"answered"}
        _no_secrets(value)
        db.execute("UPDATE campaign_reviews SET status='answered',payload=? WHERE campaign_id=? AND threshold=?",(store.encode(value),campaign_id,threshold))
        _effect(root,'direction_review_answered',campaign_id,value)
        return value


def evidence(root, terms):
    """Return current references before an agent labels experience a gap."""
    from .records import list_records, validate_claim
    if not isinstance(terms,list) or not terms or len(terms)>30 or any(not isinstance(t,str) or not t.strip() for t in terms):
        raise WorkspaceError("Evidence lookup needs 1..30 nonempty skill terms")
    facts=list_records(root,"fact");claims=list_records(root,"claim")
    superseded={f.get("supersedes") for f in facts}
    normalize=lambda value:re.sub(r"[^\w]+","",str(value).casefold())
    result=[]
    for term in terms:
        found=[];absent=[]
        for fact in facts:
            if fact['id'] in superseded:continue
            if normalize(term) in normalize(str(fact.get('field',''))+' '+str(fact.get('value',''))):
                ref={"kind":"fact","id":fact['id'],"version":fact['version']}
                if fact['status'] in {'candidate_confirmed','document_supported'}:found.append(ref)
                elif fact['status']=='confirmed_absent':absent.append(ref)
        for claim in claims:
            if normalize(term) in normalize(claim.get('safe_wording','')):
                try:validate_claim(root,claim)
                except ValueError:continue
                found.append({"kind":"claim","id":claim['id'],"version":claim['version']})
        result.append({"term":term,"status":"conflicting" if found and absent else "evidence_found" if found else "confirmed_absent" if absent else "unknown",
                       "references":found+absent,"next_action":"Inspect references and proficiency context; text matching alone does not establish direct expertise."})
    return result


def query(root, kind, entity_id=None, limit=25):
    tables = {"companies":"companies", "opportunities":"opportunities", "documents":"documents",
        "contacts":"contacts", "actions":"actions", "referrals":"referral_waits", "reviews":"campaign_reviews", "inbox":"inbox_requests",
        "operations":"operations", "events":"events", "attempts":"attempts", "applications":"applications"}
    if kind not in tables or type(limit) is not int or not 1 <= limit <= 500:
        raise WorkspaceError("Choose a supported registry and limit 1..500")
    table = tables[kind]
    if kind == "applications":
        return store.rows(root,"SELECT * FROM applications" + (" WHERE id=?" if entity_id else "") + " LIMIT ?", (entity_id,limit) if entity_id else (limit,))
    if kind == "events":
        return store.payloads(root,"events", " WHERE operation_id=? OR entity_id=? ORDER BY sequence DESC LIMIT ?", (entity_id,entity_id,limit))
    if entity_id:
        if kind in {"reviews", "referrals"}:
            field = "campaign_id" if kind == "reviews" else "opportunity_id"
        else:
            field = "id"
        return store.payloads(root, table, f" WHERE {field}=? LIMIT ?", (entity_id, limit))
    return store.payloads(root, table, " LIMIT ?", (limit,))


def report(root):
    with locked_workspace(root):
        db = store.connection(root)
        return {"opportunities":db.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
            "applications":db.execute("SELECT COUNT(*) FROM applications WHERE submitted_at IS NOT NULL").fetchone()[0],
            "receipt_count":db.execute("SELECT COUNT(DISTINCT application_id) FROM receipts").fetchone()[0],
            "by_source":[dict(row) for row in db.execute("SELECT json_extract(o.payload,'$.resource_class') AS source,COUNT(*) AS submitted FROM applications a JOIN opportunities o ON o.id=a.opportunity_id WHERE a.submitted_at IS NOT NULL GROUP BY source")],
            "by_company":[dict(row) for row in db.execute("SELECT c.id,c.name,c.parent_id,COUNT(*) AS submitted FROM applications a JOIN opportunities o ON o.id=a.opportunity_id JOIN companies c ON c.id=o.company_id WHERE a.submitted_at IS NOT NULL GROUP BY c.id")],
            'by_company_group':[dict(row) for row in db.execute("WITH RECURSIVE groups(id,root_id) AS (SELECT id,id FROM companies WHERE parent_id IS NULL UNION ALL SELECT c.id,g.root_id FROM companies c JOIN groups g ON c.parent_id=g.id) SELECT g.root_id,c.name,COUNT(*) AS submitted FROM applications a JOIN opportunities o ON o.id=a.opportunity_id JOIN groups g ON g.id=o.company_id JOIN companies c ON c.id=g.root_id WHERE a.submitted_at IS NOT NULL GROUP BY g.root_id")],
            "by_route":[dict(row) for row in db.execute("SELECT json_extract(payload,'$.route_snapshot.route') AS route,COUNT(DISTINCT application_id) AS submitted FROM operations WHERE stage='submission_observed' AND application_id IS NOT NULL GROUP BY route")],
            "milestones":[dict(row) for row in db.execute("SELECT milestone.value AS milestone,COUNT(DISTINCT COALESCE(operation.application_id,operation.opportunity_id)) AS processes FROM operations operation,json_each(operation.payload,'$.milestones') milestone GROUP BY milestone.value")],
            'outbound_elapsed_seconds':db.execute("SELECT SUM(json_extract(payload,'$.elapsed_seconds')) FROM attempts").fetchone()[0],
            'cohort_age_days':[dict(row) for row in db.execute("SELECT CAST(julianday('now')-julianday(submitted_at) AS INTEGER) AS observed_age_days,COUNT(*) AS applications FROM applications WHERE submitted_at IS NOT NULL GROUP BY observed_age_days")],
            "pending_actions":store.payloads(root, "actions", " WHERE status IN ('pending','blocked') ORDER BY due_at IS NULL,due_at LIMIT 25"),
            "direction_reviews":store.payloads(root, "campaign_reviews", " WHERE status='pending' ORDER BY campaign_id,threshold"),
            "referral_waits":store.payloads(root,"referral_waits"," WHERE json_extract(payload,'$.status')='waiting' ORDER BY json_extract(payload,'$.wait_until') LIMIT 25"),
            "observation_limits":"Counts are observed records; receipt absence is not failure. Interview cohorts need an explicit observation window. Effort is unknown unless observed."}
