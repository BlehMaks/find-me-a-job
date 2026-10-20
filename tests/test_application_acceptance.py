import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fmj.workspace import create_workspace
from fmj.records import read_events, save_record
from fmj.campaign import (AuthorityError, CampaignBlocked, add_blocker, create_operation,
    dispatch_operation, load_operation, preflight_attachments, resolve_blocker, status)


def make_policy(root):
    return save_record(root, "campaign-policy", {"id":"campaign-1", "approved":True,
        "markets":["example"], "languages":["en"], "approved_titles":["Researcher"],
        "hard_exclusions":{}, "resource_classes":["official"], "expansion_authority":False})


class ApplicationAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.config = create_workspace(self.root)
        make_policy(self.root)
        self.opportunity = {"employer":"Synthetic Lab", "requisition_id":"R1", "title":"Researcher",
            "resource_class":"official", "portal":"portal-1", "session":"session-1"}

    def attachment(self, field="cv", required=True):
        path = self.root / "artifacts" / (field + ".pdf")
        path.write_bytes(b"%PDF-1.7\nsynthetic upload fixture")
        return {"path":str(path), "field":field, "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                "workspace_id":self.config["id"], "mime_type":"application/pdf", "required":required}

    def send(self, operation, actual_form):
        return dispatch_operation(self.root, operation["id"], "owner", lambda _: {"status":"submission_observed", "evidence":"portal confirmed"}, actual_form=actual_form, controlled=True)

    def test_preflight_rejects_stale_upload_missing_validation_and_oversize(self):
        attachment = self.attachment()
        operation = create_operation(self.root, self.opportunity, "campaign-1", attachments=[attachment], form_values={"name":"Synthetic Candidate"})
        form = {"recipient":None, "attachments":[attachment], "fields":{"name":"Old Autofill"}}
        with self.assertRaisesRegex(CampaignBlocked, "values"):
            self.send(operation, form)
        form["fields"] = {"name":"Synthetic Candidate"}
        form["validation_errors"] = ["Required declaration"]
        with self.assertRaisesRegex(CampaignBlocked, "validation"):
            self.send(operation, form)
        form.pop("validation_errors")
        form["constraints"] = {"cv":{"max_bytes":4}}
        with self.assertRaisesRegex(CampaignBlocked, "size"):
            self.send(operation, form)
        form["constraints"] = {"cv":{"accepted_extensions":[".pdf"], "accepted_types":["application/pdf"], "max_count":1}}
        Path(attachment["path"]).write_bytes(b"%PDF-1.7\nchanged after verification")
        with self.assertRaisesRegex(CampaignBlocked, "changed"):
            self.send(operation, form)
        self.assertEqual(load_operation(self.root, operation["id"])["stage"], "ready")

    def test_supporting_docs_wrong_client_and_optional_failure(self):
        attachment = self.attachment()
        wrong = dict(attachment, workspace_id="other-client")
        with self.assertRaisesRegex(CampaignBlocked, "ownership"):
            preflight_attachments(self.root, [wrong], [wrong])
        misrouted = dict(attachment, role="reference")
        with self.assertRaisesRegex(CampaignBlocked, "Supporting"):
            preflight_attachments(self.root, [misrouted], [misrouted])
        optional = self.attachment("supporting", required=False)
        operation = create_operation(self.root, self.opportunity, "campaign-1", attachments=[attachment, optional])
        result = self.send(operation, {"fields":{}, "recipient":None, "attachments":[attachment]})
        self.assertEqual(result["stage"], "submission_observed")
        self.assertIn("optional_attachment_skipped", [event["type"] for event in read_events(self.root)])

    def test_required_pdf_field_contract_from_observed_fixture(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/forms/attachment-fields.json").read_text())
        constraints = fixture["constraints"]
        with self.assertRaisesRegex(CampaignBlocked, "Required attachment"):
            preflight_attachments(self.root, [], [], constraints)
        cv = self.attachment()
        self.assertEqual(len(preflight_attachments(self.root, [cv], [cv], constraints)), 1)
        wrong = dict(cv, mime_type="text/plain")
        with self.assertRaisesRegex(CampaignBlocked, "type"):
            preflight_attachments(self.root, [wrong], [wrong], constraints)

    def test_shared_login_blocker_does_not_block_unrelated_portals(self):
        blocker = add_blocker(self.root, "login", {"portal":"portal-1", "session":"session-1"},
            "Login form observed", "User completes permitted credential handoff", "owner")
        duplicate = add_blocker(self.root, "login", {"portal":"portal-1", "session":"session-1"},
            "Login form observed", "User completes permitted credential handoff", "owner")
        self.assertEqual(blocker["id"], duplicate["id"])
        blocked = create_operation(self.root, self.opportunity, "campaign-1")
        other = create_operation(self.root, dict(self.opportunity, portal="portal-2", requisition_id="R2"), "campaign-1")
        with self.assertRaises(CampaignBlocked):
            self.send(blocked, {"fields":{}, "recipient":None, "attachments":[]})
        self.assertEqual(self.send(other, {"fields":{}, "recipient":None, "attachments":[]})["stage"], "submission_observed")
        resolve_blocker(self.root, blocker["id"], "owner", "Authenticated session observed")
        self.assertEqual(status(self.root)["blockers"], [])
        self.assertIn("blocker_resolved", [event["type"] for event in read_events(self.root)])

    def test_wrong_recipient_reply_all_and_quote_placement(self):
        recipient = {"channel":"email", "address":"recruiter@example.invalid"}
        operation = create_operation(self.root, self.opportunity, "campaign-1", action="send_message", recipient=recipient, purpose="reply")
        form = {"fields":{}, "attachments":[], "recipient":dict(recipient, address="wrong@example.invalid")}
        with self.assertRaisesRegex(CampaignBlocked, "recipients"):
            self.send(operation, form)
        form["recipient"] = recipient
        form["cc"] = ["unintended@example.invalid"]
        with self.assertRaisesRegex(CampaignBlocked, "copied"):
            self.send(operation, form)
        form.pop("cc")
        form.update(quoted_history="Old thread", new_text_position="inside_quote")
        with self.assertRaisesRegex(CampaignBlocked, "above"):
            self.send(operation, form)
        form["new_text_position"] = "above_quote"
        self.assertEqual(self.send(operation, form)["stage"], "submission_observed")

    def test_answer_scope_supersession_and_stale_policy(self):
        answer = save_record(self.root, "answer", {"id":"answer-1", "question":"Travel?", "answer":"Yes",
            "scope":{"type":"employer", "employer":"Other Lab"}, "confirmation":"confirmed",
            "confirmed_by":"candidate", "confirmed_at":"2026-01-01T00:00:00+00:00"})
        with self.assertRaisesRegex(CampaignBlocked, "another employer"):
            create_operation(self.root, self.opportunity, "campaign-1", answers=[answer])
        operation = create_operation(self.root, self.opportunity, "campaign-1")
        make_policy(self.root)
        with self.assertRaisesRegex(CampaignBlocked, "Policy changed"):
            self.send(operation, {"fields":{}, "recipient":None, "attachments":[]})

    def test_timeout_is_scoped_not_a_global_permission_diagnosis(self):
        with self.assertRaisesRegex(CampaignBlocked, "exact"):
            add_blocker(self.root, "timeout", {}, "One button timed out", "Retry visible control", "owner")
        operation = create_operation(self.root, self.opportunity, "campaign-1")
        callback = lambda _: {"status":"delivery_unknown", "evidence":"Upload timed out; status unobserved"}
        result = dispatch_operation(self.root, operation["id"], "owner", callback,
            actual_form={"fields":{}, "recipient":None, "attachments":[]}, controlled=True)
        self.assertEqual(result["stage"], "delivery_unknown")
        self.assertEqual(status(self.root)["blockers"], [])

    def test_outreach_is_not_counted_as_an_application(self):
        application = create_operation(self.root, self.opportunity, "campaign-1")
        self.send(application, {"fields":{}, "recipient":None, "attachments":[]})
        recipient = {"channel":"email", "address":"researcher@example.invalid"}
        outreach = create_operation(self.root, self.opportunity, "campaign-1", action="send_message", recipient=recipient)
        self.send(outreach, {"fields":{}, "recipient":recipient, "attachments":[]})
        current = status(self.root)
        self.assertEqual(current["submission_count"], 1)
        self.assertEqual(current["communication_count"], 1)
        self.assertEqual({item["action"] for item in current["operations"]}, {"apply", "send_message"})
