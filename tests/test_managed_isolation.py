from pathlib import Path
import tempfile
import unittest

from fmj.workspace import create_workspace
from fmj.records import RecordError, load_record, save_record
from fmj.campaign import (AuthorityError, CampaignBlocked, answer_clarification,
    authorize_client, bind_client, grant_authority, require_action_authority, resume_campaign,
    set_pause, status)


class ManagedIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "client-a"
        self.other = Path(self.temp.name) / "client-b"
        create_workspace(self.root, mode="managed", owner="client-a", operator="operator")
        create_workspace(self.other, mode="managed", owner="client-b", operator="operator")
        self.binding = bind_client(self.root, "client-a", "operator", 101, 201, "client-a-browser")
        bind_client(self.other, "client-b", "operator", 102, 202, "client-b-browser")

    def test_authenticated_identity_and_distinct_browser_bindings(self):
        self.assertEqual(authorize_client(self.root, 101, 201)["client"], "client-a")
        for chat, user in ((102,202), (101,202), (102,201)):
            with self.assertRaises(AuthorityError):
                authorize_client(self.root, chat, user)
        other = authorize_client(self.other, 102, 202)
        self.assertNotEqual(self.binding["browser_profile"], other["browser_profile"])
        with self.assertRaises(RecordError):
            save_record(self.other, "client-binding", self.binding)

    def test_workspace_client_binding_cannot_be_reassigned(self):
        with self.assertRaisesRegex(AuthorityError, "permanently"):
            bind_client(self.root, "client-b", "operator", 303, 404, "other-browser")
        current = authorize_client(self.root, 101, 201)
        self.assertEqual(current["client"], "client-a")
        self.assertEqual(current["version"], self.binding["version"])
        # Rotating the same client's explicitly confirmed chat remains supported.
        changed = bind_client(self.root, "client-a", "operator", 111, 211, "new-browser")
        self.assertEqual(changed["client"], "client-a")
        with self.assertRaises(AuthorityError):
            authorize_client(self.root, 101, 201)

    def test_client_resume_only_own_pause_no_access_or_financial_mutation(self):
        set_pause(self.root, "operator", "Operator review")
        set_pause(self.root, "client-a", "Client request")
        resumed = resume_campaign(self.root, "client-a")
        self.assertTrue(resumed["paused"])
        self.assertEqual([item["actor"] for item in resumed["pauses"]], ["operator"])
        self.assertFalse(status(self.other)["paused"])
        self.assertTrue(load_record(self.root, "client-binding", "client")["enabled"])
        self.assertEqual(resume_campaign(self.root, "operator")["pauses"], [])
        for action in ("change_campaign", "manage_access", "commercial_terms", "manage_resources"):
            with self.assertRaises(AuthorityError):
                require_action_authority(self.root, "client-a", action)
        with self.assertRaises(AuthorityError):
            grant_authority(self.root, "agent", ["apply"], by="client-a")

    def test_factual_question_scoped_to_one_client_and_service_escalation(self):
        question = {"id":"question-1", "question":"Which methods did you personally use?",
                    "scope":{"type":"personal", "experience":"project-1"},
                    "intended_actor":"client-a", "status":"pending"}
        save_record(self.root, "clarification", question)
        with self.assertRaises(AuthorityError):
            answer_clarification(self.root, question["id"], "Synthetic answer", "client-b")
        answered = answer_clarification(self.root, question["id"], "Used spectroscopy", "client-a", update_id=1)
        self.assertEqual(answered["status"], "answered")
        with self.assertRaises(AuthorityError):
            answer_clarification(self.root, question["id"], "Duplicate reply", "client-a", update_id=1)
        with self.assertRaises(RecordError):
            load_record(self.other, "clarification", question["id"])
        question.update(id="question-2", scope={"type":"price"})
        save_record(self.root, "clarification", question)
        with self.assertRaisesRegex(AuthorityError, "operator"):
            answer_clarification(self.root, question["id"], "Change price", "client-a")

    def test_telegram_not_enabled_for_self_hosted(self):
        path = Path(self.temp.name) / "local"
        create_workspace(path)
        with self.assertRaises(AuthorityError):
            bind_client(path, "owner", "owner", 1, 2, "browser")
