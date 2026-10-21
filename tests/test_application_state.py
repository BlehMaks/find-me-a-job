import multiprocessing
from pathlib import Path
import tempfile
import unittest

from fmj.workspace import WorkspaceBusy, atomic_write_json, create_workspace
from fmj.records import save_record
from fmj.campaign import (CampaignBlocked, create_operation, dispatch_operation,
    load_operation, match_receipt, recover_dispatches, reconcile_operation, set_pause, status)


def policy(root):
    return save_record(root, "campaign-policy", {"id":"campaign-1", "approved":True,
        "markets":["example"], "languages":["en"], "approved_titles":["Researcher"],
        "hard_exclusions":{}, "resource_classes":["official"], "expansion_authority":False})


def opportunity(requisition="R1", **changes):
    value = {"employer":"Synthetic Institute", "requisition_id":requisition,
        "title":"Researcher", "resource_class":"official", "portal":"portal-1"}
    value.update(changes)
    return value


def form():
    return {"fields":{}, "recipient":None, "attachments":[]}


def crash_during_dispatch(root, operation_id, started):
    def send(_):
        started.set()
        import time
        time.sleep(20)
    dispatch_operation(root, operation_id, "owner", send, actual_form=form(), controlled=True)


class ApplicationStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        create_workspace(self.root)
        policy(self.root)

    def operation(self, req="R1"):
        return create_operation(self.root, opportunity(req), "campaign-1")

    def test_duplicate_discovery_and_dispatch_are_not_repeated(self):
        operation = self.operation()
        self.assertEqual(operation["id"], self.operation()["id"])
        calls = []
        result = dispatch_operation(self.root, operation["id"], "owner", lambda intent: calls.append(intent) or {"status":"submission_observed", "evidence":{"portal":"submitted"}}, actual_form=form(), controlled=True)
        self.assertEqual(result["acknowledgement"], "unmatched")
        with self.assertRaises(CampaignBlocked):
            dispatch_operation(self.root, operation["id"], "owner", lambda _: calls.append(True), actual_form=form(), controlled=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(status(self.root)["submission_count"], 1)
        self.assertFalse(match_receipt(self.root, operation["id"], {"employer":"Synthetic Institute", "evidence":"generic mail"}))
        self.assertTrue(match_receipt(self.root, operation["id"], {"employer":"Synthetic Institute", "requisition_id":"R1", "evidence":"specific mail"}))
        self.assertEqual(status(self.root)["acknowledgement_count"], 1)

    def test_timeout_requires_observed_reconciliation(self):
        operation = self.operation()
        def timeout(_):
            raise TimeoutError("No observed outcome")
        result = dispatch_operation(self.root, operation["id"], "owner", timeout, actual_form=form(), controlled=True)
        self.assertEqual(result["stage"], "delivery_unknown")
        with self.assertRaises(CampaignBlocked):
            dispatch_operation(self.root, operation["id"], "owner", lambda _: None, actual_form=form(), controlled=True)
        with self.assertRaises(CampaignBlocked):
            reconcile_operation(self.root, operation["id"], "not_sent", None)
        reconcile_operation(self.root, operation["id"], "not_sent", {"portal":"draft remains; verified no prior submission"})
        self.assertEqual(load_operation(self.root, operation["id"])["stage"], "not_sent")

    def test_pause_in_flight_and_recover_after_process_crash(self):
        operation = self.operation()
        ctx = multiprocessing.get_context("spawn")
        started = ctx.Event()
        worker = ctx.Process(target=crash_during_dispatch, args=(str(self.root), operation["id"], started))
        worker.start()
        try:
            self.assertTrue(started.wait(10))
            # Controls can persist a pause while the outbound callback is in flight.
            set_pause(self.root, "owner")
            self.assertTrue(status(self.root)["paused"])
            with self.assertRaises(WorkspaceBusy):
                recover_dispatches(self.root)
            with self.assertRaises(WorkspaceBusy):
                dispatch_operation(self.root, operation["id"], "owner", lambda _:None, actual_form=form(), controlled=True)
        finally:
            worker.terminate()
            worker.join(10)
        self.assertEqual(recover_dispatches(self.root), [operation["id"]])
        self.assertEqual(load_operation(self.root, operation["id"])["stage"], "delivery_unknown")

    def test_no_evidence_or_production_verifier_is_not_success(self):
        operation = self.operation()
        with self.assertRaises(CampaignBlocked):
            dispatch_operation(self.root, operation["id"], "owner", lambda _:None, actual_form=form())
        result = dispatch_operation(self.root, operation["id"], "owner", lambda _: {"status":"submission_observed"}, actual_form=form(), controlled=True)
        self.assertEqual(result["stage"], "delivery_unknown")


if __name__ == "__main__":
    unittest.main()

class NativeDispatchBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        create_workspace(self.root)
        policy(self.root)
        self.first = create_operation(self.root, opportunity("N1"), "campaign-1")
        self.second = create_operation(self.root, opportunity("N2"), "campaign-1")

    def test_bridge_preflight_ticket_one_use_and_inflight_pause(self):
        from fmj.campaign import AuthorityError, begin_dispatch, complete_dispatch
        with self.assertRaises(CampaignBlocked):
            begin_dispatch(self.root, self.first["id"], "owner", form(), None)
        bridge = begin_dispatch(self.root, self.first["id"], "owner", form(), lambda intent: True)
        self.assertNotIn(bridge["ticket"], str(load_operation(self.root, self.first["id"])))
        with self.assertRaises(AuthorityError):
            complete_dispatch(self.root, self.first["id"], "wrong-ticket", "submission_observed", "portal confirmed")
        with self.assertRaises(CampaignBlocked):
            begin_dispatch(self.root, self.second["id"], "owner", form(), lambda intent: True)
        with self.assertRaises(CampaignBlocked):
            dispatch_operation(self.root, self.second["id"], "owner", lambda intent: None, actual_form=form(), controlled=True)
        set_pause(self.root, "owner", "Pause after the native action was authorized")
        result = complete_dispatch(self.root, self.first["id"], bridge["ticket"], "submission_observed", "Portal receipt observed")
        self.assertEqual(result["stage"], "submission_observed")
        self.assertTrue(status(self.root)["paused"])
        with self.assertRaises(AuthorityError):
            complete_dispatch(self.root, self.first["id"], bridge["ticket"], "submission_observed", "same receipt")

    def test_recovered_native_action_cannot_replay_or_complete_with_old_ticket(self):
        from fmj.campaign import AuthorityError, begin_dispatch, complete_dispatch
        bridge = begin_dispatch(self.root, self.first["id"], "owner", form(), lambda intent: True)
        self.assertEqual(recover_dispatches(self.root), [self.first["id"]])
        with self.assertRaises(AuthorityError):
            complete_dispatch(self.root, self.first["id"], bridge["ticket"], "submission_observed", "Unreconciled browser state")
        with self.assertRaises(CampaignBlocked):
            begin_dispatch(self.root, self.second["id"], "owner", form(), lambda intent: True)
        reconcile_operation(self.root, self.first["id"], "not_sent", "Current portal verified no submission")
        second = begin_dispatch(self.root, self.second["id"], "owner", form(), lambda intent: True)
        result = complete_dispatch(self.root, self.second["id"], second["ticket"], "submission_observed", None)
        self.assertEqual(result["stage"], "delivery_unknown")
