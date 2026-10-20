from pathlib import Path
import tempfile
import unittest
from fmj.workspace import create_workspace
from fmj.campaign import AuthorityError, HUMAN_RESERVED, bind_client, human_handoff, require_action_authority
from fmj.records import read_events


class InterviewHandoffTests(unittest.TestCase):
    def test_invitation_and_offer_decisions_remain_human_owned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            create_workspace(root)
            for action in HUMAN_RESERVED:
                with self.assertRaises(AuthorityError):
                    require_action_authority(root, "owner", action)
            event = human_handoff(root, "confirm_appointment", {
                "company":"Synthetic Institute", "proposed_time":"2026-11-10T10:00:00Z",
                "draft_response":"Thank you. I will confirm my availability shortly.",
                "preparation":{"evidence_stories":["Use confirmed project contribution"],
                    "gap_answer":"No direct expertise claimed; explain related methods"}})
            self.assertEqual(event["type"], "human_decision_required")
            self.assertEqual(event["data"]["responsible_actor"], "owner")
            self.assertEqual([item["type"] for item in read_events(root)], ["human_decision_required"])

    def test_managed_personal_decision_routes_to_client_not_operator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            create_workspace(root, mode="managed", owner="candidate", operator="operator")
            event = human_handoff(root, "accept_offer", {"draft":"Please review the offer"})
            self.assertEqual(event["data"]["responsible_actor"], "candidate")
            bind_client(root, "bound-candidate", "operator", 1, 2, "browser")
            event = human_handoff(root, "confirm_appointment", {"draft":"Please review availability"})
            self.assertEqual(event["data"]["responsible_actor"], "bound-candidate")
