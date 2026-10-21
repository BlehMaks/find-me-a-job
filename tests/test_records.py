from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from fmj.workspace import create_workspace
from fmj.records import (RecordError, append_event, canonical_url, confirmed_answer,
                         load_record, opportunity_key, read_events, save_record, validate_claim)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        create_workspace(self.root)

    def fact(self, status="candidate_confirmed", **changes):
        value = {"id":"fact-1", "subject":"project-1", "field":"contribution",
                 "value":"Designed the prototype", "status":status,
                 "confirmed_by":"candidate", "confirmed_at":"2026-01-01T00:00:00+00:00"}
        value.update(changes)
        return save_record(self.root, "fact", value)

    def test_confirmation_without_document_and_unknown_vs_absence(self):
        fact = self.fact()
        claim = save_record(self.root, "claim", {"id":"claim-1", "fact_ids":[fact["id"]],
            "safe_wording":"Designed the prototype", "status":"approved"})
        self.assertTrue(validate_claim(self.root, claim))
        self.fact("confirmed_absent", value=None)
        with self.assertRaises(RecordError):
            validate_claim(self.root, claim)
        with self.assertRaises(RecordError):
            save_record(self.root, "claim", {"id":"claim-2", "fact_ids":[fact["id"]],
                "safe_wording":"Has direct expertise", "status":"approved"})
        self.assertEqual(load_record(self.root, "fact", "fact-1", 1)["status"], "candidate_confirmed")
        self.assertEqual(load_record(self.root, "fact", "fact-1")["status"], "confirmed_absent")

    def test_conflict_and_stale_claim_cannot_be_used(self):
        self.fact()
        claim = save_record(self.root, "claim", {"id":"claim-1", "fact_ids":["fact-1"],
            "safe_wording":"Designed the prototype", "status":"approved"})
        self.fact(value="Co-designed the prototype")
        with self.assertRaisesRegex(RecordError, "reviewed"):
            validate_claim(self.root, claim)
        self.fact("conflicting")
        with self.assertRaises(RecordError):
            save_record(self.root, "claim", claim)

    def test_superseded_scoped_answers_and_submitted_snapshot(self):
        scope = {"type":"employer", "employer":"Synthetic Research"}
        first = save_record(self.root, "answer", {"id":"answer-1", "question":"Travel?",
            "answer":"Occasional", "scope":scope, "confirmation":"confirmed",
            "confirmed_by":"candidate", "confirmed_at":"2026-01-01T00:00:00+00:00"})
        event = append_event(self.root, "application_observed", data={"answers":[first]})
        second = deepcopy(first)
        second.update(id="answer-2", answer="Flexible", supersedes="answer-1")
        save_record(self.root, "answer", second)
        self.assertEqual(confirmed_answer(self.root, "Travel?", scope)["answer"], "Flexible")
        self.assertEqual(read_events(self.root)[1]["data"]["answers"][0]["answer"], "Occasional")
        first["answer"] = "mutated"
        self.assertEqual(event["data"]["answers"][0]["answer"], "Occasional")
        with self.assertRaises(RecordError):
            confirmed_answer(self.root, "Travel?", {"type":"campaign"})

    def test_new_id_supersession_invalidates_old_claim_and_blocks_cycles(self):
        self.fact()
        claim = save_record(self.root, "claim", {"id":"claim-1", "fact_ids":["fact-1"],
            "safe_wording":"Designed the prototype", "status":"approved"})
        self.fact(id="fact-2", supersedes="fact-1", value="Co-designed the prototype")
        with self.assertRaisesRegex(RecordError, "superseded"):
            validate_claim(self.root, claim)
        with self.assertRaisesRegex(RecordError, "cycles"):
            self.fact(id="fact-1", supersedes="fact-2")
        with self.assertRaisesRegex(RecordError, "new ID"):
            self.fact(id="fact-2", supersedes="fact-2")
        self.assertEqual(load_record(self.root, "fact", "fact-1")["value"], "Designed the prototype")

    def test_event_corruption_detected(self):
        from fmj.store import connection, encode
        from fmj.workspace import locked_workspace
        append_event(self.root, "test")
        with locked_workspace(self.root):
            db = connection(self.root)
            data = json.loads(db.execute("SELECT payload FROM events").fetchone()[0])
            data["actor"] = "different"
            db.execute("UPDATE events SET payload=?", (encode(data),))
        with self.assertRaisesRegex(RecordError, "corrupted"):
            read_events(self.root)

    def test_cas_and_no_secret_records(self):
        first = self.fact()
        self.fact(value="Changed")
        with self.assertRaisesRegex(RecordError, "changed"):
            save_record(self.root, "fact", first, expected_version=1)
        with self.assertRaisesRegex(RecordError, "secret"):
            append_event(self.root, "bad", data={"password":"synthetic-secret"})
        with self.assertRaises(RecordError):
            self.fact(id="../outside")

    def test_opportunity_identity_not_company_only(self):
        self.assertEqual(canonical_url("https://EXAMPLE.invalid/jobs/7/?utm_source=alert#apply"), "https://example.invalid/jobs/7")
        self.assertEqual(opportunity_key("Synthetic Lab", "R7"), opportunity_key("synthetic lab", "r7"))
        self.assertNotEqual(opportunity_key("Synthetic Lab", "R7"), opportunity_key("Synthetic Lab", "R8"))
        self.assertEqual(opportunity_key("Synthetic Lab", url="https://example.invalid/jobs/7?utm_medium=mail"), opportunity_key("Synthetic Lab", url="https://example.invalid/jobs/7"))
        with self.assertRaises(RecordError):
            canonical_url("https://name:secret@example.invalid/jobs")


if __name__ == "__main__":
    unittest.main()
